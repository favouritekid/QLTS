# Magic-Link Admission Confirmation Flow

> **Status:** Production (shipped 2026-04-18 via PR-1 + PR-2 + PR-4).
> **Audit reference:** `Documents/CONFIRMED_STATE_AUDIT_2026-04-18.md`

This document is the canonical reference for how an admission profile moves
from `approved` to `confirmed`. It supersedes the `confirm_enrollment()` /
`get_admission_for_owner` design sketched in
`Documents/ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md` — that symbol set
was never shipped and the code described below is what actually runs.

---

## 1. Why a magic link?

`confirmed` is an **applicant-intent** state. The school has approved the
profile; before enrollment the school needs the applicant to assert, in an
auditable way, that they still want the seat. Two goals:

1. **Compliance / consent** — the applicant, not a staff member, marks intent.
2. **Operational** — removes one manual click from officer workflow while
   keeping fraud-resistance (token + CCCD).

Direct admin transition `approved → enrolled` is blocked by state-machine
validation. Admins wanting to bypass the applicant gate use `override` (→
`overridden` → `enrolled`); this is audited separately.

---

## 2. Lifecycle overview

```
(approved)
    │
    │  officer/admin calls POST /admissions/{id}/send-confirmation
    ▼
AdmissionConfirmationToken  ────────────────────────┐
    │  (token + expires_at + attempt_count=0)      │
    │                                               │
    │  lead receives email with                     │
    │  ${FRONTEND_URL}/confirm/{token}              │
    ▼                                               │
(lead clicks link, lands on public page)            │
    │                                               │
    │  GET /api/admissions/confirm/{token}          │
    │  → ConfirmTokenInfoResponse (valid / expired  │
    │    / locked / already_used / attempts left)   │
    │                                               │
    │  lead enters last 4 CCCD digits               │
    │                                               │
    │  POST /api/admissions/confirm/{token}         │
    │  body: { last_digits_citizen_id }             │
    ▼                                               │
  [CCCD matches?]  ── no ─→ attempt_count++, locked_at set after 5
    │
   yes
    │
    ▼
profile.status = "confirmed", profile.version += 1,
token.confirmed_at = now, audit log row, lead pipeline sync
    │
    ▼
Celery send_admission_confirmed_notification_task
    (applicant gets "confirmed + next steps" email)

Enrollment is a separate step — staff eventually calls
POST /admissions/{id}/enroll which requires status ∈ {confirmed, overridden}.
```

---

## 3. Token contract

| Property | Value | Location |
|---|---|---|
| Entropy | 256 bits, `secrets.token_urlsafe(32)` | `admission_service.generate_confirmation_token` (service/admission_service.py:4940) |
| Storage | `admission_confirmation_token` row, unique on `profile_id` | `models.admission.AdmissionConfirmationToken` |
| TTL | `settings.ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS` (default 7) | `app/config.py` |
| Idempotency | Repo calls `invalidate_existing_tokens(profile_id)` before insert — regenerating replaces the old row | `admission_repository.create_confirmation_token` (repositories/admission_repository.py:1028) |
| Max CCCD attempts | `settings.ADMISSION_CONFIRM_MAX_ATTEMPTS` (5) | `app/config.py` |
| CCCD digits verified | `settings.ADMISSION_CONFIRM_CCCD_DIGITS` (4) | `app/config.py` |
| Router lock | Row-level `SELECT … FOR UPDATE` on both token + profile during verify | `admission_repository.get_token_for_confirm:1084` |

---

## 4. Endpoints

### `POST /admissions/{profile_id}/send-confirmation`

- **Auth:** CasbinAuth (manager / admin) + IDOR via `get_admission_for_manager`.
- **Preconditions:** `profile.status == "approved"`. Otherwise 400 with
  `"Cannot generate confirmation token for profile with status '<status>'"`.
- **Effect:** Generates fresh token row (old token rows invalidated). Returns
  token value, expiry, target email/phone.
- **Post-commit:** Queues `send_magic_link_confirmation_task`. Enqueue wrapped
  in `try/except`; broker failure does NOT 500 the HTTP call — operator can
  retry from the UI.

File: `app/routers/admissions.py:2284`.

### `GET /api/admissions/confirm/{token}`

- **Auth:** Public (CSRF-exempt; see `app/middleware/csrf.py:49`).
- **Rate limit:** 100/hour (prevents token enumeration).
- **Returns** `ConfirmTokenInfoResponse`
  (`app/schemas/admission.py:1198`):
  - `valid`, `expired`, `locked`, `already_used` — terminal flags
  - `attempts_remaining` — int, ≤ `ADMISSION_CONFIRM_MAX_ATTEMPTS`
  - `profile_name` — for "Xin chào <name>" greeting
  - `expires_at` — UTC

File: `app/routers/admissions.py:2144`.

### `POST /api/admissions/confirm/{token}`

- **Auth:** Public.
- **Body:** `ConfirmTokenVerifyRequest` — `{ last_digits_citizen_id: "1234" }`.
- **Rate limits:** 200/hour global + 100/day per IP (+ token-level
  `ADMISSION_CONFIRM_MAX_ATTEMPTS` lockout).
- **Happy path:** Status flips to `confirmed`, version bumps, token marked
  used, audit log written (`source="magic_link"`), lead pipeline synced.
- **Wrong CCCD:** 400 with attempts remaining. `attempt_count` and
  `locked_at` are committed even on failure — frontends must refetch
  `GET /confirm/{token}` after error or UI state will lie.
- **Expired / locked / already used:** 400 with a specific message.
- **Post-commit:** Queues `send_admission_confirmed_notification_task` to the
  applicant's email. Same enqueue `try/except` guarantee.

File: `app/routers/admissions.py:2175`. Service:
`app/services/admission_service.py:5063` (`verify_and_confirm`).

---

## 5. Email delivery

Both emails go through Celery so SMTP hiccups retry instead of crashing the
HTTP flow.

| Task | Template | Subject (VI) | When |
|---|---|---|---|
| `send_magic_link_confirmation_task` | `admission_confirmation.html` | 🎓 Xác nhận nhập học — Hành động cần thiết | After `send-confirmation` |
| `send_admission_confirmed_notification_task` | `admission_confirmed_success.html` | ✅ Xác nhận nhập học thành công | After applicant verifies CCCD |

**Timezone:** both tasks convert ISO UTC inputs to `settings.TIMEZONE`
(default `Asia/Ho_Chi_Minh`) via `zoneinfo.ZoneInfo` before rendering, so
users see local-time deadlines.

**Retries:** `autoretry_for=(Exception,), max_retries=3, default_retry_delay=60`.
Permanent SMTP rejections (e.g. Resend sandbox "only verified recipients")
retry 3 × 60s then give up — logged with stack trace.

**No internal fanout in the email tasks.** Admin/officer notifications for the
`confirmed` transition are fired separately by the existing
`APPLICATION_STATUS_CHANGED` router dispatch after `verify_and_confirm()`
commits. The Celery tasks here are lead-facing only.

Skip condition: if `lead.email` is falsy, the callback returns `{"status":
"skipped", "reason": "no_email"}` and the state change still succeeds.

---

## 6. Frontend public page

`frontend/src/app/confirm/[token]/page.tsx` — Next.js 16 dynamic route with
`params: Promise<{ token: string }>` and the repo's standard
`generateStaticParams()` placeholder pattern.

Gated as public in `frontend/src/proxy.ts` (`PUBLIC_ROUTE_PREFIXES`).
Applicants arriving without a session are **not** redirected to `/login`.

The form (`src/components/forms/ConfirmAdmissionForm.tsx`) renders all
terminal states up front (expired / locked / already used / !valid) and
invalidates the `GET /confirm/{token}` query on any submit error so
`attempts_remaining` and `locked` reflect the just-committed backend state
after a wrong-CCCD 400.

Hook: `src/hooks/admissions/useAdmissionConfirm.ts`.
Zod schemas: `src/lib/zod/admissions.ts` (mirror
`app/schemas/admission.py:1198-1244`).

---

## 7. Security notes

- **No auth on /confirm/** — token is the only credential; compromise of the
  token + CCCD leak is required to impersonate. CCCD lockout after 5 tries
  bounds that risk.
- **Row lock on verify** — `get_token_for_confirm` uses `SELECT … FOR UPDATE`
  so simultaneous confirms on the same token serialize; only the first
  commits.
- **Audit** — `audit_service.log_status_change(..., source="magic_link",
  actor_user_id=None)` records every flip.
- **CSRF exempt** — `middleware/csrf.py:49` exempts `/api/admissions/confirm/`
  because applicants cannot hold a CSRF cookie pre-auth.
- **Rate limits** — per-endpoint + per-IP + per-token (see §4 above).

---

## 8. Operational runbook

**Re-send a magic link:** Officer/admin calls
`POST /admissions/{id}/send-confirmation` again. Repo invalidates the
previous token; the applicant can only use the latest link.

**Locked token after 5 wrong tries:** Re-send issues a fresh token with
`attempt_count=0`. The old token stays locked in the table for audit.

**SMTP outage:** Celery retries; if all three retries fail, inspect
`celery-worker` logs. The confirmation succeeds or fails independently of
whether the success email went out.

**Prod env requirements:**
- `FRONTEND_URL` = `https://qlts.tnpc.edu.vn`
- `MAIL_*` configured (current provider: Resend — domain must be verified
  at `resend.com/domains`, otherwise only the sandbox sender address is
  delivered)
- `TIMEZONE` = `Asia/Ho_Chi_Minh` (default)
- `ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS` (default 7)

---

## 9. What's out of scope for this flow

- **Auto-generating the token on `approve_profile()`** — still manual
  (officer clicks "Send confirmation"). Deferred PR-3; see
  `Documents/CONFIRMED_STATE_AUDIT_2026-04-18.md` §Deferred.
- **Concurrent-confirm / stale-version / TTL-boundary tests** — deferred
  P1 hardening per the same audit.
- **UI polish** (confirmed filter tab, approved-state guidance banner,
  enroll button rename) — deferred P2.
