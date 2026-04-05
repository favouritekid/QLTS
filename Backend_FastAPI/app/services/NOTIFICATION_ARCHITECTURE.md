# Notification Architecture Guardrails

Quick reference for adding or modifying notification features.
For full system architecture, see `MASTER_ARCHITECTURE.md`.

---

## Layer Boundaries

```
Router (HTTP thin layer)
  |  Depends: auth, RBAC, IDOR via deps.py
  |  Calls: service functions only
  |  Owns: db.commit()
  |
Service (business logic, no FastAPI imports)
  |  Calls: repository, raises domain exceptions
  |  Owns: db.flush() — never db.commit()
  |
Repository (data access, SQLAlchemy ORM)
  |  Owns: queries, db.flush()
```

**Rules:**
- Router NEVER instantiates a repository directly for notification business logic
- Service NEVER raises `HTTPException` — use `BusinessRuleViolation`, `ResourceNotFoundError`, etc.
- Service returns `(result, post_commit_callback)` when side effects follow commit

---

## When to use `dispatch()` vs `safe_dispatch()`

| Function | Transaction | Error handling | When to use |
|----------|-------------|----------------|-------------|
| `dispatch()` | Caller owns | Caller handles | Service needs atomic commit with business data, or needs the callback |
| `safe_dispatch()` | Self-commits | Swallows all errors | Router after-commit for non-critical notifications |

**Rule of thumb:** If the notification is the *reason* for the endpoint, use `dispatch()`.
If the notification is a *side effect* of another action (e.g., admissions status change), use `safe_dispatch()`.

---

## Adding a New Event

Checklist for every new `SystemEvents` entry:

1. **Define event** in `app/core/events.py` with payload docstring
2. **Add seed rule** in `app/scripts/reset_notification_rules_dev.py`
   - Choose resolver groups: `lead_owner`, `all_admins`, `unit_managers`, `specific_users`, `collaborator_user`
   - Choose channels: `browser`, `email`, `zalo`
3. **Emit in router** using `safe_dispatch()` (typical) or service using `dispatch()`
   - Include `dedupe_key` to prevent duplicates
   - Include `application_id` / `lead_id` for source traceability
4. **Verify source extraction** — `_extract_source_from_payload()` maps payload keys to `(source_type, source_id)`:
   - `application_id` -> `admission_profile`
   - `lead_id` -> `lead`
   - `collaborator_id` -> `collaborator`
5. **Consider:**
   - Does this event need external recipients? (requires consent)
   - Does this event skip user preference? (`skip_preference_check=True` for critical alerts)
   - Does this event have a cooldown concern? (reuse unique `dedupe_key` pattern)
   - Does this event also need `LEAD_STATUS_CHANGED`? (admissions paths)

---

## Deduplication

- **Internal (per-user):** `dedupe_key + channel + user_id` checked via `NotificationDeliveryRepository.find_existing_user_ids_by_dedupe()`
- **External (per-destination):** `dedupe_key + channel + destination` checked via `NotificationDeliveryRepository.exists_external_delivery()`
- **Cooldown:** Redis key `notif:cooldown:{event}:{uid}:{channel}:{dedupe_key}:step{step}` with configurable TTL

---

## File Map

| Concern | File |
|---------|------|
| Event enum + payload docs | `app/core/events.py` |
| Dispatch orchestration | `app/services/notification_dispatcher.py` |
| Delivery lifecycle | `app/services/notification_delivery_service.py` |
| Delivery analytics | `app/services/notification_delivery_ops_service.py` |
| Consent management | `app/services/notification_consent_service.py` |
| Quota + health | `app/services/notification_quota_service.py` |
| Seed rules | `app/scripts/reset_notification_rules_dev.py` |
| Resolvers | `app/services/notification_resolvers.py` |
| Rule CRUD | `app/services/notification_rule_crud_service.py` |
| Circuit breaker | `app/services/notification_circuit_breaker.py` |
| Worker tasks | `app/tasks/delivery_tasks.py` |
