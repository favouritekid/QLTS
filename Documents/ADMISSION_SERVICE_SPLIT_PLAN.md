# Admission Service Split Plan — tách `admission_service.py`

> **Trạng thái:** READY-TO-EXECUTE · **Lập:** 2026-06-02 · **Chưa code.**
> **Nguồn:** workflow 8-agent (khảo sát 4 chiều → thiết kế → 2 vòng phản biện đối kháng → chốt).
> **Mục tiêu file đích:** `Backend_FastAPI/app/services/admission_service.py` (10,734 dòng).

---

## 0. Mục tiêu & bối cảnh

Tách god-file `admission_service.py` (nợ kiến trúc #1 theo `system-bloat-assessment-2026-06-02`: vừa lớn nhất vừa churn nhất — 128 commit) thành sub-package nhiều module con, **an toàn cho solo dev, không downtime, test luôn xanh**, qua chuỗi PR nhỏ độc lập.

## 1. Sự thật cấu trúc (đã verify bằng grep/read — KHÔNG dùng số "1 class/107 method" của báo cáo bloat, số đó SAI)

- File là **MODULE-OF-FUNCTIONS**: **80 hàm top-level** (`^(async )?def`; survey đếm 79 vì sót `_validate_documents` L966).
- **1 class** `LeadAdmissionEligibility` (L1203) là **dataclass DTO** (3 attribute, 0 method) — giá trị trả về của `check_lead_level_admission_eligibility` (L1214).
- 14 `def` thụt lề là **closure** lồng trong hàm (finalize/`_post_commit`/`_audit_log_callback`/`_send_email_callback`/`_notification_callback`/`_compute_document_permissions`) — không đếm riêng.
- **FSM lõi ĐÃ tách sẵn**: file import `admission_state_service.transition` (alias `state_transition`, L48 top-level) + `admission_state_machine.validate_transition` (deferred, ~11 call-site). File này là **ORCHESTRATOR** gọi sang 2 module FSM đó.
- **74 importer** trên app + tests + **4 cross-service** (`priority_override_service`, `quota_matrix_service`, `lead_service`, `magic_link_service`) + **1 script** (`scripts/smoke_e4_phase5_ut_flows.py`).
- Mọi hàm trả `AdmissionProfile` cho API gọi `_populate_response_fields` (L2487) sau flush; projection lead-state qua `admission_event_mapping` + `lead_admission_sync` (KHÔNG qua SystemEvents).

## 2. Chiến lược: FACADE-FIRST

Giữ `admission_service.py` thành **facade vỏ ~110–150 dòng** (chỉ import + re-export, 0 logic, 0 fastapi, 0 `def`). Toàn bộ implementation chuyển vào **sub-package mới `app/services/admission/`** (KHÔNG dùng flat `admission_*_service.py` vì đã có `admission_scoring_service` / `admission_quota_service` / `admission_state_service` / `admission_state_machine` / `admission_document_policy` / `admission_correction_helpers` / `admission_choice_*_service` — va tên).

**Re-export phục vụ 2 import-style đã verify:**
- (A) **Dominant** module-qualified: `from app.services import admission_service` rồi `admission_service.X(...)` (router `admissions.py` L149/527/613/853/977/1032/1084/1145; `admissions_v2.py` L1076/1107/1255; `magic_link_service` L203/230/282/313/342; `lead_service` L4522 deferred).
- (B) **Minority** direct-symbol: `priority_override_service:66` (`_strip_display_fields_from_evidence`), `quota_matrix_service:36` (`QUOTA_OCCUPYING_STATUSES`), `scripts/smoke...:35` (`_audit_warning_dismissed_if_missing`), ~20 test import helper trực tiếp.

→ **Cùng 1 cơ chế EXPLICIT re-export** (KHÔNG `import *`, KHÔNG `__all__` ở facade — giữ hành vi file gốc; mỗi sub-module đặt `__all__` riêng). Re-export **PHẢI là alias trực tiếp** `from .admission.X import name` — **CẤM** wrap `lambda/partial/functools.wraps` (vì `test_wave4_15b` pin `inspect.signature(check_lead_level_admission_eligibility)` với `academic_year=None`, và magic-link unpack 2-tuple).

## 3. 🚨 BLOCKER — re-export KHÔNG cứu attribute-monkeypatch trên bare-name cross-module

**Nguyên lý:** `from x import name` ở facade tạo **binding mới**; `setattr(facade, name, mock)` KHÔNG đổi binding trong `x` → lời gọi **bare-name** bên trong `x` vẫn dùng object cũ. Re-export giải **import-resolution**, KHÔNG giải **monkeypatch-resolution**.

**Verified vỡ:** `test_phase_e4_pr4_compliance` (L471-477/565-571/633-639) patch 7 helper trên facade `svc` rồi gọi `svc.get_profile`; `_setup_upload_mocks` (L526-528) patch `get_profile`/`_sniff_document_signature`/`_populate_response_fields`. Các symbol này được gọi **bare-name** trong `get_profile` (L3833-3870), `_populate_response_fields` (L2538-2564), `upload_document` (L5603/5657/5776). Nếu move sang module khác mà giữ patch facade → **~11 test giả-pass / vỡ im lặng**.

**Phân biệt 2 cơ chế:**
- ✅ **MODULE-QUALIFIED-call sống** qua re-export: `reset_document` (router L1145 gọi `admission_service.reset_document`; `test_admission_doc_realtime_emit` L555 `patch.object(svc,'reset_document')` TRÚNG).
- ❌ **BARE-NAME-call cross-module KHÔNG sống** → cần co-locate hoặc qualify.

**Fix (quy tắc bất biến):** mọi symbol vừa (i) bị attribute-monkeypatch trên facade VÀ (ii) gọi bare-name bởi hàm move sang module khác →
1. **Co-locate** nguyên khối cụm bị-patch vào `core_response.py` (bare-name resolve cùng namespace).
2. **Đổi patch-target** test sang module thật (`app.services.admission.core_response.<symbol>` / `documents_service._sniff_document_signature`) — đổi đường dẫn patch **≠** cut test.
3. **Thêm** `assert mock.called=True` để bắt no-op.
4. 6 doc-fn self-call `get_profile`/`_populate_response_fields` → đổi sang **module-qualified DEFERRED qua facade** (`from app.services import admission_service` inline, rồi `admission_service.get_profile(...)`) — patch `svc.get_profile` vẫn TRÚNG vì resolve qua facade attribute tại call-time. Deferred-inside-function (KHÔNG top-level) để tránh cycle facade↔sub-module.

## 4. Cấu trúc đích — `app/services/admission/`

### 4.1 `shared.py` — LEAF tuyệt đối (đầu DAG)
**TOP-LEVEL IMPORT ALLOWLIST cứng** (cấm mọi thứ khác): `models`, `repositories` (hoặc deferred), `utils.exceptions`, `utils.masking`, `utils.admission_status`, `utils.admission_round_guards`, `core.constants(UserRole)`, `core.events(SystemEvents)`, `core.admission_correction_constants`, `schemas.admission(DEFAULT_UPLOAD_CONFIG)`, `admission_metrics`, `dataclasses/datetime/decimal/typing/structlog/sqlalchemy`.
**CẤM top-level:** `lead_service` (deferred-inline như gốc), `priority_override_service`, `priority_service`, `quota_matrix_service`, `notification_*`, `admission_state_service`, `admission_state_machine`, mọi sub-module `admission/`.

Hàm: `LeadAdmissionEligibility` (L1203) + `check_lead_level_admission_eligibility` (L1214, **giữ** `academic_year=None`), `_validate_scores` (L895), `_validate_documents` (L966), `_validate_personal_info` (L1089), `_compute_completion_percent` (L1118), `_check_idor_access` (L282, raise 404), `_resolve_idor_filters` (L257), `_create_admission_milestone_consultation` (L2606), `_strip_display_fields_from_evidence` (L2271), `_enrich_priority_evidence_display` (L2298), `_sync_available_actions` (L1329), `_apply_minor_correction_state` (L1388). Constants: `QUOTA_OCCUPYING_STATUSES` (L347), `_BULK_SAFE_DOMAIN_EXCEPTIONS` (L80), `_EVIDENCE_DISPLAY_ONLY_FIELDS` (L2265).

### 4.2 `core_response.py` — cụm bị-monkeypatch-bare-name (giải BLOCKER)
Import `shared` 1 chiều. Gom **nguyên khối**:
`_populate_response_fields` (L2487, contract sau flush — CẤM fork), `_compute_frontend_fields` (L1459, ~812 dòng, to nhất; closure `_compute_document_permissions`), `_calculate_and_update_totals` (L4351), `_resolve_verifier_names` (L1414), `_resolve_minor_correction_state` (L1347), `_load_priority_audit_log` (L2567), `_populate_priority_evidence_projections` (L2365), `get_profile` (L3799, INLINE 7 collaborator bare-name L3833-3870).

### 4.3 `query_service.py` — đọc thuần (rủi ro thấp)
Import `shared` + `core_response`. `get_profiles` (L3570), `get_profiles_for_export` (L3661), `get_status_counts` (L3710), `get_admission_stats` (L3740), `get_academic_years` (L3783).

### 4.4 `documents_service.py`
6 doc-fn đổi bare-name self-call → facade-qualified deferred. `priority_service` deferred L5218, `priority_override` deferred L6156 (CẤM nâng top-level).
`upload_document` (L5548), `upload_priority_evidence_document` (L5918), `confirm_document_format` (L6273), `mark_paper_submitted` (L6365), `reject_document` (L6461), `reset_document` (L6556), `get_document_file_for_download` (L5472), `record_application_fee_payment` (L7824), `check_application_fee_status` (L7978), `_authorize_document_action` (L190), `_sniff_document_signature` (L113, bị patch `_setup_upload_mocks` → giữ ở module này, patch-target = `documents_service._sniff_document_signature`), `_resolve_under` (L90).

### 4.5 `create_update_service.py`
Import `shared` + `core_response`. `create_profile` (L2899, ~671), `update_profile` (L3986, ~365, per-field exclude_unset → validate candidate state), `_reresolve_documents_snapshot` (L3875), `_extract_allowed_subject_codes` (L2764), `_serialize_subject_groups` (L2799), `_merge_subject_weights` (L2865). applied_rules rebuild + `flag_modified` (chỉ 5 fee key — immutability trigger).

### 4.6 `submit_service.py` — **KHÔNG import `fee_quota`** (verified submit không gọi quota/fee/`_perform_enrollment_core`)
Import `shared` + `core_response`; `priority_service` deferred L4641; `admission_scoring_service` deferred L5053; `state_transition`. `submit_and_evaluate` (L4860, ~612), `_validate_eligibility_all_choices` (L4593), `_audit_warning_dismissed_if_missing` (L4754, **re-export tại PR-5**), `_kv_unresolved_error_message` (L4509), `_assert_kv_resolved_for_submit` (L4578), `_is_current_era_ward` (L4830). Giữ 2-tuple (magic_link L282).

### 4.7 `fee_quota_service.py` — pure rule engine
Import `shared` (`QUOTA_OCCUPYING_STATUSES`). `check_enrollment_fee_eligibility` (L739, test_finance_api 12x), `_check_fee_gate_legacy` (L765), `_check_fee_gate_semester_hk1` (L822), `_assert_quota_or_bypass` (L439, ~230), `_resolve_quota_context` (L360), `_count_quota_occupying_profiles` (L410), `_audit_quota_bypass_denied` (L669).

### 4.8 `lifecycle_service.py` — FSM orchestrator
Import `shared` + `core_response` + `fee_quota` + `state_transition` (top-level) + `validate_transition` (**DEFERRED inline** — HAI module FSM khác nhau, mang CẢ HAI).
`approve_profile` (L7181), `reject_profile` (L7418), `request_revision` (L7619), `resubmit_profile` (L8009), `override_profile` (L8233), `finalize_profile` (L8556), `withdraw_profile` (L8844), `enroll_student` (L7078), `_perform_enrollment_core` (L6765, ~313, begin_nested + redis lock student_code), `_lock_admission_profile_for_write` (L6700), `apply_minor_correction` (L9034, **trả `(profile, socket_envelope)` — shape khác**), `mark_student_dropped` (L9229, milestone `student_dropped→sts12`). Giữ 2-tuple resubmit/withdraw.

### 4.9 `confirm_service.py`
Import `shared` + `core_response` + `state_transition` + `validate_transition` (deferred L9966). `verify_and_confirm` (L9727, ~362, 2-tuple), `generate_confirmation_token` (L9515), `generate_action_magic_link` (L9418), `get_token_info` (L9667), `claim_review` (L8422), `unclaim_review` (L8493). *(test_token_locked PRE-EXISTING fail — KHÔNG điều tra, xem `confirm-token-locked-preexisting-fail`.)*

### 4.10 `bulk_service.py` — đóng facade; **KHÔNG import `lifecycle`** (verified bulk INLINE transition)
Import `shared` + `core_response` + `fee_quota` (`_assert_quota_or_bypass`) + `state_transition` + `validate_transition` (deferred L10123/10373). `bulk_approve` (L10089, ~251), `bulk_reject` (L10340, ~220), `bulk_assign` (L10560, ~175, result+callback), `delete_profile` (L8732), `_safe_bulk_error_message` (L152). **Sau PR này `admission_service.py` chỉ còn facade.**

## 5. DAG & no-cycle
`shared` (leaf) ← `core_response` ← {query, documents, create_update, submit, lifecycle, confirm, bulk}; `fee_quota` ← {lifecycle, bulk}. **Không cycle** (verified: 7 module facade-kéo state_service/commission/notification_bundle/dispatcher/correction_helpers + priority_override/quota_matrix init sạch — không import sub-module ở top).
**Gate tự động:** `tests/unit/test_admission_facade_no_cycle.py` (import 4 module 2 thứ tự) + `python -c 'import ...'` cho `admission_service`, `priority_override_service`, `quota_matrix_service`, `lead_service` — **chạy MỖI PR**.

## 6. Chuỗi PR (rủi ro tăng dần)

| PR | Nội dung | Rủi ro | Ước tính |
|----|----------|--------|----------|
| **PR-0** | sub-package + `shared.py` (leaf) + facade + test no-cycle. Chỉ move symbol KHÔNG-bị-patch-bare-name | Cao (cycle nền móng) | 0.75–1d |
| **PR-1.5** | `core_response.py` (BLOCKER): move `_populate_response_fields`+`get_profile`+6 collaborator nguyên khối; đổi patch-target test_pr4/pr2 + assert mock.called | **BLOCKER** | 1–1.25d |
| **PR-1** | `query_service.py` (list/export/stats) | Thấp | 0.5d |
| **PR-2** | `documents_service.py` (bare-name self-call → facade-deferred) | TB–Cao | 1d |
| **PR-3** | `fee_quota_service.py` (pure engine) | Thấp | 0.5d |
| **PR-4** | `create_update_service.py` | TB | 1d |
| **PR-5** | `submit_service.py` (độc lập PR-3) | Cao | 1–1.5d |
| **PR-6** | `lifecycle_service.py` | Cao | 1.5d |
| **PR-7** | `confirm_service.py` | TB–Cao | 1d |
| **PR-8** | `bulk_service.py` → đóng facade (độc lập PR-6) | TB | 1d |

*Có thể nén ~8.5d nếu gộp PR-1.5+PR-1 (cùng cụm read) hoặc PR-7+PR-8.*

**Quy trình test mỗi PR:** one-off throwaway container (`docker compose run --rm --no-deps` + qlts_test + `RUN_MIGRATIONS=false` + explicit `-e DATABASE_URL=...qlts_test`); PR đụng dispatch (5/6/7) chạy **full notification CI**; chạy anchor matrix Casbin/permission/IDOR + diff computed-fields golden snapshot (GET vs mutation) ở PR-0/PR-1.5/PR-2/PR-6.

## 7. Hợp đồng kiến trúc bất biến
- `_populate_response_fields` sau flush + nested eager-load (`lead.assigned_officer` + `assigned_reviewer`); **không fork**.
- `(result, post_commit_callback)`; KHÔNG `db.commit()` (chỉ flush); KHÔNG import fastapi; raise domain exception.
- `dispatch()`/`safe_dispatch()` đúng transaction-frame; `begin_nested()` (strict=True) cho atomic pairs.
- Projection lead-state qua `lead_admission_sync` + `_create_admission_milestone_consultation` (KHÔNG SystemEvents).

## 8. doNotTouch (lằn ranh)
1. KHÔNG đổi signature/tuple-shape public (router + 4 cross-service magic_link + `check_enrollment_fee_eligibility`/`check_lead_level_admission_eligibility`). Giữ `academic_year=None` (pin `test_wave4_15b`).
2. KHÔNG sửa `admissions.py`/`admissions_v2.py` — giữ module-qualified call.
3. KHÔNG đổi 4 cross-service consumer + script smoke (`_audit_warning_dismissed_if_missing` re-export PR-5).
4. KHÔNG re-merge `admission_state_service`/`admission_state_machine` — chỉ orchestrate gọi CẢ HAI.
5. KHÔNG đụng engine flat đã có (scoring/quota/document_policy/correction_helpers/choice_*/priority_service).
6. KHÔNG đổi `APPLICATION_*` / `application_id` (=AdmissionProfile.id backward-compat).
7. KHÔNG thay projection bằng SystemEvents; `student_dropped→sts12` (KHÔNG generic sync).
8. KHÔNG thêm fastapi / `db.commit()`; facade tuyệt đối 0 logic.
9. KHÔNG cut/skip test, KHÔNG xóa assertion. Được ĐỔI patch-target + THÊM `assert mock.called`.
10. KHÔNG đổi applied_rules mutation (rebuild dict + `flag_modified`, chỉ 5 fee key).
11. KHÔNG fork `_populate_response_fields`/6 collaborator — move nguyên khối vào `core_response`.
12. `apply_minor_correction` giữ `(profile, socket_envelope)` (router L1820 dùng `['payload']/['rooms']`).
13. Re-export chỉ alias trực tiếp — CẤM wrap.
14. `priority_override/priority_service` trong documents/submit/upload giữ DEFERRED-inline — CẤM top-level.

## 9. Rủi ro & mitigation (tóm tắt — chi tiết §3, §8)
1. **Monkeypatch no-op (BLOCKER)** → co-locate `core_response` + đổi patch-target + assert mock.called.
2. **Import cycle** → `shared` allowlist cứng + deferred priority/lead + test no-cycle mỗi PR.
3. **`validate_transition` deferred bị quên → NameError runtime** → grep trong block move + chạy anchor thật.
4. **Re-export wrap vỡ signature/2-tuple** → alias trực tiếp, giữ nguyên shape.
5. **`apply_minor_correction` shape riêng** → anchor assert phần-tử-2 là dict (NOT callable).
6. **Casbin/permission/IDOR drift** → anchor matrix + diff computed-fields per PR.
7. **dispatch frame** → move closure nguyên vẹn, full notification CI ở PR-5/6/7.
8. **Heavy suite contamination** → one-off container, không exec live.

## 10. Ước tính & vận hành
**~9.5–11 ngày** thực (solo), 10 PR. Mỗi PR ~30–60p CI overhead. Commit **KHÔNG push** tới khi user approve per-push (`push-approval-required`).

---
*Liên quan: `system-bloat-assessment-2026-06-02`, `local-test-oneoff-container-pattern`, `pattern-change-impact-audit`, `dispatch-bundle-strict-required`, `confirm-token-locked-preexisting-fail`.*
