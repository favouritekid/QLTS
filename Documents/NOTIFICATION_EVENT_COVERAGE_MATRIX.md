# Notification Coverage Matrix

Date: 2026-04-04
Source of truth:
- `Backend_FastAPI/app/core/event_catalog.py`
- `Documents/NOTIFICATION_REFACTOR_BLUEPRINT.md`

## Coverage Status

| Module | Current event coverage | Status | Notes |
|---|---|---|---|
| Lead | `lead_assigned`, `lead_assignment_failed`, `lead_reassigned`, `lead_status_changed`, `lead_created`, `lead_deleted`, `lead_restored`, `lead_imported`, `officer_availability_changed` | Covered | `lead_updated` is intentionally `broadcast_only`, not admin-configurable |
| Consultation | `consultation_created`, `consultation_updated`, `consultation_deleted`, `consultation_reminder` | Covered | Immediate fix remains for consultation -> `lead_status_changed` cascade on real pipeline change |
| Admission | `application_created`, `application_status_changed`, `application_deleted` | Partial | Immediate fix remains for `application_status_changed / overridden`; `withdrawn` is out of scope by design |
| Finance | `payment_received`, `payment_verified` | Partial | `payment_overdue` remains planned backlog; `fee_calculated`, `invoice_issued`, `payment_rejected`, `refund_processed`, `fee_fully_paid`, `application_fee_paid` are out of scope by design |
| CTV | `ctv_claim_submitted`, `ctv_claim_approved`, `ctv_claim_rejected`, `ctv_approved`, `ctv_suspended`, `ctv_commission_created`, `ctv_attribution_expiring`, `ctv_attribution_expired`, `ctv_weekly_summary` | Covered | `ctv_lead_converted` is intentionally `internal_future` |
| System | `system_alert`, `holiday_calendar_incomplete`, `system_announcement`, `user_role_changed`, `user_deactivated` | Covered | Admin/internal user notification only |
| Security | `suspicious_login` | Covered | User-facing security event |
| Pipeline | `pipeline_config_updated` | Covered | Admin/internal event |
| Organization | `unit_*`, `program_*`, `offering_*` | Broadcast only | Real-time broadcast, not admin-configurable notification rules |
| Dorm | `dorm_fee_created`, `dorm_room_assigned`, `dorm_maintenance_request` | Not user-covered | All are `internal_future` pending Dorm module work |
| Asset | `asset_maintenance_alert`, `asset_checked_out` | Not user-covered | All are `internal_future` pending Asset module work |

## Catalog Totals

| Classification | Count |
|---|---:|
| `user` | 34 |
| `broadcast_only` | 10 |
| `internal_future` | 7 |
| Total `SystemEvents` in catalog | 51 |

## Module Verdict

### Fully covered now
- Lead
- Consultation
- CTV
- System
- Security
- Pipeline

### Intentionally broadcast-only
- Organization (`unit_*`, `program_*`, `offering_*`)
- `lead_updated`

### Partially covered, follow-up still needed
- Admission
- Finance

### Not yet implemented as real notification modules
- Dorm
- Asset

## Official scope decision

See:
- `Documents/NOTIFICATION_SCOPE_DECISION.md`

### Immediate fixes

| ID | Gap | Module |
|---|---|---|
| A16 | `application_status_changed / overridden` dispatch missing | Admission |
| GAP-C1/C2/C3 | Consultation -> `lead_status_changed` cascade | Consultation |

### Planned backlog

| ID | Gap | Module |
|---|---|---|
| F3 | `payment_overdue` beat task + promotion | Finance |

### Out of scope by design

| Item | Module |
|---|---|
| `application_status_changed / withdrawn` | Admission |
| `fee_fully_paid` | Finance |
| `payment_rejected` | Finance |
| `invoice_issued` | Finance |
| `refund_processed` | Finance |
| `fee_calculated` | Finance |
| `application_fee_paid` | Finance |
| `ctv_lead_converted` | CTV |
| Dorm event promotion | Dorm |
| Asset event promotion | Asset |

## Template Seeding Guidance

Important:
- `notification_template` has no `enabled` / `inactive` field.
- A seeded template is inert until a `notification_rule` or `notification_action.template_code` actually references it.
- The safest workflow is:
  1. seed the template library
  2. review in admin UI / DB
  3. attach templates to rules later
  4. keep any draft rules disabled if you want an explicit inactive review state

## Recommended template library split

1. Baseline internal templates
- One `system` template for every current `notification_class="user"` event in catalog
- Supports browser/email defaults and gives admins a reusable starting point

2. ZNS draft templates
- Only for events that already make sense for external recipient resolution:
  - `payment_verified`
  - `application_status_changed`
  - `consultation_reminder`

3. Do not pre-seed ZNS templates for
- `broadcast_only` events
- `internal_future` events
- broad internal-only events like `system_alert`
- lead-owner/internal workflow events such as `lead_assigned`
- collaborator/internal workflow events such as `ctv_claim_approved`
