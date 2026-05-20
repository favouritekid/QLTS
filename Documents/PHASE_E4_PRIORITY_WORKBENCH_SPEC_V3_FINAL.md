# Phase E.4 — Priority Workbench Spec (V3 Final)

**Status:** LOCKED 2026-05-19 (chờ user confirm 5 decisions trước khi implement)
**Branch:** `feat/phase-e4-priority-workbench`
**WIP commit:** `16f9126b` (Foundation: PriorityAuditTimeline + zod schema)
**Estimated work:** 22-26h realistic (~3-3.5 working days) — covers B1+B2+B3 upload-path rework + ADM-007 preservation + G1 atomicity endpoint + G2 eager-load audit 17 call sites + G3 defensive cleaner + **cycle 5 additions:** P0.1 partial unique migration + P0.2 BE 7→8 step renumber + matrix tests + P0.3 schema split + P0.5 Casbin policy + G0a priority_evidence_documents service compute. Per memory `solo-dev-batch-prs-to-reduce-ci-overhead`

---

## Tóm tắt

Workbench refactor cho Step 4 (Ưu tiên tuyển sinh) tối ưu cho officer xử lý 50 hồ sơ/day. Gộp Wave 3 UT verify từ Step 8 vào Step 4, giúp officer không phải nhảy tab. Mở rộng Step 6 DocumentsTab để quản lý cả path documents + UT evidence documents (Option A — single source of truth).

**Hành trình quyết định:** v1 (2-col grid + tiles + search) → v2 (1-col linear + Đồng ý button) → v3 (move trình độ sang Học tập tab) → **v3-final** (Option A DocumentsTab centralization + critical BE bug fix transient attr pattern).

---

## I. Design principles

1. **1-cột vertical linear** — top→bottom, tab order = visual order
2. **Happy path zero ack** — engine result là source of truth, "Tiếp tục" cuối tab = implicit accept
3. **Single override path** — dialog (admin only) qua disclosure, không có tile/radio conflict
4. **Input layer (§1) tách output layer (§2)** — special-case là input modifier, override là output bypass
5. **Engine reasoning explicit** — lý do + căn cứ pháp lý (từ BE) để officer scan/trust
6. **5 KV states rõ ràng** — happy 🟢 / ambiguous 🟠 / missing ⚠ / frozen 🔒 / override 🔧
7. **Documents central** — DocumentsTab (Step 6) quản lý mọi giấy tờ, PriorityTab (Step 4) quản lý decisions

---

## II. Wireframe Step 4 — PriorityTab

### Header (compact 1-dòng)

```
┌──────────────────────────────────────────────────────────────┐
│ Step 4 of 8 · Ưu tiên tuyển sinh                              │
│ 🟢 Tạm tính: KV1 + UT04 = +1,75đ · UT07 chờ duyệt             │
└──────────────────────────────────────────────────────────────┘
```

State badge:
- `🟢` engine OK + có verified UT
- `🟠` engine ambiguous (cần manual)
- `⚠` missing input (cultural/vocational chưa ghi nhận)
- `🔒` post-submit frozen
- `🔧` override active

### § 1. Trình độ + Trường hợp đặc biệt (INPUT layer)

```
┌─ § 1. TRÌNH ĐỘ + TRƯỜNG HỢP ĐẶC BIỆT ─────────────────────────┐
│                                                                │
│ Trình độ:                                                       │
│   Văn hóa:  [Tốt nghiệp THPT ▼]      ← Tab 1                  │
│   Nghề:     [Chưa có bằng nghề ▼]    ← Tab 2                  │
│                                                                │
│ Trường hợp đặc biệt:                                            │
│   ☐ Bật trường hợp đặc biệt           ← Tab 3                  │
│      (PTDT nội trú, dự bị ĐH, lớp tạo nguồn, quân nhân/CAND)   │
│      ↳ Mã xã/phường: [01_00025_______]  ← Tab 4 (revealed)    │
└──────────────────────────────────────────────────────────────┘
```

**Rationale tách input vs output:** Special-case = "engine ơi, tính KV theo thường trú thay vì trường" (engine vẫn resolve). Override = "engine sai, officer ấn định cứng" (bypass engine + version guard + acknowledge_post_publish).

### § 2. KV — 5 states

#### Happy (75%)

```
│  ┌─ Engine kết quả ───────────────────────────────────────┐  │
│  │ 🟢 KV1 (+0,75đ)                                          │  │
│  │ Lý do: 3/3 năm cấp 3 tại THPT Bảo Lộc                   │  │
│  │        (Lâm Đồng — vùng miền núi)                       │  │
│  │ Căn cứ: TT 05/2021 Phụ lục 01 Mục 5.b                   │  │
│  │        ↑ from BE response.rule_law_citation              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ▾ Cán bộ ấn định thủ công (admin only) — collapsed default   │
│     [ Mở dialog override ]                                     │
```

#### Ambiguous (5%) — FE derives từ `preview.requires_manual_override === true`

```
│  ┌─ Engine flag ──────────────────────────────────────────┐  │
│  │ 🟠 Cần xác minh thủ công                                 │  │
│  │ Lý do: {preview.reason — text từ engine, vd "tied_grad   │  │
│  │        uation_year_and_grade"}                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│  [ Chọn KV thủ công ]  ← primary, mở dialog                    │
```

#### Missing input (5%) — FE derives từ `!cultural || !preview`

```
│  ┌─ Engine chưa đủ data ─────────────────────────────────┐  │
│  │ ⚠ Cần ghi nhận trình độ văn hóa + lịch sử học THPT trước.│  │
│  │ Vui lòng fill §1 ở trên và tab "Học tập".              │  │
│  └──────────────────────────────────────────────────────────┘  │
```

(no primary action — officer phải fill input trước)

#### Frozen post-submit — FE derives từ `frozenSnapshot.kv_resolved && profile.status !== 'draft' && !manual_override_*`

```
│  ┌─ Engine kết quả (đã chốt) ────────────────────────────┐  │
│  │ 🔒 KV1 (+0,75đ) · chốt lúc 19/5 09:00 · qua engine     │  │
│  │ Lý do: {frozenSnapshot.reason}                          │  │
│  │ Căn cứ: {frozenSnapshot.rule_law_citation}              │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ▾ Cán bộ ấn định lại (admin only) — collapsed                │
│     [ Mở dialog override ]                                     │
```

#### Override active — FE derives từ `frozenSnapshot.manual_override_reason` non-null

```
│  ┌─ Officer ấn định ─────────────────────────────────────┐  │
│  │ 🔧 KV1 (+0,75đ) · override                              │  │
│  │ Bởi: admin Phạm Thái Hà · 19/5 15:08                   │  │
│  │ Lý do: "Lớp tạo nguồn theo QĐ Bộ → KV1"                │  │
│  │ Engine ban đầu: KV3 (không cộng)                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ▾ Cán bộ ấn định lại (admin only)                             │
│     [ Mở dialog override ]                                     │
```

### § 3. UT — display + verify (no upload widget, Option A)

```
┌─ § 3. ĐỐI TƯỢNG ƯU TIÊN (UT) ────────────────────────────────┐
│  Officer đã ghi nhận: 2 diện (1 verified, 1 pending)           │
│                                                                │
│  ┌─ UT04 ─────────────────────────────────────────────────┐  │
│  │ Con thương binh, con liệt sĩ                  +1,00đ    │  │
│  │ ✅ Đã duyệt · bởi Trịnh Tố Uyên · 19/5 09:30           │  │
│  │ Minh chứng: hosp_42.pdf  [Xem PDF]                      │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌─ UT07 ─────────────────────────────────────────────────┐  │
│  │ Hộ nghèo                                       +0,50đ    │  │
│  │ ⏳ Chờ duyệt                                              │  │
│  │ Minh chứng: ho_ngheo.pdf  [Xem PDF]                      │  │
│  │ [ ✓ Duyệt ]  [ ✗ Từ chối ]   ← Tab 5, 6 per pending UT  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌─ UT08 (pending no file) ───────────────────────────────┐  │
│  │ Người nhiễm chất độc hóa học             +0,50đ          │  │
│  │ ⏳ Chờ duyệt                                              │  │
│  │ ⚠ Chưa có minh chứng                                     │  │
│  │ → [ Mở tab Giấy tờ để upload ]                          │  │
│  │ [ ✓ Duyệt (hồ sơ giấy) ]  [ ✗ Từ chối ]                  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ▾ Bổ sung diện UT khác — collapsed default                   │
│     └─ catalog full UT01-UT08 checkbox list                    │
│        (range theo priority_object_config[year], 7-8 codes     │
│        tùy seed năm 2026; UT08 hiển thị nếu admin đã seed)     │
│        ↳ Untick code → confirm dialog (xem dưới)               │
│                                                                │
│  EMPTY (chưa có UT nào ghi nhận):                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Hồ sơ chưa ghi nhận diện UT nào.                     │    │
│  │ ▾ Bổ sung diện UT                                    │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### Untick UT confirm dialog (UX safety guard)

Khi user untick 1 UT code mà UT đó đã có file minh chứng → hiển thị confirm dialog **TRƯỚC khi xóa**:

```
┌─ Bỏ chọn UT07? ─────────────────────────────────────────────┐
│ ⚠ Thao tác này sẽ XOÁ VĨNH VIỄN file minh chứng:             │
│                                                                │
│   ho_ngheo_xacnhan.pdf  (uploaded 19/5/2026)                   │
│                                                                │
│ Bạn cần upload lại nếu sau này tick UT07 trở lại.              │
│                                                                │
│              [ Huỷ ]    [ Xoá file và bỏ chọn ]                │
└──────────────────────────────────────────────────────────────┘
```

- Default focus = "Huỷ" (safer)
- Confirm = "Xoá file và bỏ chọn" (destructive, red button)
- Nếu UT code chưa có file đính kèm: untick trực tiếp **không** hiển thị dialog (no destructive action)
- Soft delete + 30d retention defer Phase E.5 — MVP hard delete với confirm dialog là acceptable safety guard

### § 4. Tóm tắt + audit + actions

```
┌─ § 4. TÓM TẮT ───────────────────────────────────────────────┐
│  Tổng tạm tính: KV1 +0,75đ + UT04 +1,00đ = +1,75đ              │
│  (UT07 chờ duyệt → chưa cộng)                                  │
│                                                                │
│  ▸ Audit log (3 thao tác trước đó) — disclosure                │
│    └─ when expanded: PriorityAuditTimeline (existing)          │
│  ▸ Căn cứ pháp lý (TT 05/2021) — disclosure                    │
│                                                                │
│              [ Lưu thay đổi ]    [ Tiếp tục → ]                │
│              ← Tab 7              ← Tab 8, Enter               │
└──────────────────────────────────────────────────────────────┘
```

---

## III. Wireframe Step 6 — DocumentsTab (mở rộng — Option A)

```
┌─ Tab "Giấy tờ" (Step 6) ────────────────────────────────────────┐
│                                                                  │
│ ── Giấy tờ bắt buộc (từ ngành tuyển sinh) ─────                 │
│ ✓ Học bạ THPT              [Xem PDF] [Tải lại]  ✅ Verified      │
│ ✓ CCCD                     [Xem PDF] [Tải lại]  ✅ Verified      │
│ ✗ Bằng tốt nghiệp THPT     [⬆ Tải lên]          ⏳ Pending       │
│ ✗ Ảnh 3x4                  [⬆ Tải lên]          ⏳ Pending       │
│ ✗ Giấy khám sức khoẻ       [⬆ Tải lên]          ⏳ Pending       │
│                                                                  │
│ ── Giấy tờ minh chứng ưu tiên (từ UT đã khai) ────              │
│ ✓ Giấy chứng nhận con thương binh                                │
│    (cho UT04 +1,00đ)        [Xem PDF] [Tải lại]  ✅ Verified    │
│    → Trạng thái duyệt: tab "Ưu tiên" §3                          │
│ ⏳ Giấy chứng nhận hộ nghèo                                       │
│    (cho UT07 +0,50đ)        [Xem PDF] [Tải lại]  ⏳ Chờ duyệt   │
│    → Trạng thái duyệt: tab "Ưu tiên" §3                          │
│ ✗ Giấy xác nhận chất độc hóa học                                 │
│    (cho UT08 +0,50đ)        [⬆ Tải lên]          ⏳ Chưa nộp    │
│                                                                  │
│ ── Eligibility summary ─────────────────────────                 │
│ Bắt buộc:  2/5 verified  · cần 3 nữa                             │
│ Ưu tiên:   1/2 docs uploaded · UT08 thiếu minh chứng             │
└──────────────────────────────────────────────────────────────────┘
```

UT documents auto-derive khi officer ghi nhận UT codes vào hồ sơ. DocumentsTab compute UI shape từ:

**FE consume server-computed `priority_evidence_documents`** (per G0a — DocumentsTab response contract).
BE pre-computes mỗi entry với label + bonus + file ref + verification status. FE chỉ render, KHÔNG raw query `profile_documents`:

```typescript
// FE DocumentsTab Priority section:
profile.priority_evidence_documents.map(item => ({
  sub_code: item.sub_code,
  label: item.label,          // từ priority_object_config.evidence_doc_type
  bonus: item.bonus_points,    // từ catalog
  document_id: item.document_id,    // null khi chưa upload
  document_file_path: item.document_file_path,  // S3 path, FE basename extract
  status: item.status,         // missing | uploaded | verified | rejected
  verification_status: item.verification_status,  // priority_object_evidence[code].status
}))
```

BE service compute logic (centralize trong `_populate_response_fields` per G0a Section VI):

```python
profile.priority_evidence_documents = [...]  # see G0a snippet
```


---

## IV. Officer flow estimate (50 hồ sơ/day)

| Case | % | Actions | Time |
|---|---|---|---|
| Happy path (engine OK + UT verify) | 75% (37.5) | Scroll Step 4 + 1-2 verify clicks + Continue | ~10s |
| Special-case toggle | 10% (5) | ☐ check + commune fill + verify + Continue | ~25s |
| Engine ambiguous | 5% (2.5) | Dialog KV + reason + verify + Continue | ~45s |
| Override (admin disagree) | 5% (2.5) | Disclosure + dialog + verify + Continue | ~60s |
| Missing data | 5% (2.5) | Fill §1 + scroll + verify + Continue | ~20s |
| Missing UT doc | <1% | Navigate Step 6 + upload + back Step 4 + verify | ~40s |
| **TOTAL 50 hồ sơ** | | | **~14-15 phút** |

≈ **17-18s/profile avg**.

---

## V. File plan

### Frontend NEW

| File | LOC | Purpose |
|---|---|---|
| `priority/PriorityHeaderBanner.tsx` | ~60 | 1-dòng compact header với engine state badge + tạm tính |
| `priority/PriorityInputsSection.tsx` | ~180 | §1: cultural + vocational + special-case switch + commune |
| `priority/EngineResultCard.tsx` | ~220 | §2 5 states (happy/ambiguous/missing/frozen/override); reads `rule_law_citation` từ BE |
| `priority/UtCandidateCards.tsx` | ~200 | §3 officer-edit display + verify inline (no upload widget); inline warning khi missing file (from `missing_priority_evidence_codes`); link → Step 6 để officer scan giấy; untick confirm dialog upstream của hard delete |
| `priority/PrioritySummaryPanel.tsx` | ~130 | §4 tổng + audit disclosure + actions sticky |
| `components/documents/PriorityEvidenceUploadCell.tsx` | ~80 | Wrap `FileUpload` generic với pre-filled context (category='priority_evidence', priority_sub_code=X). Mount trong DocumentsTab Priority section per row. |
| `lib/hooks/use-priority-evidence-upload.ts` | ~60 | NEW mutation hook — POST `/api/v2/admissions/{id}/priority-evidence/{sub_code}/upload` (canonical v2 group per P0.5). Invalidate `admission-profile-{id}` query + audit log query trên success |
| `lib/hooks/use-priority-evidence-delete.ts` | ~60 | NEW mutation hook — DELETE `/api/v2/admissions/{id}/priority-evidence/{sub_code}` (untick cascade per G1). Version guard + optimistic update |

### Frontend REWRITE

| File | Change | LOC |
|---|---|---|
| `tabs/PriorityTab.tsx` | Compose 4 sections linear | ~140 |
| `tabs/DocumentsTab.tsx` | Add Priority section + eligibility summary footer | +200 |
| `lib/zod/admissions.ts` | 2 schemas: `priorityObjectEvidenceEntrySchema` (write, unchanged shape + `paper_only_verification`) và NEW `priorityObjectEvidenceDisplayEntrySchema` (read, extends với `verified_by_name` + `document_file_path`). `priority_object_evidence_display` field dùng display schema. Plus `missing_priority_evidence_codes` array | +35 |
| `lib/api/priority-kv.ts` PreviewResponse | Add `rule_law_citation: string \| null` | +5 |

### Frontend DELETE

| File | Reason |
|---|---|
| `priority/KvDecisionPanel.tsx` + test | Replaced by PriorityInputsSection + EngineResultCard |
| `priority/UtPolicyPanel.tsx` + test | Replaced by UtCandidateCards |
| `components/admissions/PrioritySnapshotCard.tsx` + test | **Audit verified 2026-05-19:** 5 files reference — PriorityTab + UtPolicyPanel (cả 2 trong DELETE/REWRITE list) + chính component + test = safe delete. Không có external dependency. |

### Frontend KEEP / EXTEND

| File | Notes |
|---|---|
| `priority/PriorityAuditTimeline.tsx` + test | Mount vào §4 disclosure |
| `PriorityOverrideDialog.tsx` | Reuse 100% |
| `components/common/upload/FileUpload.tsx` | Generic component có sẵn — wrap thành `PriorityEvidenceUploadCell` (NEW, see Frontend NEW table) để bind với priority context. KHÔNG có `S3UploadButton` riêng. |
| Existing FE upload mutation pattern | Hiện tại upload qua axios mutation trong `hooks/admissions/useAdmissions.ts` POST `/admissions/{id}/documents/{doc_code}/upload`. **KHÔNG có `useUploadDocument` reusable hook** — phải thêm new mutation hook `usePriorityEvidenceUpload` cho endpoint mới (see G1 below). |

### Backend

| File | Change | LOC |
|---|---|---|
| **Migration** `profile_document` | Add `category VARCHAR(40) NOT NULL DEFAULT 'path'` + `priority_sub_code VARCHAR(2) NULL` + **DROP NOT NULL `document_type_id`** (priority_evidence rows không cần ConfigDocumentType FK — `evidence_doc_type` text từ catalog) + **DROP existing `uq_profile_document(profile_id, document_type_id)`** + add 2 partial unique indexes: `UNIQUE(profile_id, document_type_id) WHERE category='path'` và `UNIQUE(profile_id, priority_sub_code) WHERE category='priority_evidence'` + CHECK constraint cho category enum | +60 SQL |
| `models/admission_config/profile_data.py` `ProfileDocument` | Add 2 columns + drop NOT NULL `document_type_id` (relationship vẫn keep, chỉ optional cho priority_evidence rows) | +20 |
| **Migration** `priority_audit_log` CHECK | Extend `ck_priority_audit_log_action_type` thêm 2 action mới: `ut_evidence_untick` (G1 atomic delete) + `ut_evidence_warning_dismissed` (Decision #2 audit). DB hiện chỉ allow 4 actions cũ — không mở CHECK sẽ INSERT runtime fail | +10 SQL |
| `schemas/admission.py` `PriorityObjectEvidenceEntry` | **REMAIN write-only schema** — chỉ `status` + `document_id` + `verified_by` + `verified_at` + `reject_reason` + `requested_at` + `paper_only_verification` (PERSISTED field, set by service verify path). KHÔNG add display-only fields vào write schema vì `AdmissionProfileUpdate` reuse schema này (line 666) — nếu thêm display field vào, FE PATCH có thể leak vào JSONB column qua update_profile path | +5 |
| `schemas/admission.py` `PriorityObjectEvidenceDisplayEntry` | **NEW separate read-only schema** inherit từ `PriorityObjectEvidenceEntry` + `verified_by_name` + `document_file_path`. CHỈ dùng trong `priority_object_evidence_display` projection. Tách input/output → ngăn write path leak display fields vào JSONB | +25 |
| `schemas/admission.py` `AdmissionProfileResponse` | Add `priority_object_evidence_display: Optional[Dict[...]] = None` + `missing_priority_evidence_codes: list[str]` (cả 2 đều transient — set on ORM instance không phải column) | +20 |
| `schemas/admission.py` `PreviewPriorityKvResponse` | Add `rule_law_citation: Optional[str] = None` | +5 |
| `services/priority_service.py` (engine — actual file name, KHÔNG phải `priority_resolution.py`) | Add `RULE_LAW_CITATION` map + `resolve_law_citation()` | +40 |
| `services/admission_service.py` `_populate_response_fields` | **Set TRANSIENT attr** `profile.priority_object_evidence_display = enriched_dict` + `profile.missing_priority_evidence_codes = [...]` (NOT mutate columns). **Eager-load audit (G2 below):** add `selectinload(AdmissionProfile.documents)` vào các call sites chưa có | +60 |
| `services/admission_service.py::upload_document` (existing line 4413) | **EXTEND existing function** — KHÔNG có file `services/document_service.py`. Add 2 optional params `category='path'` (default) + `priority_sub_code: Optional[str]=None`. Preserve **ADM-007 staging/finalize pattern**: tuple return `(profile, finalize(committed: bool))`. Khi `category='priority_evidence'`: validate sub_code ∈ catalog year + persist columns | +60 |
| `services/admission_service.py` `verify_object_evidence` (existing priority_override) | Lookup doc qua `(profile_id, category='priority_evidence', priority_sub_code=code)`; allow null doc + audit flag `paper_only_verification` (default case phần lớn hồ sơ) | +30 |
| `services/admission_service.py` untick UT cascade | **NEW dedicated endpoint** — see Section VI G1 atomicity contract. Endpoint orchestrates JSONB update + DELETE doc + finalize callback trong 1 transaction | +50 |
| **`routers/admissions_v2.py`** priority-evidence endpoints | **Canonical route group** — existing v2 router đã host priority-related endpoints (verify_priority_object_evidence line 1016, reject_priority_object_evidence line 1066). Add 2 NEW endpoints cùng nhóm cho consistency: `POST /api/v2/admissions/{id}/priority-evidence/{sub_code}/upload` + `DELETE /api/v2/admissions/{id}/priority-evidence/{sub_code}`. Cả 2 endpoint delegate vào `admission_service.upload_document` (extend) + `untick_priority_evidence` (new) | +70 |
| `routers/admissions.py` upload endpoint (line 824) | Existing endpoint `POST /api/admissions/{id}/documents/{doc_code}/upload` — KHÔNG mở thêm path. Path docs route hiện hữu giữ nguyên. Priority evidence route hoàn toàn tách qua v2 group. | unchanged |
| **`casbin_config/policy_templates.py`** | Add 2 new policy entries (mirror pattern verify/reject existing): `POST /api/v2/admissions/*/priority-evidence/*/upload` (officer/admin allow + accountant deny) + `DELETE /api/v2/admissions/*/priority-evidence/*` (officer/admin allow + accountant deny). Plus rerun `sync_notification_rules` không cần (đây là Casbin not notifications) | +20 |
| **`services/admission_service.py`** step_status inline dicts (line 1126 trong `_compute_completion_percent` line 1082 + line 1768 trong `_compute_frontend_fields` line 1404) + step_weights inline (line 1136) | **CRITICAL renumber:** BE hiện compute 7-step inline model với Step 4=Scores, Step 5=Documents. Phase E.4 FE 8-step model với Step 4=Priority (new gộp KV+UT), Step 5=Scores, Step 6=Documents, Step 7=Tuition, Step 8=Finalize. Phải update inline step_status dict ở cả 2 chỗ + step_weights dict (rebalance 7→8 entries, total=100) + validation_summary mapping. Plus update PipelineSidebar `stepErrorCount` mapping line 82 (currently personal→1, gpa→4, documents→5 — sai sau renumber). KHÔNG có function `_calculate_step_status` riêng. | +60 |

---

## VI. ⚠ CRITICAL — BE service code pattern (no ORM mutation)

### Schema verification (verified 2026-05-19 against codebase)

**`ProfileDocument` model** (`Backend_FastAPI/app/models/admission_config/profile_data.py:81`) hiện có các columns:
- `id`, `profile_id` (FK admission_profile), `document_type_id` (FK config_document_type)
- `status` (missing/uploaded/verified/rejected/paper_submitted)
- **`file_path`** (String 500, S3 path) — KHÔNG có `filename` column
- `verified_by`, `verified_at`, `uploaded_at`, etc.

**Original filename** chỉ được lưu trong **`DocumentAuditLog.original_filename`** (line 278, String 255) tại thời điểm upload. Vì vậy:

- ❌ **WRONG (in older spec drafts):** `select(ProfileDocument.id, ProfileDocument.filename)` — column không tồn tại, runtime crash.
- ✅ **FIX:** Service code dùng `models.ProfileDocument.file_path` (S3 path String 500). Display filename ở FE bằng `path.split('/').pop()` (basename extract). Approach này không thêm migration column, đơn giản nhất cho launch.
- **Optional fidelity upgrade (defer Phase E.5+):** Add column `original_filename VARCHAR(255)` vào `profile_document` + backfill từ `document_audit_log` nếu officer feedback report tên file S3 hashed/UUID khó đọc. Hiện tại upload service đặt file_path theo pattern `profile_{id}/{document_type}_{timestamp}.{ext}` → basename còn human-readable, đủ dùng.

**`PriorityObjectConfig.evidence_doc_type`** (`models/priority_config.py:160`) là `String(100)` — text Việt sẵn (vd "Giấy chứng nhận hộ nghèo"). KHÔNG phải FK đến `ConfigDocumentType`. DocumentsTab Priority section dùng **TRỰC TIẾP** text này làm label hiển thị — không cần FE hard-code map, không cần BE join với document type catalog.

### Migration SQL (full)

```sql
-- Add 2 columns to profile_document
ALTER TABLE profile_document
  ADD COLUMN category VARCHAR(40) NOT NULL DEFAULT 'path',
  ADD COLUMN priority_sub_code VARCHAR(2) NULL;

-- CHECK constraint: priority_sub_code only set when category='priority_evidence'
ALTER TABLE profile_document
  ADD CONSTRAINT ck_priority_evidence_sub_code
  CHECK (
    (category = 'priority_evidence' AND priority_sub_code IS NOT NULL)
    OR (category != 'priority_evidence' AND priority_sub_code IS NULL)
  );

-- Partial index for UT evidence lookups (most common query path)
CREATE INDEX idx_profile_document_priority
  ON profile_document(profile_id, priority_sub_code)
  WHERE category = 'priority_evidence';
```

**Downtime:** Migration ADD COLUMN với DEFAULT là **instant DDL** trên PostgreSQL ≥ 11 — không cần downtime. Không có backfill cần chạy (existing rows tự nhận DEFAULT 'path'). Total migration <1s.

### The bug avoided

❌ **WRONG** (would persist denormalized data to DB):

```python
# DO NOT DO THIS — priority_object_evidence is an ORM JSONB column.
# Assigning to it marks the row dirty → router's db.commit() persists
# denormalized verified_by_name + document_file_path → schema drift on re-read.
profile.priority_object_evidence = enriched
```

### Correct pattern — transient attribute

✅ **RIGHT** (transient Python attr, not tracked by SQLAlchemy):

```python
# Pydantic schema:
class AdmissionProfileResponse(BaseModel):
    # Raw JSONB column — backend write path uses this
    priority_object_evidence: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # Phase E.4 (Option A) — denormalized projection for workbench UI.
    # Populated by admission_service._populate_response_fields as a transient
    # attribute on the ORM instance. JSONB column NEVER receives denormalized
    # data — avoids dirty-flag persistence cascade.
    # FE pattern: prefer `priority_object_evidence_display ?? priority_object_evidence`.
    priority_object_evidence_display: Optional[Dict[str, Dict[str, Any]]] = None


# Service code:
async def _populate_response_fields(...) -> None:
    # ... existing logic ...

    evidence = profile.priority_object_evidence or {}
    if evidence:
        user_ids = {
            e.get("verified_by")
            for e in evidence.values()
            if isinstance(e, dict) and e.get("verified_by")
        }
        doc_ids = {
            e.get("document_id")
            for e in evidence.values()
            if isinstance(e, dict) and e.get("document_id")
        }

        user_names: dict[int, str] = {}
        if user_ids:
            rows = await db.execute(
                select(models.User.id, models.User.full_name)
                .where(models.User.id.in_(user_ids))
            )
            user_names = {row.id: row.full_name for row in rows}

        doc_paths: dict[int, str] = {}
        if doc_ids:
            # ProfileDocument has only `file_path` (S3 path String 500) — NO `filename`
            # column exists (verified against models/admission_config/profile_data.py:115).
            # FE derives display filename via path.split('/').pop() (basename extract).
            # See section "Schema verification" above for optional fidelity upgrade path.
            rows = await db.execute(
                select(
                    models.ProfileDocument.id,
                    models.ProfileDocument.file_path,
                )
                .where(models.ProfileDocument.id.in_(doc_ids))
            )
            doc_paths = {row.id: row.file_path for row in rows if row.file_path}

        enriched: dict[str, dict] = {}
        for code, entry in evidence.items():
            if not isinstance(entry, dict):
                enriched[code] = entry
                continue
            e = dict(entry)
            if e.get("verified_by") and e["verified_by"] in user_names:
                e["verified_by_name"] = user_names[e["verified_by"]]
            if e.get("document_id") and e["document_id"] in doc_paths:
                # Pass full S3 path; FE extracts basename for display
                e["document_file_path"] = doc_paths[e["document_id"]]
            enriched[code] = e

        # Transient attribute — NOT a column, NOT tracked by SQLAlchemy.
        # Pydantic's from_attributes reads this when serializing because
        # the field exists on the AdmissionProfileResponse schema.
        profile.priority_object_evidence_display = enriched
```

### Engine law citation map

```python
# In services/priority_service.py (NOT priority_resolution.py — file rename verified 2026-05-20):

RULE_LAW_CITATION: dict[str, str] = {
    "thpt_multi_school_longest_duration": "TT 05/2021 Phụ lục 01 Mục 5.b",
    "thpt_single_school": "TT 05/2021 Phụ lục 01 Mục 5.a",
    "permanent_address_special": "TT 05/2021 Phụ lục 01 Mục 4",
    "manual_override": "TT 05/2021 Phụ lục 01 Mục 6 (admin override)",
    "ambiguous_requires_manual": None,  # no clear law citation
    # ... cover all rule_applied values
}

def resolve_law_citation(rule_applied: Optional[str]) -> Optional[str]:
    if not rule_applied:
        return None
    return RULE_LAW_CITATION.get(rule_applied)
```

Called by both `/preview-priority-kv` (response builder) AND `_populate_response_fields` for frozen `priority_resolution_snapshot`.

### Inline warning compute (NOT eligibility gate)

UT missing-file là vấn đề **officer data-entry quality**, không phải candidate fraud → không block eligibility. Compute danh sách codes thiếu file để FE hiện inline warning màu cam ở §3 UT card:

```python
def _populate_response_fields(profile, ...) -> None:
    # ... existing logic ...

    # Phase E.4 — Compute missing priority evidence codes for FE inline warning.
    # NOT eligibility gate: officer có thể submit với verify "Hồ sơ giấy"
    # khi giấy chưa scan kịp. Warning purely UX reminder cho officer
    # tự discipline trước submit.
    priority_codes = profile.priority_object_codes or []
    if priority_codes:
        uploaded_codes = {
            doc.priority_sub_code
            for doc in profile.documents or []
            if doc.category == "priority_evidence"
            and doc.priority_sub_code
        }
        # Transient attr — FE hiện badge "⚠ Thiếu minh chứng cho UT07"
        # per code trong UtCandidateCards
        profile.missing_priority_evidence_codes = sorted(
            set(priority_codes) - uploaded_codes
        )
    else:
        profile.missing_priority_evidence_codes = []
```

FE field trên `AdmissionProfileResponse`:

```python
class AdmissionProfileResponse(BaseModel):
    # ... existing fields ...
    # Phase E.4 — Codes có ghi nhận UT nhưng officer chưa scan file.
    # FE dùng để render inline warning ở §3 UT card. KHÔNG ảnh hưởng
    # eligibility_status — officer có quyền verify "Hồ sơ giấy" và submit.
    missing_priority_evidence_codes: list[str] = Field(default_factory=list)
```

### Audit flag — paper_only_verification (default case)

Officer verify UT cho hồ sơ giấy (giấy chưa scan vào hệ thống) là **phần lớn hồ sơ** trong nghiệp vụ VN hiện tại — KHÔNG phải exception. Đặt tên `paper_only_verification=true` thay vì `verified_without_evidence` để officer hiểu workflow này là chuẩn, không phải sai. Tỷ lệ thực tế đo qua Sentry/log analytics post-launch để có số liệu cụ thể.

```python
async def verify_object_evidence(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    sub_code: str,
    document_id: Optional[int],  # None → paper-only verify
    officer: models.User,
    ...
) -> ...:
    # ... existing logic + version guard ...

    paper_only = document_id is None

    profile.priority_object_evidence[sub_code] = {
        "status": "verified",
        "verified_by": officer.id,
        "verified_at": datetime.now(timezone.utc),
        "document_id": document_id,  # None acceptable
        "paper_only_verification": paper_only,
    }

    # Audit log entry — preserves paper_only flag cho thanh tra
    audit_row = models.PriorityAuditLog(
        profile_id=profile.id,
        action_type="ut_evidence_verified",
        actor_id=officer.id,
        new_value={"sub_code": sub_code, "document_id": document_id},
        audit_metadata={
            "paper_only_verification": paper_only,
            # ... other context ...
        },
    )
    db.add(audit_row)
```

FE hiển thị badge "Hồ sơ giấy" thay vì "(admin bypass)" trên verified UT card khi `paper_only_verification=true`. Tone neutral, không gợi ý officer đang làm sai.

### G0 — BE step model renumber 7-step → 8-step (P0.2 fix audit cycle 5)

**Critical mismatch:** FE PipelineSidebar đã 8 steps (line 30 — Step 4 Priority post-Phase E.4 gộp KV+UT). BE step_status logic **KHÔNG ở function tên `_calculate_step_status` riêng** — nó là **inline step_status dict** tại 2 chỗ trong `admission_service.py`: (a) line 1126 inside `_compute_completion_percent` body (function def line 1082), và (b) line 1768 inside `_compute_frontend_fields` body (function def line 1404). Step_weights inline dict tại line 1136 (7 entries hiện tại) cũng cần rebalance lên 8 entries. Cả 2 chỗ inline dict đều dùng 7-step model với:

| Step | BE current | FE Phase E.4 | Mismatch |
|---|---|---|---|
| 1 | Personal | Personal | ✓ |
| 2 | Family | Family | ✓ |
| 3 | Academic | Academic | ✓ |
| 4 | **Scores** (gpa_error) | **Priority** (KV+UT gộp) | ❌ badge "Scores error" hiện trên Priority tab |
| 5 | **Documents** (doc_errors) | **Scores** | ❌ badge "Documents error" hiện trên Scores tab |
| 6 | Tuition (always success) | **Documents** | ❌ Documents tab show "success" mặc đoạn doc thiếu |
| 7 | Finalize | Tuition | ❌ |
| 8 | (none) | Finalize | ❌ |

**Fix scope:**
- Update inline step_status dicts ở 2 chỗ (line 1126 + 1768) + `step_weights` inline dict (line 1136) từ 7 → 8 entries:
  - Step 4: Priority (compute từ `priority_object_codes` length + KV resolved state)
  - Step 5: Scores (existing gpa logic, renumber từ step 4)
  - Step 6: Documents (existing doc logic, renumber từ step 5)
  - Step 7: Tuition (existing, renumber từ step 6)
  - Step 8: Finalize (existing eligibility gate, renumber từ step 7)
- Update validation_summary mapping (line 84-99 PipelineSidebar) — `gpa` → step 5, `documents` → step 6
- Update `handleCheckCondition` AdmissionDetailClient line 434-436 — `stepsStatus[5]` thay vì `[4]`, `stepsStatus[6]` thay vì `[5]`
- Update `step_weights` total = 100 vẫn giữ (rebalance 14/14/14/15/15/14/14 → 8 entries, vd 13/13/13/12/12/13/12/12)
- Update grouped validation errors mapping nếu có

**Step 4 Priority status compute:**
```python
# Step 4 = Priority (Phase E.4 NEW)
has_priority_input = bool(profile.cultural_education_level)
has_priority_codes = bool(profile.priority_object_codes)
kv_resolved = bool(
    profile.priority_resolution_snapshot
    and profile.priority_resolution_snapshot.get("kv_resolved")
)
step_status[4] = (
    "error" if not has_priority_input  # missing required input
    else "warning" if not kv_resolved  # engine chưa resolve (ambiguous?)
    else "success"
)
```

**Tests:** anchor matrix tests per memory [[test-fixture-drift-after-policy-refactor]] — phải update fixture cho cả 8 steps trong cùng PR. Pytest cases: empty profile → step 4 error; partial fill → step 4 warning; full happy → step 4 success.

### G0a — DocumentsTab response contract clarification (P1 fix audit cycle 5)

Spec wireframe Step 6 DocumentsTab (Section IV line ~210) compute UI từ `priority_object_codes` + `priority_object_evidence` + uploaded documents. Tuy nhiên `AdmissionProfileResponse` hiện **chỉ expose `documents_checklist`** (built từ applied_rules per line 1125 schemas/admission.py), KHÔNG expose raw `profile_documents` với `category`/`priority_sub_code` fields.

**Decision: extend response thay vì rely on raw documents query từ FE.**

Add NEW field `priority_evidence_documents: list[PriorityEvidenceDocumentItem]` trên `AdmissionProfileResponse`:

```python
class PriorityEvidenceDocumentItem(BaseModel):
    """Per-priority-UT document item cho DocumentsTab Priority section."""
    sub_code: str  # vd "07"
    bonus_points: float  # từ catalog
    label: str  # PriorityObjectConfig.evidence_doc_type (vd "Giấy chứng nhận hộ nghèo")
    document_id: Optional[int]  # null nếu chưa upload
    document_file_path: Optional[str]  # null nếu chưa upload
    status: Literal["missing", "uploaded", "verified", "rejected"]
    verification_status: Optional[str]  # từ priority_object_evidence[sub_code].status

class AdmissionProfileResponse(BaseModel):
    # ... existing ...
    priority_evidence_documents: list[PriorityEvidenceDocumentItem] = Field(default_factory=list)
```

**Service compute** (in `_populate_response_fields` after evidence enrichment):
```python
# Build priority_evidence_documents từ codes + catalog + documents query
priority_codes = profile.priority_object_codes or []
catalog_items = await _load_catalog(db, academic_year=profile.academic_year)
docs_by_code = {
    doc.priority_sub_code: doc
    for doc in (profile.documents or [])
    if doc.category == "priority_evidence" and doc.priority_sub_code
}
evidence_dict = profile.priority_object_evidence or {}

profile.priority_evidence_documents = [
    PriorityEvidenceDocumentItem(
        sub_code=code,
        bonus_points=catalog_items.get(code, {}).bonus_points or 0,
        label=catalog_items.get(code, {}).evidence_doc_type or "(Chưa có catalog)",
        document_id=docs_by_code.get(code).id if docs_by_code.get(code) else None,
        document_file_path=docs_by_code.get(code).file_path if docs_by_code.get(code) else None,
        status="uploaded" if docs_by_code.get(code) else "missing",
        verification_status=evidence_dict.get(code, {}).get("status"),
    )
    for code in priority_codes
]
```

FE DocumentsTab consume `priority_evidence_documents` directly, không cần raw query.

### G1 — Untick UT atomicity contract

Decision #4 cascade hard delete cần endpoint riêng để guarantee atomicity. **KHÔNG** dùng PATCH `/admissions/{id}` với `priority_object_codes` array mới vì:
- 3 mutations: JSONB update (priority_object_codes + priority_object_evidence) + DELETE profile_document row + audit log INSERT
- Nếu S3 delete fail giữa chừng, profile_document DELETED nhưng JSONB chưa update → state lệch
- Race window nếu FE thực hiện 2 calls

**Endpoint design:**

```
DELETE /api/v2/admissions/{id}/priority-evidence/{sub_code}
Body: { version: int }
Response: AdmissionProfileResponse (updated)
```

**Service signature:**

```python
async def untick_priority_evidence(
    db: AsyncSession,
    profile_id: int,
    sub_code: str,
    version: int,  # Optimistic lock
    current_user: models.User,
) -> tuple[models.AdmissionProfile, Callable]:
    """
    Hard delete UT evidence + cascade priority_object_codes/evidence JSONB.

    Returns tuple per ADM-007 staging/finalize: caller commits THEN calls
    finalize(committed=True) to actually delete the S3 file. Commit fail →
    finalize(False) skips delete (file still on S3 but row deleted — leak
    risk acceptable per ADM-007 since profile_document row gone means no
    reference to S3 path).
    """
    profile = await get_profile(db, profile_id, current_user)

    # Version guard FIRST (memory: version-guard-before-state-machine)
    if profile.version != version:
        raise ConflictError(...)

    # 1. Find priority_evidence document
    doc = await db.execute(
        select(models.ProfileDocument).where(
            models.ProfileDocument.profile_id == profile_id,
            models.ProfileDocument.category == "priority_evidence",
            models.ProfileDocument.priority_sub_code == sub_code,
        )
    )
    doc_row = doc.scalar_one_or_none()

    # 2. Update JSONB column (defensive cleaner per G3)
    codes = list(profile.priority_object_codes or [])
    if sub_code in codes:
        codes.remove(sub_code)
        profile.priority_object_codes = codes
    evidence = dict(profile.priority_object_evidence or {})
    evidence.pop(sub_code, None)  # strip display fields ALREADY done since we read raw column
    profile.priority_object_evidence = evidence

    # 3. Delete document row (cascade audit log via existing trigger)
    file_path_to_unlink = None
    if doc_row:
        file_path_to_unlink = doc_row.file_path
        await db.delete(doc_row)

    # 4. Insert priority_audit_log row
    db.add(models.PriorityAuditLog(
        profile_id=profile.id,
        action_type="ut_evidence_untick",  # NEW action_type
        actor_id=current_user.id,
        old_value={"sub_code": sub_code, "had_file": file_path_to_unlink is not None},
        audit_metadata={"reason": "officer_untick"},
    ))

    # 5. Bump version
    profile.version += 1
    await db.flush()

    # 6. Return finalize callback per ADM-007
    async def finalize(committed: bool):
        if committed and file_path_to_unlink:
            # Best-effort S3 delete after commit settles
            await _safe_unlink(file_path_to_unlink)
        # Commit fail: do nothing (DB rollback restores doc row; file untouched on S3)

    return profile, finalize
```

**CHECK constraint update:** Add **CẢ 2 action types mới** vào `ck_priority_audit_log_action_type` migration — `'ut_evidence_untick'` (G1 cascade) + `'ut_evidence_warning_dismissed'` (Decision #2 audit khi officer submit với missing codes). DB hiện chỉ allow 4 action cũ; thiếu 1 action sẽ runtime fail tại INSERT.

### G2 — `_populate_response_fields` documents eager-load audit

`_populate_response_fields` được gọi từ **17 call sites** (verified `admission_service.py` line 3116, 4628, 4831, 4939, 5146, 5826, 6028, 6229, 6414, 6648, 6849, 6947, 6964, 7026, 7147, 7716, 7814). Phase E.4 adds documents iteration cho `missing_priority_evidence_codes` compute → tất cả call sites phải eager-load documents để tránh `MissingGreenlet`.

**Pattern thêm `documents=` param hoặc selectinload upstream:**

| Call site | Current state | Action |
|---|---|---|
| 7147 | Already `documents=profile.documents` (explicit eager) | ✓ Keep |
| 7716 | `documents=None` (explicit skip) | ✓ Keep — function handles None branch silently |
| 3116, 4628, 4831, 4939, 5146 (5 sites trong update/state-machine paths) | Profile load uses nested `selectinload(lead).selectinload(assigned_officer)` — chưa `selectinload(documents)` | **AUDIT individually** — add `selectinload(AdmissionProfile.documents)` vào query trước call, hoặc pass `documents=` param |
| 5826, 6028, 6229, 6414, 6648 (5 sites trong action paths approve/reject/...) | Same pattern as above | Same — eager-load OR pass documents= |
| 6849, 6947, 6964, 7026, 7814 (5 sites trong magic-link/override paths) | Same | Same |

**Defensive fallback:** Add try/except in `_populate_response_fields` để swallow MissingGreenlet và default `missing_priority_evidence_codes = []` thay vì crash. Log warning. Phase E.4 launch không block path nào nếu warning compute fail; FE inline warning chỉ không hiện cho path đó.

```python
try:
    docs_for_priority = profile.documents or []
    uploaded_codes = {
        doc.priority_sub_code
        for doc in docs_for_priority
        if doc.category == "priority_evidence" and doc.priority_sub_code
    }
    profile.missing_priority_evidence_codes = sorted(
        set(profile.priority_object_codes or []) - uploaded_codes
    )
except Exception as exc:  # noqa: BLE001 — defensive against MissingGreenlet
    log.warning(
        "missing_priority_evidence_codes compute failed",
        profile_id=profile.id,
        error=str(exc),
    )
    profile.missing_priority_evidence_codes = []
```

### G3a — Schema split write vs display (P0.3 fix audit cycle 5)

`PriorityObjectEvidenceEntry` (`schemas/admission.py:480`) hiện được **reuse** trong:
- `AdmissionProfileResponse.priority_object_evidence` (response)
- `AdmissionProfileUpdate.priority_object_evidence` (PATCH request body, line 666)

→ Nếu thêm `verified_by_name` + `document_file_path` vào write schema, FE PATCH có thể (1) gửi giá trị giả, (2) BE service `update_profile` assign thẳng vào JSONB (line 3679+), (3) display fields persist xuống DB → drift schema.

**Fix:** Tách 2 schemas (mirror pattern `AdmissionProfileResponse` vs `AdmissionProfileUpdate`):

```python
# WRITE schema — used by AdmissionProfileUpdate input + JSONB column shape
class PriorityObjectEvidenceEntry(BaseModel):
    """Mirror of priority_object_evidence JSONB entry shape.
    Used by both input (AdmissionProfileUpdate) and persistence layer.
    `paper_only_verification` IS persisted (set by verify service)."""
    status: Literal["pending", "verified", "rejected"]
    document_id: Optional[int] = None
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None
    reject_reason: Optional[str] = Field(None, max_length=500)
    requested_at: Optional[datetime] = None
    paper_only_verification: bool = False  # NEW persisted field

    model_config = ConfigDict(extra="forbid")  # strict — block display fields

# READ-only display schema — used ONLY in priority_object_evidence_display
class PriorityObjectEvidenceDisplayEntry(PriorityObjectEvidenceEntry):
    """Extends write schema with denormalized display fields.
    NEVER used as input — only response serialization."""
    verified_by_name: Optional[str] = None
    document_file_path: Optional[str] = None

    model_config = ConfigDict(extra="forbid")
```

**Use sites:**
- `AdmissionProfileUpdate.priority_object_evidence` → `Dict[str, PriorityObjectEvidenceEntry]` (unchanged type)
- `AdmissionProfileResponse.priority_object_evidence` → `Dict[str, PriorityObjectEvidenceEntry]` (raw JSONB, unchanged)
- `AdmissionProfileResponse.priority_object_evidence_display` → `Dict[str, PriorityObjectEvidenceDisplayEntry]` (NEW, denormalized projection)

Pydantic strict mode (`extra="forbid"`) trên cả 2 schemas → bất kỳ assign nào leak field sai sẽ ValidationError tại serialization boundary, fail-fast.

### G3 — Defensive JSONB cleaner (strip display-only fields)

`PriorityObjectEvidenceEntry` schema dùng `ConfigDict(extra="forbid")` (line 515 schemas/admission.py). **Display-only fields** (chỉ trong `priority_object_evidence_display` TRANSIENT attr): `verified_by_name`, `document_file_path`. **`paper_only_verification` LÀ persisted field** (set bởi verify service trong JSONB), NOT a display field — không strip. Nếu code path nào lỡ assign 2 display fields trên từ projection back vào JSONB column (vd developer copy-paste sai), Pydantic strict validation sẽ raise; nhưng nếu mutate raw dict trực tiếp bypass validation, các field này sẽ persist vào DB.

**Defensive helper:**

```python
# In services/admission_service.py:

_EVIDENCE_DISPLAY_ONLY_FIELDS = frozenset({
    "verified_by_name",
    "document_file_path",
})

def _strip_display_fields_from_evidence(evidence: dict[str, dict]) -> dict[str, dict]:
    """Sanitize evidence dict before writing back to JSONB column.

    Display fields are only valid on the transient `_display` projection.
    Persisting them into the raw JSONB column would cause schema drift on
    re-read (next denormalize pass would re-add fields, growing nested dict
    each request).

    `paper_only_verification` IS a persisted field (set during verify),
    NOT stripped here.
    """
    cleaned = {}
    for code, entry in evidence.items():
        if not isinstance(entry, dict):
            cleaned[code] = entry
            continue
        cleaned[code] = {
            k: v for k, v in entry.items()
            if k not in _EVIDENCE_DISPLAY_ONLY_FIELDS
        }
    return cleaned
```

**Use sites:** Any function mutating `profile.priority_object_evidence` (verify_object_evidence, reject_object_evidence, untick_priority_evidence, manual_override_kv if it touches evidence) MUST call this helper trước assign. Centralize trong service module để consistent.

---

## VII. FE code — read denormalized field

```typescript
// lib/zod/admissions.ts

// WRITE schema — mirror persisted JSONB shape. Used by AdmissionProfileUpdate
// input + raw response field. KHÔNG có display fields để tránh leak qua PATCH.
export const priorityObjectEvidenceEntrySchema = z.object({
  status: z.enum(["pending", "verified", "rejected"]),
  document_id: z.number().int().nullable().optional(),
  verified_by: z.number().int().nullable().optional(),
  verified_at: z.string().datetime({ offset: true }).nullable().optional(),
  reject_reason: z.string().nullable().optional(),
  requested_at: z.string().datetime({ offset: true }).nullable().optional(),
  paper_only_verification: z.boolean().optional(),  // PERSISTED — set by verify service
}).strict()  // strict — block display fields tại boundary

// READ-only display schema — extends write với denormalized fields.
// CHỈ dùng cho priority_object_evidence_display projection.
export const priorityObjectEvidenceDisplayEntrySchema = priorityObjectEvidenceEntrySchema.extend({
  verified_by_name: z.string().nullable().optional(),
  document_file_path: z.string().nullable().optional(),  // S3 path, FE basename extract
}).strict()

// Schema mới cho DocumentsTab Priority section (per G0a):
export const priorityEvidenceDocumentItemSchema = z.object({
  sub_code: z.string(),
  bonus_points: z.number(),
  label: z.string(),
  document_id: z.number().int().nullable(),
  document_file_path: z.string().nullable(),
  status: z.enum(["missing", "uploaded", "verified", "rejected"]),
  verification_status: z.string().nullable(),
})

export const admissionProfileResponseSchema = z.object({
  // ... existing fields ...

  // Raw JSONB — uses WRITE schema (no display leakage)
  priority_object_evidence: z.record(z.string(), priorityObjectEvidenceEntrySchema)
    .default({}),

  // Phase E.4 — denormalized projection uses DISPLAY schema
  priority_object_evidence_display: z.record(z.string(), priorityObjectEvidenceDisplayEntrySchema)
    .nullable().default(null),

  // Phase E.4 — codes có UT ghi nhận nhưng officer chưa scan file
  missing_priority_evidence_codes: z.array(z.string()).default([]),

  // Phase E.4 G0a — server-computed Priority section rows for DocumentsTab
  priority_evidence_documents: z.array(priorityEvidenceDocumentItemSchema).default([]),
})

// Helpers consumed by UtCandidateCards:
function getEvidence(profile: AdmissionProfileResponse) {
  return profile.priority_object_evidence_display ?? profile.priority_object_evidence
}

function getDisplayFilename(filePath: string | null | undefined): string {
  if (!filePath) return ""
  return filePath.split("/").pop() ?? filePath
}

function isMissingFile(profile: AdmissionProfileResponse, subCode: string): boolean {
  return profile.missing_priority_evidence_codes.includes(subCode)
}
```

---

## VIII. Test plan

| Test file | Cases | Notes |
|---|---|---|
| `priority/PriorityHeaderBanner.test.tsx` NEW | 5 cases × 5 state badges + tạm tính text | |
| `priority/PriorityInputsSection.test.tsx` NEW | 6 cases: dropdowns + switch + commune conditional + disabled | |
| `priority/EngineResultCard.test.tsx` NEW | 12 cases: 5 states × happy/admin + law citation display + override dialog trigger | |
| `priority/UtCandidateCards.test.tsx` NEW | 13 cases: verified display + pending verify + missing-doc inline warning + officer disclosure + empty + **untick confirm dialog (cancel preserves file, confirm deletes)** + untick without file skips dialog + paper_only badge render + getDisplayFilename basename extract | |
| `priority/PrioritySummaryPanel.test.tsx` NEW | 6 cases: tổng math + audit disclosure mount + UT pending exclusion from total | |
| `tabs/PriorityTab.test.tsx` UPDATE | 8 cases: compose 4 sections + state propagation | Existing 10 cases có thể keep |
| `tabs/DocumentsTab.test.tsx` UPDATE | 6 NEW cases: priority section render + untick UT hides row + missing_priority_evidence_codes inline warning + upload with category param | |
| `tabs/AdmissionActions.test.tsx` KEEP | Already updated step 9→8 | |
| BE `tests/services/test_admission_service.py` UPDATE | 7 NEW cases (including **critical regression test** below + missing_priority_evidence_codes compute) | |
| BE `tests/services/test_document_service.py` UPDATE | 5 NEW cases: upload with category='priority_evidence' + sub_code happy / wrong category 400 / sub_code not in catalog 400 / category isolation in queries / untick cascade hard delete | |
| BE `tests/services/test_priority_engine.py` UPDATE | 3 NEW cases: rule_law_citation returned in PreviewResponse / all RULE_LAW_CITATION keys covered / law citation matches frozen snapshot | |

### Critical BE regression tests

**Test 1 — display projection isolation (existing):**

```python
async def test_evidence_enrichment_does_not_persist_to_db(db, profile_factory, user_factory):
    """Regression: _populate_response_fields must NOT mutate priority_object_evidence
    JSONB column. Denormalized verified_by_name + document_file_path must live
    on transient `priority_object_evidence_display` attribute only.
    """
    user = await user_factory(full_name="Test Officer")
    profile = await profile_factory(
        priority_object_evidence={
            "04": {"status": "verified", "verified_by": user.id, "document_id": None}
        }
    )

    await _populate_response_fields(db, profile, user)

    # Transient attr populated
    assert hasattr(profile, "priority_object_evidence_display")
    assert profile.priority_object_evidence_display["04"]["verified_by_name"] == "Test Officer"

    # Raw column UNCHANGED (no verified_by_name leak)
    assert "verified_by_name" not in profile.priority_object_evidence["04"]
    assert "document_file_path" not in profile.priority_object_evidence["04"]

    # Commit + reload → verify DB column still clean
    await db.commit()
    await db.refresh(profile)
    assert "verified_by_name" not in profile.priority_object_evidence["04"]
```

**Test 2 — missing_priority_evidence_codes transient isolation (G4 follow-up):**

```python
async def test_missing_codes_does_not_persist_to_db(db, profile_factory, user_factory, document_factory):
    """Regression: missing_priority_evidence_codes là TRANSIENT attribute,
    không có cột tương ứng trên AdmissionProfile. Nếu code path nào lỡ
    persist (vd developer thấy field tên giống cột), commit phải fail
    hoặc field bị mất silent → cả 2 paths đều cần test.
    """
    user = await user_factory()
    profile = await profile_factory(priority_object_codes=["04", "07"])
    # Only UT04 has uploaded doc; UT07 missing → expected ["07"]
    await document_factory(
        profile_id=profile.id,
        category="priority_evidence",
        priority_sub_code="04",
    )

    await _populate_response_fields(db, profile, user)

    # Transient attr populated correctly
    assert profile.missing_priority_evidence_codes == ["07"]

    # Verify it's NOT a tracked column — commit + refresh should not persist
    # (refresh wipes transient Python attrs)
    await db.commit()
    await db.refresh(profile)
    assert not hasattr(profile, "missing_priority_evidence_codes") or \
        getattr(profile, "missing_priority_evidence_codes", None) == [] or \
        getattr(profile, "missing_priority_evidence_codes", None) is None
    # Field must be re-computed on next _populate call, not persisted

    # Verify no column added to admission_profile inspect schema
    from sqlalchemy import inspect
    columns = {c.name for c in inspect(models.AdmissionProfile).columns}
    assert "missing_priority_evidence_codes" not in columns
```

**Test 3 — defensive cleaner strips display fields (G3):**

```python
async def test_strip_display_fields_removes_denormalized():
    """`_strip_display_fields_from_evidence` must remove verified_by_name +
    document_file_path before writing JSONB column, while preserving
    persisted fields (status, verified_by, document_id, paper_only_verification).
    """
    enriched = {
        "04": {
            "status": "verified",
            "verified_by": 15,
            "verified_by_name": "Trịnh Tố Uyên",  # display only
            "document_id": 42,
            "document_file_path": "uploads/admissions/17/x.pdf",  # display only
            "paper_only_verification": False,  # persisted
        }
    }
    cleaned = _strip_display_fields_from_evidence(enriched)
    assert "verified_by_name" not in cleaned["04"]
    assert "document_file_path" not in cleaned["04"]
    assert cleaned["04"]["status"] == "verified"
    assert cleaned["04"]["verified_by"] == 15
    assert cleaned["04"]["document_id"] == 42
    assert cleaned["04"]["paper_only_verification"] is False
```

---

## IX. Implementation order

**Honest estimate:** 22-26h work (~3-3.5 working days realistic). Breakdown reflects B1+B2+B3 upload rework + G1 endpoint + G2 audit + G3 cleaner + cycle 5 additions (P0.1 migration + P0.2 BE step renumber + P0.3 schema split + P0.5 Casbin + G0a priority_evidence_documents).

**Order critical:** P0.2 BE step renumber phải xong CÙNG migration để FE+BE step keys khớp ngay từ phase compile. Tách thành 2 PRs có thể, nhưng anchor matrix tests (memory `test-fixture-drift-after-policy-refactor`) phải update trong cùng PR với BE step change.

```
Hour 0-3: BE foundation + schema
  • Migration profile_document add 2 columns (category VARCHAR(40) DEFAULT 'path',
    priority_sub_code VARCHAR(2) NULL) + CHECK constraint + partial index
  • Migration priority_audit_log: extend ck_priority_audit_log_action_type
    với CẢ 2 action mới: 'ut_evidence_untick' (G1 cascade) +
    'ut_evidence_warning_dismissed' (Decision #2 submit-with-missing-codes audit)
  • Models: ProfileDocument.category + priority_sub_code + drop NOT NULL
    document_type_id + drop existing unique + add 2 partial unique indexes
  • Schemas (split write/display per G3a):
      - PriorityObjectEvidenceEntry (WRITE-only) + paper_only_verification
        field (persisted; NO display fields)
      - PriorityObjectEvidenceDisplayEntry (READ-only NEW) extends write +
        verified_by_name + document_file_path
      - PriorityEvidenceDocumentItem (NEW per G0a)
      - AdmissionProfileResponse +3 fields:
          • priority_object_evidence_display (DISPLAY schema)
          • missing_priority_evidence_codes (list[str])
          • priority_evidence_documents (list[PriorityEvidenceDocumentItem] per G0a)
      - PreviewPriorityKvResponse +rule_law_citation
  • Engine: RULE_LAW_CITATION map + resolve_law_citation()
  • Service utility: _strip_display_fields_from_evidence helper (G3)
  • Service: _populate_response_fields TRANSIENT ATTR assignment
    + defensive try/except cho documents lazy-load (G2)

Hour 3-5: BE upload extension + G2 eager-load audit
  • admission_service.upload_document EXTEND với category + priority_sub_code
    params, preserve ADM-007 staging/finalize tuple return (B2+B3)
  • G2 audit: visit 15+ _populate_response_fields call sites (skip 7147 + 7716),
    add selectinload(AdmissionProfile.documents) hoặc documents= param
  • Router POST /{id}/documents/{doc_code}/upload accept new params (B1)
  • Router POST /{id}/priority-evidence/{sub_code}/upload shortcut
  • Router DELETE /{id}/priority-evidence/{sub_code} (G1 atomic endpoint)
  • verify_object_evidence: lookup category + paper_only_verification flag
  • untick_priority_evidence: new service function với ADM-007 finalize callback

Hour 5-7: BE tests
  • 3 critical regression tests (display projection + missing_codes transient + strip cleaner)
  • upload extension tests (category param happy + wrong category 400 + sub_code validation)
  • untick atomicity tests (S3 fail mid-flight rollback + version guard)
  • G2 regression tests: 3 call sites random sample không throw MissingGreenlet
  • Run full BE test suite: docker compose exec backend pytest -m unit
  • BE smoke via python -c on profile 17

Hour 7-8: FE foundation
  • lib/zod/admissions.ts: split write/display + add PriorityEvidenceDocumentItem
    (1 WRITE-only evidence schema + 1 DISPLAY-only evidence schema + 1 new item
    schema + 3 response fields: priority_object_evidence_display,
    missing_priority_evidence_codes, priority_evidence_documents)
  • lib/api/priority-kv.ts: add rule_law_citation field
  • lib/hooks/use-priority-evidence-upload.ts (NEW mutation)
  • lib/hooks/use-priority-evidence-delete.ts (NEW mutation)
  • Type-check pass

Hour 8-13: FE components (5h, parallel-friendly với 1-1.2h/component)
  • PriorityHeaderBanner (compact 1-dòng) ~1h
  • PriorityInputsSection (§1) ~1h
  • EngineResultCard (§2 — 5 states + law citation) ~1.5h (most complex)
  • UtCandidateCards (§3 display + verify + inline warning + untick dialog) ~1.5h
  • PrioritySummaryPanel (§4) ~1h

Hour 13-14: FE compose + DocumentsTab refactor
  • Rewrite PriorityTab.tsx (compose 4 sections)
  • DocumentsTab.tsx: add Priority section + PriorityEvidenceUploadCell per row
  • DELETE KvDecisionPanel + UtPolicyPanel + PrioritySnapshotCard (audited)
  • Type-check pass

Hour 14-17: Tests
  • 5 new vitest files (banner + inputs + engine + UT cards + summary)
  • PriorityEvidenceUploadCell test
  • Update PriorityTab + DocumentsTab tests
  • Run full vitest suite (target: all green)
  • Pytest critical regression tests + full unit suite again

Hour 17-19: Smoke + push
  • Docker rebuild image
  • Chrome MCP 9 scenarios (7 existing + paper_only badge + inline warning + untick dialog) + tab order verify
  • Per-push approval → git push + PR-E.4

Hour 19-22: CI buffer + debug
  • CI cycle 1-3 (type-check, lint, vitest, build, pytest) — fix nếu fail
  • PR review feedback round
  • Hotfix nếu Chrome smoke surface bug

TOTAL: 22-26h work (~3-3.5 working days realistic)
       Includes B1+B2+B3 upload rework + ADM-007 staging preservation
       + G1 atomic endpoint + G2 eager-load audit 15+ call sites
       + G3 defensive cleaner + G3a schema split + G0 step renumber
       + G0a DocumentsTab contract + cycle 5 P0.1 partial unique migration
       + Casbin policy + extra regression tests
```

---

## X. Pre-push verification checklist

- [ ] `bash scripts/fe-check.sh type-check` — clean
- [ ] `bash scripts/fe-check.sh lint` — 0 errors
- [ ] `bash scripts/fe-check.sh test` — 100% green (~1200 tests)
- [ ] `docker compose exec backend python -m pytest tests/api/test_admission_*.py tests/services/test_admission_service.py tests/services/test_document_service.py tests/services/test_priority_engine.py -v` — clean
- [ ] **Critical BE smoke:** verify `priority_object_evidence` JSONB column unchanged after `_populate_response_fields` + commit (per regression test)
- [ ] BE smoke via `docker compose exec backend python -c "..."` on profile 17 — verify `priority_object_evidence_display['04']['verified_by_name']` non-null + raw `priority_object_evidence['04']` không có `verified_by_name`/`document_file_path`
- [ ] Chrome MCP smoke 7 scenarios:
  1. Officer mở fresh draft → §1 missing → §2 missing-data state → fill cultural → engine resolves
  2. Happy path → 🟢 KV1 + law citation visible + officer verify UT → Continue
  3. Special-case toggle → commune revealed → engine recompute
  4. Officer/admin disclosure → override dialog → 🔧 state after submit
  5. Frozen profile post-submit → 🔒 banner + admin disclosure visible
  6. Engine ambiguous (mock via React Query devtools setting `requires_manual_override=true`) → 🟠 + primary "Chọn KV thủ công"
  7. UT empty → "Hồ sơ chưa ghi nhận diện UT nào" + "Bổ sung diện UT" disclosure
  - **Paper-only verify:** verify UT khi `document_id=null` → audit log có `paper_only_verification=true` + UI badge "Hồ sơ giấy"
  - **Inline warning:** ghi nhận UT07 trên §3 mà chưa upload file → §3 UT07 card hiện "⚠ Thiếu minh chứng" inline + link → Step 6
  - **Untick confirm dialog:** untick UT07 có file → dialog hiện → Huỷ preserves, Confirm hard-deletes
  - **Tab order verify** (Tab key cycle visual top→bottom)
- [ ] DocumentsTab visual: priority section render + missing_priority_evidence inline warning correct
- [ ] Per-push approval xin từ user trước khi `git push`
- [ ] PR description: officer-driven paradigm note + 5 KV states + officer flow estimate + critical BE no-persist pattern + Option A document handling + paper_only_verification framing

---

## XI. Deferred items (post-launch)

| Item | Reason defer | Effort |
|---|---|---|
| "Đảo trạng thái" cho UT đã verified | Hiếm misclick; BE endpoint mới + state-machine reverse + audit cascade | ~3h |
| `original_filename` column trên `profile_document` | Optional fidelity upgrade nếu officer feedback report tên file S3 khó đọc. Backfill từ `document_audit_log`. Hiện tại basename extract đủ dùng. | ~1.5h |
| Measure `paper_only_verification` rate post-launch | Quantify ratio thực tế per-site (trường online vs vùng sâu) qua Sentry/log analytics → confirm Decision #3 stat | ~1h post-launch |
| Soft delete UT docs on untick (30d retention) | Hard delete MVP đủ; soft delete khi officer feedback report mất giấy | ~2h |
| UT search bar | Catalog 7 items không cần; YAGNI per launch-readiness | — |
| Mobile sticky bar + a11y polish | Desktop-only audience | — |
| Sentry breadcrumbs cho priority actions | Post-launch instrumentation theo data-driven | ~1h |
| Audit log full-page view | Currently disclosure last 20 entries | ~2h |
| Schema D extension `priority_object_config.document_type_code` link với document type catalog | Option A đã đủ cho launch; Schema D cải thiện data model | ~4h |
| Auto-binding document upload với UT codes | UX optimization sau khi có officer feedback | ~3h |

---

## XII. Decisions (cần user confirm trước implement)

> Paradigm: Officer nhập tất cả từ hồ sơ giấy candidate đem đến. Không có public portal, không có candidate self-service "khai UT". 5 decisions dưới đây frame quanh **officer data quality + audit trail**, không phải candidate fraud prevention.

1. **Pattern transient attr** — Service set `profile.priority_object_evidence_display = enriched_dict` thay vì mutate JSONB column `priority_object_evidence`. Tránh SQLAlchemy dirty-flag persist denormalized data xuống DB. Match pattern `priority_audit_log` đã ship trong WIP commit `16f9126b`. — **RECOMMEND ✅**

2. **UT evidence inline warning (KHÔNG eligibility gate)** — Khi officer ghi nhận UT code mà chưa attach file PDF, hiển thị inline warning màu cam ngay tại §3 UT card: "⚠ Thiếu minh chứng cho UT07. Mở tab Giấy tờ để upload trước khi submit." KHÔNG block `eligibility_status` ở backend vì lỗi này là officer data-entry quality, không phải candidate fraud. Officer tự chịu trách nhiệm completeness trước khi submit. **Audit trail bổ sung:** khi officer submit hồ sơ mà `missing_priority_evidence_codes` non-empty, INSERT audit row `action_type='ut_evidence_warning_dismissed'` với metadata danh sách codes thiếu file — không block, chỉ track để post-hoc thanh tra. — **RECOMMEND ✅**

3. **Verify với paper_only flag (default case, không phải bypass)** — Officer verify UT cho hồ sơ giấy (không có scan file) là **phần lớn hồ sơ** trong nghiệp vụ VN hiện tại (tỷ lệ thực tế tùy site — trường online cao thấp hơn, trường vùng sâu cao hơn — cần measurement sau launch). Field tên `paper_only_verification` (KHÔNG phải `verified_without_evidence`). UI hiển thị badge "Hồ sơ giấy" thay vì "(admin bypass)" để officer không cảm thấy đang làm sai. Audit log vẫn ghi flag để thanh tra truy được. — **RECOMMEND ✅**

4. **Untick UT cascade với confirm dialog manual** — Officer untick UT code → dialog "Bỏ chọn UT07 sẽ xóa file đính kèm ho_ngheo.pdf. Tiếp tục?" → confirm → hard delete. KHÔNG auto-cascade silent. Soft delete (30d retention) defer Phase E.5 nếu officer report mất giấy do misclick. — **RECOMMEND ✅**

5. **Implementation order BE-first** — Hour 0-3.5 BE foundation + service + test xong → type contract stable → Hour 3.5+ FE bind. Tránh FE refactor giữa chừng khi BE schema thay đổi. — **RECOMMEND ✅**

---

## XIII. Trace decision history

### Option matrix evaluation

| Option | Approach | Pros | Cons |
|---|---|---|---|
| A | DocumentsTab list cả path + UT docs | Single source of truth, batch officer workflow, eligibility gate | DocumentsTab refactor |
| B | Inline upload widget trong PriorityTab §3 | Officer 1-stop verify, candidate inline feedback | Duplicate upload UI, fragmented pool |
| C | Officer chọn document từ pool (dropdown) | Reuse Step 6 storage | Candidate phải upload trước, navigate ngược |
| D | Schema extension `priority_object_config.document_type_code` | Cleanest data model | Schema migration + catalog seed, overkill cho launch |

**Decision: Option A** — DocumentsTab centralization. Match officer batch workflow + eligibility gate + audit cross-check.

### Wireframe iteration

- **v1** — 2-col grid, KV tiles luôn visible, search bar, multiple override paths
- **v2** — 1-col linear, "Đồng ý" button, special-case nested trong override disclosure
- **v3** — Move trình độ sang tab Học tập (rejected — keep ở §1 Step 4 per Q1 answer)
- **v3-final** — Option A DocumentsTab + critical BE bug fix (transient attr) + law citation BE field + reuse `requires_manual_override` flag

### Critical bug fix history

**Audit cycle 1 (2026-05-19, BE service pattern):**

User raised: `profile.priority_object_evidence = enriched` is ORM-tracked column assignment → SQLAlchemy dirty flag → router's `db.commit()` persists denormalized data → schema drift.

Fix: TRANSIENT attribute pattern `profile.priority_object_evidence_display`, matching `priority_audit_log` pattern shipped in WIP commit `16f9126b`.

**Audit cycle 2 (2026-05-19, schema verification):**

User audit caught:
- 🔴 **BUG:** Earlier spec drafts used `models.ProfileDocument.filename` — column không tồn tại. `original_filename` chỉ có trên `DocumentAuditLog`. Per memory [[verify-schema-before-proposing]], must grep model file FIRST.
- 🟠 **GAP:** Spec không nói rõ DocumentsTab Priority section dùng label nào (FE hard-code vs BE join).
- 🟠 **GAP:** Untick UT hard delete file thiếu UX safety guard.
- 🟡 **MINOR:** Time estimate optimistic (11h dev only, không tính CI cycles).
- 🟡 **MINOR:** Migration "downtime ~1 phút" claim wrong — Postgres ≥ 11 instant DDL.

Fixes applied:
- Service code dùng `models.ProfileDocument.file_path` (S3 path) + note FE basename extract. Optional `original_filename` column defer Phase E.5+ nếu officer feedback report tên S3 khó đọc.
- Document `evidence_doc_type` là text sẵn trong DB → DocumentsTab dùng trực tiếp (no FE hard-code, no BE join).
- Untick confirm dialog wireframe + test case (section II §3 + section VIII test plan).
- Time estimate update 11h → 14-15h realistic.
- Migration zero-downtime statement (Postgres ≥ 11 instant DDL).

**Audit cycle 5 (2026-05-20, deeper codebase verification — 5 P0 + 3 P1):**

User hard review caught additional factual mismatches sau cycle 4:

- 🔴 **P0.1 — ProfileDocument constraint conflict:** Model có `document_type_id NOT NULL` + `UniqueConstraint(profile_id, document_type_id)` (line 102, 197). Priority evidence không có ConfigDocumentType FK → upload sẽ fail FK/unique. Fix: drop NOT NULL `document_type_id` + drop existing unique + add 2 partial unique indexes by category (xem Section V Migration).
- 🔴 **P0.2 — BE step model 7-step vs FE 8-step lệch:** BE step_status inline dict (admission_service.py:1126 trong `_compute_completion_percent` + line 1768 trong `_compute_frontend_fields`; step_weights inline line 1136) compute Step 4=Scores, Step 5=Documents. FE Phase E.4 đã 8-step với Step 4=Priority. Badge error mapping wrong tab! Fix: G0 subsection trong Section VI rewrite inline dict + step_weights + sidebar mapping. _Cycle 5b note: spec sửa lại function-name claim sai (`_calculate_step_status` không tồn tại — chỉ là inline dict)._
- 🔴 **P0.3 — Schema reuse risk:** `PriorityObjectEvidenceEntry` reuse trong `AdmissionProfileUpdate.priority_object_evidence` (schemas/admission.py:666). Nếu thêm display fields vào, FE PATCH có thể leak. Fix: G3a subsection — tách 2 schemas write (`PriorityObjectEvidenceEntry`) vs display (`PriorityObjectEvidenceDisplayEntry`).
- 🔴 **P0.4 — Audit action CHECK constraint:** DB hiện chỉ allow 4 action types. Cycle 4 đã add `ut_evidence_untick` cho G1. Cycle 5 phát hiện Decision #2 cũng thêm `ut_evidence_warning_dismissed`. Migration phải mở CHECK cho cả 2.
- 🔴 **P0.5 — Route inconsistency + Casbin gap:** Spec mixed `/api/admissions` vs `/api/v2/admissions/...`. Verify/reject existing endpoints ở `admissions_v2.py:1016+1066` (api/v2 prefix). Chốt canonical: priority-evidence upload/delete TẤT CẢ qua v2 group. Casbin policy_templates.py thêm 2 entries mirror pattern verify/reject (officer/admin allow + accountant deny).
- 🟡 **P1 — DocumentsTab response contract:** `documents_checklist` không có raw `category/priority_sub_code` exposed. Fix: G0a subsection — add NEW field `priority_evidence_documents: list[PriorityEvidenceDocumentItem]` vào AdmissionProfileResponse.
- 🟡 **P1 — Stale name `services/priority_resolution.py`:** Engine ở `services/priority_service.py` (verified ls). Fixed 2 references trong spec.
- 🟡 **P1 — Stale `document_filename`:** Sót 2 chỗ (file plan + section VI comment) sau cycle 4 rename. Fixed.
- 🟡 **P1 — Business overview claim "~17 giây/50%":** Estimate-only, không có baseline data. Added explicit "Note: estimate dựa UX click-count, cần measure post-launch" + reference `Documents/reports/officer_daily_activity_60d.csv` baseline.

**Audit cycle 4 (2026-05-19, factual codebase verification + execution gaps):**

User hard review caught 3 BLOCKER factual errors + 5 implementation gaps:

- 🔴 **B1:** Spec claimed reuse `S3UploadButton` + `useUploadDocument` — không tồn tại trong codebase. Reality: chỉ có generic `FileUpload.tsx` + custom hooks. Phải build `PriorityEvidenceUploadCell` wrapper + 2 new mutation hooks (`use-priority-evidence-upload`, `use-priority-evidence-delete`).
- 🔴 **B2:** Spec claimed extend `services/document_service.py` — không tồn tại. Upload logic ở `admission_service.py::upload_document` (line 4413). Router endpoint `POST /{id}/documents/{doc_code}/upload` (line 824) là `doc_code`-based, không phải `category`-based — phải add new params + new shortcut endpoint.
- 🔴 **B3:** ADM-007 staging/finalize tuple pattern bị bỏ qua. `upload_document` trả về `(profile, finalize_callback)`, router phải commit THEN finalize(True) hoặc finalize(False). Spec phải preserve khi extend.
- 🟠 **G1:** Untick UT atomicity contract chưa rõ. Add new endpoint `DELETE /{id}/priority-evidence/{sub_code}` orchestrate 4 mutations + ADM-007 finalize.
- 🟠 **G2:** `_populate_response_fields` được gọi từ 17 call sites, Phase E.4 iterate `profile.documents` → tất cả phải eager-load để tránh `MissingGreenlet`. Audit 15 call sites + defensive try/except fallback.
- 🟠 **G3:** `PriorityObjectEvidenceEntry` schema có `extra="forbid"` → service mutate JSONB phải strip display fields trước. Helper `_strip_display_fields_from_evidence` centralize logic.
- 🟠 **G4:** Critical regression test bỏ sót `missing_priority_evidence_codes` transient — add Test 2 + Test 3.
- 🟡 **G5:** PrioritySnapshotCard usage audited (5 file, 3 trong DELETE list, 2 component+test) → safe delete confirmed inline.
- 🟡 **M1:** `[[phase-e4-wip-2026-05-19]]` exists in MEMORY.md line 138 (already linked).
- 🟡 **M2:** Time estimate 14-15h lạc quan với B1+B2+B3 rework → bump 18-22h realistic. _(Note: superseded bởi Cycle 5 estimate 22-26h sau khi thêm P0.1/P0.2/P0.5 scope.)_
- 🟡 **M3:** Catalog range UT01-UT07 inconsistent với card UT08 → "UT01-UT08, range theo priority_object_config[year] seed".
- 🟡 **M4:** Hour 10-12 sequence reorder — regression tests trước Chrome MCP để fail-fast.

Decision polish:
- Decision #2: add `ut_evidence_warning_dismissed` audit row khi officer submit với missing codes — không block, chỉ track.
- Decision #3: bỏ stat "~90%" (fabricated), replace "phần lớn hồ sơ" + note "measurement sau launch".

Fixes applied: rewrite Section V file plan (FE upload reality + BE upload extension), add G1/G2/G3 subsections in Section VI, expand test plan với Test 2+3, restructure Section IX với 8-hour phases (Hour 0-3 BE foundation → Hour 3-5 upload extension → Hour 5-7 BE tests → Hour 7-8 FE foundation → Hour 8-13 FE components → Hour 13-14 compose → Hour 14-17 tests → Hour 17-19 smoke → Hour 19-22 CI buffer).

**Audit cycle 3 (2026-05-19, paradigm contamination):**

User raised: 5 decisions ban đầu (Section XII) viết theo **candidate-self-service paradigm** (candidate khai UT → officer verify → block candidate submit). Audit codebase xác nhận paradigm này SAI:

- Không có public portal candidate (no `frontend/src/app/(public)/` route, no `/apply/` group).
- `Backend_FastAPI/app/routers/public_admissions.py` chỉ catalog đọc (programs/methods/tuition), không có form khai.
- `admissions_magic_link.py:30` `MagicLinkAction` enum chỉ 4 giá trị (SUBMIT/RESUBMIT/CONFIRM/WITHDRAW), không có "khai UT".
- `Documents/Q9_07_PR5_REDESIGN.md` Phase F line 756-759 — "Admin backfill tool", officer fill on behalf, KHÔNG phải candidate portal.
- Tất cả `(dashboard)/admissions/[id]/_components/` là officer-protected route.
- "Candidate FE" trong Phase D là misnomer — data subject là candidate, UI user là officer.

Fix: Rewrite Section XII theo **officer-driven paradigm**. Officer nhập tất cả từ hồ sơ giấy candidate đem đến. "Candidate cheating prevention" frame invalid. Thay bằng "officer data quality + audit trail" frame:

- Decision 2: Bỏ eligibility gate (block submit) → inline warning UX-only (`missing_priority_evidence_codes`). Officer tự discipline.
- Decision 3: `verified_without_evidence` → `paper_only_verification` (default case 90% hồ sơ, không phải bypass). UI badge "Hồ sơ giấy" thay "(admin bypass)".
- Section II §3 wireframe: "Candidate đã khai" → "Officer đã ghi nhận"; "Candidate không khai" → "Hồ sơ chưa ghi nhận"; "(admin bypass)" → "(hồ sơ giấy)"; "(admin only, hiếm dùng)" disclosure → "Bổ sung diện UT khác" default mode officer-edit.
- Section VI service code: `original_filename` column approach (cycle 2) reverted → dùng `file_path` trực tiếp + FE basename extract. Optional `original_filename` defer Phase E.5+.
- Pydantic field `document_filename` → `document_file_path` (full S3 path).
- Business Overview Bước 4 + Compliance gate + Trade-off + Giá trị candidate rewrite theo officer paradigm.

---

## XIV. Related memories

- `[[phase-e4-wip-2026-05-19]]` — Foundation commit 16f9126b (audit timeline + zod schema)
- `[[chrome-mcp-pre-push-smoke]]` — Mandatory pre-push smoke
- `[[push-approval-required]]` — Per-push approval (NEVER skip)
- `[[launch-readiness-over-creep]]` — Defer speculative features post-launch
- `[[q9-07-legal-audit-2026-05-18]]` — Legal compliance audit (TT 05/2021 + 27/2017 + Luật GDNN 2025 + Luật Cư trú 2020)
- `[[type-check-container-isolation]]` — Docker image rebuild required for fe-check.sh to see new code

---

**End of spec v3-final.**
