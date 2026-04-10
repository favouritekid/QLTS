# Event & Notification Architecture — Deep Reference

> This is the **deep-dive** reference for the QLTS notification system.
> For quick rules, see `MASTER_ARCHITECTURE.md` PART 7.
> For CLAUDE.md quick reference, see `CLAUDE.md` Section 5.
> For audit gaps + finding tracker, see `EVENT_AUDIT_MATRIX.md`.

---

## 1. Overview

QLTS has two distinct event paths, each serving a different purpose:

1. **Notification Dispatcher** (`SystemEvents` + `dispatch()`/`safe_dispatch()`) — post-commit best-effort notifications to users via browser, email, Zalo, SMS.
2. **Lead Pipeline Projection** (`AdmissionEventProjection` + `lead_admission_sync.py`) — in-transaction atomic state sync between admission profiles and lead pipeline.

These are NOT interchangeable. See `MASTER_ARCHITECTURE.md` PART 7 Section 7.5 for why.

**Four primitives** of the notification path (see PART 7 Section 7.1):
1. `SystemEvents` enum (`app/core/events.py`) — event name namespace
2. `EventDefinition` catalog (`app/core/event_catalog.py`) — code-owned metadata entries
3. `notification_rule` DB table — admin-mutable routing rules
4. `dispatch()` / `safe_dispatch()` (`app/services/notification_dispatcher.py`) — the only publish APIs

**Six-row decision tree** for choosing which function: see PART 7 Section 7.2.

---

## 2. Component Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                     CODE-OWNED (deploy-time)                         │
│                                                                      │
│  events.py              event_catalog.py          notification_      │
│  ┌─────────────┐        ┌─────────────────┐       dispatcher.py      │
│  │ SystemEvents │        │ EventDefinition  │       ┌─────────────┐   │
│  │ enum         │───────>│ catalog          │──────>│ dispatch()   │   │
│  └─────────────┘        │ classification   │       │ safe_dispatch│   │
│                         │ resolvers        │       └──────┬───────┘   │
│                         │ channels         │              │           │
│                         │ dedup template   │              │           │
│                         │ link strategy    │              │           │
│                         └─────────────────┘              │           │
├──────────────────────────────────────────────────────────┼───────────┤
│                      DB-OWNED (runtime)                  │           │
│                                                          v           │
│  notification_rule         notification_rule_loader.py               │
│  ┌──────────────┐          ┌──────────────────────┐                  │
│  │ DB table rows │────────>│ get_rule_for_event()  │                  │
│  │ (admin edit)  │         │ (line 560, cached)    │                  │
│  └──────────────┘          └──────────┬───────────┘                  │
│                                       │                              │
│                                       v                              │
│  notification_resolvers.py     notification_channels/                │
│  ┌──────────────────────┐      ┌──────────────────────────┐          │
│  │ BaseResolver (line 34)│      │ browser_channel.py       │          │
│  │ LeadOwnerResolver    │      │ email_channel.py         │          │
│  │ UnitStaffResolver    │─────>│ zalo_channel.py          │          │
│  │ UnitManagersResolver │      │ sms_channel.py           │          │
│  └──────────────────────┘      └──────────────────────────┘          │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ Dedup: notification_dispatcher._apply_deduplication()        │    │
│  │        + Redis cooldown keys (notif:cooldown:*)              │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### Key files

| File | Role | Key line |
|------|------|----------|
| `app/core/events.py` | SystemEvents enum | All cross-module event names |
| `app/core/event_catalog.py` | EventDefinition metadata | Code-owned half of each event |
| `app/services/notification_dispatcher.py` | `dispatch()` + `safe_dispatch()` | L447, L1602 |
| `app/services/notification_rule_loader.py` | DB rule lookup (cached) | `get_rule_for_event()` L560 |
| `app/services/notification_resolvers.py` | Recipient resolution | `BaseResolver` L34 |
| `app/services/notification_channels/` | Channel delivery (browser/email/Zalo/SMS) | directory |
| `app/services/notification_rule_crud_service.py` | Admin CRUD for rules | import catalog L17 |
| `app/core/admission_event_mapping.py` | Lead projection definitions | Admission → Lead state mappings |
| `app/services/lead_admission_sync.py` | Lead projection executor | inline sync |

---

## 3. Full Dispatch Flow (ASCII Trace)

```
Caller (service/router)
  │
  ├── dispatch(db, event, payload, dedupe_key?)
  │     │
  │     ├── 1. get_event(event) → EventDefinition from catalog
  │     │     └── if retired or missing → log + return ([], None)
  │     │
  │     ├── 2. get_rule_for_event(db, event) → NotificationRule from DB
  │     │     └── if no enabled rule → log.error "No enabled DB rule" + return ([], None)
  │     │     └── ⚠️ THIS IS THE SILENT FAILURE TRAP — no exception raised
  │     │
  │     ├── 3. For each action in rule.actions:
  │     │     ├── deserialize_resolver(action) → BaseResolver subclass
  │     │     ├── resolver.resolve(db, payload) → [user_ids]
  │     │     ├── filter by notification_preference (opt-out)
  │     │     └── filter by dedup key (prevent duplicates)
  │     │
  │     ├── 4. Bulk insert Notification + NotificationDelivery rows
  │     │     └── db.flush() (NOT commit — caller owns transaction)
  │     │
  │     └── 5. Build post_commit_callback:
  │           └── callback → socket.io emit + enqueue email/Zalo worker
  │
  ├── return (notification_ids, callback)
  │
  │   [Caller: await db.commit()]     ← business data + notification rows
  │   [Caller: await callback()]      ← post-commit side effects
  │
  └── Done
```

---

## 4. Lead Projection Flow (ASCII Trace)

```
Admission Service (e.g., approve_profile)
  │
  ├── Business mutation (profile.status = "approved")
  │
  ├── sync_lead_from_admission(db, profile, ...)    ← inline call, same txn
  │     │
  │     ├── get_projection(old_status, new_status) → EventProjection
  │     │     └── from admission_event_mapping.py (20 definitions)
  │     │
  │     ├── Update lead fields (status, stage, phase, substage)
  │     │
  │     ├── Create LeadStatusHistory row
  │     │
  │     └── return (no callback — all in same transaction)
  │
  ├── await db.flush()
  │
  └── [Router: await db.commit()]     ← business + projection committed atomically
```

---

## 5. Worked Examples

### Example 1: Lead assigned via `dispatch()` (atomic)

**File**: `lead_service.py:1163-1190`

```python
# Inside begin_nested() savepoint for atomic dispatch
async with db.begin_nested():
    # ... business logic ...
    notif_ids, notif_cb = await dispatch(
        db=db,
        event=SystemEvents.LEAD_ASSIGNED,
        payload={"lead_id": lead.id, "officer_id": officer.id, ...},
        dedupe_key=f"lead_assigned:{lead.id}:{officer.id}",
    )
# Router commits outer transaction, then awaits callback
```

### Example 2: Admission bulk approve via `safe_dispatch()` (router post-commit)

**File**: `admissions.py:362`

```python
# Router — business commit already done
await safe_dispatch(
    db=db,
    event=SystemEvents.APPLICATION_STATUS_CHANGED,
    payload={...},
)
```

### Example 3: Admission profile create via projection sync (in-transaction)

**File**: `admission_service.py:1551-1560`

```python
# Inline sync — same transaction as profile creation
from .lead_admission_sync import sync_lead_from_admission
await sync_lead_from_admission(
    db=db,
    profile=new_profile,
    changed_by_user_id=current_user.id,
    reason="Admission profile created",
)
```

---

## 6. How to Add a New Event (Checklist)

1. **Add enum member** to `SystemEvents` in `app/core/events.py` with payload schema docstring.
2. **Add `EventDefinition`** to `app/core/event_catalog.py` — set classification, resolvers, channels, dedup template, link.
3. **Seed `notification_rule` row** via `app/scripts/sync_notification_rules.py`. **Without this, event is silent.**
4. **Call `dispatch()`** (service row #1) or **`safe_dispatch()`** (router/closure row #2/#5) at the call site. Consult the decision tree in `MASTER_ARCHITECTURE.md` PART 7 Section 7.2.
5. **Add unit test** asserting dispatch is invoked with expected event + payload.
6. **Verify end-to-end**: check `notification_delivery` rows, check channel logs.

---

## 7. How to Debug a Missing Notification

If a notification should fire but doesn't, check in order:

1. **Rule exists?** `SELECT * FROM notification_rule WHERE event_type = '<YOUR_EVENT>' AND is_enabled = true;` — no row = silent no-op.
2. **Catalog entry?** `from app.core.event_catalog import get_event; print(get_event(SystemEvents.YOUR_EVENT))` — `None` = not in catalog.
3. **Resolver returns users?** Add temp logging in the resolver's `resolve()` method. Empty list = no recipients.
4. **Preference opt-out?** `SELECT * FROM notification_preference WHERE user_id = <USER> AND event_group = '<GROUP>';` — user may have opted out of this channel.
5. **Dedup blocked?** Check Redis for `notif:cooldown:<dedupe_key>:<user_id>` keys. TTL = 1 hour default. Same notification won't fire twice within the window.
6. **Channel delivery failed?** Check `notification_delivery` table for status = `failed` or `dead_lettered`. Check celery-worker logs for channel-specific errors.
7. **Router forgot callback?** If using `dispatch()`, the router MUST `await callback()` after commit. Forgetting this line silently drops all notifications — no error, no log.
8. **`classification` = `internal_future`?** Catalog entry with this classification is silently skipped (domain-only emission with no user notification). Check `event_catalog.py` for the entry's `notification_class`.

---

## 8. Why No DomainEvent System?

QLTS originally scaffolded a `DomainEvent` system in `app/core/finance_events.py` (18 dataclasses + `emit_event()` + `@event_handler` decorator + `ProcessedEvent` table for idempotency). After 5 months of zero production usage, this was removed per **ADR-001** (`docs/adr/ADR-001-remove-finance-events.md`).

The `SystemEvents` + dispatcher path fulfills all production notification needs. The `ProcessedEvent` table's idempotency tracking role is served by Redis dedupe keys in the dispatcher.

If event sourcing becomes a real requirement, build with proper infrastructure (Kafka/RabbitMQ/EventStoreDB) rather than in-process scaffolding.

---

## 9. Cross-References

| Document | Purpose |
|---|---|
| `MASTER_ARCHITECTURE.md` PART 7 | Canonical rules, decision tree, target-state |
| `CLAUDE.md` Section 5 | Quick reference for agents/devs |
| `EVENT_AUDIT_MATRIX.md` | Audit findings, gap tracker, priority matrix |
| `app/services/NOTIFICATION_ARCHITECTURE.md` | Deep-dive internals (guardrail table, phase history) |
| `NOTIFICATION_PHASE_WORKLOG.md` | Historical worklog (do NOT update) |
| `docs/adr/ADR-001-remove-finance-events.md` | Decision record for DomainEvent removal |
| `docs/FINANCE_MODULE_DESIGN.md` | **HISTORICAL** — original finance module design. Drifted at 6 layers from current code (event architecture, data contracts, business flow, module structure, project status, tooling). Useful for business vocabulary only. A doc-level historical banner will be added in Phase B1. |
