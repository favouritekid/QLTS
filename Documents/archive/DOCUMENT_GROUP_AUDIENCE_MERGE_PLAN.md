# PLAN v9 — Bộ hồ sơ resolve đa chiều (Loại hình × Đối tượng/Trình độ × Phương thức)

> **7 vòng paper-review + round-8 EMPIRICAL (§8.1 dry-run PROD đã chạy 2026-05-29).** round-7: H1/H2/H3 (P2 migration). **Round-8 data thật:** 🟢 doc type `hoc_ba_thcs`+`bang_tot_nghiep_thcs` ĐÃ TỒN TẠI → §8.0 không tạo doc type (H1 moot); 🟢 H2 moot (bang_diem_thpt đã xóa, lien_thong 0 path); 🔴 id drift prod 9/10/ot21-22 ≠ seed 1/2 → match code; 🎯 trọng tâm = group 9 chinh_quy (72 CĐ + 32 TC path), TC-từ-THCS = bug gốc owner. Chi tiết §8.1. round-1 (P0/P1/P2) **+ round-2** (2 P0+2 P1+2 P2) **+ round-3** (1 BLOCKER+1 citation+1 invariant) **+ round-4** (N1/N2 must-fix + N3-N7) **+ round-5** (4 polish) **+ round-6** (sweep data/caller thật: 3 gap material G1/G2/G3 + G4/G5). Branch: `feat/document-group-audience-merge`. Mọi quyết định kèm "đã verify file:line". **Lưu ý sửa từ v1: seed group thực tế là id 1/2 (KHÔNG phải 9/10).**

> **OWNER SCOPE 2026-05-29:** GĐ1 = **machinery + cấu hình bộ THCS luôn** (không chỉ tách THPT). Thêm §8.0: tạo doc type `hoc_ba_thcs`/`bang_tot_nghiep_thcs` + seed lớp POST_THCS để THCS↔THPT khác bộ ngay. ⚠️ **Owner cần xác nhận danh mục giấy tờ THCS thực tế trước khi viết §8.0 migration.**

> **Round-6 đóng (verify data+caller 2026-05-29):** **🔴 G1** = backfill §8.2 aspirational — đối chiếu seed thật chỉ POST_THPT(ot1) có data đầy đủ; ot2 không có hoc_ba; POST_THCS chưa có doc type → **§8.0 tạo bộ THCS (owner scope)**; LIEN_THONG_*/VLVH RỖNG ("bằng TC/CĐ"=vocational không phải doc, known-limitation) → §8.1 dry-run TRƯỚC, §8.2 theo output (§8). **🔴 G2** = `resolve_documents_for_path` có 3 caller (create :3216 + save :660 + admin endpoint :617); refactor no-audience=NỀN-only sẽ mất học bạ ở view admin sau backfill → default ALL layers + backward-compat (§10.6/§10.14). **🔴 G3** = 2 merge KHÁC is_active (path không filter :914-939 / public filter :466) → hàm chung tham số `exclude_inactive`, KHÔNG xóa-vì-trùng (§10.3). **🟡 G4** = upsert NỀN lookup theo code → 2 NỀN/ot (seed HS_CHINH_QUY vs SHARED_DOC_OT_{id}) → lookup (ot, audience IS NULL) (§10.8). **🟡 G5** = preview FE tự tính audience vi phạm thin-client → BE derive từ raw input (§10.14).

> **Round-4 đóng (verify code 2026-05-29):** **🔴 N1** = KHÔNG bump schema_version (giữ =2; value 3 đỏ 2 test :209/:406 + zero runtime consumer) — §7/§10.7. **🔴 N2** = route GET document-groups KHÔNG Casbin-gated (auth qua `get_config_filter`→`get_current_active_user` deps.py:1886; 0 entry Casbin) → route mới mirror deps, KHÔNG cần casbin_rule — §10.13. **🟠 N3** = re-resolve derive dùng `profile.admission_path` primary; multi-NV nhất quán nhờ gate :4538 + 1 test — §7. **🟡 N4** = GIN cast `::admission_audience[]` — §10.1. **🟡 N5** = audit entry re-resolve (snapshot mutate không vào updated_fields :4172) — §7. **🟡 N6** = public ~6× group, P2 perf known-limitation — §9. **✅ N7** = magic-link sửa cultural cũng qua update_profile:4056 → re-resolve fire, không bypass.

> **Round-2 đóng:** P0-A = re-resolve trigger PHẢI gồm `cultural_education_level`. P0-B = `add_path_documents_delta` (partial-unique `uq_profile_document_path`). P1-A = eager-load chain derive. P1-B = §8.3 backup + runbook one-way. P2 = code≤50 + alembic head verify.

> **Round-3 đóng (verify code 2026-05-29):** **🔴 BLOCKER** = §5↔§7 mâu thuẫn CONFIG_GAP tái sinh P0-A → `derive_audience_set` **nuốt CONFIG_GAP nội bộ, luôn trả ≥ tập văn hóa** (§5); re-resolve **bỏ nhánh "giữ snapshot cũ"** (§7); anchor mạnh hóa "snapshot VẪN có học bạ" (§11). **🟠 Citation** = hard-gate cultural là `validate_eligibility` priority_service.py:1042/:1053 via `_validate_eligibility_all_choices` :4846 (raise unwrapped), KHÔNG phải KV path :5096 (do địa chỉ) — sửa §7. **🟡 Invariant** = re-resolve MERGE applied_rules per-key + flag_modified, KHÔNG gán dict mới (giữ allow_unverified_submission/path_id/round_id/scoring; submit :4974-4978 raise nếu thiếu) — §7.

## 1. Mục tiêu
Bộ hồ sơ của 1 thí sinh = hợp các lớp giấy tờ khớp theo 3 chiều: **Loại hình** (`offering_type_id`, đã có) × **Đối tượng/trình độ** (THÊM, suy từ `cultural_education_level` + `vocational_qualification` + loại hình) × **Phương thức** (`admission_method_id`, đã có).
**Khác v1**: KHÔNG union toàn bộ. Precedence tier path/method override (fork) GIỮ NGUYÊN; audience chỉ MERGE trong tier shared (§4).

## 2. Research đã verify (file:line)
| # | Kết luận | Bằng chứng |
|---|---|---|
| R1 | Tier: highest có group → thắng TOÀN BỘ (if path / elif method / else shared) | admission_path_service.py:909-939; admission_path_repository.py:386-475 |
| R2 | Snapshot `applied_rules.mandatory_docs`+`doc_configs`, schema_version=2 | admission_service.py:3221-3303, :3331 |
| R3 | ProfileDocument CHỈ tạo từ mandatory_docs | admission_service.py:3472-3475; admission_repository.py:864-902 |
| R4 | Action gate chặn doc ngoài mandatory_docs | admission_service.py:215-222 |
| R5 | Checklist pass-1 lặp mandatory_docs; doc non-mandatory KHÔNG hiện | admission_service.py:1886, :2029-2100 |
| R6 | Editable states = draft/rejected/revision_requested | admission_service.py:3892-3903; admission_state_machine.py:78-175 |
| R7 | Cultural set qua update_profile, KHÔNG re-resolve docs | admission_service.py:4055-4058, :4124-4168 |
| R8 | Seed FILE: group 1 (HS_CHINH_QUY ot1) + 2 (HS_LIEN_THONG ot2). **⚠️ PROD THẬT (§8.1 2026-05-29): group 9 (ot21 chinh_quy, 6 items) + 10 (ot22 lien_thong, 5 items); doc type THCS đã có** → match code/(ot,audience) KHÔNG id | seed:351-401 + dryrun PROD |
| R9 | Enum admission_audience đã có (5 giá trị, không base), create_type=False | phase1_03:79-97; schemas/admission_path.py:61-67 |
| R10 | upsert dùng `groups[0]` (bug multi-layer) | admission_config_service.py:474-490; document_group_repository.py:82-100 |
| R11 | Public có merge RIÊNG; audience hiện lọc PATH (applicable_to), không lọc doc layer | public_admissions_service.py:456-470, :866-886, :262-272 |
| R12 | Không import cycle (public không import path_service) → module chung an toàn | grep cross-import |
| R13 | DocumentSource = shared/method_override/path_override; FE dùng để phát hiện fork | schemas/admission_path.py:48, :593-610 |
| R14 | derive_target_level_and_type có thể raise CONFIG_GAP_TARGET_LEVEL | priority_service.py:905-992 |
| R15 | FE key `["shared-document-group", offeringTypeId]`; route `/document-groups/shared/{ot}` | useMasterData.ts:409-431; admission_config.py:825-863 |
| R16 | Alembic head — **VERIFY LẠI khi code** (P2): chạy `docker compose exec backend alembic heads` trên branch; nếu >1 head → tạo merge revision TRƯỚC; tuyệt đối KHÔNG tin head suy ra bằng tay (branch có 125+ migration) | alembic/versions |

## 3. Schema: cột `DocumentGroup.applicable_audience`
`ARRAY(admission_audience)` NULLABLE. NULL = lớp NỀN tier shared (luôn merge). `[..]` = merge khi `&& audience_set` (GIN index, dùng `&&` không `= ANY`). `code` unique → layer mới sinh code có hậu tố audience (**P2: hậu tố deterministic; assert `len(code) ≤ 50` — dài nhất `SHARED_DOC_OT_2_LIEN_THONG_CD` ~28 ký tự, dư**).

## 4. Resolve mới (P0.1) — GIỮ tier precedence, audience CHỈ merge trong shared
```
if path_groups:    layers=path_groups;   src="path_override"   # fork nguyên cũ, KHÔNG đụng audience
elif method_groups:layers=method_groups; src="method_override" # fork nguyên cũ
else:              layers=filter_shared_by_audience(shared_groups, audience_set); src="shared"
doc_map = mandatory_wins_merge(layers); remove completed-grad docs (§6)
```
`filter_shared_by_audience`: giữ group audience NULL (NỀN) + group `&& audience_set`. `audience_set=None` (legacy/admin preview) → chỉ NỀN (backward-compat); public xử lý riêng §9.
**§4.2 Tombstone: DEFER** — audience chỉ merge trong shared tier, không trộn path/method → không có ca "path override loại giấy nền audience". Rebuild path sạch (owner cho xóa) là đủ. Mở phase 2 `layer_kind=tombstone` nếu sau cần.

## 5. Mapping `derive_audience_set(profile, path) -> set[str]`
- **Chiều văn hóa (suy TRỰC TIẾP từ `cultural_education_level`, KHÔNG qua derive):** completed/graduated_thcs→POST_THCS; completed/graduated_thpt, graduated_gdtx→POST_THPT; None→∅.
- **Chiều loại hình (qua `derive_target_level_and_type` + vocational):** lien_thong+TC→LIEN_THONG_TC; lien_thong+CĐ→LIEN_THONG_CD; vlvh→VLVH; chinh_quy→∅.
- **N1-VLVH known-limitation (GĐ1):** enum có VLVH nhưng §8.2 backfill KHÔNG tạo group VLVH (seed không có giấy đặc thù VLVH) → profile VLVH match NỀN+văn-hóa, KHÔNG có lớp VLVH riêng (chủ đích GĐ1). Admin tự upsert lớp VLVH qua panel nếu cần. Ghi rõ trong §8.2.
- **Fail-safe CONFIG_GAP (R14) — NUỐT NỘI BỘ trong `derive_audience_set`:** chỉ `derive_target_level_and_type` (chiều loại hình) mới raise CONFIG_GAP. Bọc try/except QUANH RIÊNG call đó → rớt **chỉ chiều loại hình**, vẫn trả **đầy đủ chiều văn hóa** (POST_THPT/THCS vẫn còn vì suy trực tiếp từ cultural). Log warning. ⟹ `derive_audience_set` **không bao giờ raise CONFIG_GAP ra ngoài** và **luôn trả ≥ tập văn hóa** — đây là invariant chống P0-A tái sinh (xem §7 BLOCKER round-3).

## 6. completed/graduated (P0.2) — LOẠI bằng TN khỏi set (KHÔNG optional)
Verify R3-R5: hạ is_mandatory=False làm doc KHÔNG hiện/upload được (pipeline chỉ tạo+gate+render theo mandatory_docs). → **Quyết định GĐ1: `completed_*` → LOẠI document bằng TN khỏi resolved set** (không vào mandatory_docs/doc_configs/ProfileDocument). `derive` tính kèm `completed_doc_codes`; resolve bỏ item sau merge.
**Phương án 2 (tách active_doc_codes vs required_doc_codes) DEFER GĐ2** — cần đổi pipeline 3 điểm (R3/R4/R5) + bump schema + grandfather; chỉ mở khi cần "giấy khuyến nghị nộp thêm".
**N3-mã hằng số (verify code):** `compute_completed_doc_codes` hardcode mã bằng TN PHẢI khớp seed/catalog: `bang_tot_nghiep_thpt` ✅ verify seed (zq6w...:366,:395); **`bang_tot_nghiep_thcs` TẠO MỚI ở §8.0** (GĐ1 mở rộng owner scope) → completed_thcs sẽ loại đúng bằng TN THCS. Để hằng số trong `document_resolution_service` đồng bộ seed/§8.0, tránh removal âm thầm fail khi mã đổi.

## 7. Re-resolve (P1) — TOÀN BỘ editable states, INSERT-only DELTA
Verify R6/R7. **Trigger: `cultural_education_level` HOẶC `vocational_qualification` đổi (audience phụ thuộc 2 field này) + status ∈ {draft, rejected, revision_requested} + có admission_path_id.**

**P0-A (verify code) — vì sao trigger PHẢI gồm cultural:** submit ĐÃ hard-gate cultural qua `_validate_eligibility_all_choices` (:4846) → `validate_eligibility` (priority_service.py:**1042** CĐ chính quy / :**1053** TC chính quy): `cultural=None` (hoặc sai bậc) ⇒ trả `False` ⇒ raise `BusinessRuleViolation` **UNWRAPPED** ⇒ submit abort TRƯỚC :5064/:5096. (Address hard-gate riêng :5115-5123. **KV-unresolved :5096 do địa chỉ/commune/school chi phối, KHÔNG do cultural** — citation v3 cũ sai cơ chế, đã sửa.) NHƯNG submit check `mandatory_docs` từ **SNAPSHOT** (:4852,:4965), KHÔNG re-resolve; cultural set qua update_profile vốn KHÔNG re-resolve (R7). ⟹ Nếu KHÔNG re-resolve khi cultural đổi: tạo hồ sơ cultural trống (snapshot=NỀN, thiếu học bạ/bằng TN) → set cultural sau → submit qua eligibility (cultural đã set) NHƯNG snapshot NỀN cũ ⇒ học bạ/bằng TN **âm thầm không bắt buộc = REGRESSION**. Re-resolve-on-cultural-change đóng đúng lỗ này (eligibility gate không cứu vì cultural đã set; chỉ doc snapshot stale).

**P0-B (verify code) — INSERT-only = DELTA, KHÔNG reuse `initialize_documents_for_profile`:** ProfileDocument có partial-unique `uq_profile_document_path (profile_id, document_type_id) WHERE category='path'`, cột `category` default 'path' (profile_data.py:110-114,211-221). `initialize_documents_for_profile` (admission_repository.py:864-902) add **VÔ ĐIỀU KIỆN, không set category, không check tồn tại** ⇒ reuse khi re-resolve = UNIQUE violation ⇒ vỡ TOÀN BỘ update_profile (blast radius lớn). ⟹ Repo method MỚI `add_path_documents_delta(profile_id, codes)`: SELECT codes đã có (category='path') → INSERT chỉ code thiếu, set `category='path'` tường minh. KHÔNG xóa / đụng row có upload.

**P1-A (verify code) — eager-load chain re-resolve:** chiều "loại hình" của audience dùng `derive_target_level_and_type`, fail-closed CONFIG_GAP nếu chain chưa eager-load (priority_service.py:929-936). Path re-resolve PHẢI eager-load `academic_info→offering→program→degree_level_ref + offering_type_config` (+ cột audience), nếu không §5 fallback chỉ-văn-hóa **âm thầm rớt layer LIEN_THONG/VLVH** (hồ sơ liên thông mất giấy đặc thù, không báo lỗi).

**🔴 BLOCKER round-3 — CONFIG_GAP: KHÔNG được "giữ snapshot cũ":** `derive_audience_set` đã **nuốt CONFIG_GAP nội bộ** (§5) → luôn trả ≥ tập văn hóa → re-resolve **LUÔN apply** (POST_THPT vẫn ra học bạ/bằng TN). ⟹ Re-resolve **KHÔNG** có nhánh "CONFIG_GAP → giữ snapshot NỀN-only" (đó chính là failure mode tái sinh P0-A ở nhánh CONFIG_GAP). Outer try/except CHỈ cho exception **bất ngờ** (DB error...) và khi đó **propagate (loud-fail) — KHÔNG im lặng giữ snapshot NỀN-only**.

**🟡 Invariant round-3 — MERGE applied_rules, KHÔNG replace:** submit raise nếu `schema_version!=1` mà thiếu `allow_unverified_submission` (:4974-4978). ⟹ re-resolve **update TỪNG key** (`mandatory_docs`, `doc_configs`) + `flag_modified(profile,"applied_rules")`, **TUYỆT ĐỐI KHÔNG gán dict mới** — phải giữ `allow_unverified_submission` + `admission_path_id` + `admission_round_id` + scoring config (min_gpa/allowed_subject_codes/...), nếu không submit vỡ :4975 + scoring vỡ.

**🔴 N1 round-4 — KHÔNG bump schema_version:** create giữ `schema_version=2` (R2, :3331). Runtime gate chỉ phân biệt `==1`/`>=2` (:985,:4971) → value 3 KHÔNG có consumer + làm ĐỎ 2 test assert cứng `==2` (test_admission_submit_requires_verified_docs.py:209, test_adm_024_strict_default_migration.py:406). ⟹ re-resolve **KHÔNG đụng schema_version** (giữ nguyên 2) — chỉ merge mandatory_docs/doc_configs.

`_reresolve_documents_snapshot`: derive_audience_set mới (chain eager-loaded §10.5, CONFIG_GAP nuốt nội bộ §5) → **merge per-key** mandatory_docs/doc_configs + flag_modified (giữ schema_version=2 + mọi key khác); `add_path_documents_delta` cho code thiếu (doc rớt → is_extra qua pass-2 read-only, KHÔNG xóa). **N5: ghi 1 audit entry re-resolve** (update_profile audit `updated_fields=data.keys()` :4172 KHÔNG bắt mutation snapshot → mất dấu "vì sao checklist đổi"). **N3: derive dùng `profile.admission_path` (path primary trong applied_rules.admission_path_id); multi-NV cùng target_level+admission_type được submit gate MULTI_NV_INCONSISTENT :4538 đảm bảo → audience nhất quán; thêm 1 test multi-NV re-resolve.** Đặt sau set cultural (:4058) trước flush (:4131). Status ngoài 3 trạng thái → gate chặn → đóng băng (không cần block riêng).

## 8. Backfill (P1) — dry-run TRƯỚC, viết §8.2 theo data thật + rebuild path
**8.1 DRY-RUN (BẮT BUỘC chạy TRƯỚC khi finalize §8.2, read-only)**: SQL `GROUP BY (offering_type_id, admission_method_id, admission_path_id, code)` đếm item. Script `scripts/dryrun_document_group_audience_2026.sql`. **§8.2 viết theo OUTPUT §8.1, KHÔNG aspirational.**

**✅ §8.1 ĐÃ CHẠY PROD 2026-05-29 (round-8 empirical):**
- **2 group shared, 0 method/path override**: group **9** `HS_CHINH_QUY` (ot **21** chinh_quy) + group **10** `HS_LIEN_THONG` (ot **22** lien_thong). ⚠️ **ID PROD = 9/10, ot 21/22 — KHÁC seed file (1/2)** → backfill match code/(ot,audience), KHÔNG hardcode id.
- **Group 9 items (6)**: hoc_ba_thpt, bang_tot_nghiep_thpt, cccd, giay_khai_sinh, anh_3x4, giay_kham_suc_khoe (`giay_chung_nhan_uu_tien` ĐÃ XÓA — prod drift xác nhận).
- **Group 10 items (5)**: bang_tot_nghiep_thpt, cccd, giay_khai_sinh, anh_3x4, giay_kham_suc_khoe (KHÔNG hoc_ba_thpt; `bang_diem_thpt` ĐÃ XÓA → **H2 moot**).
- **config_document_type (8)**: 🟢 `hoc_ba_thcs` + `bang_tot_nghiep_thcs` **ĐÃ TỒN TẠI active** → §8.0 KHÔNG tạo doc type, chỉ wire vào layer.
- **Path inventory (query 4)**: chinh_quy(ot21) = cao_dang **72 path** + trung_cap **32 path**; **lien_thong(ot22) = 0 path/0 offering** (group 10 UNUSED); vlvh/tu_xa/lien_ket = 0.
- **🎯 KẾT LUẬN**: mục tiêu thật = **group 9 (chinh_quy ot21)**. TC chính quy (32 path) tuyển từ THCS (:1053) nhưng group 9 ép hoc_ba_thpt+bang_tot_nghiep_thpt cho MỌI hồ sơ = **bug gốc owner báo**. Group 10 unused → split tùy chọn (không tác động thực tế).

**🔴 G1 round-6 — DATA THẬT: backfill chỉ đỡ được POST_THPT(ot1); 4/5 audience INERT.** Đối chiếu seed (zq6w...:351-401):
- **ot1 (HS_CHINH_QUY)**: `hoc_ba_thpt`+`bang_tot_nghiep_thpt`+cccd+khai_sinh+anh+kham_SK+`giay_chung_nhan_uu_tien` → split POST_THPT = {hoc_ba_thpt, bang_tot_nghiep_thpt} ✅ REAL.
- **ot2 (HS_LIEN_THONG)**: `bang_tot_nghiep_thpt`+cccd+khai_sinh+anh+kham_SK+`bang_diem_thpt` — **KHÔNG có hoc_ba_thpt**; split POST_THPT = {bang_tot_nghiep_thpt}. **🟠 H2 round-7: `bang_diem_thpt` (bảng điểm THPT) PHẢI vào POST_THPT(ot2), KHÔNG để NỀN** — ot2 phục vụ CẢ CĐ liên thông (yêu cầu THPT :1037) lẫn TC liên thông (yêu cầu THCS :1049); để NỀN sẽ ép TC-liên-thông-từ-THCS nộp bảng điểm THPT họ không có. **Điều kiện: §8.1 dry-run + path inventory xác nhận ot2 CÓ path TC liên thông; nếu ot2 chỉ CĐ liên thông → để NỀN cũng được.** (Lưu ý prod đã xóa bang_diem_thpt → §8.1 quyết định cuối.)
- **LIEN_THONG_TC / LIEN_THONG_CD / VLVH**: **KHÔNG có doc nguồn trong seed** ("bằng TC/CĐ" là `vocational_qualification` :1037/:1049, KHÔNG phải document) → backfill RỖNG. **INERT tới khi admin upsert layer qua panel (known-limitation §5).**
- **POST_THCS**: seed chưa có doc type THCS → **GĐ1 mở rộng (owner chốt 2026-05-29): TẠO doc type THCS + seed lớp POST_THCS** (xem §8.0 mới). KHÔNG còn inert.
- ⚠️ **PROD drift**: `giay_chung_nhan_uu_tien` + `bang_diem_thpt` đã bị XÓA khỏi prod (MoET 2026-05-29) → §8.1 dry-run trên PROD ra tập khác seed → §8.2 phải dựa output đó.

**Tuyên bố GĐ1:** POST_THPT(ot1) đầy đủ + POST_THPT(ot2) partial + **POST_THCS qua doc type mới (§8.0)** = nhu cầu gốc THCS↔THPT được phục vụ. LIEN_THONG_*/VLVH vẫn known-limitation (cần doc đặc thù sau).

**8.0 (round-8 SIMPLIFIED) — Wire lớp POST_THCS dùng doc type CÓ SẴN:**
- 🟢 **§8.1 xác nhận `hoc_ba_thcs` + `bang_tot_nghiep_thcs` ĐÃ TỒN TẠI active trong prod** → **KHÔNG tạo doc type** (H1 collision moot — nhưng TUYỆT ĐỐI không INSERT vì đụng cả code+name UNIQUE). Reference code có sẵn.
- **Lớp POST_THCS**: tạo group `{POST_THCS}` cho **group shared ot21 (chinh_quy)** chứa 2 item `hoc_ba_thcs`+`bang_tot_nghiep_thcs`. Trọng tâm: 32 path trung_cap chinh_quy tuyển từ THCS. (Group 10 lien_thong unused → bỏ qua hoặc thêm sau.) CĐ chính quy vô hại (eligibility :1042 chặn cultural=graduated_thcs khỏi CĐ → lớp chỉ kích hoạt cho TC-từ-THCS).
- Phụ thuộc §5: cultural `completed_thcs`/`graduated_thcs` → POST_THCS → resolve 2 doc THCS.
- **Owner xác nhận**: 2 doc (hoc_ba_thcs + bang_tot_nghiep_thcs) có ĐỦ cho bộ hồ sơ THCS không, hay cần thêm.

**8.2 Migration backfill** (idempotent, match code theo §8.1, KHÔNG hard-code id — **prod id 9/10 ≠ seed 1/2**): mỗi shared group (method+path NULL): giữ NỀN (audience NULL, item nền cccd/khai_sinh/anh/khám_SK); tách `hoc_ba_thpt`+`bang_tot_nghiep_thpt` (code TỒN TẠI) → group `{POST_THPT}` (code mới unique); **POST_THCS từ §8.0** (group 9 ot21). **Group 9 (chinh_quy ot21) = trọng tâm thật**; group 10 (lien_thong ot22) chỉ có bang_tot_nghiep_thpt để split + đang unused (0 path) → split để nhất quán nhưng không tác động. **KHÔNG tạo group rỗng cho LIEN_THONG_*/VLVH (known-limitation §5).** Profile cũ snapshot bất biến. **N4-idempotent: rerun skip cả bước MOVE (item đã ở group audience → bỏ qua), không chỉ skip tạo group** — guard "code chưa thuộc group audience". **🟡 H3 round-7: downgrade phải HOÀN NGUYÊN split THẬT** — xóa group POST_THPT/POST_THCS + move item về NỀN, KHÔNG chỉ drop cột applicable_audience (nếu chỉ drop cột mà để group tách → code cũ post-rollback merge TẤT CẢ shared group/ot → profile mới over-require cả THPT+THCS). KHÔNG drop enum, giữ doc type THCS (chỉ thêm, non-destructive).
**8.3 Rebuild path sạch — ONE-WAY DOOR (P1-B)** (owner cho xóa prod): xóa path/method override group trộn lẫn → path fall-back shared đã split. **KHÔNG reversible: downgrade migration CHỈ gộp lại phần split §8.2, KHÔNG khôi phục group đã xóa.** Bắt buộc trước khi xóa: (a) **backup table** `document_group_backup_<date>` copy mọi row method/path-override (giữ ≥90 ngày — ref memory `migration-rollback-data-preservation-review`); (b) **runbook owner duyệt TỪNG path**; (c) **dry-run §8.1 chạy trên PROD data** (admin có thể đã upsert method/path group sau seed → phát hiện trước). KHÔNG tự động trong migration.

## 9. Public documents (P1) — grouped by audience
Verify R11. **Quyết định: không-audience → trả ALL layers GROUPED BY audience** (`audience_layers: [{audience, audience_label, documents}]`); giữ `shared_documents`=NỀN cho FE cũ. Caller truyền audience → NỀN + overlap. Tách merge dùng module §10.3.
**N6 (P2, perf): sau backfill mỗi offering_type ≤6 group (NỀN+POST_THPT+POST_THCS+LIEN_THONG_TC/CD+VLVH) thay 1 → public catalog merge in-memory × ot × method × scope nặng hơn. Severity thấp (cached + bảng nhỏ) nhưng verify selectinload batching + TTL cache khi code. Known-limitation nếu chưa tối ưu.**

## 10. File-by-file (code-ready)
**Backend:**
1. `models/admission_config/document_group.py` — cột applicable_audience + GIN index (reuse enum create_type=False). **N4: query phải CAST tham số `:set::admission_audience[]` (không phải text[], kẻo "operator does not exist" / bỏ index); filter chuẩn = `WHERE applicable_audience IS NULL OR applicable_audience && :set::admission_audience[]` (nhánh IS NULL = NỀN không vào GIN, seq-scan riêng OK vì bảng nhỏ; empty set `&& '{}'`=false → chỉ NỀN). EXPLAIN ANALYZE verify.**
2. `alembic/versions/<rev>_add_applicable_audience...py` (down_revision = HEAD thực tế R16) — add column + GIN + **§8.0 (seed doc type `hoc_ba_thcs`/`bang_tot_nghiep_thcs` + lớp POST_THCS, owner-confirmed danh mục)** + backfill §8.2. Upgrade chỉ thêm (non-destructive); downgrade gộp split nhưng GIỮ doc type THCS.
3. **`services/document_resolution_service.py` (MODULE MỚI)** — `mandatory_wins_merge`, `filter_shared_by_audience`, `AUDIENCE_LABELS`. Chỉ import models/schemas (no cycle R12). Cả path_service + public dùng chung. **🔴 G3 round-6: 2 merge KHÔNG đồng nhất — path (:914-939) KHÔNG filter is_active; public (:466) CÓ `not item.document_type.is_active: continue`. ⟹ hàm chung nhận tham số `exclude_inactive: bool`: path/create caller=`False` (giữ hành vi snapshot), public caller=`True` (giữ hardening storefront #348). KHÔNG xóa-vì-"trùng" (chúng KHÁC hành vi); test CẢ 2 caller.**
4. `repositories/document_group_repository.py` — `get_shared_group_by_audience(ot, audience)`; get_shared_groups trả audience; get_filtered filter audience.
4b. **`repositories/admission_repository.py` — `add_path_documents_delta(profile_id, codes)` MỚI (P0-B):** SELECT ProfileDocument codes đã có (category='path') → INSERT chỉ code thiếu, set `category='path'`. Idempotent, KHÔNG xóa upload, KHÔNG reuse `initialize_documents_for_profile`.
5. `repositories/admission_path_repository.py` — selectinload thêm cột audience (không đổi chữ ký). **+ path query của re-resolve (trong admission_service update_profile) PHẢI eager-load chain derive `academic_info→offering→program→degree_level_ref+offering_type_config` (P1-A) cho `derive_target_level_and_type`.**
6. `services/admission_path_service.py` — `derive_audience_set` + `compute_completed_doc_codes` + `resolve_documents_for_profile(...)`; refactor `resolve_documents_for_path`. **🔴 G2 round-6 — 3 CALLER (audit hidden caller TRƯỚC khi swap):** (a) create `admission_service.py:3216` (derive audience từ profile — đúng), (b) save-response `admission_path_service.py:660`, (c) **admin endpoint `routers/admission_paths.py:617` `get_resolved_documents`** (FE admin gọi KHÔNG audience). Nếu wrapper(audience_set=None)=NỀN-only → (b)(c) MẤT học bạ/bằng TN sau backfill (list co lại, lệch bộ hồ sơ thí sinh thật). ⟹ **default no-audience cho (b)(c) = trả ALL layers** (grouped như §9, superset — admin vẫn thấy học bạ → backward-compat FE); thêm `?audience=` để lọc 1 diện. Create (a) tự derive từ profile, không dùng default.
7. `services/admission_service.py` — create snapshot audience_set=None, **schema_version GIỮ =2 (N1)**; update_profile `_reresolve_documents_snapshot` §7 INSERT-only delta + merge per-key + audit entry (N5).
8. `services/admission_config_service.py` — sửa get/upsert_shared_document_group: lookup (ot, audience), bỏ groups[0] (R10), sinh code unique theo audience. **🟡 G4 round-6: lookup NỀN (audience IS NULL) phải match group seed THEO `(offering_type_id, applicable_audience IS NULL)`, KHÔNG theo code** — seed dùng `HS_CHINH_QUY`/`HS_LIEN_THONG` còn upsert sinh `SHARED_DOC_OT_{id}` (:502); nếu lookup theo code sẽ tạo group NỀN thứ 2 trùng ot → 2 NỀN/ot. Reuse group NỀN hiện hữu bất kể code.
9. `services/public_admissions_service.py` — §9 audience_layers + dùng module §10.3.
10. `schemas/document_group.py` + `schemas/admission_config.py` — thêm applicable_audience.
11. `schemas/admission_path.py` — GIỮ DocumentSource nguyên nghĩa; THÊM field `applicable_audience` + `layer_kind` trên ResolvedDocumentResponse (KHÔNG overload source) — P2.
12. `schemas/public_admissions.py` — `PublicAdmissionsAudienceDocumentLayer` + `audience_layers`.
13. `routers/admission_config.py` — route `/document-groups/shared/{ot}/{audience}` (audience vào PATH cho cache key — P2). **N2 (verify code): route GET document-groups KHÔNG Casbin-gated — GET cũ `/document-groups/shared/{ot}` (:825-844) chỉ có deps `get_config_filter`+`get_db`; `get_config_filter` (deps.py:1886) đã `Depends(get_current_active_user)` ⇒ auth bằng current_user, KHÔNG check_permission/Casbin (grep casbin_config = 0 entry document-group). ⟹ route mới MIRROR đúng deps đó (`get_config_filter`+`get_db`) → kế thừa auth, KHÔNG cần casbin_rule migration, KHÔNG 403. TUYỆT ĐỐI không thêm check_permission.**
14. `routers/admission_paths.py` — GET `/paths/{id}/documents` (route :617 hiện hữu): default no-audience → ALL layers (G2); thêm `?audience=` lọc 1 diện. **AN TOÀN Casbin: audience là query param, path KHÔNG đổi → policy :535 vẫn cover.** **🟡 G5 round-6 — preview thí sinh THIN-CLIENT:** dialog "Xem trước theo TS" (§5b) nhận **raw `cultural_education_level` + `vocational_qualification` (+ offering_type)** → BE `derive_audience_set` rồi resolve; KHÔNG để FE tự tính audience (vi phạm thin-client, memory `fe-thin-client-compliance`). `?audience=` chỉ dùng cho **bộ lọc lớp ở config panel** (admin chọn lớp để sửa — filter hợp lệ, KHÔNG phải business logic), KHÔNG dùng cho preview thí sinh.

**Frontend:**
15. `_components/shared/types.ts` — AdmissionAudience union; thêm applicable_audience + layer_kind.
16. `lib/api/master-data.ts` + `hooks/admissions/useMasterData.ts` — audience vào path + queryKey `["shared-document-group", ot, audience]` (R15 P2).
17. `Phase1Master/SharedDocumentConfigPanel.tsx` — Select Đối tượng (filter lớp để sửa) + (optional) Phương thức + nút Xem trước; reset modifications khi đổi audience. Bảng giấy tờ GIỮ NGUYÊN. **G5: nút "Xem trước theo TS" gửi raw cultural/vocational/offering_type cho BE derive — KHÔNG tự tính audience.**
18. `Phase3Config/ConfigDocuments.tsx` — badge layer_kind + applicable_audience (render BE).

## 5b. Wireframe FE (giữ từ v1)
### HIỆN TẠI (1 chiều)
```
Loại hình: [ Chính quy ▼ ]
[bảng giấy tờ: ☑ Học bạ THPT | ☑ Bằng TN THPT | ☑ CCCD ... | Bắt buộc | Up file | Thứ tự]  [💾 Lưu]
```
### SAU FEATURE (3 bộ lọc lớp + Xem trước, bảng GIỮ NGUYÊN)
```
Loại hình: [ Tất cả ▼ ]   Đối tượng: [ Sau THPT ▼ ]   Phương thức: [ Tất cả ▼ ]   [👁 Xem trước theo TS]
LỚP: "Tất cả loại hình × Sau THPT"   ⓘ NỀN (Đối tượng=Tất cả) luôn gộp thêm cho mọi thí sinh.
[bảng giấy tờ như cũ]  [💾 Lưu lớp]

[Xem trước] → dialog: Loại hình + Trình độ VH + Phương thức → [Tính bộ hồ sơ]
  → CCCD(NỀN), Khai sinh(NỀN), Ảnh/Khám SK(NỀN), Học bạ THPT(Lớp Sau THPT), Bằng TN THPT(Lớp Sau THPT)★
  (★=bắt buộc khi tốt nghiệp; "completed" → LOẠI khỏi bộ hồ sơ)
```
Controls: Đối tượng (MỚI, enum BE), Phương thức (MỚI optional), Xem trước (MỚI, BE resolve). Thin-client: options+preview từ BE; badge dùng `layer_kind`/`applicable_audience` (KHÔNG overload source).

## 11. Test
- Unit derive_audience_set (5 cultural × 4 vocational × 3 type; CONFIG_GAP fallback); compute_completed_doc_codes (completed→loại bằng TN).
- Resolve MERGE (mở rộng test_phase2_engine_3tier_resolution.py): NỀN-only=cũ; POST_THPT layer; **path_override KHÔNG bị audience trộn** (anti-regression P0.1); mandatory-wins; completed→bằng TN bị loại.
- Integration (test_admission_documents_audience.py mới): create=NỀN; PATCH cultural ở 3 editable→re-resolve INSERT-only; doc rớt→is_extra; PATCH ở submitted→gate chặn.
- **P0-A end-to-end (anchor regression):** create hồ sơ cultural trống (snapshot NỀN, KHÔNG có học bạ/bằng TN) → PATCH cultural=`completed_thpt` → assert snapshot mandatory_docs CÓ học bạ+bằng TN → submit assert 2 doc đó BẮT BUỘC (không submit được khi thiếu).
- **P0-B (anchor):** re-resolve khi code đã tồn tại (vd CCCD nền) → `add_path_documents_delta` KHÔNG vi phạm `uq_profile_document_path`, update_profile thành công, upload cũ còn nguyên.
- **P1-A + BLOCKER round-3 (anchor MẠNH):** re-resolve khi `derive_target_level_and_type` raise CONFIG_GAP (config NULL) + cultural=`graduated_thpt` → derive_audience_set nuốt CONFIG_GAP nội bộ, trả `{POST_THPT}` → **assert snapshot VẪN có học bạ + bằng TN** (KHÔNG chỉ "update_profile không vỡ" — anchor cũ không bắt được lỗ CONFIG_GAP). + assert applied_rules còn `allow_unverified_submission`/`admission_path_id` sau merge (invariant round-3) → submit KHÔNG raise :4975.
- upsert 2 layer không đè (R10); backfill seed 1/2→split, idempotent, downgrade; public audience=None grouped.
- **N1 (anchor):** create snapshot assert `schema_version==2` (KHÔNG bump 3) → 2 test :209/:406 vẫn xanh.
- **N3 multi-NV (anchor):** hồ sơ uses_choice_engine 2 choice cùng offering_type → PATCH cultural → re-resolve dùng profile.admission_path → audience nhất quán, snapshot đúng.
- **G2 admin endpoint (anchor):** GET `/paths/{id}/documents` KHÔNG audience SAU backfill → assert VẪN có học bạ/bằng TN (ALL layers, không co lại); `?audience=POST_THPT` → lọc đúng 1 diện.
- **G3 is_active (anchor 2 caller):** merge chung với doc_type inactive → create/path (`exclude_inactive=False`) GIỮ doc inactive; public (`exclude_inactive=True`) BỎ doc inactive (storefront #348 không regression).
- **G1 data thật (anchor):** backfill trên seed → POST_THPT(ot1) có hoc_ba+bằng TN; LIEN_THONG/VLVH RỖNG (assert không tạo group rỗng); profile cũ snapshot bất biến.
- **§8.0 THCS (anchor):** sau §8.0 → hồ sơ cultural=`graduated_thcs` (TC từ THCS) resolve ra `hoc_ba_thcs`+`bang_tot_nghiep_thcs`; hồ sơ cultural=`graduated_thpt` KHÔNG dính doc THCS (đúng phân biệt THCS↔THPT — nhu cầu gốc).
- CI: thêm test vào backend-test.yml Tier 4+5.

## 12. Rollout
**Chia 2 đợt co blast radius (round-1):** ĐỢT A = code + schema (cột applicable_audience + GIN), KHÔNG backfill. **⚠️ Framing chính xác (round-8 #2):** ĐỢT A inert cho cultural ∈ {graduated_*, None} (filter NỀN trả nguyên bộ → snapshot không đổi), NHƯNG **completed_*** ĐỔI hành vi NGAY: PATCH cultural=completed_thpt/thcs → re-resolve LOẠI bằng TN khỏi snapshot (§6 — TS hoàn thành chưa có bằng, không ép nộp). Đây là fix đúng, KHÔNG phải bug; nhưng KHÔNG phải "zero behavior change" tuyệt đối. Profile cũ snapshot bất biến (chỉ re-fire khi PATCH cultural/vocational). ĐỢT B (gated owner) = backfill §8.2 + §8.0 POST_THCS + rebuild path §8.3.
Branch → CI xanh (gồm anchor N1/N3 + P0-A/P0-B/P1-A) → owner duyệt (re-resolve INSERT-only + dry-run output + public schema) → merge squash → deploy CÓ migration: cold cutover (RUN_MIGRATIONS_ON_STARTUP=false, alembic ĐỢT A, verify GIN EXPLAIN) → ĐỢT B: dry-run §8.1 trên PROD, backfill §8.2, verify split, rebuild path §8.3 (backup table + owner duyệt từng path). **KHÔNG có feature flag — cold cutover ship code+data theo 2 đợt; "bật flag" đã bỏ (không định nghĩa flag nào).** Enum đã có→không tạo. Ref runbook §3.5/§7.2.

## 13. Risks
1. Union phá fork → tier precedence giữ, audience chỉ shared (§4) + test anti-regression.
2. completed=optional bất khả thi → loại khỏi set (§6).
3. upsert single-group (R10) → lookup (ot,audience) + test.
4. Backfill làm checklist profile mới co lại → chủ đích; profile cũ bất biến.
5. CONFIG_GAP raise → **nuốt nội bộ trong derive_audience_set, luôn trả ≥ tập văn hóa** (§5); re-resolve KHÔNG giữ snapshot NỀN-only (BLOCKER round-3).
6. GIN miss → dùng `&&` + **CAST `:set::admission_audience[]` (N4)**; query `IS NULL OR && :set::audience[]`; EXPLAIN ANALYZE.
7. 2 nơi resolve drift → module chung document_resolution_service.
8. FE cache đè → audience vào route+queryKey.
9. Tombstone defer → known-limitation phase 2.
10. code unique collision → hậu tố audience + check tồn tại + assert ≤50 (P2).
11. **P0-A doc snapshot stale** (cultural set sau create không vào snapshot) → re-resolve trigger gồm cultural/vocational (§7) + test e2e anchor (§11).
12. **P0-B UNIQUE violation re-resolve** (đụng uq_profile_document_path) → `add_path_documents_delta` delta INSERT (§7/§10.4b) + test anchor.
13. **P1-A audience rớt layer liên thông** (derive CONFIG_GAP do thiếu eager-load) → eager-load chain (§10.5) + try/except fallback + test anchor.
14. **P1-B rebuild path one-way** (downgrade không khôi phục group đã xóa) → backup table + runbook owner + dry-run PROD (§8.3).
15. **BLOCKER round-3: §5↔§7 mâu thuẫn CONFIG_GAP** (giữ snapshot cũ tái sinh P0-A ở nhánh CONFIG_GAP) → derive_audience_set nuốt nội bộ + re-resolve luôn apply (§5/§7) + anchor mạnh §11.
16. **Citation round-3: hard-gate cultural** thực ra ở `validate_eligibility` :1042/:1053 via :4846 (raise unwrapped), KHÔNG phải KV :5096 (do địa chỉ) → sửa §7.
17. **Invariant round-3: replace applied_rules vỡ submit** (:4974-4978 + scoring) → MERGE per-key + flag_modified, KHÔNG gán dict mới (§7).
18. **N1 round-4: schema_version=3 làm đỏ 2 test + zero benefit** (assert ==2 tại :209/:406; runtime chỉ ==1/>=2) → KHÔNG bump, giữ =2 (§7/§10.7).
19. **N2 round-4: route {audience} 403** → verify route GET document-groups KHÔNG Casbin-gated (auth qua get_config_filter→current_user); mirror deps, KHÔNG thêm casbin_rule/check_permission (§10.13).
20. **N3 round-4: multi-NV derive đa path** → re-resolve derive dùng profile.admission_path primary; submit gate MULTI_NV_INCONSISTENT :4538 đảm bảo nhất quán; +1 test multi-NV (§7).
21. **N4 round-4: GIN trên ARRAY(enum)** → cast `::admission_audience[]` (xem risk 6).
22. **N5 round-4: re-resolve mutate snapshot không vào audit** (updated_fields=data.keys() :4172) → thêm audit entry re-resolve (§7).
23. **N6 round-4: public catalog ~6× group** → P2 perf, verify selectinload batching + TTL; known-limitation (§9).
24. **P2 round-5: VLVH inert GĐ1** (enum có VLVH, backfill không tạo group) → known-limitation chủ đích; admin upsert nếu cần (§5/§8.2).
25. **P2 round-5: "bật flag" mơ hồ** (không định nghĩa flag) → bỏ; cold cutover 2 đợt code+data (§12).
26. **P2 round-5: compute_completed_doc_codes hardcode mã** → hằng số đồng bộ seed (`bang_tot_nghiep_thpt` ✅; `bang_tot_nghiep_thcs` verify catalog lúc code) (§6).
27. **P2 round-5: idempotency bước MOVE** (rerun không được re-move item đã split) → guard "code chưa thuộc group audience" (§8.2).
28. **🔴 G1 round-6: backfill §8.2 aspirational vs data thật** (4/5 audience không có doc nguồn trong seed; ot2 không có hoc_ba; "bằng TC/CĐ"=vocational không phải doc) → §8.1 dry-run TRƯỚC, §8.2 viết theo output; **owner chốt 2026-05-29: GĐ1 mở rộng TẠO doc type THCS + lớp POST_THCS (§8.0)** để phục vụ nhu cầu gốc; LIEN_THONG/VLVH vẫn known-limitation (§8).
29. **🔴 G2 round-6: refactor resolve_documents_for_path regression view admin** (3 caller :3216/:660/:617; no-audience=NỀN-only mất học bạ sau backfill) → default no-audience trả ALL layers + backward-compat FE + liệt kê 3 caller (§10.6/§10.14).
30. **🔴 G3 round-6: 2 merge khác is_active** (path không filter; public filter) → hàm chung tham số `exclude_inactive`, mỗi caller giữ hành vi; test cả 2 (§10.3).
31. **🟡 G4 round-6: upsert NỀN lookup theo code → 2 NỀN/ot** (seed HS_CHINH_QUY vs upsert SHARED_DOC_OT_{id}) → lookup theo (ot, audience IS NULL) reuse group hiện hữu (§10.8).
32. **🟡 G5 round-6: preview FE tự tính audience vi phạm thin-client** → preview nhận raw cultural/vocational, BE derive; `?audience=` chỉ cho filter panel (§10.14/§17).
33. **🟠 H1 round-7: config_document_type.name UNIQUE** (:176) → §8.0 idempotent phải pre-check cả name, KHÔNG ON CONFLICT(code) đơn lẻ (§8.0).
34. **🟠 H2 round-7: bang_diem_thpt(ot2) ép TC-liên-thông-từ-THCS** nếu để NỀN → đưa vào POST_THPT(ot2); §8.1 xác nhận ot2 có path TC liên thông (§8.2/G1).
35. **🟡 H3 round-7: downgrade chỉ drop cột → over-require** (group split đứng yên, code cũ merge tất cả) → downgrade hoàn nguyên split thật (§8.2).
