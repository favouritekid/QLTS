# QĐ 861 / TT 05/2021 → KV Commune Mapping — Data Source Research

**Date**: 2026-05-17
**Owner**: solo dev
**Audience**: Q9 #07 PR4 (CSV import for `vn_commune_area_map`)

---

## Critical finding — DON'T rebuild what's already shipped

Repo đã có **3,321 wards post-sáp nhập 1/7/2025** + **34 provinces mới** seeded sẵn:

| File | Rows | Schema |
|------|------|--------|
| `Documents/Seeding data/data province/wards.sql` | 3,321 | `(ward_code VARCHAR(6), name, province_code VARCHAR(2))` — codes from BNV (vd `00025` = Phường Giảng Võ) |
| `Documents/Seeding data/data province/provinces.sql` | 34 | Hà Nội/HCM/Huế/Đà Nẵng/Hải Phòng/Cần Thơ + 28 tỉnh — đã apply Nghị quyết UBTVQH 16/6/2025 |
| `Documents/Seeding data/data province/ward_mappings.sql` | 10,039 | Old→new code mappings (pre→post sáp nhập) |

**Schema mismatch warning**: `wards.sql` dùng `(province_code, ward_code)` 2-tier (no district level vì sáp nhập đã xóa cấp huyện), trong khi `VnCommuneAreaMap` model dùng `(commune_code, province, district, ward)` 4-field text — PR4 sẽ cần map. District field có thể null hoặc derive từ ward_mappings old_district.

→ **Step 1 dataset = JOIN wards.sql với KV classification từ QĐ 861/698**, KHÔNG cần tải lại admin division.

---

## Sources by Priority

### P1 — QĐ 861/QĐ-TTg (2021) — primary KV I/II/III source

- **Source PDF**: <https://vanban.chinhphu.vn/?pageid=27160&docid=203373> (WebFetch denied — robots/auth)
- **Best alternate mirror**: <https://luatvietnam.vn/chinh-sach/quyet-dinh-861-qd-ttg-danh-sach-cac-xa-khu-vuc-iii-ii-i-2021-2025-203245-d1.html> — **HTML table inline, parseable** (verified 50 rows extracted, sample below)
- **Backup**: <https://thuvienphapluat.vn/van-ban/Van-hoa-Xa-hoi/Quyet-dinh-861-QD-TTg-2021-danh-sach-cac-xa-III-II-I-vung-dong-bao-dan-toc-thieu-so-mien-nui-476885.aspx> — also has HTML tables
- **Coverage**: 3,434 xã ở 51 tỉnh (cũ — pre-sáp nhập 2021), 1,673 KV I + 210 KV II + 1,551 KV III
- **Caveat**: Districts/wards là **tên cũ** trước sáp nhập 2025 → phải fuzzy-match với `wards.sql` (post-sáp nhập tên mới) qua `ward_mappings.sql` (old→new code) — đây là lý do `ward_mappings.sql` 10k rows tồn tại trong repo

### P2 — QĐ 698/QĐ-TTg (19/7/2024) — amendment

- **Source**: <https://vanban.chinhphu.vn/?pageid=27160&docid=210708>
- **Alternate**: <https://thuvienphapluat.vn/van-ban/Van-hoa-Xa-hoi/Quyet-dinh-698-QD-TTg-2024-dieu-chinh-danh-sach-xa-khu-vuc-III-vung-dan-toc-thieu-so-mien-nui-618054.aspx>
- **Changes**: Add 2 thị trấn vào KV I (TT Yên Sơn-Tuyên Quang, TT Quân Chu-Thái Nguyên) + xã Mường Báng (Tủa Chùa, Điện Biên) KV II → KV III + 2 deletions from KV I. Diff << 1% — apply as patch sau base import QĐ 861.

### P3 — QĐ 353/QĐ-TTg (15/3/2022) — coastal/island disadvantaged

- **Source**: <https://thuvienphapluat.vn/van-ban/Van-hoa-Xa-hoi/Quyet-dinh-353-QD-TTg-2022-phe-duyet-Danh-sach-huyen-ngheo-vung-bai-ngang-ven-bien-506772.aspx>
- **Coverage**: 74 huyện nghèo + 54 xã đặc biệt khó khăn vùng bãi ngang ven biển hải đảo ở 12 tỉnh — bổ sung KV1 cho tuyển sinh
- **Status**: ~54 rows extra, low priority Stage 1

### P4 — TT 06/2026/TT-BGDĐT — 2026 university admission regulation

- **Source**: <https://baochinhphu.vn/bo-gddt-chot-quy-dinh-tuyen-sinh-dai-hoc-2026-102260505095923563.htm>
- **Issued**: 15/02/2026
- **Confirms**: KV1=0.75, KV2-NT=0.50, KV2=0.25, KV3=0 (đã match seed plan trong `phase1_08b`)
- **CRITICAL**: Phụ lục I định nghĩa criteria, NHƯNG **không list xã cụ thể** → vẫn phải reference QĐ 861/698 + QĐ 353 + danh sách phường nội thành TP TW
- **Post-01/07/2025 phân quyền UBND tỉnh ban hành QĐ riêng giai đoạn 2026-2030** → roadmap vẫn pending province-level revisions

### P5 — Open-data fallbacks

- <https://danhmuchanhchinh.gso.gov.vn/> — GSO catalog, có "Xuất Excel" button (lookup district/ward, NO KV classification)
- <https://github.com/ThangLeQuoc/vietnamese-provinces-database> — v3.0.2 (20/7/2025), post-merger, has `code`, **KHÔNG có KV** field — confirmed via WebFetch
- <https://github.com/daohoangson/dvhcvn> — 3-level admin JSON, **KHÔNG có KV** — confirmed

→ **Không có dataset open-source nào pre-joined KV + commune.** Phải tự build.

---

## Sample data — verified extraction từ luatvietnam.vn (50 rows)

```csv
province,district,ward,area_code,source
An Giang,Tri Tôn,Thị trấn Tri Tôn,KV1,QĐ861
An Giang,Tri Tôn,Xã An Tức,KV1,QĐ861
An Giang,Tri Tôn,Xã Ô Lâm,KV1,QĐ861
An Giang,Tri Tôn,Xã Cô Tô,KV1,QĐ861
An Giang,Tri Tôn,Xã Châu Lăng,KV1,QĐ861
An Giang,Tri Tôn,Xã Lương Phi,KV1,QĐ861
An Giang,Tri Tôn,Xã Lê Tri,KV1,QĐ861
An Giang,Tri Tôn,Xã Núi Tô,KV1,QĐ861
An Giang,Tịnh Biên,Xã An Cư,KV1,QĐ861
An Giang,Tịnh Biên,Xã Văn Giáo,KV1,QĐ861
An Giang,Tịnh Biên,Xã An Hảo,KV1,QĐ861
An Giang,Tịnh Biên,Xã Tân Lợi,KV1,QĐ861
An Giang,Tịnh Biên,Xã Vĩnh Trung,KV1,QĐ861
An Giang,An Phú,Xã Nhơn Hội,KV1,QĐ861
An Giang,Tân Châu,Xã Châu Phong,KV1,QĐ861
An Giang,Thoại Sơn,Thị trấn Óc Eo,KV1,QĐ861
Bắc Giang,Lạng Giang,Xã Hương Sơn,KV1,QĐ861
Bắc Giang,Lạng Giang,Xã Yên Mỹ,KV1,QĐ861
Bắc Giang,Lạng Giang,Xã Hương Lạc,KV1,QĐ861
Bắc Giang,Sơn Động,Thị trấn An Châu,KV1,QĐ861
```

> NOTE: TT 06/2026 KV I/II/III của QĐ 861 đều = **KV1 tuyển sinh** (đều thuộc "vùng đồng bào dân tộc thiểu số và miền núi"). Không phải mapping I→KV1, II→KV2, III→KV3 — đây là common confusion. KV1 = ưu tiên cao nhất bonus 0.75.

---

## Mapping rules — QĐ 861 KV → TT 06/2026 KV tuyển sinh

| QĐ 861 zone | Meaning | TT 06/2026 area_code | Bonus |
|-------------|---------|---------------------|-------|
| KV I (an toàn) | Xã miền núi DTTS bước đầu phát triển | **KV1** | 0.75 |
| KV II (khó khăn) | Xã miền núi DTTS còn khó khăn | **KV1** | 0.75 |
| KV III (đặc biệt khó khăn) | Xã miền núi DTTS đặc biệt khó khăn | **KV1** | 0.75 |
| QĐ 353 xã bãi ngang | Đặc biệt khó khăn coastal | **KV1** | 0.75 |
| Phường nội thành TP TW (HN, HCM, HP, ĐN, Cần Thơ, Huế) | Inner-city | **KV3** | 0 |
| Phường thuộc TX/TP trực thuộc tỉnh + xã ngoại thành TP TW | Thị xã/TP cấp tỉnh | **KV2** | 0.25 |
| Tất cả xã còn lại | Nông thôn không-KV1 | **KV2-NT** | 0.50 |

→ Algorithm: default `KV2-NT` cho mọi xã không-classification, sau đó override theo 3 list (QĐ 861 → KV1, QĐ 353 → KV1, phường nội thành TP TW → KV3, phường khác/xã ngoại thành TP TW → KV2).

---

## Recommended approach (Top-1)

**Approach A — Hybrid join** (recommended):

1. **Base** = `wards.sql` 3,321 rows post-merger 2025 (already in repo)
2. **Default** all wards → `area_code = 'KV2-NT'`
3. **Extract** QĐ 861 + 698 (~3,434 rows) từ luatvietnam.vn HTML (continue WebFetch in 50-row chunks)
4. **Extract** QĐ 353 ~54 xã bãi ngang
5. **Override** phường nội thành 5-6 TP TW → `KV3` (Hà Nội, HCM, Hải Phòng, Đà Nẵng, Cần Thơ, Huế — derive từ province_code + name LIKE 'Phường%')
6. **Override** phường/xã thuộc TP cấp tỉnh → `KV2`
7. **Fuzzy-match** pre-2025 xã names trong QĐ 861 với post-2025 ward_code via `ward_mappings.sql` old→new mapping. Confidence threshold + manual review queue
8. **Output**: CSV `commune_code, province, district, ward, area_code, effective_from_year, source` ready for PR4 import

**Effort estimate**:
- Extract QĐ 861 từ HTML (3,434 rows, ~70 chunks × 50 rows): ~3h scripted WebFetch
- Extract QĐ 353 (~54 rows): ~15 min
- Build default + TP TW override: ~30 min SQL
- Fuzzy match old→new commune via ward_mappings: ~2h (Levenshtein/trigram, manual review ~5% edge cases)
- QA verification sample 50 rows: ~30 min
- **Total Stage 1: 6-7 hours actual work, ship within 1 day**

**Fallback if WebFetch rate-limited**:
- Manual paste full HTML tables of QĐ 861 từ luatvietnam.vn vào file local (đã verified inline table format)
- Or screenshot+OCR (lower confidence, NOT recommended)

---

## Top-10 priority provinces (data-entry fallback)

Nếu Approach A blocked, manual entry theo volume:

| Rank | Province | Reason | Est commune count |
|------|----------|--------|-------------------|
| 1 | Hà Nội | Capital, TP TW, big enrollment | 526 |
| 2 | HCM | TP TW, largest enrollment | 273 |
| 3 | Hải Phòng | TP TW | 167 |
| 4 | Đà Nẵng | TP TW | 94 |
| 5 | Cần Thơ | TP TW | 103 |
| 6 | Huế | TP TW (mới 2026) | 133 |
| 7 | Thanh Hóa | Province, large DTTS + bãi ngang | 166 |
| 8 | Nghệ An | Largest geographic + DTTS | 130 |
| 9 | Đồng Nai | Bordering HCM, high migration | 95 |
| 10 | Hà Tĩnh | DTTS + bãi ngang | 69 |

→ TP TW (1-6) = ~1,296 communes, mostly KV2/KV3 → can be done quickly (default → KV3 cho phường, KV2 cho xã). 7-10 = ~460 communes mix → manual review.

---

## Schema verification — MOET school code format

**Question**: `(moet_province_code, moet_school_code)` composite unique?

**Answer**: **YES, confirmed via Q9_07_PR5_REDESIGN.md** line 84-87:

```sql
CREATE UNIQUE INDEX uq_vn_school_moet_code_active
    ON vn_school(moet_province_code, moet_school_code)
    WHERE is_active = true;
```

MOET issues mỗi tỉnh 1 namespace school code → tuple unique GLOBAL. Format: province (3 chars) + school (variable, typically 5-7 chars numeric). Reference file `3. Danh sach trường THPT 21.4.2025.xls` mentioned in Q9_07 plan as canonical seed; need separate import script (NOT in scope this research). Sample provincial files may be available via MOET portal nhưng KHÔNG có public Excel download URL surface trong search — likely needs phone request to Sở GD&ĐT.

---

## Next actions

1. ✅ Research done — sources identified, samples verified
2. 🟡 PR4-prep: Write Python script in `Backend_FastAPI/scripts/build_kv_dataset.py` that:
   - Loads `wards.sql` (3,321 rows)
   - Loads `ward_mappings.sql` (old→new mapping)
   - Fetches luatvietnam.vn HTML in chunks (50 rows × 70 = 3,500 total target)
   - Parses + fuzzy-matches old commune name → new ward_code
   - Outputs `Backend_FastAPI/app/seed/vn_commune_kv.csv` for PR4 import
3. 🟡 Manual review queue: ~5% edge cases (split/merge ambiguities) → admin spreadsheet
4. 🔴 Stage 2 deferred: per-province UBND QĐ giai đoạn 2026-2030 (rolling out 2026-2027) — handle via admin CRUD UI in PR5 onwards

---

## Open questions for user

1. Tách-rời commune codes của xã/phường mới sau sáp nhập 2025 dùng BNV-issued 5-digit ward_code (`00025`, `00070`) hay dùng tên tỉnh+ward concatenation cho `commune_code` trong `VnCommuneAreaMap`? Schema cho `commune_code VARCHAR(20)` — recommend dùng BNV 5-digit prefix với province để có 7-digit canonical key (vd `01_00025`).
2. Default value `KV2-NT` cho mọi commune không có classification — accept? (Conservative: candidate KHÔNG được bonus error-of-favor; risk: mới sinh sống TP nhưng schema chưa override KV3 sẽ được +0.5đ sai)
3. PR4 import có cần admin manual review queue front-load không, hay accept fuzzy-match confidence ≥ 0.9 auto-apply + < 0.9 hold queue?
