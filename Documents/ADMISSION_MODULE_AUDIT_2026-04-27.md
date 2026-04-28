# Admission Module Audit - 2026-04-27

> **Update 2026-04-28 (Wave 2 — Product/Compliance audit)**
> 
> - **Trạng thái 22 ADM cũ**: **15 đã ship + deploy prod**, 7 defer/chưa làm. PR #156 (ADM-013) đã deploy 2026-04-28 (verified: `qlts-backend-1` healthy, code có ADM-013 lock pattern). Chi tiết tại [Status snapshot](#status-snapshot-2026-04-28).
> - **8 finding mới**: ADM-023…ADM-030 phát sinh từ pass đánh giá user guide ở góc độ product/compliance/UX (rate limit magic link, schema_version legacy, evidence paper docs, quota enforcement, change-path flow, finalize rollback, bulk approve UX, magic-link reminder). Chi tiết tại [Wave 2 findings](#wave-2-findings--2026-04-28).
> - **Decisions 2026-04-28**: Q12 → Option B (hard cap + admin override); Q9 → A3+B1+C2 (hybrid lock + 3 resend/24h + reminder 24h+6h); Q11 → **ADM-025 CLOSED-NOT-NEEDED** (đã verify `admission_document_policy.py:174-180` chặn `paper_submitted` khi `requires_upload=true`; existing `requires_upload=true` + file upload pattern = digital evidence, không cần thêm `evidence_photo_path`).
> - **ADM-031 thêm 2026-04-28**: DocumentsTab UI quá kỹ thuật cho officer — 4 sub-finding (row task-orientation, format dialog wording, enum `photo` 4 nhãn khác nhau, progress uploaded==verified). UI-only PR 4-6h, không touch backend.
> - **Claim đã verify FALSE** (không phải bug): officer submit IDOR, confirmed→withdrawn refund, resubmit race, minor-correction whitelist, bulk-assign cross-unit, duplicate CCCD, officer audit log, fee/payment 4-eyes cross-entity. Xem [Verified-FALSE log](#verified-false-claims--2026-04-28).

## Phạm vi

Review tĩnh toàn bộ luồng chính của module admission: profile workflow, admission path/config, document upload/reset, fee status, bulk actions, export CSV, magic-link confirmation, frontend admission detail và path admin UI.

Chưa chạy test tự động trong lượt audit này. Các kết luận dưới đây dựa trên đọc code và đối chiếu kiến trúc `AGENTS.md`, `MASTER_ARCHITECTURE.md`, `FRONTEND_ARCHITECTURE_V3.md`, security/IDOR guidelines.

Wave 2 (2026-04-28) bổ sung góc nhìn product/compliance từ user guide review: rate limit, schema versioning, evidence retention, quota enforcement, finalize rollback và workflow gaps.

## Cách phân loại

- `Bug`: hành vi sai, sai quyền, sai dữ liệu, hoặc có khả năng gây mất/nhầm dữ liệu.
- `Edge case`: lỗi chỉ xuất hiện trong rollback, concurrency, dữ liệu lịch sử, nhiều năm học, hoặc trạng thái hiếm.
- `Gap`: thiếu guard, audit, test, contract hoặc invariant, hiện có thể chưa crash nhưng rủi ro vận hành cao.

Severity:

- `P1`: cần xử lý sớm vì ảnh hưởng bảo mật, dữ liệu hoặc cấu hình đang active.
- `P2`: rủi ro trung bình, nên vào backlog gần.
- `P3`: hardening, UX/contract/test gap.

## Status snapshot 2026-04-28

Tính theo `origin/main` HEAD `473accf1` + prod backend container `qlts-backend-1` (healthy, image build 2026-04-28 17:15 +07).

| Bucket | Count | ADMs |
| --- | --- | --- |
| Đã ship + deploy prod | 15 | ADM-001, 003, 004, 005, 006, 007, 008, 009, 010, 012, 013, 014, 015, 019, 021 |
| Chưa thực hiện / defer | 7 | ADM-002, 011, 016, 017, 018, 020, 022 |

PR #156 (ADM-013 profile-first FOR UPDATE lock) deployed 2026-04-28 — verified in container: `admission_service.py:4024, 5520, 5815, 6791` chứa ADM-013 lock pattern.

PR mapping (Wave 1 + Wave 2 hardening):

| PR | Findings shipped |
| --- | --- |
| #149 | ADM-001, 004, 005, 006, 010, 012, 019 |
| #150 | ADM-008, 009, 014 |
| #151 | ADM-021 |
| #152 | ADM-003 |
| #153 | ADM-007 |
| #155 | ADM-015 |
| #156 | ADM-013 (deployed 2026-04-28) |

Chi tiết defer:

| ADM | Severity | Lý do giữ |
| --- | --- | --- |
| ADM-002 | P3 | Intent giữ method-level template; backlog: rename "Method documents" + show affected paths trước khi save. |
| ADM-011 | P2 | Bulk assign thiếu lock/version; technical next sau #156. |
| ADM-016 | P2 | FE tự tính scoring; cần đưa scoring về backend/thin-client (tracked với PR6 weighted-scoring memory). |
| ADM-017 | P2 | Implicit newest published intake; technical priority sau ADM-011 (cùng wave concurrency/data invariant). |
| ADM-018 | P3 | Intent giữ multi-year active paths; cần UI/API rõ academic year. |
| ADM-020 | P3 | Orphan files sau delete; chờ product/compliance quyết retention/quarantine/delete. |
| ADM-022 | P3 | Meta item — coverage gap. Bundle theo PR fix tương ứng, không tách PR riêng. |

## Tóm tắt nhanh

| ID | Severity | Loại | Nhóm | Phát hiện |
| --- | --- | --- | --- | --- |
| ADM-001 | P1 | Bug/Security | IDOR | `GET /api/admissions/{profile_id}/fee-status` chỉ yêu cầu login, không kiểm tra scope profile. |
| ADM-002 | P3 | Intent/UX gap | Admission path documents | `DocumentGroup` là method-level template theo design; route/UI "path documents" dễ gây hiểu nhầm scope. |
| ADM-003 | P1 | Gap/Data | Admission path criteria | `upsert_criteria` mutate trực tiếp `path.criteria`; nếu nhiều path trỏ cùng `criteria_id`, thay đổi lan chéo path. |
| ADM-004 | P1 | Bug/Config | Activation | API activate path không validate criteria/documents dù route và coverage matrix nói có. |
| ADM-005 | P1 | Bug/Config | Lifecycle | Criteria/documents vẫn sửa được trên path `active`/`archived`; guard chỉ có ở `update_path`. |
| ADM-006 | P1 | Bug/Security | Export | CSV export ghi thẳng field do user nhập, có rủi ro CSV/formula injection. |
| ADM-007 | P1 | Bug/Data | Upload/reset | File vật lý bị xóa/ghi trước DB commit, rollback có thể làm DB và filesystem lệch nhau. |
| ADM-008 | P2 | Gap/RBAC | Admission path | Manager có thể activate/deactivate path dù comment nghiệp vụ nói "Admin approves = activate". |
| ADM-009 | P2 | Bug/Security | Config detail | Một số detail endpoint admission-config thiếu `get_config_filter`, có thể đọc inactive/draft config. |
| ADM-010 | P2 | Bug/API | Filters/export | `payment_status` được validate ở list, nhưng không validate ở status-counts/export; invalid value bị bỏ qua và có thể export rộng hơn mong đợi. |
| ADM-011 | P2 | Edge/Data | Bulk assign | Bulk assign không lock/version profile/lead, concurrent assign có thể last-writer-wins. |
| ADM-012 | P2 | Gap/Security | Bulk actions | Bulk approve/reject/assign trả `str(e)` trực tiếp trong response lỗi theo từng item. |
| ADM-013 | P2 | Edge/Concurrency | Magic link | Confirm token lock claim không đúng: comment nói lock token + profile, code chỉ lock token row chính; override/delete token dùng thứ tự khác. |
| ADM-014 | P2 | Gap/Audit | Override | Admin override chỉ `log.warning`, chưa ghi durable audit vào `entity_audit_log`. |
| ADM-015 | P2 | Bug/Contract | Optimistic lock | Override/finalize document có version check nhưng request schema không có `version`; client gửi version cũng bị bỏ qua. |
| ADM-016 | P2 | Bug/Frontend | Scoring | Frontend tự tính total score và không xử lý `best_n`/`required_subject_count` như backend. |
| ADM-017 | P2 | Edge/Data | Academic year | `create_profile` tự chọn published/newest academic info nếu có nhiều intake published, thiếu invariant "one published intake". |
| ADM-018 | P3 | Intent/UX gap | Active paths dropdown | Multi-year active paths là design; UI/API cần làm rõ academic year nếu giữ pattern này. |
| ADM-019 | P3 | Gap/Security | File upload | Upload chỉ tin `content_type`, extension lạ fallback `.bin` thay vì reject/sniff content. |
| ADM-020 | P3 | Gap/Data | Delete profile | Xóa draft profile không cleanup thư mục `uploads/admissions/{profile_id}`. |
| ADM-021 | P3 | Gap/Frontend | Path actions | `available_actions`/`can_edit` path là role-agnostic, UI có thể hiện action backend sẽ chặn. |
| ADM-022 | P3 | Gap/Test | Coverage | CSV injection đã có test riêng; các regression còn lại nên bundle theo PR fix tương ứng. |
| ADM-023 | P1 | Bug/Security | Magic link | `/send-confirmation` rate limit per IP (200/h), không per profile_id; resend tạo token mới với attempt_count=0 → CCCD 4-digit (10⁴) brute-forceable; không có cumulative lock trên profile. |
| ADM-024 | P2 | Edge/Data | PR #6 fail-closed | Profile `schema_version=1` (legacy hoặc migration backfill) keep `allow_unverified_submission=True` vĩnh viễn; mọi path tồn tại tại deploy time bị backfill `True` → fail-open mặc định cho path cũ. Không có upgrade job. |
| ADM-025 | ~~P1~~ CLOSED | Compliance/Data | Document evidence | **CLOSED-NOT-NEEDED 2026-04-28**: existing `DocumentType.requires_upload=true` + file upload pattern đã đủ làm evidence số; policy guard `admission_document_policy.py:174-180` chặn paper_submitted với requires_upload=true. |
| ADM-026 | P1 | Compliance/Data | Quota enforcement | `annual_admission_quota` chỉ check ở activate path (precondition `quota > 0`); approve / bulk_approve / finalize không enforce `current_enrolled < quota`. Có thể vượt chỉ tiêu Tổng cục duyệt. |
| ADM-027 | P2 | Gap/Workflow | Change path | Không có endpoint `change_path` / `transfer_path`; thí sinh đổi nguyện vọng buộc withdraw + tạo profile mới, mất tài liệu verified + fee đã nộp. Use case rất phổ biến mùa cao điểm. |
| ADM-028 | P3 | Gap/Ops | Magic link TTL | `ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS=7`; email task gửi 1 lần (`email_tasks.py:182`); không có Celery beat reminder + không có dashboard "magic links sắp hết hạn". |
| ADM-029 | P3 | Gap/Workflow | Finalize rollback | `ENROLLED` là state terminal; không có endpoint admin-only undo finalize trong grace period. Sai khóa/ niên khóa phải drop_student + tạo profile mới. |
| ADM-030 | P3 | Gap/UX | Bulk approve | Bulk approve button disable khi 1 row vi phạm `available_actions.approve`, không có per-row tooltip/highlight chỉ ra row blocking. Manager peak-time chọn 100+ hồ sơ phải dò thủ công. |
| ADM-031 | P2 | Gap/UX | Documents tab | UI `DocumentsTab` quá kỹ thuật cho officer: row không nói rõ next-step, format dialog dễ làm officer tưởng là "chứng cứ", enum `photo` có 4 nhãn khác nhau ("Ảnh chụp" vs "Bản photocopy" vs "Bản photo/scan" vs "Bản photocopy"), progress count `uploaded` ngang `verified`. **UI-only fix, không touch backend** — backend model đã đủ. |

## Phân loại intent vs oversight

Phân loại này được cập nhật sau bước check git blame, comments và design docs.

### Nhóm 1 - Intent thuần

Giữ design hiện tại, có thể cần document/UI rõ hơn:

- `ADM-002`: `DocumentGroup` là method-level template theo design DRY. Model/comment xác định documents phụ thuộc `offering_type + admission_method`; commit `71b6b0af` ghi "use full override strategy". Vấn đề chính là route/UI gọi là path documents dễ làm người dùng hiểu là path-level config.
- `ADM-018`: repository comment ghi rõ active paths by offering lấy "across all academic years"; multi-year intake là feature.

### Nhóm 2 - Intent nhưng code chưa enforce/đồng bộ

- `ADM-005`: admin emergency edit là intent, nhưng `upsert_criteria`/`upsert_documents` thiếu guard nên manager có thể bypass rule manager chỉ sửa draft.
- `ADM-008`: comment/spec nói "Admin approves = activate", nhưng route activate/deactivate đang cho manager đi qua.
- `ADM-013`: magic-link design doc nói lock cả token và profile, nhưng code hiện chỉ lock chắc chắn token row.

### Nhóm 3 - Oversight rõ ràng

Các finding này nên được xem là bug/gap cần fix: `ADM-001`, `ADM-003`, `ADM-004`, `ADM-006`, `ADM-007`, `ADM-009`, `ADM-010`, `ADM-011`, `ADM-012`, `ADM-014`, `ADM-015`, `ADM-016`, `ADM-017`, `ADM-019`, `ADM-021`.

### Nhóm 4 - Ambiguous

- `ADM-020`: cần quyết định product/compliance: sau delete profile thì xóa file luôn hay giữ trong retention/quarantine.

### Test gap riêng

- `ADM-022`: CSV injection đã có coverage trong `test_csv_injection.py`; các gap test còn lại nên đi kèm PR fix tương ứng.

## Open questions

1. `ADM-002`: Giữ method-level template và đổi route/UI thành "Method documents" kèm cảnh báo affected paths, hay tách path-level override layer?
2. `ADM-005`: Admin edit active path có cần version/audit log riêng không?
3. `ADM-008`: Manager activate được phép hay admin-only?
4. `ADM-013`: Cần lock profile thật trong code hay chỉnh doc để xác nhận lock token là đủ?
5. `ADM-016`: FE bỏ tự tính và chờ backend response, hay port đầy đủ `best_n` logic và đánh dấu "preview"?
6. `ADM-018`: Active paths giữ multi-year hay filter current academic year? Nếu giữ thì UI có chọn/hiển thị year không?
7. `ADM-020`: Sau delete, xóa file luôn hay chuyển sang quarantine/retention bucket?
8. `ADM-017`: Enforce "1 published intake/offering" bằng DB constraint, hay client phải chỉ định `academic_year` khi tạo profile?

## Kế hoạch fix theo wave

### Wave 1 - P1 Security/Data Integrity

| PR | Finding | Effort | Mô tả |
| --- | --- | --- | --- |
| W1-1 | ADM-001 | 1-2h | Thêm `Depends(get_admission_for_user)` hoặc scope check tương đương cho `/fee-status`; test cross-unit/unassigned. |
| W1-2 | ADM-006 | 1-2h | Thêm `csv_safe_cell()` prefix `'` cho cell bắt đầu `=`, `+`, `-`, `@`, tab, CR; extend test CSV injection hiện có. |
| W1-3 | ADM-005 | 2h | Apply guard archived/manager-non-draft cho `upsert_criteria` và `upsert_documents`. |
| W1-4 | ADM-004 | 2h | Unify `validate_activation` với readiness logic của coverage matrix. |
| W1-5 | ADM-007 | 4-6h | Stage upload vào temp path; DB commit trước; move/cleanup qua post-commit callback. |

### Wave 2 - Contract & data model

Chạy sau khi chốt Q1, Q4, Q5.

| PR | Finding | Effort |
| --- | --- | --- |
| W2-1 | ADM-015 | 2-3h |
| W2-2 | ADM-003 | 4-6h |
| W2-3 | ADM-002 | 2-4h |
| W2-4 | ADM-013 | 2-3h |

### Wave 3 - Auth/Audit/Validation hardening

| PR | Finding | Effort |
| --- | --- | --- |
| W3-1 | ADM-008 | 1-2h |
| W3-2 | ADM-009 | 2-3h |
| W3-3 | ADM-010 | 1-2h |
| W3-4 | ADM-014 | 2-3h |
| W3-5 | ADM-019 | 2-3h |

### Wave 4 - UX/contract & concurrency

Chạy sau khi chốt Q5, Q6.

| PR | Finding | Effort |
| --- | --- | --- |
| W4-1 | ADM-016 | 4-6h |
| W4-2 | ADM-021 | 2-3h |
| W4-3 | ADM-011 | 2-3h |
| W4-4 | ADM-012 | 2h |

### Wave 5 - Edge case & retention

Chạy sau khi chốt Q7, Q8.

| PR | Finding | Effort |
| --- | --- | --- |
| W5-1 | ADM-017 | 3-4h |
| W5-2 | ADM-018 | 2h |
| W5-3 | ADM-020 | 2-3h |

### Wave 6 - Test coverage

`ADM-022` không nên là PR riêng lớn; mỗi PR fix ở các wave trên bundle regression test tương ứng.

## Chi tiết phát hiện

### ADM-001 - Fee status endpoint thiếu IDOR scope

Severity: `P1`

Loại: `Bug/Security`

Evidence:

- `Backend_FastAPI/app/routers/admissions.py:1251` định nghĩa `/{profile_id}/fee-status`.
- `Backend_FastAPI/app/routers/admissions.py:1257` chỉ dùng `get_current_active_user`.
- `Backend_FastAPI/app/services/admission_service.py:4894` `check_application_fee_status`.
- `Backend_FastAPI/app/services/admission_service.py:4907` gọi `repo.get_by_id(profile_id)` và trả fee fields.

Impact:

Bất kỳ user authenticated nào có thể thử ID profile và đọc `requires_fee`, `fee_amount`, `fee_status`, `fee_paid_at`, `can_approve` của hồ sơ ngoài scope. Đây là IDOR rõ ràng vì endpoint không dùng `get_admission_for_user`/`get_admission_for_manager` và service không gọi `_check_idor_access`.

Hướng xử lý:

Đưa profile access vào dependency hoặc truyền `current_user` vào service rồi gọi `_check_idor_access`. Thêm test cross-unit, same-unit-but-unassigned officer, admin allowed.

### ADM-002 - Document config của path thực tế là shared method override

Severity: `P3`

Loại: `Intent/UX gap`

Intent classification:

Đây không còn được xem là data bug sau khi đối chiếu blame/comments/design docs. `DocumentGroup` là method-level template theo design DRY; model/comment xác định documents phụ thuộc `offering_type + admission_method`, và commit `71b6b0af` ghi "use full override strategy".

Evidence:

- `Backend_FastAPI/app/services/admission_path_service.py:258` `upsert_documents`.
- `Backend_FastAPI/app/services/admission_path_service.py:275-284` tìm `DocumentGroup` theo `offering_type_id` và `admission_method_id`.
- `Backend_FastAPI/app/services/admission_path_service.py:304-306` xóa toàn bộ `DocumentGroupItem` của group đó rồi insert lại.
- `Backend_FastAPI/app/routers/admission_paths.py:373-390` route tên là update documents cho một `path_id`.

Impact:

Rủi ro chính là UX/API wording: Admin/Manager có thể nghĩ đang sửa hồ sơ yêu cầu cho một admission path, trong khi design là sửa template theo method. Nếu giữ design hiện tại, route/UI cần làm rõ đây là method-level document override và cảnh báo affected paths.

Hướng xử lý:

Ưu tiên theo intent hiện tại: đổi naming/UI copy thành "Method documents" hoặc "Document template for method", hiển thị affected paths trước khi lưu, và audit theo `DocumentGroup`. Chỉ tách path-level override nếu product quyết định scope cần độc lập theo path.

### ADM-003 - Criteria có thể bị mutate chéo path

Severity: `P1`

Loại: `Gap/Data`

Evidence:

- `Backend_FastAPI/app/services/admission_path_service.py:211` `upsert_criteria`.
- `Backend_FastAPI/app/services/admission_path_service.py:221-225` nếu `path.criteria` tồn tại thì update trực tiếp object đó.
- `Backend_FastAPI/app/services/admission_path_service.py:244-246` xóa toàn bộ subject group mappings theo `criteria.id`.

Impact:

Nếu dữ liệu seed/import/migration cho phép nhiều `AdmissionPath` trỏ cùng `criteria_id`, thao tác sửa criteria của một path sẽ đổi criteria và subject groups của các path khác. Hiện code không enforce invariant "criteria owned by exactly one path".

Hướng xử lý:

Thêm DB unique constraint hoặc service invariant để criteria là path-owned. Khi sửa criteria shared, clone criteria mới cho path trước khi mutate. Bổ sung migration cleanup dữ liệu shared nếu có.

### ADM-004 - Activate path không validate criteria/documents

Severity: `P1`

Loại: `Bug/Config`

Evidence:

- `Backend_FastAPI/app/routers/admission_paths.py:419-425` route doc nói phải có criteria, document config, quota.
- `Backend_FastAPI/app/services/admission_path_service.py:333-370` `validate_activation` chỉ check status và quota, phần criteria/documents là placeholder.
- `Backend_FastAPI/app/services/admission_path_service.py:603-610` coverage matrix lại tính `can_activate = has_criteria and has_documents and has_quota`.
- `frontend/src/app/(dashboard)/admin/admission-config/_components/Phase3Config/ConfigReview.tsx:224-227` UI enable nút activate dựa trên `path.can_activate`.

Impact:

API có thể activate path thiếu criteria/documents. UI/coverage matrix có thể báo chưa ready nhưng backend route vẫn cho activate nếu gọi trực tiếp hoặc nếu response `can_activate` bị tính bằng placeholder.

Hướng xử lý:

Hoàn thiện `validate_activation` dùng cùng logic với coverage matrix: criteria tồn tại, resolved documents không rỗng, quota > 0, status hợp lệ. Thêm test route activate draft thiếu criteria/docs trả 400.

### ADM-005 - Active/archived path vẫn sửa criteria/documents được

Severity: `P1`

Loại: `Bug/Config`

Evidence:

- `Backend_FastAPI/app/services/admission_path_service.py:180-188` `update_path` chặn archived và chặn manager sửa non-draft.
- `Backend_FastAPI/app/routers/admission_paths.py:343-357` update criteria gọi thẳng `upsert_criteria`.
- `Backend_FastAPI/app/routers/admission_paths.py:378-390` update documents gọi thẳng `upsert_documents`.
- `Backend_FastAPI/app/services/admission_path_service.py:211-256` và `258-327` không có status guard tương đương.

Impact:

Path đã active hoặc archived vẫn có thể bị đổi rule/document requirement, làm thay đổi behavior của hồ sơ sau khi tuyển sinh đã mở. Đây là rủi ro governance và audit.

Hướng xử lý:

Áp cùng lifecycle guard cho `upsert_criteria` và `upsert_documents`: archived không sửa; manager chỉ draft; admin muốn sửa active phải tạo revision/version hoặc deactivate trước.

### ADM-006 - CSV export có rủi ro formula injection

Severity: `P1`

Loại: `Bug/Security`

Evidence:

- `Backend_FastAPI/app/routers/admissions.py:511-523` ghi `lead.full_name`, `lead.email`, `lead.phone`, `profile.citizen_id`, `program.name` trực tiếp vào CSV.
- Các field này có thể bắt đầu bằng `=`, `+`, `-`, `@`, tab hoặc carriage return.

Impact:

Khi staff mở CSV bằng Excel/LibreOffice, field độc hại có thể được xử lý như công thức. Đây là vector CSV/formula injection từ dữ liệu lead/applicant.

Hướng xử lý:

Escape cell nguy hiểm trước khi write CSV, ví dụ prefix `'` cho giá trị bắt đầu bằng ký tự công thức hoặc control char. Bổ sung test export với lead name `=HYPERLINK(...)`.

### ADM-007 - File upload/reset mutate filesystem trước DB commit

Severity: `P1`

Loại: `Bug/Data`

Evidence:

- `Backend_FastAPI/app/services/admission_service.py:3274-3281` upload xóa old file trước khi DB update/commit.
- `Backend_FastAPI/app/services/admission_service.py:3296-3297` upload ghi file mới trước `db.flush`.
- `Backend_FastAPI/app/services/admission_service.py:3315` chỉ flush, router commit sau.
- `Backend_FastAPI/app/services/admission_service.py:3695-3705` reset xóa file vật lý trước flush/commit.

Impact:

Nếu DB flush/commit/audit/callback fail sau khi xóa/ghi file, DB có thể vẫn trỏ old file đã mất, hoặc file mới nằm orphan. Đây là consistency bug giữa DB và filesystem.

Hướng xử lý:

Stage upload vào temp path, update DB, commit, rồi move/cleanup bằng post-commit callback. Với reset, đánh dấu DB trước rồi xóa file post-commit; rollback không được xóa file.

### ADM-008 - Manager có thể activate/deactivate path

Severity: `P2`

Loại: `Gap/RBAC`

Evidence:

- `Backend_FastAPI/app/routers/admission_paths.py:112-114` `get_admission_path_for_user` cho admin/manager full access.
- `Backend_FastAPI/app/routers/admission_paths.py:414-430` activate chỉ dùng dependency trên.
- `Backend_FastAPI/app/routers/admission_paths.py:451-462` deactivate tương tự.
- `Backend_FastAPI/app/services/admission_path_service.py:183-188` comment business rule nói "Manager can only edit draft paths (Admin approves = activate)".

Impact:

Nếu nghiệp vụ thật sự yêu cầu admin duyệt/activate, manager hiện có thể bypass approval lifecycle. Nếu manager được phép activate thì comment, UI text và audit rule đang lệch.

Hướng xử lý:

Chốt lại policy. Nếu admin-only, thêm guard role trong service hoặc route. Nếu manager được phép, sửa documentation/comment và audit.

### ADM-009 - Admission-config detail endpoints thiếu auth/active filter

Severity: `P2`

Loại: `Bug/Security`

Evidence:

- List endpoint dùng `get_config_filter`: `Backend_FastAPI/app/routers/admission_config.py:99-105`.
- `get_config_filter` enforce non-admin chỉ xem active: `Backend_FastAPI/app/core/deps.py:1877-1890`.
- Detail endpoints không dùng filter/current_user:
  - `Backend_FastAPI/app/routers/admission_config.py:113-120` subject by code.
  - `Backend_FastAPI/app/routers/admission_config.py:223-229` subject group by code.
  - `Backend_FastAPI/app/routers/admission_config.py:355-362` method by code.
  - `Backend_FastAPI/app/routers/admission_config.py:809-819` shared document group.

Impact:

Non-admin hoặc anonymous-like callers theo router dependency hiện tại có thể đọc config inactive/draft bằng detail route, trong khi list route đã cố tình lọc active.

Hướng xử lý:

Áp `Depends(get_config_filter)` cho detail routes và trả 404 nếu item inactive mà user không phải admin/manager.

### ADM-010 - `payment_status` filter không nhất quán giữa list/status-counts/export

Severity: `P2`

Loại: `Bug/API`

Evidence:

- List validate: `Backend_FastAPI/app/routers/admissions.py:111-113`.
- Status counts không validate: `Backend_FastAPI/app/routers/admissions.py:160-190`.
- Export không validate: `Backend_FastAPI/app/routers/admissions.py:456-488`.
- Repository helper bỏ qua invalid value vì chỉ có các nhánh `paid/unpaid/partial/no_fee`: `Backend_FastAPI/app/repositories/admission_repository.py:251-282`.

Impact:

Client typo `payment_status=paidd` ở export/status-counts sẽ không filter và có thể nhận dataset rộng hơn mong đợi trong scope của user. Đây là data minimization/API contract gap.

Hướng xử lý:

Centralize enum validation cho mọi endpoint nhận `payment_status`. Invalid value trả 400.

### ADM-011 - Bulk assign thiếu lock/version

Severity: `P2`

Loại: `Edge/Data`

Evidence:

- `Backend_FastAPI/app/services/admission_service.py:7036-7039` loop lấy profile bằng `get_profile_by_id_with_lead`.
- `Backend_FastAPI/app/services/admission_service.py:7050-7052` set `profile.lead.assigned_officer_id`.
- `Backend_FastAPI/app/services/admission_service.py:7069` flush sau cả batch.
- Không có `with_for_update`/version check trong path này.

Impact:

Hai admin/manager bulk assign cùng profile hoặc một bulk assign đụng single assign có thể last-writer-wins. Audit có thể ghi nhiều assignment nhưng final officer không deterministic theo ý người dùng.

Hướng xử lý:

Lock lead/profile row khi assign, hoặc dùng optimistic version trên lead/profile. Cân nhắc trả conflict nếu row đã thay đổi trong batch.

### ADM-012 - Bulk action leak raw exception text

Severity: `P2`

Loại: `Gap/Security`

Evidence:

- Bulk approve: `Backend_FastAPI/app/services/admission_service.py:6736-6739` trả `str(e)` vào `errors`.
- Bulk reject: `Backend_FastAPI/app/services/admission_service.py:6952-6955`.
- Bulk assign: `Backend_FastAPI/app/services/admission_service.py:7064-7067`.

Impact:

Internal DB/validation exception có thể bị trả về client staff. Với batch API, điều này dễ lộ implementation detail và làm error contract không ổn định.

Hướng xử lý:

Map domain exceptions sang message an toàn. Generic exception chỉ trả "Unexpected error" kèm correlation id; log chi tiết server-side.

### ADM-013 - Magic-link confirm không lock profile như comment nói

Severity: `P2`

Loại: `Edge/Concurrency`

Evidence:

- `Backend_FastAPI/app/repositories/admission_repository.py:1088-1090` docstring nói lock token và profile.
- `Backend_FastAPI/app/repositories/admission_repository.py:1100-1107` query select token + `selectinload(profile)` + `with_for_update`.
- `selectinload` chạy query riêng cho profile, nên lock chỉ chắc chắn áp trên row token của main select.
- Confirm update profile status: `Backend_FastAPI/app/services/admission_service.py:6434-6455`.
- Override invalidate tokens sau khi đổi profile: `Backend_FastAPI/app/services/admission_service.py:5188-5190`, repository delete token `1149-1167`.

Impact:

Concurrent magic-link confirm và override/finalize có thể có race/deadlock/serialization abort tùy isolation và DB. Comment tạo cảm giác đã lock profile nhưng code chưa đảm bảo.

Hướng xử lý:

Lock profile row explicit bằng query `SELECT AdmissionProfile ... FOR UPDATE` theo `token.profile_id` sau khi lock token, và chuẩn hóa lock order cho confirm/override/finalize.

### ADM-014 - Override thiếu durable audit

Severity: `P2`

Loại: `Gap/Audit`

Evidence:

- `Backend_FastAPI/app/services/admission_service.py:5217-5220` TODO ghi rõ chưa wire vào `audit_service.log_*`, hiện chỉ `log.warning`.

Impact:

Admin override là bypass nghiệp vụ quan trọng nhưng không có audit durable trong DB như các action khác. Log runtime có thể bị rotate/mất và khó truy vấn compliance.

Hướng xử lý:

Ghi `entity_audit_log` với old/new status, reason, bypass_rules, actor, timestamp, source. Thêm regression test query audit row sau override.

### ADM-015 - Optimistic lock của override/finalize không hoạt động theo contract

Severity: `P2`

Loại: `Bug/Contract`

Evidence:

- Override route doc nói request có `version`: `Backend_FastAPI/app/routers/admissions.py:1693-1697`.
- Finalize route doc nói request có `version`: `Backend_FastAPI/app/routers/admissions.py:1853-1855`.
- `OverrideRequest` không có field `version`: `Backend_FastAPI/app/schemas/admission.py:1202-1229`.
- `FinalizeRequest` là empty model: `Backend_FastAPI/app/schemas/admission.py:1232-1242`.
- Router truyền `data.model_dump()`: `Backend_FastAPI/app/routers/admissions.py:1710-1715` và `1865-1870`.
- Service chỉ check nếu `data.get("version") is not None`: `Backend_FastAPI/app/services/admission_service.py:5172-5178`, `5422-5428`.

Impact:

Client/tests có gửi `version` cũng bị Pydantic ignore trước khi vào service. Các action override/finalize mất optimistic lock dù documentation nói có.

Hướng xử lý:

Thêm `version: int` vào request schemas hoặc bỏ doc/check nếu quyết định không lock. Khuyến nghị require version cho state-changing admin actions.

### ADM-016 - Frontend scoring không khớp backend ở `best_n`

Severity: `P2`

Loại: `Bug/Frontend`

Evidence:

- Frontend helper tự tính score: `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/admission-scoring.ts:32-58`.
- UI dùng total để hiện badge/đạt sàn: `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/AdmissionScoresTab.tsx:77-85`, `307-355`.
- Backend chọn subject theo mode trước khi tính: `Backend_FastAPI/app/services/admission_scoring_service.py:253-259`.
- Backend `best_n` sort score desc rồi lấy N: `Backend_FastAPI/app/services/admission_scoring_service.py:395-401`.
- Frontend tests chỉ cover weighted sum fallback, không cover `best_n`/fixed required count: `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/admission-scoring.test.ts:4-35`.

Impact:

Với `subject_selection_mode = best_n` hoặc `required_subject_count` nhỏ hơn số môn nhập, frontend có thể cộng tất cả môn và báo đạt điểm sàn trong khi backend chỉ lấy N môn. Dù backend là source of truth, UI gây hiểu nhầm cho officer/manager.

Hướng xử lý:

Không tự tính eligibility/scoring ở frontend; hiển thị `score_result`/computed fields backend trả về. Nếu cần preview, gọi endpoint preview backend hoặc port đầy đủ selection logic và mark rõ là preview.

### ADM-017 - `create_profile` chọn academic info theo implicit newest/published

Severity: `P2`

Loại: `Edge/Data`

Evidence:

- `Backend_FastAPI/app/services/admission_service.py:1803-1812` lấy history `published_only=False`, chọn first published hoặc first record.
- `Backend_FastAPI/app/repositories/organization_repository.py:652-670` history sort `academic_year.desc()`.

Impact:

Nếu một offering có nhiều academic info published, hồ sơ mới sẽ được gán vào năm mới nhất một cách implicit. Nếu team đang mở song song nhiều intake/năm học, lead có thể vào sai config/quota/fee.

Hướng xử lý:

Enforce invariant one published academic info per offering hoặc yêu cầu admission path/academic_year rõ trong create flow. Thêm DB constraint partial hoặc service validation.

### ADM-018 - Active path dropdown multi-year cần UI rõ hơn

Severity: `P3`

Loại: `Intent/UX gap`

Intent classification:

Đây là design intent nếu giữ multi-year intake pattern. Repository comment ghi rõ active paths by offering lấy "across all academic years".

Evidence:

- `Backend_FastAPI/app/repositories/admission_path_repository.py:145-163` `get_active_paths_by_offering_id` lấy active paths cho offering qua mọi `OfferingAcademicInfo.is_published == True`.
- Comment line 150 nói "across all academic years".

Impact:

Nếu nhiều academic year cùng published, dropdown admission methods cho lead có thể hiển thị nhiều path/method qua nhiều năm. Đây là feature nếu UI hiển thị year rõ; là UX/data-entry risk nếu người dùng không biết mình đang chọn intake nào.

Hướng xử lý:

Nếu giữ multi-year: response/UI phải hiển thị `academic_year` và có thể cho filter/chọn year. Nếu product muốn intake đơn tại một thời điểm, chuyển sang filter current academic year và enforce invariant ở ADM-017.

### ADM-019 - File upload validation chưa đủ cứng

Severity: `P3`

Loại: `Gap/Security`

Evidence:

- `Backend_FastAPI/app/services/admission_service.py:3242-3248` validate bằng `file.content_type`.
- `Backend_FastAPI/app/services/admission_service.py:3284-3289` extension không thuộc whitelist thì đổi thành `.bin` thay vì reject.

Impact:

`content_type` từ client có thể giả mạo. `.bin` fallback làm policy file type mơ hồ, trong khi message nói chỉ PDF/JPG/PNG.

Hướng xử lý:

Sniff magic bytes và reject extension/content mismatch. Không fallback `.bin` cho upload yêu cầu tài liệu chính thức.

### ADM-020 - Delete draft profile không cleanup uploaded files

Severity: `P3`

Loại: `Gap/Data`

Evidence:

- `Backend_FastAPI/app/services/admission_service.py:5531-5635` delete profile tạo consultation/audit rồi `db.delete(profile)`.
- Không có cleanup `uploads/admissions/{profile_id}`.

Impact:

Draft profile đã upload tài liệu rồi bị xóa sẽ để lại file vật lý orphan. Đây là chi phí lưu trữ và rủi ro dữ liệu cá nhân.

Hướng xử lý:

Sau commit, xóa thư mục profile upload. Nếu cần retention compliance, chuyển sang quarantine/retention bucket có audit thay vì để orphan.

### ADM-021 - Admission path action flags chưa role-aware

Severity: `P3`

Loại: `Gap/Frontend/API contract`

Evidence:

- `Backend_FastAPI/app/services/admission_path_service.py:514-531` `compute_available_actions` chỉ dựa vào status.
- `Backend_FastAPI/app/services/admission_path_service.py:533-544` `can_edit/can_activate` cũng không nhận user role.
- UI dựa vào fields này để hiện action: `frontend/src/app/(dashboard)/admin/admission-config/_components/Phase3Config/PathsList.tsx:249-276`.

Impact:

Frontend V3 nói UI phải theo permission flags backend. Nhưng flags hiện không role-aware, nên manager có thể thấy action mà backend/service policy muốn admin-only, hoặc thấy `save` trên active path trong khi `update_path` sẽ chặn manager.

Hướng xử lý:

Tính `available_actions`, `can_edit`, `can_activate` theo `(path, current_user)` trong response builder.

### ADM-022 - Test coverage gaps

Severity: `P3`

Loại: `Gap/Test`

Observed gaps:

- Fee-status tests hiện chủ yếu happy path; chưa thấy regression cross-unit/unassigned IDOR cho `GET /api/admissions/{id}/fee-status`.
- Chưa thấy backend regression cho activation thiếu criteria/docs, manager activate/deactivate, hoặc criteria/documents edit trên active/archived path.
- CSV injection đã có coverage trong `test_csv_injection.py`; khi sửa ADM-006 chỉ cần extend nếu test hiện tại chưa cover admission export cụ thể. Vẫn thiếu test invalid `payment_status` cho export/status-counts.
- File upload/reset/delete chưa có test rollback/cleanup file vật lý.
- Bulk admission assign chưa có concurrency/last-writer test; bulk approve/reject có bundle tests nhưng raw error mapping còn gap.
- Override có workflow tests, nhưng chưa có durable audit assertion và version conflict assertion thực sự fail khi stale.
- Frontend scoring tests chỉ cover weighted sum; thiếu `best_n`, fixed required count, and "backend source of truth" rendering behavior.

## Ưu tiên xử lý đề xuất

1. Fix ngay ADM-001, ADM-004, ADM-005, ADM-006, ADM-007 vì ảnh hưởng bảo mật hoặc production data.
2. Giữ ADM-002 theo method-level intent trừ khi product chọn path-level override; ADM-003 vẫn cần enforce invariant/clone để tránh shared criteria ngoài ý muốn.
3. Thêm regression tests cho P1 trước hoặc cùng PR fix.
4. Chuẩn hóa contract state-changing actions: action flags role-aware, version bắt buộc, error response không leak.
5. Dọn edge cases academic year/published intake để tránh sai dữ liệu trong mùa tuyển sinh.

---

## Wave 2 findings — 2026-04-28

Phát hiện từ pass đánh giá user guide ở góc độ product/compliance/UX. Các finding bên dưới đã được verify trực tiếp tại code; xem [Verified-FALSE log](#verified-false-claims--2026-04-28) cho các claim không phải bug.

### ADM-023 — Magic-link brute-force qua resend + rate limit per-IP

Severity: `P1`

Loại: `Bug/Security`

Evidence:

- `Backend_FastAPI/app/config.py:354-355` — `ADMISSION_CONFIRM_CCCD_DIGITS=4`, `ADMISSION_CONFIRM_MAX_ATTEMPTS=5`.
- `Backend_FastAPI/app/services/admission_service.py:6823` — verify so sánh `profile.citizen_id[-4:]`; tăng `token_obj.attempt_count` (line 6827) chứ không tăng counter trên `AdmissionProfile`.
- `Backend_FastAPI/app/repositories/admission_repository.py:1028-1058` — `create_confirmation_token` luôn gọi `invalidate_existing_tokens(profile_id)` rồi tạo token mới với `attempt_count=0`.
- `Backend_FastAPI/app/routers/admissions.py:2084` — `/send-confirmation` có `@limiter.limit(RateLimits.DATA_WRITE)` (200/h).
- `Backend_FastAPI/app/core/rate_limits.py:41` — `Limiter` global `key_func=get_remote_address`, không dùng `get_user_id_key` hoặc per-resource key.
- `Backend_FastAPI/app/models/admission.py:516` — `AdmissionConfirmationToken.profile_id` `unique=True` (1 active token tại 1 thời điểm).

Impact:

CCCD 4 chữ số chỉ có 10⁴ = 10.000 tổ hợp. Mỗi lần manager bấm "Send Confirmation" tạo token mới với 5 attempts → attacker gửi yêu cầu resend nhiều lần (rate limit per IP, có thể vòng IP) sẽ tích lũy attempts không giới hạn. Không có cumulative lock trên `AdmissionProfile` để chặn cross-token brute force.

Rủi ro thực tế giảm bởi `/send-confirmation` yêu cầu manager scope (`get_admission_for_manager`), nên attacker phải có manager creds hoặc social engineer manager bấm resend. Với scope hiện tại nguy cơ trung bình; với token confirmation public endpoint nguy cơ cao.

Hướng xử lý:

1. Thêm rate limit per `profile_id` trên `/send-confirmation` (vd 3 resend/24h/profile, dùng Redis key `confirm_send:{profile_id}`).
2. Thêm `confirmation_lock_until` trên `AdmissionProfile`; khi tổng `attempt_count` cộng dồn qua các token vượt ngưỡng (vd 10 fail/24h), khoá profile, yêu cầu admin unlock.
3. Cân nhắc dùng full CCCD (12 chữ số = 10¹²) hoặc thêm DOB ngày-tháng làm second factor; CCCD-4 hiện không đạt chuẩn auth secondary.
4. Audit log mỗi lần invalidate token + thông báo lead nếu phát hiện regenerate bất thường.

### ADM-024 — Schema_version=1 grandfathering tạo bypass vĩnh viễn cho fail-closed

Severity: `P2`

Loại: `Edge/Data`

Evidence:

- `Backend_FastAPI/alembic/versions/aa1i2j3k4l5m_pr6_allow_unverified_submission.py:62` — migration set `admission_path.allow_unverified_submission = TRUE` cho **mọi** path tại deploy time.
- `Backend_FastAPI/alembic/versions/aa1i2j3k4l5m_pr6_allow_unverified_submission.py:75-87` — backfill `applied_rules` với `schema_version: 1` + `allow_unverified_submission: TRUE` cho profile ở status `draft/submitted/rejected/revision_requested/resubmitted`.
- `Backend_FastAPI/app/services/admission_service.py:541-544` — validator default `schema_version=1` → `allow_unverified=True` (legacy mode).
- `Backend_FastAPI/app/services/admission_service.py:2095-2104` — profile mới `schema_version=2` + snapshot từ `admission_path.allow_unverified_submission`. Vì migration set tất cả path = TRUE, profile mới dưới path cũ vẫn `allow_unverified=True`.
- `applied_rules` immutable qua trigger `enforce_applied_rules_immutability` → không thể upgrade schema_version sau create.

Impact:

Thiết kế "snapshot tại create" là intent (memory `[finance-design-doc-not-canonical]` ngầm ủng hộ pattern này), nhưng hệ quả là:

1. Draft tồn đọng từ pre-PR#6 + draft tồn đọng tại deploy time keep `allow_unverified=true` mãi mãi.
2. Path cũ chưa được admin flip về `False` sau migration cũng forward `allow_unverified=true` cho mọi profile mới.
3. Không có job/UI cho admin biết path nào đang ở chế độ legacy + flip về strict.

Đây không phải security hole nhưng làm fail-closed của PR #6 không có hiệu lực thực tế trong production hiện tại.

Hướng xử lý:

1. **Operational**: Audit prod query để biết bao nhiêu path đang `allow_unverified=true`; thiết lập kế hoạch flip về `false` khi UI verify document đầy đủ tools.
2. **UI**: Cho admin thấy flag này trên Path detail + cảnh báo "Legacy fail-open mode".
3. **Data hygiene**: Job định kỳ liệt kê profile draft/rejected có `schema_version=1` để biết populate. Nếu cần upgrade, đẩy qua override trigger.
4. **Doc**: Update user guide làm rõ sematic `schema_version=1` ≠ "ngẫu nhiên cũ" mà là grandfather flag.

### ADM-025 — Paper_submitted không có evidence để compliance audit

Severity: `P1`

Loại: `Compliance/Data`

**Status: CLOSED-NOT-NEEDED (2026-04-28)**

Resolution: Hệ thống đã có pattern đúng — `DocumentType.requires_upload`. Document cần evidence số hóa thì cấu hình `requires_upload=true` (file upload chính = evidence). Document chỉ cần ghi nhận bản giấy thì `requires_upload=false` + `paper_submitted`. Không thêm `evidence_photo_path` để tránh bắt officer upload 2 ảnh cho cùng document.

Verified guard: `Backend_FastAPI/app/services/admission_document_policy.py:174-180` — action `paper_submitted` chỉ authorize khi `(not requires_upload)`. Document `requires_upload=true` không thể bị bypass qua paper_submitted.

Evidence (giữ lại để tham chiếu lịch sử):

- `Backend_FastAPI/app/repositories/admission_repository.py:985-1022` — `confirm_document_format()` set `verified_format`, `status='verified'`. Cho doc `requires_upload=true` đã có file upload làm evidence.
- `Backend_FastAPI/app/services/admission_document_policy.py:174-180` — guard chặn paper_submitted với requires_upload=true.

Cleanup nhỏ (chỉ làm nếu sau này phát sinh):

1. UI wording rõ "Upload ảnh/scan tài liệu" cho doc `requires_upload=true` để officer hiểu file chính là evidence.
2. Có thể thêm `physical_location` (text) cho doc `requires_upload=false` nếu trường cần quản lý kho hồ sơ giấy — đây là enhancement, không phải compliance gap.

Re-open trigger: nếu audit thực tế phát hiện `paper_submitted` vẫn áp dụng được cho doc `requires_upload=true` (tức policy guard bị bypass).

### ADM-026 — Quota tuyển sinh không enforce ở approve/finalize

Severity: `P1`

Loại: `Compliance/Data`

Evidence:

- `Backend_FastAPI/app/models/offering_academic_info.py:44` — `annual_admission_quota` field tồn tại.
- `Backend_FastAPI/app/services/admission_path_service.py:469-491` — chỉ check `quota > 0` ở `validate_activation` (precondition gate, không phải runtime check).
- `Backend_FastAPI/app/services/admission_service.py:4488` (`approve_profile`), `5786` (`finalize_profile`), `6963` (`bulk_approve_profiles`) — không có query `SELECT COUNT(*) WHERE status='enrolled' AND offering_academic_info_id=?` để so sánh với quota.
- `grep "quota" admission_service.py` → 0 hits ngoài phần KPI planning.

Impact:

Trường có thể tuyển vượt chỉ tiêu Tổng cục GDNN duyệt → vi phạm pháp lý Luật GDNN. Bulk approve mùa cao điểm (tháng 8-9) đặc biệt nguy hiểm vì manager có thể chọn vài trăm hồ sơ cùng lúc.

Hướng xử lý:

1. Hard cap ở `approve_profile` + `bulk_approve_profiles` + `finalize_profile`: query enrolled count, raise `BusinessRuleViolation("Vượt chỉ tiêu tuyển sinh")` nếu vượt.
2. Soft warning trên dashboard manager khi `enrolled / quota > 0.8`.
3. Bulk approve trả về preview "X/Y sẽ vượt chỉ tiêu" trước khi execute.
4. Cân nhắc DB constraint partial unique nếu DB constraint khả thi.

### ADM-027 — Không có change-path workflow

Severity: `P2`

Loại: `Gap/Workflow`

Evidence:

- `grep -in "change_path|change_program|transfer_path" Backend_FastAPI/app/routers/admissions.py` → 0 matches.
- User guide quick reference: "Hồ sơ sai ngành/phương thức → Withdraw → tạo profile mới".
- Withdraw là final state transition với multiple side effects (lead pipeline, applied_rules immutable).

Impact:

Use case "thí sinh đổi nguyện vọng" cực phổ biến TNPC (vd Công nghệ ô tô → Điện công nghiệp). Hiện tại buộc:

1. Withdraw profile cũ → mất audit trail liên kết.
2. Tạo profile mới → nhập lại thông tin, upload lại tài liệu.
3. Manager re-verify từ đầu.
4. Application fee đã nộp → cần manual refund hoặc transfer qua Finance flow.

Gây UX nặng + risk lệch dữ liệu nếu officer copy-paste sai.

Hướng xử lý:

1. Thêm endpoint `POST /api/admissions/{id}/change-path` (admin/manager only); body: `{new_path_id, reason}`.
2. Logic: clone documents verified sang admission_path mới (nếu method tương thích), reset criteria/scoring, giữ application fee đã nộp (Finance side: cập nhật fee allocation).
3. Audit log đầy đủ: old_path, new_path, actor, reason, ts.
4. State machine: chỉ cho change từ `draft / submitted / rejected / revision_requested` (không cho từ approved trở đi để tránh phá data verified).

### ADM-028 — Magic-link TTL không có auto-reminder + dashboard

Severity: `P3`

Loại: `Gap/Ops`

Evidence:

- `Backend_FastAPI/app/config.py:348-350` — `ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS=7`.
- `Backend_FastAPI/app/tasks/email_tasks.py:182` — `send_magic_link_confirmation_task` chỉ gửi 1 lần lúc generate.
- `grep "magic_link\|expire.*token\|expiring_soon" Backend_FastAPI/app/tasks/` → chỉ có `consultation_reminders`, không có magic-link reminder.
- Không có endpoint `GET /api/admissions/expiring-confirmations`.

Impact:

Mùa cao điểm có thể có hàng trăm magic link hết hạn cùng lúc → manager xử lý thủ công không khả thi. Thí sinh có thể quên xác nhận, đặc biệt tuần đầu sau approve (tỷ lệ confirmation thấp do quá tải email).

Hướng xử lý:

1. Celery beat task `check_magic_link_expiring_task` chạy mỗi giờ; gửi reminder lead khi token còn 24h/12h/6h.
2. Endpoint `GET /api/admissions/expiring-confirmations` (manager scope) liệt kê profile có token sắp hết hạn cho dashboard.
3. Tích hợp với notification rule (rule mới `magic_link_expiring` trong catalog).
4. Atomic check khi confirm sát giờ hết hạn: `verify_token` đã có `with_for_update` (ADM-013 PR #156); thêm assertion `expires_at > now()` ngay trước update để tránh confirm sau expiry.

### ADM-029 — Không có rollback finalize-enrollment

Severity: `P3`

Loại: `Gap/Workflow`

Evidence:

- `Backend_FastAPI/app/services/admission_state_machine.py:55-66` — `ENROLLED → set()` (terminal).
- `Backend_FastAPI/app/routers/admissions.py:1871-1950` — `/finalize-enrollment` không có endpoint counterpart `/undo-finalize` hay `/revert-enrollment`.
- `mark_student_dropped` (admission_service.py:6525+) là side-channel `is_dropped=True` chứ không revert state.

Impact:

Sai lúc finalize (nhầm khóa học, niên khóa, lớp) phải:

1. `drop_student` → `is_dropped=True` (audit chỉ là side channel, vẫn `enrolled` state).
2. Tạo profile mới + upload lại tài liệu.

Không thân thiện với mùa cao điểm khi admin/manager thao tác nhanh.

Hướng xử lý:

1. Endpoint `POST /api/admissions/{id}/undo-finalize` (admin-only) cho phép revert trong grace period (vd 24h sau finalize).
2. Logic: xóa `Student` record (or soft-delete với `is_active=False`); revert profile về `confirmed` hoặc `overridden`; lock student_code không reuse.
3. Audit log durable trong `entity_audit_log`.
4. Cảnh báo UI "Đã quá grace period 24h, phải drop_student".

### ADM-031 — DocumentsTab UI quá kỹ thuật cho officer

Severity: `P2`

Loại: `Gap/UX (Frontend-only)`

Status: `OPEN — UI-only PR ready (không touch backend)`

Audit theo code thật xác nhận: backend model đầy đủ (`requires_upload` + `submission_format` + `actual_submission_format` + `verified_format` + `paper_submitted` policy guard). Confusion thuần ở UI layer.

**Sub-finding 31.1 — Row không hướng next-step cho officer**

Evidence:

- `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/DocumentsTab.tsx:400-474` — column 3 hiển thị badge `Online / Nộp giấy`; column 5 có button upload icon + checkbox "Đã nộp" rời rạc.
- Cùng status `Chưa nộp`, officer phải tự suy ra row nào cần tải file vs row nào ghi nhận giấy.

Impact: Officer mới onboard mất thời gian; risk làm sai (upload file vào row chỉ nhận giấy hoặc ngược lại).

Hướng xử lý: Đổi thành task-oriented copy:

- `requires_upload=true` + status missing → label row "Cần tải ảnh/scan" + button text "Tải file".
- `requires_upload=false` + status missing → label "Nhận bản giấy tại quầy" + button text "Đánh dấu đã nhận giấy".

**Sub-finding 31.2 — Format dialog gây nhầm "chứng cứ"**

Evidence:

- `DocumentsTab.tsx:538-590` — dialog title "Xác nhận loại bản nộp"; description chỉ ghi tên doc + "Yêu cầu: ..."; không giải thích đây là **loại bản thực tế** của file/giấy vừa nhận.
- Officer dễ tưởng phải nộp thêm 1 ảnh chứng cứ ngoài file đã upload.

Hướng xử lý:

- Đổi title/description: "Loại bản thực tế trong file/giấy này" thay vì "Xác nhận loại bản nộp".
- Hiển thị rõ "Yêu cầu của hồ sơ: X" + cảnh báo soft (badge vàng) nếu officer chọn khác yêu cầu.
- Dùng từ "loại bản" hoặc "phiên bản tài liệu" — KHÔNG dùng từ "chứng cứ" hay "evidence".

**Sub-finding 31.3 — Enum `photo` có 4 nhãn khác nhau**

Evidence:

| File | Line | Nhãn cho `photo` |
| --- | --- | --- |
| `DocumentsTab.tsx` (FORMAT_CONFIG) | 91 | "Ảnh chụp" |
| `DocumentsTab.tsx` (RadioGroup dialog) | 574 | "Bản photocopy" |
| `DocumentChecklist.tsx` | 323 | "Bản photo/scan" |
| `lib/utils/admission-helpers.ts` | 75 | "Bản photocopy" |

Cùng 1 enum, 4 wording → đây là nguyên nhân chính làm officer nhầm `submission_format` (loại bản hệ thống yêu cầu) với evidence (file chụp).

Hướng xử lý:

- Centralize FORMAT_CONFIG vào `lib/utils/admission-helpers.ts` (hoặc `lib/constants/document-format.ts`).
- Chuẩn hóa duy nhất 1 nhãn cho mỗi enum:
  - `original` → "Bản gốc"
  - `certified_copy` → "Bản sao chứng thực"
  - `photo` → **"Bản chụp/scan không chứng thực"** (đề xuất; rõ nghĩa, khớp với cả Camera icon + scan workflow)
- Mọi chỗ khác (DocumentsTab, DocumentChecklist, badge, dialog, helpers) import từ 1 nguồn duy nhất.
- Test snapshot wording để regression nếu có người sửa label tương lai.

**Sub-finding 31.4 — Progress count uploaded == verified**

Evidence:

- `DocumentsTab.tsx:280-286` — `completedCount` = filter `status in (uploaded | verified | paper_submitted)`. Tất cả tính ngang.
- Officer thấy progress 100% ngay sau upload → tạo cảm giác hồ sơ đã đủ chắc chắn, dù manager chưa kiểm tra.

Hướng xử lý:

- Đổi label progress: "Đã ghi nhận X/Y" thay vì "Đã hoàn thành X/Y" cho `uploaded` + `paper_submitted`.
- Cân nhắc tách 2 progress bar: "Đã ghi nhận" (uploaded + paper_submitted) vs "Đã kiểm tra" (verified). Hoặc dùng segmented bar 2 màu.
- Nếu workflow cuối là `verified`-required, label phụ "Chờ kiểm tra" hiện rõ trên row uploaded chưa verify.

### Đề xuất PR UI-only cho ADM-031

1. Centralize FORMAT_CONFIG vào `lib/utils/admission-helpers.ts`; xóa duplicate ở DocumentsTab/DocumentChecklist.
2. Cập nhật DocumentsTab row labels theo task-oriented (sub-finding 31.1).
3. Cập nhật format dialog wording (sub-finding 31.2).
4. Tách progress display thành "Đã ghi nhận" vs "Đã kiểm tra" (sub-finding 31.4).
5. Test Vitest cho 2 case: doc `requires_upload=true` (cần tải file) + `requires_upload=false` (chỉ ghi nhận giấy).

**Effort: 4-6h. Không migration, không backend change.**

### ADM-030 — Bulk approve UX thiếu row-level feedback

Severity: `P3`

Loại: `Gap/UX`

Evidence:

- `frontend/src/app/(dashboard)/admissions/_components/AdmissionsClient.tsx:331-342` — `canApprove = selectedRows.every(row => row.available_actions?.approve)`; nút disable nếu bất kỳ row nào không có quyền.
- `AdmissionsBulkActionsBar.tsx:91-98` — render nút disabled không có tooltip giải thích.
- Không có per-row indicator (badge/highlight) chỉ ra row đang block.

Impact:

Manager mùa cao điểm chọn 50-100 hồ sơ; 1 row ở `draft` (không approve được) làm disable nút. Manager không biết row nào → mất thời gian dò thủ công, gây bực + sai sót.

Hướng xử lý:

1. Thay logic `every` bằng `partition`: lọc ra các row eligible, hiển thị tooltip "X/Y có thể approve, Z bị bỏ qua".
2. Highlight row blocking với badge màu vàng + reason ("Trạng thái draft", "Chưa được assign").
3. Bulk action chấp nhận subset eligible thay vì all-or-nothing (kèm confirm dialog).

---

## Wave 7 — Product/compliance hardening (2026-04-28, revised)

PR #156 (ADM-013) đã deploy 2026-04-28. Q12 + Q9 đã chốt → 2 PR Tier 1 sẵn sàng start. Q11 → ADM-025 CLOSED-NOT-NEEDED.

### Tier 1 — Lane assignment theo file ownership (2026-04-28)

Chia song song theo **file ownership**, không theo số ADM. Lane B + Lane C đều đụng `admission_service.py` → KHÔNG song song nếu cùng 1 backend dev.

| Lane | PR | Finding | Effort | Branch | Files chạm | Khi start |
| --- | --- | --- | --- | --- | --- | --- |
| **A** | W7-2.5 | ADM-031 | 4-6h | `fix/admission-audit-w7-2-5-adm-031-documents-ui` | FE-only: `DocumentsTab.tsx`, `DocumentChecklist.tsx`, `lib/utils/admission-helpers.ts`, FE tests | **Ngay** — không conflict với backend |
| **B** | W7-1 | ADM-026 | 6-8h | `fix/admission-audit-w7-1-adm-026-quota` | Backend: quota check trong approve/bulk/finalize, schema `bypass_quota`+`bypass_reason`, audit log, BE tests | **Ngay** — P1 compliance ưu tiên cao nhất |
| **C** | W7-2 | ADM-023 + ADM-028 | 8-12h | `fix/admission-audit-w7-2-adm-023-028-magic-link` | Backend (overlap `admission_service.py` với Lane B): alembic migration lock fields, Celery beat, notification event, confirm/send-token rework | **Đợi Lane B PR mở + CI xanh** rồi start full. Nếu có BE dev thứ 2: làm phần ít overlap trước (migration/model + Celery skeleton + notification template), chưa rework confirm/send-token cho tới khi rebase được Lane B. |

Lane A + Lane B chạy song song ngay; Lane C đợi Lane B stabilize.

### Wave 7 chi tiết các PR khác (Tier 1 specs full)

| PR | Finding | Spec |
| --- | --- | --- |
| W7-1 | ADM-026 | Hard cap quota + admin-only bypass (Q12 chốt Option B). Helper `_assert_quota_or_bypass` trong approve/bulk/finalize; `bypass_quota` + `bypass_reason` (≥20 ký tự); manager → 403; mỗi bypass ghi `entity_audit_log` (quota, enrolled before/after, actor, reason); FE warning ở 80%. |
| W7-2 | ADM-023 + ADM-028 | Magic-link hardening (Q9 chốt A3+B1+C2). Hybrid lock (cooldown 5/30/120/1440min, hard lock ≥30 fails/24h), 3 resend/24h/profile (Redis), reminder Celery beat 24h+6h trước expiry. Migration thêm `confirmation_lock_until / confirmation_attempt_total / confirmation_locked_at / confirmation_lock_count`. Audit log bắt buộc mỗi hard-lock, rate-limit hit, reminder sent. |
| W7-2.5 | ADM-031 | DocumentsTab UI-only refactor: centralize FORMAT_CONFIG (1 nhãn cho enum `photo` toàn FE), task-oriented row copy (`Cần tải ảnh/scan` vs `Nhận bản giấy tại quầy`), format dialog wording không dùng từ "chứng cứ", tách progress "Đã ghi nhận" vs "Đã kiểm tra". Vitest cho 2 case requires_upload true/false. |

### Tier 2 — P2 / P3 (sau Tier 1)

| PR | Finding | Effort | Dependency |
| --- | --- | --- | --- |
| W7-3 | ADM-011 + ADM-030 | 4-7h | Bulk operations: backend lock/version + FE per-row tooltip/highlight |
| W7-4 | ADM-027 | 8-12h | Endpoint change-path + clone documents/fee allocation + state machine guard | Q13 |
| W7-5 | ADM-016 | 4-6h | FE scoring source-of-truth (port hoặc preview-only) | Q5 |
| W7-6 | ADM-017 | 3-4h | Published intake invariant | Q8 |
| W7-7 | ADM-024 | 3-4h | Audit prod path `allow_unverified=true` + UI flag warning + ops doc |
| W7-8 | ADM-002 + ADM-018 | 4-6h | Path config UX rename "Method documents" + academic_year column | Q1, Q6 |
| W7-9 | ADM-029 | 4-6h | Endpoint undo-finalize (admin, grace period) | Q14 |
| W7-10 | ADM-020 | 2-3h | Delete profile cleanup files | Q7 |

### Closed / Removed

| PR | Finding | Lý do |
| --- | --- | --- |
| ~~W7-3 (cũ)~~ | ADM-025 | CLOSED-NOT-NEEDED — existing `requires_upload=true` pattern đã đủ làm digital evidence; policy guard chặn paper_submitted với requires_upload=true (`admission_document_policy.py:174-180`). |

## Open questions Wave 2

9. **ADM-023 ✅ CHỐT 2026-04-28**: A3 + B1 + C2 — hybrid cooldown (5/30/120/1440min) + hard lock ≥30 fails/24h + 3 resend/24h/profile + reminder 24h+6h trước expiry. Audit log bắt buộc hard-lock, rate-limit hit, reminder sent.
10. **ADM-024**: Có job opt-in flip prod path từ `allow_unverified=true` về `false` theo từng path không, hay chờ admin manual?
11. **ADM-025 ✅ CHỐT 2026-04-28**: CLOSED-NOT-NEEDED. `requires_upload=true` + file upload = digital evidence; policy guard đã chặn paper_submitted với requires_upload=true. Không thêm `evidence_photo_path`.
12. **ADM-026 ✅ CHỐT 2026-04-28**: Option B — hard cap + admin-only bypass với `bypass_reason` ≥20 ký tự + entity_audit_log đầy đủ (quota, enrolled before/after, actor, reason). Manager không bypass được.
13. **ADM-027**: Change-path có giữ application fee không? Refund partial nếu fee path mới thấp hơn?
14. **ADM-029**: Grace period undo-finalize bao lâu (24h / 7 ngày / hết tháng)? Có notification gửi student không?

## Verified-FALSE claims — 2026-04-28

Các claim đã verify và **không phải bug**, log để tránh re-investigate.

| Claim | Phân tích nhanh | Evidence |
| --- | --- | --- |
| Officer submit thiếu IDOR | `submit_and_evaluate` gọi `_check_idor_access` ở service layer (line 3006). Pattern khác với resubmit/withdraw (đều enforce ở service, không phải dependency) — chỉ là doc inconsistency, không phải security gap. | `admission_service.py:2951,3006` |
| Confirmed → withdrawn không refund | State machine cấm transition này; `CONFIRMED → {ENROLLED}` only. User guide đọc sai. | `admission_state_machine.py:55-66` |
| Resubmit race không có optimistic lock | PR #155/#156 đã ship FOR UPDATE + version check. | `admission_service.py:5320-5360` |
| Minor correction whitelist chỉ ở FE | Backend 2-layer: `SAFE_MINOR_CORRECTION_FIELDS` frozenset + path-level allowlist intersection + `HARD_DENY_FIELDS`. FE chỉ là mirror. | `admission_correction_constants.py:27-49`, `admission_service.py:6295-6306` |
| Bulk assign không check unit | M4 fix đã chặn cross-unit (admin bypass). | `admission_service.py:7455-7458` |
| Duplicate CCCD | Composite unique `(citizen_id, academic_year)`. | `models/admission.py:45` |
| Officer audit log | Đầy đủ: update_profile (2799), upload_document (3477), apply_minor_correction (6383). | `admission_service.py` các dòng tương ứng |
| Fee creator vs Payment creator 4-eyes | Application fee là path-snapshot (`applied_rules.application_fee` line 2084), không do officer set. Tuition Fee là finance flow riêng; constraint `chk_payment_no_self_approval` đúng phạm vi của Payment. Cross-entity 4-eyes là policy question, không phải bug. | `admission_service.py:2084`, `payment.py:73-77`, `fee.py:256` |
| Không check duplicate CCCD across academic year | Là design intent: cho phép cùng CCCD đăng ký nhiều năm/intake. | `models/admission.py:91-98` |

### Doc clarifications cần update (không phải code change)

- **`confirmed_via` enum**: 3 giá trị `magic_link | admin_override | officer` (`models/admission.py:52`). User guide cần liệt kê.
- **Accountant role**: Casbin policy đầy đủ (`casbin_config/policy_templates.py:201-279`); kế thừa Officer perms. User guide thiếu section dành riêng — cần bổ sung.
- **Notification "optional"**: enable/disable qua `NotificationRule.enabled` boolean ở `/admin/notification-rules`. "Optional" trong code là field nullable, không phải feature toggle. User guide cần phân biệt rõ.
- **Drop student**: Profile vẫn `enrolled` state với `is_dropped=True` side channel; Student record persistent; `student_code` không reusable; không có re-enrollment path. User guide cần làm rõ chính sách bảo lưu (nếu có).
- **Submit IDOR pattern**: Service-layer enforce (an toàn) nhưng pattern khác resubmit/withdraw → cân nhắc unify dùng `get_admission_for_user` dependency để consistent với ADM-001 fix.
- **Override chỉ từ approved**: Là design intent. Nếu cần "delegated approval" cho admin trong absence của manager là feature request mới, không phải bug.
