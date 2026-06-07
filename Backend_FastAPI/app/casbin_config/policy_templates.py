# app/config/policy_templates.py
"""
Policy Templates Configuration

This module defines reusable policy templates for common permission patterns.
Templates can be applied to roles to quickly set up standard permission sets.

Each template contains:
- display_name: Human-readable name
- description: What permissions this template grants
- category: Group similar templates together
- policies: List of policy rules (subject placeholder will be replaced)

=============================================================================
ROLE HIERARCHY PATTERN (TREE, post 2026-05-15 fix)
=============================================================================

Role hierarchy uses tree-shape inheritance for separation of duties:

                       ┌─────────────┐
                       │    Admin    │  Full system access (wildcard ALLOW)
                       └──────┬──────┘
                              │
                       ┌──────┴──────┐
                       │  Manager    │  (Users/Leads/Admissions)
                       └──────┬──────┘
                              │
              ┌───────────────┴──────────────┐
              │                              │
        ┌─────┴──────┐                ┌──────┴─────┐
        │  Officer   │                │ Accountant │
        │ (Admission │                │  (Finance  │
        │ consultant)│                │   Ops)     │
        └─────┬──────┘                └──────┬─────┘
              │                              │
              └────────────┬─────────────────┘
                           ▼
                      ┌───────────┐
                      │   User    │  Basic permissions
                      └───────────┘

Casbin Grouping Policies (g-type rules):
  g, role:officer, role:user
  g, role:accountant, role:officer
  g, role:manager, role:officer        # Manager does NOT inherit Accountant!
  g, role:admin, role:manager

REMOVED 2026-05-15: `g, role:admin, role:accountant` diamond edge.
Reason: admin already has wildcard ALLOW `/*.*` so the inheritance edge
only causes admin to inherit accountant DENY entries (admin-rollback,
claim, request-revision, waitlist-promote) → admin gets unintended 403s.
Tree shape preserves separation-of-duties while eliminating leaked DENYs.
See alembic phase3_02 for prod data migration.

Benefits:
  - Separation of Duties: Manager cannot do finance ops, Accountant cannot manage users
  - Least Privilege: Each role only has required permissions
  - Admin Override: Admin has wildcard `/*.*` ALLOW (no inheritance needed)

Template Design:
  - Each template defines ONLY the permissions UNIQUE to that role
  - Inherited permissions come automatically via Casbin g-rules
  - Example: Accountant template has finance-specific policies only,
    officer permissions come via inheritance

=============================================================================
"""

from typing import Dict, List, Literal, TypedDict


# B1: Casbin deny-first effect (PLAN §3.3.b + RISK_REVIEW P0-01).
# `auth_model.conf` declares `p = sub, obj, act, eft` and the canonical
# Casbin effect `e = some(where (p.eft == allow)) && !some(where (p.eft
# == deny))` — any matching deny short-circuits to forbidden, otherwise
# at least one matching allow grants access. Default for legacy / new
# rules is "allow"; `accountant` carries explicit deny rows for the
# admission state-machine routes accountant must NOT be able to drive
# (claim / request-revision / publish-result / waitlist-* /
# admin-rollback) since accountant inherits officer (g, role:accountant,
# role:officer) and would otherwise pass through that route guard.
PolicyEft = Literal["allow", "deny"]


class PolicyRule(TypedDict, total=False):
    """Type definition for a single policy rule.

    ``eft`` is optional in source data (defaults to ``"allow"`` via
    ``apply_template``), so 3-field rules keep their existing shape and
    do not need bulk rewrites.  New deny rules opt in by writing
    ``"eft": "deny"`` explicitly.
    """
    subject: str  # Placeholder: {role} will be replaced
    object: str   # Resource path (e.g., /api/leads/*)
    action: str   # HTTP method or regex (e.g., GET, POST, .*)
    eft: PolicyEft  # "allow" (default) or "deny"


class PolicyTemplate(TypedDict):
    """Type definition for a policy template."""
    display_name: str
    description: str
    category: str
    policies: List[PolicyRule]


# =============================================================================
# CORE ROLE TEMPLATES (Based on system defaults)
# =============================================================================

OFFICER_TEMPLATE: PolicyTemplate = {
    "display_name": "Officer (Lead Access)",
    "description": "Standard permissions for sales officers: view and manage assigned leads",
    "category": "core",
    "policies": [
        # Lead access
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "POST"},  # Create lead
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "PUT"},  # Update lead
        {"subject": "{role}", "object": "/api/leads/check-duplicate", "action": "GET"},  # Duplicate check for create/edit form
        {"subject": "{role}", "object": "/api/leads/{id}/workflow-context", "action": "GET"},  # Workflow context
        {"subject": "{role}", "object": "/api/leads/{id}/consultations", "action": "GET"},  # List consultations
        {"subject": "{role}", "object": "/api/leads/{id}/consultations", "action": "POST"},  # Create consultation
        {"subject": "{role}", "object": "/api/leads/{id}/consultations/{consultation_id}", "action": "PUT"},  # Update
        {"subject": "{role}", "object": "/api/leads/{id}/consultations/{consultation_id}", "action": "DELETE"},  # Delete own
        {"subject": "{role}", "object": "/api/leads/{id}/action", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/{id}/timeline", "action": "GET"},  # Lead timeline
        {"subject": "{role}", "object": "/api/leads/{id}/insights", "action": "GET"},  # Lead insights
        {"subject": "{role}", "object": "/api/leads/{id}/audit-logs", "action": "GET"},  # Lead audit log history
        {"subject": "{role}", "object": "/api/leads/my/reassign-quota", "action": "GET"},  # Reassign quota
        {"subject": "{role}", "object": "/api/leads/import/template", "action": "GET"},  # Import template
        {"subject": "{role}", "object": "/api/leads/import", "action": "POST"},  # Import leads
        # Admin users (read-only) — needed for officer filter bar and lead assignment dialog
        {"subject": "{role}", "object": "/api/admin/users", "action": "GET"},
        # Collaborators — GET for referrer dropdown, POST to propose new CTV (pending), GET detail
        {"subject": "{role}", "object": "/api/collaborators", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}", "action": "GET"},
        # Organization units (read-only) — needed for SmartUnitSelector in LeadDialog & dashboard
        {"subject": "{role}", "object": "/api/organization-units", "action": "GET"},
        # Pipeline access (for consultation statuses in QuickDisposition)
        {"subject": "{role}", "object": "/api/pipeline/stages", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/all", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/board", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/allowed-next-statuses", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/loss-reasons", "action": "GET"},
        # Officer Dashboard access (Phase 4: Unified Dashboard)
        {"subject": "{role}", "object": "/api/officer/stats", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/dashboard", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/leaderboard", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/team-stats", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/upcoming-activities", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/availability", "action": "POST"},
        {"subject": "{role}", "object": "/api/officer/my-kpi-plan", "action": "GET"},  # Gap 2
        {"subject": "{role}", "object": "/api/officer/recommendations", "action": "GET"},  # Phase 7
        # Admissions access (Admission Profile workflow)
        {"subject": "{role}", "object": "/api/admissions", "action": "GET"},   # List profiles
        {"subject": "{role}", "object": "/api/admissions", "action": "POST"},  # Create profile
        {"subject": "{role}", "object": "/api/admissions/{id}", "action": "GET"},   # Read profile
        {"subject": "{role}", "object": "/api/admissions/{id}", "action": "PUT"},   # Update profile
        {"subject": "{role}", "object": "/api/admissions/{id}/submit", "action": "POST"},  # Submit
        {"subject": "{role}", "object": "/api/admissions/{id}/resubmit", "action": "POST"},  # Resubmit after rejection
        {"subject": "{role}", "object": "/api/admissions/{id}/withdraw", "action": "POST"},  # Withdraw applicant-initiated
        {"subject": "{role}", "object": "/api/admissions/{id}/send-confirmation", "action": "POST"},  # Send magic link
        # W2-1 fix Wave 7 (2026-05-16) — Generate magic-link cho 3 non-confirm
        # actions (submit/resubmit/withdraw). Officer triggers generate-side;
        # candidate consume qua /magic-link/{action}/{token} (PR #280 wired).
        {"subject": "{role}", "object": "/api/admissions/{id}/send-magic-link", "action": "POST"},
        {
            "subject": "{role}",
            "object": "/api/admissions/{id}/record-fee-payment",
            "action": "POST",
            "eft": "allow",
        },
        # Post-approval minor correction — Casbin admits the role; service
        # narrows further with status whitelist + per-path allowlist +
        # HARD_DENY checks. IDOR via get_admission_for_user (admin all /
        # manager unit / officer unit + assigned).
        {"subject": "{role}", "object": "/api/admissions/{id}/minor-correction", "action": "POST"},
        # REMOVED: enroll is ADMIN-ONLY per Decision 10 (Admission State ≠ Authorization)
        # {"subject": "{role}", "object": "/api/admissions/{id}/enroll", "action": "POST"},
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/upload", "action": "POST"},  # Upload doc
        # PR #5 — paper-submitted is officer-initiated for paper-only docs
        # (requires_upload=false); service-layer guard enforces the
        # owning-officer + profile-editable + missing-status contract.
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/paper-submitted", "action": "POST"},
        # PR #13 — officer records a graduation-proof upgrade (provisional
        # cert → official diploma) WITHOUT changing doc status. Mirrors
        # paper-submitted (officer-initiated); service layer narrows IDOR +
        # bang_tot_nghiep_thpt-only. Manager/admin inherit; accountant has no
        # deny row (same as paper-submitted — finance never reaches the
        # owning-officer scope check).
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/graduation-proof", "action": "POST"},
        # Phase 3 multi-NV read-only (PR-3B). Officer can VIEW result-published
        # profiles + choice list for their assigned unit; mutations stay
        # manager-only per RBAC matrix plan v0.7. Service-layer IDOR
        # (get_choice_for_user) narrows to assigned officer scope.
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices",           "action": "GET"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/publish-result",    "action": "GET"},
        # Phase 3 PR-3D-B BE-1 — Choice CRUD (retroactive add/edit NV).
        # Officer can mutate choices on their assigned profile (IDOR
        # get_choice_for_user narrows scope); manager + admin inherit via
        # diamond. Accountant DENY block below. Service-layer status
        # whitelist (draft + revision_requested) is the second guard.
        # keyMatch4 wildcard matches single-segment {profile_id} +
        # {choice_id} (per existing matcher in auth_model.conf).
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices",           "action": "POST"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices/*",         "action": "DELETE"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices/*",         "action": "PATCH"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices/*/scores",  "action": "PATCH"},
        # Q9 #07 Phase E — Priority bonus + UT evidence verify/reject.
        # Officer scope: assigned to profile (IDOR check trong service);
        # manager + admin inherit via diamond (verify/reject). Accountant
        # DENY block below.
        # Phase E.4 commit 7 hardening (yêu cầu nghiệp vụ #10): override-
        # priority-kv MOVED TO MANAGER_TEMPLATE — officer KHÔNG được override
        # KV. Service-layer priority_override_service hard-deny officer ngay
        # đầu override_kv là defense-in-depth.
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-objects/*/verify",     "action": "PATCH"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-objects/*/reject",     "action": "PATCH"},
        # Q9 #07 Phase E.4 PR-2 — Priority evidence upload + untick (officer
        # ALLOW). Mirror verify/reject above; Casbin admits the route, service
        # layer enforces version guard + sub_code-in-codes + status whitelist.
        # Accountant DENY block đối ứng dưới.
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-evidence/*/upload",    "action": "POST"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-evidence/*",           "action": "DELETE"},
        # Wave 1 read endpoints — KV preview + UT catalog. Used by candidate
        # (BASIC_USER_TEMPLATE also has these) AND officer/manager/admin via
        # this template. Accountant DENY block below.
        {"subject": "{role}", "object": "/api/v2/admissions/*/preview-priority-kv",           "action": "POST"},
        {"subject": "{role}", "object": "/api/v2/admissions/priority-objects/catalog",        "action": "GET"},
        # PR #7 — officer can create the official fee record for their own
        # assigned profile. Casbin admits the route; _fee_calc_authorized +
        # _compute_permissions narrow the scope to the owning officer on a
        # profile in approved/confirmed/enrolled status.
        {"subject": "{role}", "object": "/api/fees/calculate", "action": "POST"},
        # PR #7 review — CalculateFeeDialog populates the installment-plan
        # Select from /api/installment-plans so the UI reflects the real
        # seed (FULL / TWO_TERM / QUARTERLY) rather than guessing codes.
        # Read-only; admin inherits via wildcard, manager/accountant via
        # diamond inheritance on officer.
        {"subject": "{role}", "object": "/api/installment-plans", "action": "GET"},
        {"subject": "{role}", "object": "/api/installment-plans/{plan_id}", "action": "GET"},
        # Admission aggregate endpoints (read-only)
        {"subject": "{role}", "object": "/api/admissions/stats", "action": "GET"},  # Stats dashboard
        {"subject": "{role}", "object": "/api/admissions/status-counts", "action": "GET"},  # Tab badges
        {"subject": "{role}", "object": "/api/admissions/academic-years", "action": "GET"},  # Year filter
        # PR #13.7 — "nợ bằng" reminder list (provisional graduation cert still
        # outstanding). IDOR-scoped in the service (officer assigned scope).
        {"subject": "{role}", "object": "/api/admissions/pending-diploma", "action": "GET"},
        # Admission config (read-only lookup data)
        {"subject": "{role}", "object": "/api/program-offerings", "action": "GET"},  # Dropdown data
        {"subject": "{role}", "object": "/api/admission-config/subjects", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/methods", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/criteria", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/criteria/{criteria_code}", "action": "GET"},
        # Admission Configuration Console (Phase 1)
        {"subject": "{role}", "object": "/api/admission-config/years", "action": "GET"},  # Academic years dropdown
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
        # Finance Module - Officer (Tư vấn viên) can only VIEW fees/invoices/payments
        # and CREATE payment intents (to send payment links to parents)
        # Officer CANNOT record cash payments or verify payments (accounting staff only)
        {"subject": "{role}", "object": "/api/fees", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/by-profile/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/summary/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/by-fee/{fee_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/by-invoice/{invoice_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/intents", "action": "POST"},  # Create payment intent (online)
        {"subject": "{role}", "object": "/api/payments/intents/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/methods", "action": "GET"},
        # NOTE (PR #324 Commit 5) — Officer DENY for /api/leads/export,
        # /bulk-assign, /bulk-delete, /distribution-preview was DESIGNED
        # here but NOT shipped. Reason: officer sits as an inheritance
        # parent in the diamond (admin -> manager -> officer; accountant
        # -> officer), so a DENY at the officer subject propagates UP
        # to manager + admin AND DOWN to accountant via Casbin's
        # `g(r.sub, p.sub)` policy expansion — verified empirically with
        # `test_casbin_lead_static_route_collision.py` 2026-05-23 (test
        # showed 11/16 cells flipped to DENY). The keyMatch4 collision
        # bypass that exposes these 4 routes to officer is mitigated
        # at the FE layer (`LeadDialog.tsx:285` enabled-gate). A proper
        # BE fix needs a custom matcher (e.g., `keyMatchPriority` or
        # `keyMatch4Numeric`) that respects the regex constraint inside
        # `{token}` — tracked separately per memory
        # `launch-readiness-over-creep` + `lead-keymatch4-collision-followup`.
    ]
}

ACCOUNTANT_TEMPLATE: PolicyTemplate = {
    "display_name": "Accountant (Kế toán viên)",
    "description": "Finance staff: record payments, issue invoices, verify payments, waive fees. Inherits from Officer via g-rules.",
    "category": "core",
    "policies": [
        # =========================================================================
        # DIAMOND INHERITANCE: Accountant inherits Officer permissions via:
        #   g, role:accountant, role:officer
        # These are ADDITIONAL accountant-only permissions (Finance operations)
        # Accountant does NOT inherit Manager (separation of duties)
        # =========================================================================
        # Profile access (SELF only)
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
        # Sessions & Security (SELF only)
        {"subject": "{role}", "object": "/api/sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/sessions/{id}", "action": "DELETE"},
        {"subject": "{role}", "object": "/api/sessions/revoke-all", "action": "POST"},
        {"subject": "{role}", "object": "/api/security/login-history", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/active-sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/not-me", "action": "POST"},

        # =====================================================================
        # FINANCE MODULE - Full accounting operations
        # =====================================================================

        # DASHBOARD - Finance overview
        {"subject": "{role}", "object": "/api/finance/dashboard", "action": "GET"},

        # FEES - Read + Calculate + Waive + Recalculate (not Cancel - admin only)
        {"subject": "{role}", "object": "/api/fees", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/by-profile/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/summary/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/calculate", "action": "POST"},
        {"subject": "{role}", "object": "/api/fees/{id}/waive", "action": "POST"},
        {"subject": "{role}", "object": "/api/fees/{id}/recalculate", "action": "POST"},

        # INVOICES - Full CRUD (except delete)
        {"subject": "{role}", "object": "/api/invoices", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/by-fee/{fee_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/{id}/issue", "action": "PUT"},
        {"subject": "{role}", "object": "/api/invoices/{id}/cancel", "action": "PUT"},
        {"subject": "{role}", "object": "/api/invoices/{id}/apply-penalty", "action": "POST"},

        # PAYMENTS - Record + Verify + Reject (giai đoạn đầu accountant tự verify)
        {"subject": "{role}", "object": "/api/payments", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments", "action": "POST"},  # Record payment
        {"subject": "{role}", "object": "/api/payments/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/by-invoice/{invoice_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/{id}/verify", "action": "PUT"},  # Verify payment
        {"subject": "{role}", "object": "/api/payments/{id}/reject", "action": "PUT"},  # Reject payment
        {"subject": "{role}", "object": "/api/payments/intents", "action": "POST"},
        {"subject": "{role}", "object": "/api/payments/intents/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/methods", "action": "GET"},

        # ACCOUNTING PERIODS - View only (create/close is admin only)
        {"subject": "{role}", "object": "/api/accounting/periods", "action": "GET"},
        {"subject": "{role}", "object": "/api/accounting/periods/current", "action": "GET"},
        {"subject": "{role}", "object": "/api/accounting/periods/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/accounting/periods/{id}/summary", "action": "GET"},

        # REFUNDS — DEAD POLICY removed 2026-05-16. Refunds module deferred
        # (no router exists; live probe /api/refunds → 404). Per memory
        # `finance-event-decisions`, REFUND_PROCESSED tagged internal_future
        # với 0 prod traffic. Promote back when router ships.

        # Admission config (read-only lookup data)
        {"subject": "{role}", "object": "/api/admission-config/subjects", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/methods", "action": "GET"},

        # =====================================================================
        # B1: ACCOUNTANT DENY rules — admission state-machine routes
        # PLAN §3.3.b + RISK_REVIEW P0-01.
        #
        # Accountant inherits officer (g, role:accountant, role:officer).
        # If officer ever gains an admission state-machine route via
        # OFFICER_TEMPLATE (or via #15 wiring the new /api/v2/admissions
        # internal staff endpoints), accountant would silently inherit
        # access. The deny-first effect of the new auth_model.conf
        # (p = sub, obj, act, eft + canonical Casbin allow-and-deny
        # effect) ensures these explicit denies override any allow that
        # might reach accountant via inheritance.
        #
        # NOTE: the routes listed here use the /api/v2/admissions/...
        # prefix that #15 will introduce. Adding the deny rows ahead of
        # #15 is intentional — when #15 lands, accountant is already
        # forbidden by Casbin and the test matrix catches any drift.
        # The keyMatch4 wildcard covers /api/v2/admissions/{id}/<verb>
        # (single-segment id) per the existing matcher in
        # auth_model.conf.
        {"subject": "{role}", "object": "/api/v2/admissions/*/claim",             "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/request-revision",  "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/publish-result",    "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/waitlist-promote",  "action": "POST", "eft": "deny"},
        # RE-ADDED 2026-05-16 Wave 5: T11 waitlist-reject endpoint shipped.
        # Phase3_02 dropped row from DB (endpoint was dead); phase3_04 re-adds
        # since endpoint exists. Separation-of-duties — finance staff không
        # quyết định reject candidate dự bị.
        {"subject": "{role}", "object": "/api/v2/admissions/*/waitlist-reject",   "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/admin-rollback",    "action": "POST", "eft": "deny"},
        # PR-3D-B BE-1 — Choice CRUD: accountant explicitly denied per
        # separation-of-duties; finance staff do not touch admission state.
        # Mirror officer ALLOW above so accountant via tree inheritance
        # still bounces off deny effect.
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices",           "action": "POST",   "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices/*",         "action": "DELETE", "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices/*",         "action": "PATCH",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/choices/*/scores",  "action": "PATCH",  "eft": "deny"},
        # Q9 #07 Phase E — Priority bonus mutations: accountant explicitly
        # denied. Finance staff không quyết định KV ưu tiên / verify UT
        # evidence. Mirror officer ALLOW block above so accountant via tree
        # inheritance (role:accountant → role:officer) bounces off deny effect.
        {"subject": "{role}", "object": "/api/v2/admissions/*/override-priority-kv",          "action": "POST",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-objects/*/verify",     "action": "PATCH", "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-objects/*/reject",     "action": "PATCH", "eft": "deny"},
        # Q9 #07 Phase E.4 PR-2 — Priority evidence upload + untick (accountant
        # DENY). Finance staff không scan/quản lý minh chứng UT; mirror officer
        # ALLOW block above so accountant via inheritance (role:accountant →
        # role:officer) bounces off deny effect.
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-evidence/*/upload",    "action": "POST",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/*/priority-evidence/*",           "action": "DELETE", "eft": "deny"},
        # Wave 1 read endpoints — accountant không cần xem priority data;
        # separation-of-duties giữ kế toán khỏi admission scoring info.
        {"subject": "{role}", "object": "/api/v2/admissions/*/preview-priority-kv",           "action": "POST",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/v2/admissions/priority-objects/catalog",        "action": "GET",   "eft": "deny"},
        # F8 + F9 fix 2026-05-16: accountant inherits Officer (g, role:accountant,
        # role:officer) which grants admission/lead list endpoints. Finance
        # workflows operate on profile_id passed from invoice/payment forms,
        # not on full list views — accountant has no business need to enumerate
        # admissions or leads, and `/api/leads` returns 391 leads with phone
        # numbers (PII leak). admission_service._resolve_idor_filters also
        # raises a defensive "Unexpected role 'accountant' for admission access"
        # which leaks internal code state; deny at Casbin → clean 403 from
        # gateway, service code never receives the role.
        {"subject": "{role}", "object": "/api/admissions",                "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}",           "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}",           "action": "PUT",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions",                "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}/submit",    "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}/resubmit",  "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}/withdraw",  "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}/minor-correction", "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}/send-confirmation", "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/{id}/send-magic-link", "action": "POST", "eft": "deny"},  # W2-1 Wave 7 accountant deny
        {"subject": "{role}", "object": "/api/admissions/stats",          "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/status-counts",  "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/admissions/academic-years", "action": "GET",  "eft": "deny"},
        # PR #13.7 — nợ bằng list carries candidate PII (name/phone); finance
        # staff have no business need + separation-of-duties. Mirror the
        # /stats /status-counts denies above (accountant inherits officer).
        {"subject": "{role}", "object": "/api/admissions/pending-diploma", "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads",                     "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads",                     "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/{id}",                "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/{id}",                "action": "PUT",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/{id}/timeline",       "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/{id}/insights",       "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/{id}/audit-logs",     "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/{id}/consultations",  "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/check-duplicate",     "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/import",              "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/import/template",     "action": "GET",  "eft": "deny"},
        # PR #324 Commit 5 — mirror OFFICER_TEMPLATE block above for the
        # 4 lead static routes. Separation-of-duties: finance staff never
        # operate the lead distribution / export / bulk-assign / bulk-delete
        # paths. Inheritance via `g, role:accountant, role:officer` would
        # otherwise let accountant flow through any future officer ALLOW
        # added to these paths; explicit deny pins the contract.
        {"subject": "{role}", "object": "/api/leads/export",               "action": "GET",  "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/bulk-assign",          "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/bulk-delete",          "action": "POST", "eft": "deny"},
        {"subject": "{role}", "object": "/api/leads/distribution-preview", "action": "GET",  "eft": "deny"},
    ]
}

MANAGER_TEMPLATE: PolicyTemplate = {
    "display_name": "Manager (User & Lead Manager)",
    "description": "Manager permissions: lead CRUD (except DELETE) + user administration. Inherits from Officer via g-rules.",
    "category": "core",
    "policies": [
        # =========================================================================
        # DIAMOND INHERITANCE: Manager inherits Officer permissions via:
        #   g, role:manager, role:officer
        # These are ADDITIONAL manager-only permissions (not in Officer template)
        # Manager does NOT inherit Accountant (separation of duties)
        # =========================================================================
        # User management
        {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        # Lead management - explicit policies (no wildcard)
        # Manager can: List, Create, View, Update leads
        # Manager CANNOT: Delete leads (requires admin) - Security Decision #3
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "PUT"},
        {"subject": "{role}", "object": "/api/leads/{id}/assign", "action": "POST"},
        # Lead export — single endpoint với ?format=csv|excel|json query param
        # (router: leads.py:315 @router.get("/export")). Fixed 2026-05-16:
        # previous entries /api/leads/export/csv + /export/excel pointed to
        # non-existent paths (live probe → 404), leaving FE blocked when
        # manager clicked "Xuất CSV/Excel".
        {"subject": "{role}", "object": "/api/leads/export", "action": "GET"},
        # Bulk operations (manager-specific)
        {"subject": "{role}", "object": "/api/leads/bulk-assign", "action": "POST"},  # Bulk assign
        {"subject": "{role}", "object": "/api/leads/distribution-preview", "action": "GET"},  # Preview distribution
        {"subject": "{role}", "object": "/api/leads/import/template", "action": "GET"},  # Import template
        {"subject": "{role}", "object": "/api/leads/import", "action": "POST"},  # Import leads
        # Admission State Machine (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
        {"subject": "{role}", "object": "/api/admissions/{id}/approve", "action": "POST"},  # Approve profile
        {"subject": "{role}", "object": "/api/admissions/{id}/reject", "action": "POST"},  # Reject profile
        {"subject": "{role}", "object": "/api/admissions/{id}/request-revision", "action": "POST"},  # Request revision
        {"subject": "{role}", "object": "/api/admissions/{id}/override", "action": "POST"},  # Override decision
        # Q9 #07 Phase E.4 commit 7 — Manual KV override (manager-explicit;
        # officer hard-blocked at service level per nghiệp vụ #10). Admin
        # inherits via wildcard `/*`.
        {"subject": "{role}", "object": "/api/v2/admissions/*/override-priority-kv", "action": "POST"},
        # NOTE: /withdraw lives in OFFICER_TEMPLATE — manager inherits via diamond.
        {"subject": "{role}", "object": "/api/admissions/{id}/claim", "action": "POST"},  # Claim profile for review
        {"subject": "{role}", "object": "/api/admissions/{id}/unclaim", "action": "POST"},  # Unclaim profile
        {"subject": "{role}", "object": "/api/admissions/{id}/drop", "action": "POST"},  # Drop enrolled student
        {"subject": "{role}", "object": "/api/admissions/{id}/send-confirmation", "action": "POST"},  # Send magic link
        {"subject": "{role}", "object": "/api/admissions/{id}/send-magic-link", "action": "POST"},  # W2-1 Wave 7 manager generate magic-link 3 actions
        # PR #5 — reviewer actions on individual documents. Casbin admits
        # the route at role level; admission_service enforces unit scope +
        # allowed doc_status per _compute_document_permissions.
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/verify-format", "action": "PATCH"},
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/reject", "action": "POST"},
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/reset", "action": "POST"},
        # Phase 3 multi-NV transitions (PR-3B). Routes shipped under /api/v2/
        # namespace; counterpart accountant DENY rules already in
        # ACCOUNTANT_TEMPLATE Phase 1 B1 (lines 319-324 above), so manager
        # gets the ALLOW side here. T17 admin-rollback NOT in manager
        # template — admin-only via inherited wildcard `/*`.
        # BONUS-35 keyMatch4 route convention `{id:[0-9]+}` applied by
        # downstream router PRs (PR-3C engine + PR-3D-B admin queue + PR-3E
        # magic-link) — Casbin matcher uses `/api/v2/admissions/*/<verb>`
        # wildcard so policy stays stable across router regex tightening.
        {"subject": "{role}", "object": "/api/v2/admissions/*/publish-result",    "action": "POST"},  # T6
        {"subject": "{role}", "object": "/api/v2/admissions/*/waitlist-promote",  "action": "POST"},  # T10
        {"subject": "{role}", "object": "/api/v2/admissions/*/waitlist-reject",   "action": "POST"},  # T11
        # Admission Configuration Console (Phase 1: Admission Path Management)
        # NOTE: Manager can create/edit paths, but ONLY ADMIN can activate/deactivate
        {"subject": "{role}", "object": "/api/admission-config/years", "action": "GET"},  # Academic years
        {"subject": "{role}", "object": "/api/admission-config/paths", "action": "GET"},  # List paths
        {"subject": "{role}", "object": "/api/admission-config/paths", "action": "POST"},  # Create path (draft)
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}", "action": "GET"},  # Get path
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}", "action": "PUT"},  # Update path
        # REMOVED: activate/deactivate - Admin only (Manager creates, Admin approves)
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}/documents", "action": "GET"},  # Resolved docs
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}/validate-activation", "action": "GET"},  # Validate
        # Finance Module - Manager can verify/reject payments, waive fees, apply penalties
        {"subject": "{role}", "object": "/api/finance/dashboard", "action": "GET"},  # Finance overview
        {"subject": "{role}", "object": "/api/fees/{id}/waive", "action": "POST"},  # Waive fee
        {"subject": "{role}", "object": "/api/fees/{id}/recalculate", "action": "POST"},  # Recalculate fee
        {"subject": "{role}", "object": "/api/invoices/{id}/cancel", "action": "PUT"},  # Cancel invoice
        {"subject": "{role}", "object": "/api/invoices/{id}/apply-penalty", "action": "POST"},  # Apply penalty
        {"subject": "{role}", "object": "/api/payments/{id}/verify", "action": "PUT"},  # Verify payment (maker-checker)
        {"subject": "{role}", "object": "/api/payments/{id}/reject", "action": "PUT"},  # Reject payment
        {"subject": "{role}", "object": "/api/accounting/periods/{id}", "action": "GET"},  # View period details
        {"subject": "{role}", "object": "/api/accounting/periods/{id}/summary", "action": "GET"},  # View period summary
        # CTV Management (Phase 1: Collaborator System)
        {"subject": "{role}", "object": "/api/collaborators", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators/{id}", "action": "PUT"},
        {"subject": "{role}", "object": "/api/collaborators/{id}/approve", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}/suspend", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/claims", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators/claims/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators/claims/{id}/review", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}/reactivate", "action": "POST"},
        # Lead validity management (Phase 1: CTV System)
        {"subject": "{role}", "object": "/api/leads/{id}/validity", "action": "POST"},
        # Commission Management (Phase 2: CTV Commission System)
        {"subject": "{role}", "object": "/api/admin/commission-policies", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commission-policies", "action": "POST"},
        {"subject": "{role}", "object": "/api/admin/commission-policies/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commission-policies/{id}", "action": "PUT"},
        {"subject": "{role}", "object": "/api/admin/commissions", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}/approve", "action": "POST"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}/reject", "action": "POST"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}/pay", "action": "POST"},
    ]
}

# =============================================================================
# COLLABORATOR TEMPLATE (Phase 1: CTV System)
# NO inheritance from user — standalone permissions
# =============================================================================

COLLABORATOR_TEMPLATE: PolicyTemplate = {
    "display_name": "Collaborator (CTV)",
    "description": "External collaborator: submit leads, view own stats only. No inheritance.",
    "category": "core",
    "policies": [
        # CTV self-service ONLY
        {"subject": "{role}", "object": "/api/ctv/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/leads/submit", "action": "POST"},
        {"subject": "{role}", "object": "/api/ctv/leads/check-phone", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/claims", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/stats", "action": "GET"},
        # CTV Commission (Phase 2)
        {"subject": "{role}", "object": "/api/ctv/commissions", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/commissions/stats", "action": "GET"},
        # Minimal auth-related (NO session management, NO security endpoints)
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
    ]
}

ADMIN_TEMPLATE: PolicyTemplate = {
    "display_name": "Administrator (Full Access)",
    "description": "Complete system access with no restrictions",
    "category": "core",
    "policies": [
        # Wildcard access to everything
        {"subject": "{role}", "object": "/*", "action": ".*"},
    ]
}

# =============================================================================
# CUSTOM ROLE TEMPLATES (Business-specific)
# =============================================================================

AUDITOR_TEMPLATE: PolicyTemplate = {
    "display_name": "Auditor (Report Analyst)",
    "description": "Read-only access to reports, statistics, and activity logs",
    "category": "custom",
    "policies": [
        # Read-only access to analytics
        {"subject": "{role}", "object": "/api/admin/activity-logs", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/statistics", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
    ]
}

LEAD_VIEWER_TEMPLATE: PolicyTemplate = {
    "display_name": "Lead Viewer (Read Only)",
    "description": "View-only access to leads module without modification rights",
    "category": "custom",
    "policies": [
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
    ]
}

USER_MANAGER_TEMPLATE: PolicyTemplate = {
    "display_name": "User Manager",
    "description": "Manage users (create, edit, delete) without lead access",
    "category": "custom",
    "policies": [
        {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        {"subject": "{role}", "object": "/api/admin/users/*", "action": ".*"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{id}", "action": "DELETE"},
    ]
}

BASIC_USER_TEMPLATE: PolicyTemplate = {
    "display_name": "Basic User",
    "description": "Minimal permissions: profile, notifications, sessions, security",
    "category": "core",
    "policies": [
        # Profile access (SELF only - IDOR protected)
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access (SELF only - IDOR protected)
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{id}", "action": "DELETE"},
        # Notification preferences (SELF only)
        {"subject": "{role}", "object": "/api/notifications/preferences", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/preferences", "action": "PUT"},
        {"subject": "{role}", "object": "/api/notifications/preferences/{channel}", "action": "PUT"},
        # Notification event group preferences (SELF only)
        {"subject": "{role}", "object": "/api/notifications/event-groups", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/event-groups", "action": "PATCH"},
        # Sessions (SELF only - manage own sessions)
        {"subject": "{role}", "object": "/api/sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/sessions/{id}", "action": "DELETE"},
        {"subject": "{role}", "object": "/api/sessions/revoke-all", "action": "POST"},
        # Security (SELF only - security settings)
        {"subject": "{role}", "object": "/api/security/login-history", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/active-sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/not-me", "action": "POST"},
        # Admission config (read-only lookup data for all users)
        {"subject": "{role}", "object": "/api/admission-config/subjects", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/methods", "action": "GET"},
        # Q9 #07 Phase E Wave 1 — candidate-facing priority bonus reads.
        # KV preview + UT catalog cho candidate self-fill priority data.
        # Officer/manager/admin inherit through their templates (not via
        # g-rule chain — those have explicit entries in OFFICER_TEMPLATE).
        # Accountant DENY in ACCOUNTANT_TEMPLATE overrides any allow.
        {"subject": "{role}", "object": "/api/v2/admissions/*/preview-priority-kv",    "action": "POST"},
        {"subject": "{role}", "object": "/api/v2/admissions/priority-objects/catalog", "action": "GET"},
        # NOTE: Admission confirmation is now PUBLIC via magic link
        # POST /api/admissions/confirm/{token} - no auth required (token + CCCD = auth)
    ]
}

# =============================================================================
# TEMPLATE REGISTRY
# =============================================================================

POLICY_TEMPLATES: Dict[str, PolicyTemplate] = {
    # Core templates (system roles)
    "admin": ADMIN_TEMPLATE,
    "manager": MANAGER_TEMPLATE,
    "accountant": ACCOUNTANT_TEMPLATE,  # Finance staff
    "officer": OFFICER_TEMPLATE,
    "collaborator": COLLABORATOR_TEMPLATE,  # External CTV
    "user": BASIC_USER_TEMPLATE,

    # Custom templates (business-specific)
    "auditor": AUDITOR_TEMPLATE,
    "lead_viewer": LEAD_VIEWER_TEMPLATE,
    "user_manager": USER_MANAGER_TEMPLATE,
}

# =============================================================================
# SYSTEM ROLES (Cannot be deleted or modified)
# =============================================================================

SYSTEM_ROLES = [
    {
        "name": "role:admin",
        "display_name": "Administrator",
        "description": "Full system access with all permissions",
        "is_system_role": True,
        "template_id": "admin",
    },
    {
        "name": "role:manager",
        "display_name": "Manager",
        "description": "Manage users and leads with elevated permissions",
        "is_system_role": True,
        "template_id": "manager",
    },
    {
        "name": "role:accountant",
        "display_name": "Accountant",
        "description": "Finance staff: record payments, issue invoices, verify payments",
        "is_system_role": True,
        "template_id": "accountant",
    },
    {
        "name": "role:officer",
        "display_name": "Officer",
        "description": "Admission consultant with lead management capabilities",
        "is_system_role": True,
        "template_id": "officer",
    },
    {
        "name": "role:collaborator",
        "display_name": "Collaborator",
        "description": "External collaborator: submit leads, view own stats",
        "is_system_role": True,
        "template_id": "collaborator",
    },
    {
        "name": "role:user",
        "display_name": "User",
        "description": "Basic user with minimal permissions",
        "is_system_role": True,
        "template_id": "user",
    },
]

# =============================================================================
# CRITICAL POLICIES (Cannot be deleted - will lock system)
# =============================================================================

CRITICAL_POLICIES = [
    # Admin wildcard access - removing this locks all admins out
    ("role:admin", "/*", ".*"),
]


def get_template(template_id: str) -> PolicyTemplate:
    """
    Get a policy template by ID.

    Args:
        template_id: Template identifier (e.g., "officer", "manager")

    Returns:
        PolicyTemplate dict

    Raises:
        KeyError: If template not found
    """
    return POLICY_TEMPLATES[template_id]


def apply_template(template_id: str, role: str) -> List[PolicyRule]:
    """
    Apply a template to a specific role, replacing ``{role}`` placeholder.

    Each rule is normalized to a 4-field shape (``subject``, ``object``,
    ``action``, ``eft``). Source rules that omit ``eft`` get the safe
    default ``"allow"`` so the seed code path produces canonical Casbin
    rows for the deny-first ``auth_model.conf`` introduced in B1.

    Args:
        template_id: Template identifier (e.g., "officer", "manager").
        role: Role subject (with prefix, e.g., ``"role:custom"``).

    Returns:
        List of ``PolicyRule`` dicts with ``{role}`` substituted and
        ``eft`` populated.

    Example:
        >>> apply_template("officer", "role:custom")
        [
            {"subject": "role:custom", "object": "/api/leads",
             "action": "GET", "eft": "allow"},
            ...
        ]
    """
    template = get_template(template_id)
    policies: List[PolicyRule] = []

    for policy in template["policies"]:
        policies.append({
            "subject": policy["subject"].replace("{role}", role),
            "object": policy["object"],
            "action": policy["action"],
            "eft": policy.get("eft", "allow"),
        })

    return policies


def is_system_role(role: str) -> bool:
    """
    Check if a role is a system role (cannot be deleted).

    Args:
        role: Role name (e.g., "role:admin")

    Returns:
        True if system role, False otherwise
    """
    return any(r["name"] == role for r in SYSTEM_ROLES)


def is_critical_policy(subject: str, obj: str, action: str) -> bool:
    """
    Check if a policy is critical (cannot be deleted).

    Args:
        subject: Policy subject (e.g., "role:admin")
        obj: Policy object (e.g., "/*")
        action: Policy action (e.g., ".*")

    Returns:
        True if critical policy, False otherwise
    """
    return (subject, obj, action) in CRITICAL_POLICIES


# =============================================================================
# FEATURE-BASED PERMISSION MAP (Business-Level Abstraction)
# =============================================================================

class FeatureDefinition(TypedDict):
    """Type definition for a feature permission set."""
    display_name: str
    policies: List[PolicyRule]


FEATURE_MAP: Dict[str, FeatureDefinition] = {
    "view_leads": {
        "display_name": "Xem Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "GET"},
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        ]
    },
    "edit_leads": {
        "display_name": "Sửa Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "PUT"},
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "PATCH"},
        ]
    },
    "create_leads": {
        "display_name": "Tạo Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "POST"},
        ]
    },
    "delete_leads": {
        "display_name": "Xóa Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "DELETE"},
        ]
    },
    "restore_leads": {
        "display_name": "Khôi phục Leads đã xóa",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{id}/restore", "action": "POST"},
        ]
    },
    "manage_users": {
        "display_name": "Quản lý Users",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
            {"subject": "{role}", "object": "/api/admin/users/*", "action": ".*"},
        ]
    },
    "view_reports": {
        "display_name": "Xem Báo cáo",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/statistics", "action": "GET"},
            {"subject": "{role}", "object": "/api/admin/activity-logs", "action": "GET"},
        ]
    },
    "manage_notifications": {
        "display_name": "Quản lý Thông báo",
        "policies": [
            {"subject": "{role}", "object": "/api/notifications", "action": ".*"},
            {"subject": "{role}", "object": "/api/notifications/*", "action": ".*"},
        ]
    },
}
