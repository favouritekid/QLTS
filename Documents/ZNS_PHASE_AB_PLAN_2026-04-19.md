# ZNS Integration — Phase A+B Implementation Plan

**Created**: 2026-04-19
**Scope**: Wire ZNS template `333738` (Nhắc lịch hẹn) into event `consultation_reminder` end-to-end via 1 PR, 2 commits.
**Owner**: backend + notification
**Status**: Ready to start

---

## 1. Goals

### In scope

**Commit A — Foundation scaffold** (additive, behavior-neutral except settings extraction):
- Reusable helpers: `datetime_helpers.format_vn_date/datetime`, `id_helpers.format_lead_code/profile_code/booking_code`.
- Add 4 settings: `SCHOOL_ADDRESS` (default = existing email address), `SCHOOL_BANK_NAME`, `SCHOOL_BANK_ACCOUNT`, `SCHOOL_BANK_HOLDER` (bank vars default empty).
- Refactor `email_service.py:77` to read from `settings.SCHOOL_ADDRESS` (multichannel consistency).
- `.env.example` documentation for the 4 new vars.
- Unit tests for utilities.

**Commit B — Wire 333738 to consultation_reminder**:
- Extend `EventPayload.for_consultation_reminder` with 4 new keys (`scheduled_time_vn`, `booking_code`, `lead_code`, `major_name`) via pre-resolved kwargs pattern.
- Eager-load `lead.offering.program` in `notification_tasks.py` before passing to builder.
- Update `event_catalog.py` + `event_metadata.py` (UI admin + parity tests).
- Update parity + payload tests; add 4 new unit tests.
- SQL merge script: JSONB-merge `template_id=333738` + `external_resolver="lead_contact"` into `notification_action.id=63`.

### Non-goals
- No channel content mode change (remains `channel_native`).
- No rule/event creation — `CONSULTATION_REMINDER` + rule 11 + action 63 all exist.
- No Phase C/D/E wiring in this PR (bank info wiring + lead_created + invoice_issued + survey task deferred).
- No Alembic migration — configuration/data change on one existing row only.

---

## 2. Verified context (pre-code research)

| # | Question | Answer |
|---|---|---|
| 1 | `Lead.offering` relationship | `Lead.offering_id` FK → `program_offering.id`; `Lead.offering = relationship("ProgramOffering")` (`app/models/lead.py:199,265`). `ProgramOffering.program = relationship("MajorProgram", back_populates="offerings")` (`program_offering.py:64`). Eager-load: `selectinload(Lead.offering).selectinload(ProgramOffering.program)`. Major name at `lead.offering.program.name`. |
| 2 | `lead_contact` in resolver whitelist | ✅ Confirmed `notification_rule_crud_service.py:23-24` — valid values `{"lead_contact", "admission_contact", "collaborator_contact"}`. |
| 3 | Email address literal | At `email_service.py:77` (NOT :73 as originally stated — :73 is `app_name`). Literal: `"02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk"`. Also referenced allowlist line 104. |
| 4 | `tests/utils/` exists | ✅ With `__init__.py`, `conftest.py`, peer files. Just add new test modules. |
| 5 | SQL migration pattern | `Backend_FastAPI/scripts/` exists with precedent `update_phase_workflow.sql`. Plain `.sql` manually applied. No Alembic data migration required. |
| 6 | Action-level `external_resolver` override rule-level | ✅ Confirmed `notification_dispatcher.py:580-613, 821-863`. External resolution at Step 6.6 is **additive** per-action. Internal resolution at Step 3 sees `is_external_only = not action.recipient_config and action.config.external_resolver` and skips internal for that action. Rule-level `recipient_config` doesn't conflict — `lead_contact` resolver reads `payload.lead_id` directly. **UPDATE action #63 is correct approach.** |
| 7 | `datetime_helpers.py` exists | ❌ Does NOT exist. Current `app/utils/`: `csv_helpers`, `file_helpers`, `masking`, `exceptions`, `phone_helpers`, `redis_lock`. Create new module. |
| 8 | Admin UI variables source | `notification_rules.py:95` → `get_notifiable_events()` → reads `event_catalog.py`. Parity tests read `event_metadata.py`. **BOTH files must be updated** to avoid drift. |

### Deviations from initial brief
- `event_catalog.py` + `event_metadata.py` live under `app/core/`, not `app/` root.
- Test files live under `tests/unit/` not `tests/api/` (parity line 615, not 618).
- Email literal at `email_service.py:77`, not :73.
- Booking code prefix: plan uses `BK-{id:06d}` (shorter than `CONS-`, simpler). ⚠️ **Decision: confirm with user or keep `CONS-` for semantic clarity.**

---

## 3. Commit A — Foundation scaffold

### Files

| File | Change | Lines |
|---|---|---|
| `app/utils/datetime_helpers.py` | NEW | ~30 |
| `app/utils/id_helpers.py` | NEW | ~15 |
| `app/config.py` | Add 4 Settings fields | ~6 |
| `app/services/email_service.py:77` | Replace literal with `settings.SCHOOL_ADDRESS` | 1 |
| `.env.example` | Document 4 new vars | ~6 |
| `tests/utils/test_datetime_helpers.py` | NEW | ~40 |
| `tests/utils/test_id_helpers.py` | NEW | ~25 |

### Utility specs

**`datetime_helpers.py`:**
```python
def format_vn_date(dt: datetime | None) -> str:
    """DD/MM/YYYY (10 chars, fits Zalo DATE maxLength=20). Empty string if None."""

def format_vn_datetime(dt: datetime | None, *, tz: str = "Asia/Ho_Chi_Minh") -> str:
    """DD/MM/YYYY HH:MM (16 chars). Naive dt treated as UTC then converted."""
```

**`id_helpers.py`:**
```python
def format_lead_code(lead_id: int) -> str:          # "LEAD-000123"
def format_profile_code(profile_id: int) -> str:    # "HS-000123"
def format_booking_code(consultation_id: int) -> str:  # "CONS-000123"
```

### Settings

```python
# app/config.py
SCHOOL_ADDRESS: str = "02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk"
SCHOOL_BANK_NAME: str = ""
SCHOOL_BANK_ACCOUNT: str = ""
SCHOOL_BANK_HOLDER: str = ""
```

### Test strategy

- Helper edge cases: `None` input, naive datetime, timezone-aware, length boundary (<20 chars for date+time).
- ID helpers: zero-padding, prefix correctness, `[:30]` boundary.
- Email regression: existing email tests green (literal default preserved).

### Acceptance

- `docker compose exec backend pytest tests/utils/ -v` green.
- Email-related test suite green unchanged.
- No new pydantic-settings warnings.

---

## 4. Commit B — 333738 reminder wiring

### Files

| File | Change | Lines |
|---|---|---|
| `app/services/notification_payloads.py:244-256` | Extend `for_consultation_reminder` signature + 4 derived keys | ~15 |
| `app/tasks/notification_tasks.py:217-251` | Eager-load `lead.offering.program`, resolve `major_name`, pass as kwarg | ~10 |
| `app/core/event_catalog.py:425-433` | Add 4 `_var` entries to CONSULTATION_REMINDER | ~10 |
| `app/core/event_metadata.py:402-410` | Mirror EventVariable entries | ~10 |
| `tests/unit/test_notification_payloads.py:458-491` | Update `test_exact_keys` + 4 new tests | ~40 |
| `tests/unit/test_notification_parity.py:615` | No matrix change (parity reads keys dynamically) | 0 |
| `scripts/wire_zns_333738_consultation_reminder.sql` | NEW — JSONB merge script | ~20 |

### Payload builder (pure, no ORM)

```python
@staticmethod
def for_consultation_reminder(
    consultation, lead, *,
    minutes_until: int,
    major_name: str = "N/A",   # NEW — pre-resolved by caller
) -> dict:
    return {
        # existing keys unchanged
        "consultation_id": consultation.id,
        "lead_id": lead.id,
        "lead_name": lead.full_name or "Unknown",
        "lead_phone": lead.phone or "",
        "officer_id": lead.assigned_officer_id or consultation.officer_id,
        "scheduled_at": consultation.scheduled_at.isoformat(),
        "minutes_until": minutes_until,
        # NEW keys (derived, pure — no DB access)
        "scheduled_time_vn": format_vn_datetime(consultation.scheduled_at),
        "booking_code": format_booking_code(consultation.id),
        "lead_code": format_lead_code(lead.id),
        "major_name": (major_name or "N/A")[:30],
    }
```

### Task query enrichment

```python
# notification_tasks.py:~217
from sqlalchemy.orm import selectinload
from app.models import Lead, Consultation, ProgramOffering  # ensure imports

query = (
    select(Consultation, Lead)
    .join(Lead, Consultation.lead_id == Lead.id)
    .options(
        selectinload(Lead.offering).selectinload(ProgramOffering.program),
    )
    .where(...)  # existing reminder window filters
)

# After fetching:
for consultation, lead in consultations_with_leads:
    major = (
        lead.offering and lead.offering.program and lead.offering.program.name
    ) or "N/A"
    _, notif_cb = await notification_dispatcher.dispatch(
        db=session,
        event=SystemEvents.CONSULTATION_REMINDER,
        payload=EventPayload.for_consultation_reminder(
            consultation, lead,
            minutes_until=minutes_until,
            major_name=major,  # NEW
        ),
    )
```

### SQL merge script

`Backend_FastAPI/scripts/wire_zns_333738_consultation_reminder.sql`:

```sql
-- Purpose: wire ZNS template 333738 into notification_action.id=63
--          (rule_id=11 consultation_reminder, step=2, channel=zalo).
-- Safe merge: COALESCE handles NULL config; || preserves existing keys.
-- Deploy order: run THIS script BEFORE restarting celery-beat/worker
--               to avoid beat tick with old config.

BEGIN;

UPDATE notification_action
SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object(
    'external_resolver', 'lead_contact',
    'zalo_template_id', 333738,
    'zalo_template_data', jsonb_build_object(
        'schedule_time', '$scheduled_time_vn',
        'customer_name', '$lead_name',
        'address',       '02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk',
        'booking_code',  '$booking_code',
        'ten_nganh_hoc', '$major_name',
        'ma_hoc_vien',   '$lead_code'
    )
)
WHERE id = 63;

-- Verification
SELECT id, rule_id, step, channel, content_mode, config
FROM notification_action
WHERE id = 63;

COMMIT;

-- Rollback (if needed):
--   UPDATE notification_action
--   SET config = config - 'external_resolver' - 'zalo_template_id' - 'zalo_template_data'
--   WHERE id = 63;
```

### Test strategy

- `pytest tests/unit/test_notification_payloads.py -v -k Reminder`: existing + 4 new tests green.
- `pytest tests/unit/test_notification_parity.py -v`: drift tests green.
- `pytest tests/unit/test_notification_contract.py -v`: catalog edits don't break contract.
- Manual: apply SQL to local DB; `SELECT config FROM notification_action WHERE id=63` confirms merge preserves prior keys + adds new.

### New unit tests

1. `test_major_name_from_kwarg` — pass `major_name="Công nghệ thông tin"`, assert it appears in payload.
2. `test_major_name_defaults_na_when_none` — omit kwarg, assert `"N/A"`.
3. `test_major_name_truncated_to_30_chars` — pass 50-char string, assert `[:30]`.
4. `test_scheduled_time_vn_format` — lock output to `%d/%m/%Y %H:%M` exactly.

### Acceptance

- All listed tests green; no drift from metadata parity.
- Local consultation inside 15-min window triggers real ZNS send end-to-end (template 333738 rendered, `notification_delivery.status = 'sent'`).
- `lead.offering.program` is loaded — no lazy-load exception from the task's session.

---

## 5. Deploy procedure (strict order)

1. **Local** — full pytest suite green:
   ```bash
   docker compose exec backend pytest tests/unit/ tests/utils/ -v
   ```

2. **Git** — `git push` feature branch → PR → review → merge to main.

3. **VPS pull**:
   ```bash
   ssh -i ~/.ssh/id_ed25519_qlts root@qlts.tnpc.edu.vn
   cd /opt/qlts && git pull
   ```

4. **Update `.env.production`** on VPS — append:
   ```
   SCHOOL_ADDRESS="02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk"
   SCHOOL_BANK_NAME=""
   SCHOOL_BANK_ACCOUNT=""
   SCHOOL_BANK_HOLDER=""
   ```

5. **Apply SQL BEFORE restart** (prevents beat tick with old config):
   ```bash
   docker compose --env-file .env.production -f docker-compose.yml \
     exec -T postgres psql -U qlts -d qlts_production \
     -f /app/scripts/wire_zns_333738_consultation_reminder.sql
   ```
   Or via host if script not mounted inside container.

6. **Restart services**:
   ```bash
   docker compose --env-file .env.production up -d \
     --force-recreate --no-deps backend celery-worker celery-beat
   ```

7. **Smoke verify**:
   - Create a real consultation with `scheduled_at = now() + 10 min` on a lead that has phone + offering linked.
   - Wait ≤60s for beat tick.
   - Query: `SELECT status, provider_message_id, error_reason FROM notification_delivery WHERE channel='zalo' ORDER BY id DESC LIMIT 3;`
   - Expect `status='sent'` + msg_id non-null.
   - Recipient phone receives ZNS with correct major name, booking code, schedule time.

### Ordering rationale

SQL before restart guarantees that from the first beat tick post-restart, action 63 already has `template_id` + `external_resolver`. Restarting before SQL would produce one beat cycle dispatching with old config → gateway error or wasted quota.

---

## 6. Rollback plan

### Commit B
- **Code**: `git revert <B-sha>` → redeploy backend + celery.
- **SQL** (rollback snippet included in script):
  ```sql
  UPDATE notification_action
  SET config = config - 'external_resolver' - 'zalo_template_id' - 'zalo_template_data'
  WHERE id = 63;
  ```

### Commit A
- **Code**: `git revert <A-sha>`; no DB change to roll back.
- **.env.production**: new keys harmless if left (pydantic ignores extras); if strict mode, remove lines.

---

## 7. Risks + mitigations (top 5)

| # | Risk | Mitigation |
|---|---|---|
| 1 | Parity drift blocks PR — only catalog OR only metadata updated → drift tests fail | Touch BOTH files in same commit; run parity tests locally before push |
| 2 | Eager-load returns None — `lead.offering` or `lead.offering.program` can be NULL | Short-circuit: `(lead.offering and lead.offering.program and lead.offering.program.name) or "N/A"`; unit test covers None path via builder default |
| 3 | Beat tick during deploy window — cadence 60s | Strict order: SQL first, restart second. During restart, celery-beat is down so no tick executes |
| 4 | Template field length violations — DATE ≤20, STRING ≤30 | `format_vn_datetime` returns exactly 16 chars; ID helpers use fixed-width padding; `major_name` explicitly `[:30]`; unit tests assert length bounds |
| 5 | Silent loss of existing keys during merge — bare `jsonb_build_object` assignment would wipe other keys | Script uses `COALESCE(config, '{}'::jsonb) \|\| jsonb_build_object(...)`; verification SELECT included |

---

## 8. Open questions (non-blocking)

- **Booking code prefix**: `BK-` (shorter) vs `CONS-` (semantic). Default proposed: `CONS-{id:06d}`. User to confirm in commit review.
- **`major_name` fallback text**: `"N/A"` vs `"Chưa xác định"` vs empty string. Default proposed: `"N/A"` (English, shorter, safe for Zalo character set).

---

## 9. Critical files

```
D:\QLTS\Backend_FastAPI\app\utils\datetime_helpers.py        (NEW)
D:\QLTS\Backend_FastAPI\app\utils\id_helpers.py              (NEW)
D:\QLTS\Backend_FastAPI\app\config.py                        (edit)
D:\QLTS\Backend_FastAPI\app\services\email_service.py        (edit, :77)
D:\QLTS\Backend_FastAPI\app\services\notification_payloads.py (edit, :244)
D:\QLTS\Backend_FastAPI\app\tasks\notification_tasks.py      (edit, :217)
D:\QLTS\Backend_FastAPI\app\core\event_catalog.py            (edit, :425)
D:\QLTS\Backend_FastAPI\app\core\event_metadata.py           (edit, :402)
D:\QLTS\Backend_FastAPI\tests\utils\test_datetime_helpers.py (NEW)
D:\QLTS\Backend_FastAPI\tests\utils\test_id_helpers.py       (NEW)
D:\QLTS\Backend_FastAPI\tests\unit\test_notification_payloads.py (edit, :458)
D:\QLTS\Backend_FastAPI\tests\unit\test_notification_parity.py (edit, :615 — parity dict)
D:\QLTS\Backend_FastAPI\scripts\wire_zns_333738_consultation_reminder.sql (NEW)
D:\QLTS\.env.example                                         (edit)
```

---

## 10. Effort estimate

| Item | LOC | Time |
|---|---|---|
| Commit A utilities + settings + email refactor + tests | ~125 | 25 min |
| Commit B payload + task + catalog/metadata + tests + SQL | ~120 | 35 min |
| Local run tests + fix fallouts | — | 15 min |
| Deploy + smoke verify | — | 15 min |
| **Total Phase A+B** | **~245 LOC + 1 SQL** | **~90 min** |
