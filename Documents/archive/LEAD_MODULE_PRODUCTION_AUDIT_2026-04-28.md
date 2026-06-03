# Lead Module Production Audit

Date: 2026-04-28
Scope: Current lead module production review covering backend API, service/repository behavior, authorization, frontend contract, and test coverage.
Reviewer: Codex

## Executive Summary

The lead module has several production-blocking issues around data exposure, import reliability, workflow invariants, and authorization consistency.

Highest priority fixes:

1. Mask duplicate-check responses to prevent lead PII enumeration.
2. Fix `/api/leads/import` role behavior and post-commit notification crash.
3. Remove or rework bulk pipeline-stage update because it bypasses the consultation/FSM source of truth.
4. Ensure all lead read endpoints require active users and route-level Casbin authorization.
5. Align manager export policy with the actual `/api/leads/export` endpoint.

## Findings

### P0 - Duplicate Check Leaks Lead PII Across Scope

Files:
- `Backend_FastAPI/app/routers/leads.py:129`
- `Backend_FastAPI/app/routers/leads.py:183`
- `Backend_FastAPI/app/casbin_config/policy_templates.py:95`

Issue:
`GET /api/leads/check-duplicate` is available to officers through Casbin. The endpoint returns details about conflicting leads, including full name, phone, unit, and assigned officer. Because phone checks are global and email checks accept caller-provided `unit_id`, a user can enumerate lead existence and PII outside their allowed scope.

Impact:
Broken access control / IDOR-style information disclosure. This exposes applicant/lead PII and operational ownership data.

Recommended fix:
- Return only `{ phone_available: false, email_available: false, conflict_code: "exists" }` for conflicts the caller cannot access.
- Only include conflict details if `get_lead_for_user`-equivalent scope validation passes for the conflicting lead.
- Validate `unit_id` and `exclude_id` against caller scope.
- Add rate-limit/monitoring focused on duplicate checks.

Suggested tests:
- Officer checking another unit's phone receives no PII.
- Officer cannot use arbitrary `unit_id` to enumerate email conflicts.
- Manager only sees details for descendant-unit conflicts.

### P0 - Lead Import Can Fail for Admin/Manager and Return 500 After Commit

Files:
- `Backend_FastAPI/app/routers/leads.py:1437`
- `Backend_FastAPI/app/routers/leads.py:1493`
- `Backend_FastAPI/app/routers/leads.py:1495`
- `Backend_FastAPI/app/routers/leads.py:1510`
- `Backend_FastAPI/app/services/lead_service.py:3427`
- `Backend_FastAPI/app/services/lead_service.py:3431`

Issue:
The import handler documents Officer/Admin/Manager support, but always passes `auto_assign_officer_id=current_user.id`. The service requires that ID to belong to a role `officer`, so manager/admin imports fail. For officers, imports can commit successfully and then crash with `NameError` because `_rooms_for_lead(lead)` references an undefined `lead`.

Impact:
Unreliable import flow. Users can see a failed request while rows were already inserted, causing duplicate retries and support confusion.

Recommended fix:
- Branch role behavior explicitly:
  - Officer: force `default_unit_id=current_user.unit_id`, `auto_assign_officer_id=current_user.id`.
  - Manager: force unit scope, no self auto-assign unless assigning to a selected valid officer in scope.
  - Admin: allow explicit unit/officer behavior, or import unassigned with later distribution.
- Replace `_rooms_for_lead(lead)` with a safe room target based on created lead IDs, unit, or a dedicated import notification resolver.
- Wrap post-commit notification in `safe_dispatch` with variables that are definitely defined.

Suggested tests:
- Officer import returns 200 and creates assigned leads.
- Manager import returns 200 according to intended behavior, or 403/400 if unsupported.
- Admin import returns expected result.
- Successful import response does not 500 after commit.

### P0 - Bulk Stage Update Bypasses FSM and Status Invariants

Files:
- `Backend_FastAPI/app/services/lead_service.py:1472`
- `Backend_FastAPI/app/services/lead_service.py:3948`
- `Backend_FastAPI/app/services/lead_service.py:4007`
- `Backend_FastAPI/app/repositories/lead_repository.py:981`

Issue:
Normal lead updates block direct updates to `consultation_status_id` and `pipeline_stage_id`; status changes are supposed to go through consultation/FSM logic. `bulk_update_pipeline_stage` directly updates `pipeline_stage_id` only, without syncing `consultation_status_id`, `status`, history, notifications, or `version`.

Impact:
Leads can enter impossible workflow states. UI and reports may disagree because status, consultation status, and pipeline stage no longer represent the same lifecycle state.

Recommended fix:
- Remove the endpoint if it is an admin maintenance shortcut not safe for production.
- Or replace it with a bulk FSM transition endpoint that validates allowed transitions and updates all derived fields atomically.
- At minimum, bump `version`, write history, and validate `pipeline_stage_id` against the selected consultation status.

Suggested tests:
- Bulk stage update cannot create stage/status mismatch.
- Version increments for every affected lead.
- History is written for every changed lead.

### P1 - Some Lead Read Endpoints Bypass Active User and Casbin Checks

Files:
- `Backend_FastAPI/app/core/deps.py:964`
- `Backend_FastAPI/app/core/deps.py:967`
- `Backend_FastAPI/app/routers/leads.py:562`
- `Backend_FastAPI/app/routers/leads.py:900`
- `Backend_FastAPI/app/routers/leads.py:911`

Issue:
`get_lead_for_user` depends on `get_current_user`, not `get_current_active_user`. Some lead read endpoints use only `LeadAccessDep` and do not also require `CasbinAuth`, including audit logs, timeline, and insights.

Impact:
An inactive user with a still-valid session can still read lead detail-related data if IDOR conditions pass. Route-level policy changes in Casbin may not apply to these endpoints.

Recommended fix:
- Change `get_lead_for_user` to depend on `get_current_active_user`.
- Add `current_user: models.User = CasbinAuth` to all endpoints that currently rely only on `LeadAccessDep`, or make `LeadAccessDep` include active-user and permission checks by design.
- Add regression tests for inactive users and for missing Casbin policy denial.

Suggested tests:
- Inactive assigned officer cannot read lead timeline/audit/insights.
- Removing a Casbin policy denies the endpoint even when IDOR scope would otherwise pass.

### P1 - Manager Export Policy Does Not Match Actual Endpoint

Files:
- `Backend_FastAPI/app/routers/leads.py:315`
- `Backend_FastAPI/app/casbin_config/policy_templates.py:302`
- `frontend/src/lib/api/leads.ts:483`

Issue:
The route is `GET /api/leads/export?format=csv|xlsx`. Frontend calls `/api/leads/export`. Manager policies grant `/api/leads/export/csv` and `/api/leads/export/excel`, which do not match the actual route.

Impact:
Managers can be blocked from export despite UI expecting manager-or-above export access.

Recommended fix:
- Replace manager policies with `GET /api/leads/export`.
- Add migration/sync step to update existing Casbin rules in the database.
- Keep export scope filtering through `get_lead_list_filter`.

Suggested tests:
- Manager can export only scoped leads from `/api/leads/export?format=csv`.
- Officer export behavior matches intended policy.

### P1 - Bulk Assign Drops Assignment Notification Callbacks

Files:
- `Backend_FastAPI/app/services/lead_service.py:2182`
- `Backend_FastAPI/app/services/lead_service.py:3903`

Issue:
`assign_lead_manually` returns a post-commit callback for notifications. `bulk_assign_leads` calls this function but ignores `_cb`, so assignment records can be persisted without dispatching assignment notifications/realtime updates.

Impact:
Bulk assignment succeeds but users may not receive assignment notifications and UIs may not refresh until polling/manual refresh.

Recommended fix:
- Collect callbacks during bulk assignment and return a bulk post-commit callback.
- Router should run that callback after `await db.commit()`.
- Consider a single bulk notification event if per-lead notifications are too noisy.

Suggested tests:
- Bulk assign dispatches expected notification callbacks after commit.
- Callback failure does not roll back assigned leads.

### P2 - Import Reads Entire File Into Memory Before Size Validation

Files:
- `Backend_FastAPI/app/routers/leads.py:1474`
- `Backend_FastAPI/app/services/lead_service.py:3436`

Issue:
The router reads the entire uploaded file before the service checks the 10 MB limit. Large uploads consume memory before validation.

Impact:
Potential memory pressure or request-worker degradation from oversized uploads.

Recommended fix:
- Enforce request/file size at reverse proxy and FastAPI middleware level.
- Check `Content-Length` before reading where available.
- Read uploads in bounded chunks if large-file handling is needed.

### P2 - Frontend Still Uses Role-Based Permission Decisions

Files:
- `frontend/src/lib/utils/permissions.ts:4`
- `frontend/src/components/leads/LeadDialog.tsx:207`
- `frontend/src/components/leads/LeadDialog.tsx:710`
- `frontend/src/components/leads/command-center/LeadDetailPanel.tsx:110`
- `frontend/src/components/leads/command-center/LeadDetailPanel.tsx:313`

Issue:
The frontend still derives lead actions from `user.role` utilities even though backend `LeadDetail` exposes permission/action fields. This is marked as TODO in the utility file.

Impact:
Not a backend security bypass by itself, but the UI can show actions that backend denies or hide actions backend allows. This causes confusing production behavior and conflicts with the thin-client architecture.

Recommended fix:
- Prefer `lead.permissions`, `lead.available_actions`, and `lead.action_blockers` for detail actions.
- Keep role utilities only for broad navigation fallback until all APIs expose explicit permission flags.

## Positive Observations

- Lead list and export both route through `get_lead_list_filter`, which centralizes role-based list scoping.
- Core detail access uses `get_lead_for_user`, returning 404 for unauthorized lead access, which is the right IDOR posture.
- Phone normalization and duplicate identity tracking are handled through structured helpers/repository patterns.
- Optimistic locking exists on key single-lead update/status paths.
- Sensitive Socket.IO emits in the notification dispatcher are scoped/fail-closed when rooms are missing.

## Recommended Remediation Order

1. Patch duplicate-check PII masking and scope validation.
2. Patch import role branching and undefined `lead` post-commit crash.
3. Disable or redesign bulk stage update behind FSM-compliant logic.
4. Make `get_lead_for_user` require active users and add CasbinAuth to read endpoints missing it.
5. Align Casbin export policy and add migration/sync for existing policy rows.
6. Collect and run bulk assignment callbacks after commit.
7. Move frontend lead action gating to backend permission flags.

## Suggested Regression Suite

Backend API:
- `test_lead_duplicate_check_masks_out_of_scope_conflict`
- `test_lead_duplicate_check_validates_unit_scope`
- `test_officer_import_succeeds_without_post_commit_500`
- `test_manager_import_behavior_matches_contract`
- `test_admin_import_behavior_matches_contract`
- `test_bulk_stage_update_cannot_desync_status_and_stage`
- `test_inactive_user_cannot_read_lead_timeline`
- `test_manager_can_export_via_actual_export_route`
- `test_bulk_assign_dispatches_callbacks_after_commit`

Frontend:
- Lead detail actions render from `lead.permissions` instead of `user.role`.
- Export button visibility matches backend-provided capability or successful policy contract.
- Import mutation handles success/error consistently and does not encourage duplicate retries after partial commit.

## Notes

This was a static production review. Docker tests were not executed during the audit.
