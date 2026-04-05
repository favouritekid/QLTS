# Notification Plan + Spec Addendum

> Status: Active
> Updated: 2026-03-25
> Scope: Applies after completion of tasks 1.1-1.6
> Purpose: Align the approved plan/spec with the real codebase before continuing with tasks 1.7+

---

## 1. Why this addendum exists

The approved architecture direction is still valid, but hard review of the current codebase shows several source-of-truth mismatches that must be frozen now so the team does not continue implementing from assumptions.

This addendum does **not** replace the approved plan/spec.
It narrows semantics, documents legacy aliases, and marks which capabilities are real, planned, deprecated, or misleading in the current system.

---

## 2. Decisions that remain unchanged

These decisions stay as-is:

- `dispatch()` / `safe_dispatch()` is the production notification entrypoint.
- Canonical channels are `browser`, `email`, `zalo`, `sms`.
- Legacy `socket` is a read-compat alias for `browser`, but new writes must use `browser`.
- Per-channel preference filtering is the correct direction.
- `create_notification()` and `execute_notification_workflow()` are deprecated surfaces.
- Future Zalo work continues on top of the Notification 2.0 dispatcher path, not the legacy workflow path.

---

## 3. Source of truth hierarchy

The notification system now has an explicit hierarchy. Team members must not treat all registries as equal.

| Layer | File | Role | Status |
|---|---|---|---|
| Event namespace | `app/core/events.py` | Canonical notification event names (`SystemEvents`) | Source of truth |
| Group mapping | `app/core/event_groups.py` | Maps each `SystemEvents` value to a preference group | Mandatory |
| Runtime defaults | `app/services/notification_registry.py` | Resolver, channels, template defaults, link defaults | Mandatory |
| DB override | `app/services/notification_rule_loader.py` + `NotificationRule` | Runtime override of registry values | Override layer |
| Channel implementation | `app/services/notification_channels/__init__.py` | Real implemented transports | Runtime truth for delivery capability |
| Admin/frontend metadata | `app/core/event_metadata.py` | UI contract for forms, variables, categories | Derived contract, not primary truth |

Rules:

1. An event must not be emitted as a user notification unless it exists in `SystemEvents`.
2. Every emitted notification event must exist in `EVENT_GROUP_MAPPING`.
3. Every emitted notification event must have runtime support via `NOTIFICATION_REGISTRY`, unless it is explicitly marked `broadcast_only`.
4. Admin-manageable events must also exist in `EVENT_METADATA_REGISTRY`.
5. Metadata must not advertise a channel that the runtime cannot actually deliver, unless it is explicitly marked `planned` and gated in UI.

---

## 4. Two buses, not one

The codebase contains two different buses and they must stay conceptually separate.

| Bus | Main files | Purpose |
|---|---|---|
| User notification bus | `app/core/events.py` (`SystemEvents`), `app/services/notification_dispatcher.py` | Persisted notifications and channel delivery |
| Transport/socket bus | `app/core/events.py` (`TransportEvents`), `app/core/dispatcher.py`, socket handlers | Low-level realtime/transport events |

Clarification:

- `TransportEvents.USER_PROFILE_UPDATED` is **not** a replacement for a user-facing notification event.
- If the business needs a real user notification for admin profile updates, a new `SystemEvents.USER_PROFILE_UPDATED` may be added later.
- Do not invent ad-hoc `SystemEvents` names in routers or services without updating enum + group + runtime + metadata.

---

## 5. Domain naming clarification

### 5.1 Legacy `APPLICATION_*` namespace

The current business domain uses `Admission` / `AdmissionProfile`.
However, the notification system still uses the older `APPLICATION_*` namespace.

This addendum freezes the following interpretation:

- `APPLICATION_*` is a **legacy notification alias** for `AdmissionProfile`.
- This alias is allowed for backward compatibility.
- New code must not treat `Application` as a separate active domain entity.

Required code comment/doc note:

- In `app/core/events.py`
- In `app/core/event_metadata.py`
- In `app/services/notification_registry.py`

Each of those areas should document:

> `APPLICATION_*` is a legacy notification namespace for AdmissionProfile compatibility.

### 5.2 Semantic narrowing

The following semantic rules are now mandatory:

| Event | Meaning now | Allowed usage |
|---|---|---|
| `APPLICATION_CREATED` | Admission profile created | Only creation |
| `APPLICATION_STATUS_CHANGED` | Admission status transition | Approved, rejected, confirmed, enrolled, resubmitted, etc. |
| `APPLICATION_DOCUMENTS_UPDATED` | Admission documents changed | Document updates only |
| `APPLICATION_DELETED` | Admission profile deleted | Delete only |

Do not reuse `APPLICATION_CREATED` for approval or enrollment flows.

---

## 6. Capability status matrix

| Capability | Code exists | Runtime used in production path | Decision |
|---|---|---|---|
| `NotificationRule.template_id` override | Yes | Yes | Supported |
| `NotificationAction` multi-step workflow | Yes | No | Future / hidden capability |
| `create_notification()` | Yes | Deprecated | Keep temporarily, no new callers |
| `execute_notification_workflow()` | Yes | Deprecated | Keep temporarily, no new callers |
| `browser` channel | Yes | Yes | Supported |
| `email` channel | Yes | Yes | Supported |
| `zalo` channel | Enum + metadata only | No | Planned, not implemented |
| `sms` channel | Enum + metadata only | No | Planned, not implemented |

Implication:

- `NotificationAction` must not be presented as a fully supported production feature in docs/UI until `dispatch()` can execute actions.
- `zalo` and `sms` must be treated as planned channels, not live channels, until channel adapters exist and are wired into `CHANNEL_REGISTRY`.

---

## 7. Event inventory decisions

### 7.1 Keep

| Event group | Decision | Notes |
|---|---|---|
| `LEAD_*` | Keep | Normal business notifications |
| `CONSULTATION_*` | Keep | `CONSULTATION_REMINDER` remains internal officer reminder |
| `APPLICATION_*` | Keep with legacy note | Alias for `AdmissionProfile` |
| `PAYMENT_RECEIVED` | Keep | Internal payment-recorded semantic |
| `PAYMENT_OVERDUE` | Keep | Finance overdue notification |
| `PAYMENT_VERIFIED` | Keep | Verified payment semantic for future external notification |
| `SYSTEM_ALERT` | Keep | Operational/system message |
| `SYSTEM_ANNOUNCEMENT` | Keep | Broad informational notice |
| `USER_ROLE_CHANGED` | Keep | User account change |
| `USER_DEACTIVATED` | Keep | User account change |
| `PIPELINE_CONFIG_UPDATED` | Keep | Operational/admin change |
| `OFFICER_AVAILABILITY_CHANGED` | Keep | Lead-routing operational event |
| `SUSPICIOUS_LOGIN` | Keep | Security notification |
| `CTV_*` | Keep | But metadata/resolver parity must be completed |

### 7.2 Keep but fix

| Event | Problem | Required fix |
|---|---|---|
| `HOLIDAY_CALENDAR_INCOMPLETE` | Missing group parity risk | Must exist in group mapping, runtime registry, and metadata together |
| `PAYMENT_VERIFIED` | Current recipient semantics do not match intended business semantics | Freeze recipient contract before Epic 2-3 |
| `APPLICATION_CREATED` | Being overloaded in admissions flows | Restrict to create-only usage |

### 7.3 Remove from notification bus unless promoted properly

| Event group | Current state | Decision |
|---|---|---|
| `UNIT_*` | Emitted by organization admin flows, but not fully modeled as user notification runtime | Remove from user notification bus unless business confirms user-facing use case |
| `PROGRAM_*` | Same as above | Same |
| `OFFERING_*` | Same as above | Same |

If the business later wants these as real user notifications, they must be promoted properly through:

1. `SystemEvents`
2. `EVENT_GROUP_MAPPING`
3. `NOTIFICATION_REGISTRY`
4. `EVENT_METADATA_REGISTRY`
5. tests

Until then, they should be treated as domain/audit/broadcast events, not part of the user notification contract.

---

## 8. Spec delta for tasks after 1.6

### 8.1 Task planning impact

No major re-plan is required.
However, tasks after 1.6 must inherit these additional constraints:

| Area | Delta |
|---|---|
| Event semantics | `APPLICATION_*` means `AdmissionProfile`; `APPLICATION_CREATED` is create-only |
| Metadata | Must be treated as derived from runtime truth, not independent design input |
| UI/admin | Do not oversell `NotificationAction`, `zalo`, or `sms` as live capabilities |
| Zalo future work | Must target the dispatcher path only |
| Security/ops alerts | `TransportEvents` and `SystemEvents` must not be mixed |

### 8.2 New mandatory acceptance criteria

The following acceptance criteria apply to future notification tasks:

1. No new notification event may be added without:
   - `SystemEvents`
   - `EVENT_GROUP_MAPPING`
   - runtime registry entry
   - metadata entry if admin-managed
2. No router/service may reference a made-up `SystemEvents` member.
3. No doc or UI may imply `Application` is the active domain if the actual entity is `AdmissionProfile`.
4. No doc or UI may present `NotificationAction` as production-ready until runtime execution exists.
5. No channel may appear as "available" unless it is either:
   - implemented in runtime, or
   - explicitly marked planned and gated

---

## 9. Required cleanup / removal plan

### 9.1 Keep for now, but deprecate harder

| Surface | Current status | Action |
|---|---|---|
| `app/services/notification_service.py:create_notification()` | Deprecated | Keep warning, remove direct callers, later delete |
| `app/services/notification_workflow.py:execute_notification_workflow()` | Deprecated | Keep warning, later archive/delete |
| legacy workflow/action mental model in docs | Misleading | Replace with dispatcher-first docs |

### 9.2 Hide or downgrade in docs/UI

| Surface | Why |
|---|---|
| `NotificationAction` | Modeled in DB but not used by production runtime |
| `zalo` channel | Planned only |
| `sms` channel | Planned only |

---

## 10. Recommended parity checks

Add automated parity checks in tests or CI:

1. Every emitted `SystemEvents` value must exist in `EVENT_GROUP_MAPPING`.
2. Every emitted user notification event must have runtime config.
3. Every admin-manageable event must have metadata.
4. Metadata channels must be a subset of implemented or explicitly gated channels.
5. Deprecated entrypoints must have no non-test production callers.

---

## 11. Immediate next-step guidance

For work after task 1.6:

- Continue the current plan.
- Do **not** rewrite the whole architecture plan.
- Treat this addendum as the binding clarification layer.
- Before Epic 2-3 begins, freeze:
  - `PAYMENT_VERIFIED` recipient semantics
  - final status of `UNIT_* / PROGRAM_* / OFFERING_*`
  - UI behavior for planned-only channels

---

## 12. Summary

The approved direction remains correct.
What changed is not the architecture, but the precision of the contract:

- `APPLICATION_*` is legacy naming for `AdmissionProfile`
- runtime truth beats metadata
- transport events are not notification events
- `NotificationAction` is not a live production capability yet
- organization events must either be promoted properly or removed from the user notification contract

This document should be read together with:

- `Documents/notification-system-guide.md`
- `Backend_FastAPI/ZALO_INTEGRATION_PLAN.md`
- `Backend_FastAPI/NOTIFICATION_EXECUTION_CHECKLIST.md`

When there is a conflict, this addendum takes precedence for current implementation work.
