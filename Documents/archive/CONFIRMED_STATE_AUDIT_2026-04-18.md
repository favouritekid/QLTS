# Audit `confirmed` state — Admission V2 Flow

**Ngày**: 2026-04-18 (updated sau commit `090a9b57` — BUG-UX-001 fix; line numbers trong `admission_service.py` đã re-verified)
**Trigger**: QA re-test sau V2 wave deploy (`c194048b`) phát hiện state machine thay đổi — thêm intermediate state `confirmed` giữa `approved` và `enrolled`.
**Quy tắc transition**:
- `approved → confirmed` chỉ qua **public magic-link + CCCD** (`verify_and_confirm`)
- `approved → enrolled` **trực tiếp → 400** (invalid transition)
- `approved → overridden → enrolled` qua admin force (đã verified working)
- `confirmed → enrolled` qua finalize endpoint

---

## 🎯 Executive Summary

| Phần | Status | Blocker? |
|---|---|---|
| 1. State-machine docs | ⚠️ Partial | Không |
| 2. Transition tests | ✅ Mostly covered | Không (3 edge cases thiếu) |
| 3. UI labels/actions | ⚠️ Partial | Có — thiếu public confirm page |
| 4. Magic-link flow readiness | 🔴 **CRITICAL** | **Có — 3 blockers go-live** |

**Verdict**: State machine *architecturally* đúng, backend core endpoints working. **End-to-end flow CHƯA production-ready** vì:
1. Email callback là **stub** (không gửi email thật)
2. Frontend public confirm page **không tồn tại**
3. Token **không auto-generate** khi approve

---

## Phần 1 — State-machine Docs

### ✅ Đã document
| File | Nội dung |
|---|---|
| `Documents/ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md:238-255` | Enum `CONFIRMED = "confirmed"` + transitions dict `APPROVED → {CONFIRMED, OVERRIDDEN}` + `CONFIRMED → {ENROLLED}` |
| `Documents/ADMISSION_PIPELINE_SYNC_SOLUTION.md:100` | Event mapping `profile_confirmed → stays stg04/sts09` |
| `Documents/ADMISSION_MATRIX_MAPPING.md:25,38-41` | Confirm = applicant intent, không đổi pipeline stage |
| `Documents/TEST_COVERAGE_MATRIX.md:57` | Test case "Magic link: approved → confirmed → enrolled" |
| `Backend_FastAPI/docs/LEAD_ADMISSION_AUDIT_REPORT.md:108` | Magic-link verified |

### ❌ Chưa document
- **`Backend_FastAPI/MASTER_ARCHITECTURE.md`**: **Không mention** state machine admission — source of truth thiếu
- **Magic-link flow chi tiết**: chưa có file riêng mô tả token lifecycle, CCCD logic, endpoint contract, TTL, retry limits
- **`verify_and_confirm()` contract**: service function ở `admission_service.py:5063` không có docstring public
- **Design rationale**: tại sao `confirmed` cần public flow (compliance? consent?) — không giải thích

### 📝 Docs cần tạo/update
1. **CREATE** `Backend_FastAPI/docs/MAGIC_LINK_CONFIRMATION_FLOW.md`: token lifecycle, CCCD verify, endpoint contract, error codes, so sánh với admin override
2. **UPDATE** `Backend_FastAPI/MASTER_ARCHITECTURE.md`: thêm Part "Admission State Machine" với diagram
3. **UPDATE** `Documents/ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md`: xóa "historical reference" cho `confirm_enrollment()`, link sang doc mới

---

## Phần 2 — Transition Tests

### Coverage matrix

| Transition | Status | Test locations |
|---|---|---|
| **T1**: `approved → confirmed` (magic-link+CCCD) | ✅ Covered | `test_admission_state_transitions.py`: happy (L609), CCCD wrong (L531), retry lock (L829), token expired (L868), replay (L356), resend invalidates (L726) |
| **T2**: Direct `approved → enrolled` → 400 | ✅ Covered | `test_admission_workflow_api.py::test_finalize_from_approved_returns_400` |
| **T3**: `confirmed → enrolled` | ✅ Covered (happy only) | `test_admission_state_transitions.py::test_happy_path_normal_flow` step 7 (L679) |
| **T4**: `approved → overridden → enrolled` | ✅ Covered (+RBAC) | `test_admin_override_flow` (L735), `test_submit_approve_override_finalize_enrolled`, `test_officer_cannot_override/finalize` |

### ⚠️ 3 edge case gaps

1. **Race condition** concurrent confirm same token → cần `asyncio.gather` test
   - Đề xuất: `test_concurrent_confirm_same_token` trong `TestTokenBasedConfirmation`

2. **Version mismatch** `confirmed → enrolled` với stale version — `confirm` increment version, finalize với version cũ cần trả 409
   - Đề xuất: `test_finalize_confirmed_with_stale_version` trong `TestVersionChecking`

3. **Token expiry boundary** — hiện test set expires_at = -1 day (rõ ràng expired). Thiếu case expires_at = now() (clock skew edge)
   - Đề xuất: `test_token_expires_at_boundary`

---

## Phần 3 — UI Labels/Actions

### ✅ FE recognize `confirmed` đầy đủ

| Config | File:line | Content |
|---|---|---|
| Zod enum | `lib/zod/admissions.ts:430` | Includes `"confirmed"` |
| Status label | `lib/zod/admissions.ts:806` | "Đã xác nhận" |
| Status color | `lib/zod/admissions.ts:781` | `bg-success-100 text-success-800` (xanh lá) |
| Badge config | `status-badge.config.ts:160-167` | Label + CheckCircle icon + emerald-700 + order 8 |
| Status config | `status-config.ts:89-97` | Banner "Hồ sơ đã được xác nhận bởi thí sinh" + allowed `[enroll]` |
| Permission adapter | `permission-adapter.ts:110-119` | `enroll: true` cho `approved/confirmed/overridden` |

### ⚠️ UI gaps (không blocker nhưng nên polish)

1. **Filter tab thiếu**: `AdmissionsClient.tsx:145-152` — tab "Đã duyệt" gộp cả `approved + confirmed + overridden`. Admin không thể filter riêng profiles đang chờ ứng viên xác nhận.

2. **Admin guidance banner thiếu**: khi xem profile status `approved`, UI không hint "Chờ ứng viên xác nhận email+CCCD, ghi danh sẽ sẵn sàng sau khi xác nhận". Banner chỉ hiện khi đã `confirmed` — admin đứng ở `approved` không biết trạng thái chờ.

3. **Button label ambiguous**: `AdmissionActions.tsx:282-287` — nút "Xác nhận nhập học" cho action `enroll` dễ confuse với "xác nhận" của applicant. Nên đổi "Ghi danh" hoặc "Hoàn tất nhập học".

### 🔴 Public confirm page MISSING

- **Kỳ vọng**: `frontend/src/app/(public)/confirm/[token]/page.tsx` hoặc `frontend/src/app/confirm/[token]/page.tsx`
- **Thực tế**: **Không tồn tại**
- **Hậu quả**: Lead click email link → 404 / blank page / redirect login
- **Cần build**: Form CCCD (4 digits) + submit POST `/api/admissions/confirm/{token}` + handle error states (expired, wrong CCCD, rate limited)

---

## Phần 4 — Magic-link Flow Readiness (🔴 CRITICAL)

### ✅ Backend đã sẵn sàng
| Component | File:line | Status |
|---|---|---|
| `GET /api/admissions/confirm/{token}` | `admissions.py:2144` | Hiển thị form info (valid, attempts remaining) |
| `POST /api/admissions/confirm/{token}` | `admissions.py:2175` | Verify CCCD, set status `confirmed` |
| `verify_and_confirm()` service | `admission_service.py:5063` | State transition + audit log |
| Rate limits | — | 200/hr global + 100/day/IP + 5 attempts/token |
| Token TTL | `ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS` | Default 7 days, configurable |
| Audit log | — | Tracks actor=None, source=`magic_link` |
| Vietnamese error messages | — | Token expired / CCCD wrong / too many attempts |

### 🔴 3 Blockers Go-Live

#### Blocker #1 — 2 email callbacks đều là STUB
**File**: `admission_service.py` — **cả hai** callback chỉ log, không gọi SMTP:

| Location | Purpose | Log line |
|---|---|---|
| `_send_email_callback()` (L4993, log L4997) | Gửi magic link khi request confirm | `"POST-COMMIT: Would send confirmation email"` |
| Post-confirm success (L5223) | Gửi thông báo "đã xác nhận thành công" cho lead + admin | `"POST-COMMIT: Would send confirmation success notification"` |

```python
# L4993 — stub #1
async def _send_email_callback():
    logger.info("POST-COMMIT: Would send confirmation email...")
    # ← KHÔNG gọi SMTP / Celery task

# L5223 — stub #2 (trong verify_and_confirm post_commit)
logger.info("POST-COMMIT: Would send confirmation success notification")
# ← cũng chưa được wire
```

**Fix cần** (cả 2 stubs):
- Stub #1 (magic link): build `f"{settings.FRONTEND_URL}/confirm/{token}"` + render template `admission_confirmation.html` với `${confirm_url}`, `${lead_name}`, `${expires_at}` → queue Celery task hoặc `email_service.send()`
- Stub #2 (success notif): render template `admission_confirmation_success.html` (hoặc dispatch notification event cho lead + admin) — confirm lead đã xác nhận, hướng dẫn bước tiếp theo

`generate_confirmation_token()` (L4940) đã work — chỉ callback email thiếu implementation

#### Blocker #2 — Frontend public confirm page MISSING
**File cần tạo**: `frontend/src/app/(public)/confirm/[token]/page.tsx` (hoặc route tương tự)
**Yêu cầu UI**:
- Form input: 4 số cuối CCCD (single field, numeric, maxLength 4)
- Gọi GET `/api/admissions/confirm/{token}` khi mount để lấy info (lead name, attempts remaining, expires_at)
- Submit: POST `/api/admissions/confirm/{token}` với body `{last_digits_citizen_id}`
- Error states: token expired → thông báo + hướng dẫn liên hệ admin; wrong CCCD → hiển thị attempts remaining; rate limited → message + countdown
- Success state: confirm thành công → thông báo + hướng dẫn chờ nhà trường liên lạc
- Mobile responsive (đa số lead sẽ click từ mobile)

#### Blocker #3 — Token không auto-generate khi approve
**File**: `admission_service.py:3462` (`approve_profile()`)
**Hiện tại**: Không gọi `generate_confirmation_token()`. Officer phải manual `POST /api/admissions/{id}/send-confirmation` sau khi approve.
**Phương án**:
- **Option A** (recommended): Auto-generate token trong `approve_profile()` post_commit callback → gửi email luôn. Thêm config flag `ADMISSION_AUTO_SEND_CONFIRMATION=True` để có thể disable nếu cần.
- **Option B**: Giữ manual nhưng thêm UI button rõ ràng + runbook ops documentation + nhắc nhở officer.

#### ℹ️ Notification rule + template
- `APPLICATION_STATUS_CHANGED` event đã seeded (`notification_registry.py:397`) với `[BROWSER, EMAIL]` channels
- Template chung `notification_generic.html` — **thiếu confirmation-specific template**
- Cần tạo: `admission_confirmation.html` với `${confirm_url}` button + CCCD note + expires_at

---

## 📋 Action Plan Theo Priority

### 🔴 P0 — Blockers go-live (chặn magic-link flow)

| # | Task | Scope | Est. effort |
|---|---|---|---|
| 1 | Implement `_send_email_callback()` thật (SMTP/Celery) | Backend 1 file | S (~30 min + test) |
| 2 | Build frontend `(public)/confirm/[token]/page.tsx` | Frontend 1 page | M (~2-3h) |
| 3 | Auto-generate token trong `approve_profile()` + config flag | Backend 1 file | S (~30 min) |
| 4 | Create email template `admission_confirmation.html` | Template 1 file | S (~20 min) |

### 🟠 P1 — Edge case tests (hardening)

| # | Task | File |
|---|---|---|
| 5 | `test_concurrent_confirm_same_token` | `tests/integration/test_admission_state_transitions.py` |
| 6 | `test_finalize_confirmed_with_stale_version` | `tests/integration/test_admission_state_transitions.py` |
| 7 | `test_token_expires_at_boundary` | `tests/integration/test_admission_state_transitions.py` |

### 🟡 P2 — UI polish

| # | Task | File |
|---|---|---|
| 8 | Thêm filter tab "Đã xác nhận" | `AdmissionsClient.tsx:145-152` |
| 9 | Banner guidance ở status `approved` | `status-config.ts` hoặc component status banner |
| 10 | Rename button "Xác nhận nhập học" → "Ghi danh" | `AdmissionActions.tsx:282-287` |

### 🟢 P3 — Docs

| # | Task | File |
|---|---|---|
| 11 | CREATE `MAGIC_LINK_CONFIRMATION_FLOW.md` | `Backend_FastAPI/docs/` |
| 12 | ADD state-machine section vào `MASTER_ARCHITECTURE.md` | `Backend_FastAPI/` |
| 13 | UPDATE `ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md` (xóa historical notes) | `Documents/` |

---

## 🔗 Evidence references

Tất cả finding có file + line để verify độc lập:

**Backend core**:
- `Backend_FastAPI/app/services/admission_service.py:3269` (enroll state guard)
- `Backend_FastAPI/app/services/admission_service.py:3462` (approve — không trigger token)
- `Backend_FastAPI/app/services/admission_service.py:4940` (generate_confirmation_token — functional)
- `Backend_FastAPI/app/services/admission_service.py:4993-5001` (email callback stub #1: magic link)
- `Backend_FastAPI/app/services/admission_service.py:5063` (verify_and_confirm service)
- `Backend_FastAPI/app/services/admission_service.py:5223` (email callback stub #2: post-confirm success)
- `Backend_FastAPI/app/routers/admissions.py:2144,2175,2189` (confirm routers)
- `Backend_FastAPI/app/routers/admissions.py:2284` (send-confirmation manual endpoint)

**Frontend**:
- `frontend/src/lib/zod/admissions.ts:430,781,806`
- `frontend/src/components/status-badge.config.ts:160-167`
- `frontend/src/app/(dashboard)/admissions/_components/AdmissionsClient.tsx:145-152`
- `frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionActions.tsx:282-287`
- `frontend/src/lib/permissions/permission-adapter.ts:110-119`

**Tests**:
- `Backend_FastAPI/tests/integration/test_admission_state_transitions.py` (L356, L531, L609, L679, L726, L735, L829, L868)
- `Backend_FastAPI/tests/api/test_admission_workflow_api.py::test_finalize_from_approved_returns_400`

**Docs**:
- `Documents/ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md:10-15,212-214,238-255`
- `Documents/ADMISSION_PIPELINE_SYNC_SOLUTION.md:100,145`
- `Documents/ADMISSION_MATRIX_MAPPING.md:25,38-41`
