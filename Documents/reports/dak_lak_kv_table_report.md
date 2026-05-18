# Bảng Khu Vực Ưu Tiên Tuyển Sinh — Đắk Lắk (proof of concept)

**Ngày**: 2026-05-18
**Scope**: 102 wards post-sáp nhập 2025 của tỉnh **Đắk Lắk mới** (sáp nhập Đắk Lắk cũ + Phú Yên cũ)
**Mục đích**: Chứng minh pipeline KV classification dùng master Excel MOET + ward_mappings + default rule

---

## I. Quy tắc xác định KV2/KV3/KV2-NT (sau khi đã xác định KV1)

Theo **TT 06/2026/TT-BGDĐT Phụ lục I** (verbatim):

| KV | Định nghĩa | Bonus |
|----|------------|-------|
| **KV1** | Xã DTTS I/II/III + thôn ĐBKK + bãi ngang + biên giới + ATK + CT 135 + đảo | **+0.75** |
| **KV2** | Thị xã/TP thuộc tỉnh + thị xã/huyện ngoại thành TP TƯ (trừ xã KV1) | +0.25 |
| **KV2-NT** | Địa phương không thuộc KV1/KV2/KV3 (rural fallback) | +0.50 |
| **KV3** | Quận nội thành của TP TƯ | 0 |

**Áp dụng post-sáp nhập 2025** (không còn cấp huyện):

```
Đã có KV1 (master Excel)?
├── YES → KV1 (canonical từ MOET file)
└── NO  → áp default rule:
    ├── Tỉnh là TP TƯ (HN/HP/Huế/ĐN/HCM/CT)?
    │   ├── YES + Phường → KV3 (nội thành)
    │   └── YES + Xã     → KV2 (ngoại thành)
    └── Tỉnh thường?
        ├── Phường → KV2 (thị xã/TP thuộc tỉnh)
        ├── Xã     → KV2-NT (rural default)
        └── Đặc khu → check master file (Cô Tô/Phú Quốc/... có thể KV1)
```

**Đắk Lắk** là tỉnh (place_type='Tỉnh', NOT TP TƯ) → chỉ có KV1, KV2, KV2-NT (không có KV3).

---

## II. Pipeline đã chạy

### Inputs

| Source | Rows | Vai trò |
|--------|------|---------|
| Master Excel `2. Danh sach xa KK, ĐBKK 21.5.2025.xls` Sheet1 | 301 (Đắk Lắk + Phú Yên cũ) | KV1 canonical pre-2025 |
| `ward_mappings.sql` filter Đắk Lắk/Phú Yên → Đắk Lắk mới | 286 mappings | old→new crosswalk |
| `wards.sql` filter province_code=66 | 102 wards mới | post-2025 target schema |
| `provinces.sql` lookup '66' | "Đắk Lắk" (Tỉnh) | Determine default rule branch |

### Steps

1. Load master Excel → 301 rows pre-2025 (175 ĐBKK + 126 Khó khăn)
2. Load 286 ward_mappings rows (Đắk Lắk + Phú Yên cũ → Đắk Lắk mới)
3. Normalize Vietnamese names (strip "(trước DATE)" / "(từ DATE)", strip prefix "Xã/Phường/Thị trấn/Huyện/Tỉnh", normalize whitespace + casefold)
4. Match each master row (huyện_norm + xã_norm) ↔ ward_mappings (old_district_norm + old_ward_norm)
5. Apply MAX-rank rule: nếu ANY old xã trong 1 new_ward có loại KK hoặc ĐBKK → new ward = **KV1**
6. Cho ward mới không có old match KK/ĐBKK: apply default rule (Đắk Lắk là TỈNH → Phường=KV2, Xã=KV2-NT)

### Crosswalk metrics

| Metric | Value |
|---|---|
| Master rows matched (in ward_mappings) | **223/301 (74.1%)** |
| KV1 new wards identified | **79/102 (77.5%)** |
| Unmatched master rows | **78** (xem mục V) |

---

## III. Bảng KV phân bố Đắk Lắk mới

| Khu vực | Số wards | % | Bonus |
|---------|----------|---|-------|
| **KV1** | 79 | 77.5% | +0.75 |
| **KV2** | 5 | 4.9% | +0.25 |
| **KV2-NT** | 18 | 17.6% | +0.50 |
| **KV3** | 0 | 0.0% | 0 |
| **TOTAL** | **102** | 100% | |

**Nhận xét**: Phân bố thiên về KV1 (77.5%) hợp lý cho Đắk Lắk + Phú Yên — cả 2 tỉnh đều có nhiều vùng núi DTTS + biên giới + có xã ĐBKK trên diện rộng.

---

## IV. Sample data (full table in `Documents/reports/dak_lak_kv_table.csv`)

### KV1 (79 wards) — sample 5 đầu

| ward_code | ward_name | KV | Số xã cũ mapped |
|-----------|-----------|-----|------------------|
| 22051 | Phường Sông Cầu | KV1 | 2 |
| 22057 | Xã Xuân Lộc | KV1 | 1 |
| 22060 | Xã Xuân Cảnh | KV1 | 3 |
| 22075 | Xã Xuân Thọ | KV1 | 2 |
| 22081 | Xã Đồng Xuân | KV1 | 7 |

### KV2 (5 wards) — Toàn bộ (Phường thuộc tỉnh)

| ward_code | ward_name | KV | Source |
|-----------|-----------|-----|--------|
| 22015 | Phường Tuy Hòa | KV2 | Default: Phường tỉnh |
| 22045 | Phường Bình Kiến | KV2 | Default: Phường tỉnh |
| 22076 | Phường Xuân Đài | KV2 | Default: Phường tỉnh |
| 22240 | Phường Phú Yên | KV2 | Default: Phường tỉnh |
| 22258 | Phường Đông Hòa | KV2 | Default: Phường tỉnh |

### KV2-NT (18 wards) — Toàn bộ (Xã rural)

| ward_code | ward_name | KV |
|-----------|-----------|-----|
| 22114 | Xã Tuy An Bắc | KV2-NT |
| 22250 | Xã Sơn Thành | KV2-NT |
| 22255 | Xã Tây Hòa | KV2-NT |
| 22276 | Xã Hòa Thịnh | KV2-NT |
| 22285 | Xã Hòa Mỹ | KV2-NT |
| 22303 | Xã Phú Hòa 2 | KV2-NT |
| 22319 | Xã Phú Hòa 1 | KV2-NT |
| 24184 | Xã Ea H'Leo | KV2-NT |
| 24301 | Xã Cuôr Đăng | KV2-NT |
| 24310 | Xã Krông Búk | KV2-NT |
| 24313 | Xã Cư Pơng | KV2-NT |
| 24316 | Xã Pơng Drang | KV2-NT |
| 24436 | Xã Cư M'ta | KV2-NT |
| 24445 | Xã Ea Trang | KV2-NT |
| 24538 | Xã Krông Ana | KV2-NT |
| 24559 | Xã Ea Na | KV2-NT |
| 24568 | Xã Dur Kmăl | KV2-NT |
| 24598 | Xã Đắk Phơi | KV2-NT |

---

## V. ⚠ Limitations & verification needed

### V.1 Unmatched 78/301 master rows (25.9%)

Sample unmatched:

| Master row | Lý do likely |
|-----------|--------------|
| Phú Yên / Thành phố Tuy Hòa (Trước 25/1/2017) / Xã An Phú (Trước 25/01/2017) | Pre-2017 admin variant; ward_mappings có thể chỉ cover post-2017 |
| Phú Yên / Thị xã Sông Cầu (Trước 15/3/2022) / Xã Xuân Hòa (Từ 25/01/2017 đến 14/3/2022) | Multiple-date variant không có trong ward_mappings |
| Phú Yên / Huyện Tuy An (Trước 15/3/2022) / Xã An Hải (Trước 01/01/2020) | Triple-version naming |
| Phú Yên / Huyện Sơn Hòa / Xã Ea Chà Rang | Có thể trực tiếp trong wards.sql (no change → no mapping row) |

→ Một số ward hiện tại được gán KV2/KV2-NT có thể **THỰC RA là KV1** nhưng do crosswalk miss. Cần manual verify.

### V.2 KV2 sample sanity check

5 Phường KV2 đều thuộc Tuy Hòa, Đông Hòa, Sông Cầu (Phú Yên) hoặc nội thành thành phố Phú Yên. **Hợp lý** vì đây là thị xã/TP thuộc tỉnh per TT 06/2026.

### V.3 KV2-NT các xã đáng nghi cần verify

Một số xã KV2-NT có tên ám chỉ vùng núi/DTTS có thể THỰC SỰ là KV1:
- `24184 Xã Ea H'Leo` — Ea H'Leo là vùng DTTS lớn — kỳ vọng KV1, hiện KV2-NT ❓
- `24313 Xã Cư Pơng` — Cư Pơng vùng DTTS Tây Nguyên — kỳ vọng KV1 ❓
- `24316 Xã Pơng Drang` — DTTS ❓
- `24445 Xã Ea Trang` — DTTS ❓
- `24598 Xã Đắk Phơi` — DTTS Đắk Lắk ❓

→ Cross-check với 78 unmatched master rows để xem xã name có match không.

### V.4 Edge cases:

1. **Phú Yên province_code không thấy trong provinces.sql post-2025** → master Excel Phú Yên rows được map sang province=66 (Đắk Lắk mới). Verify này đúng theo Nghị quyết 60/2025 sáp nhập.
2. **Hoà Bình vs Hòa Bình** — diacritic alternate spelling — nếu có trong Đắk Lắk thì cần handle. (Đắk Lắk không có)
3. **Apostrophe trong tên** ("Ea H'Leo", "Cư M'gar", "M'Đrắk") — đã handle qua normalize_vn

---

## VI. Hướng improve trước khi scale lên 34 tỉnh

1. **Improve match rate từ 74% → 95%+** bằng:
   - Multi-strategy match: ward_mappings ↔ direct wards.sql lookup ↔ fuzzy match (rapidfuzz token_set_ratio ≥85)
   - Strip multi-date suffix patterns ("(Trước A) (Từ B)" / "(Từ A đến B)" / "(trước/từ DATE1) (Từ DATE2)")
   - Match by huyện-stripped name only nếu match by (huyện + xã) fails
2. **Manual verify queue** cho fuzzy match score 70-85: ~20-30 cases per province
3. **Audit V.3** xã DTTS bị mislabel KV2-NT (thường có tên prefix "Cư/Ea/Krông/Pơng/M'/Đắk")
4. **Cross-validate với 1 file phụ:**
   - `1. Danh sach Quan-Huyen 21.4.2025.xls` — verify huyện hierarchy
5. **Document MAX-rank rule edge cases:**
   - Xã mới hợp từ 5 xã: 3 ĐBKK + 2 không có trong master → KV1 (đúng quy tắc CV 389/UBDT)
   - Xã mới hợp từ 1 phường thị xã + 1 xã ĐBKK miền núi → KV1 (đúng)

---

## VII. Output files

| File | Path | Content |
|------|------|---------|
| CSV | `Documents/reports/dak_lak_kv_table.csv` | 102 rows: ward_code, ward_name, kind, area_code, source_summary |
| JSON | `/tmp/dak_lak_kv_table.json` (in-container) | Full with nested kv1_old_sources |
| Script | `Backend_FastAPI/app/scripts/build_kv_table_dak_lak.py` | Reproducible pipeline |
| Report | `Documents/reports/dak_lak_kv_table_report.md` | This file |

---

## VIII. Trả lời câu hỏi gốc

> **Q: KV2, KV3 và KV2-NT thì xác định như thế nào nếu đã có KV1?**

**A: Theo rule TT 06/2026 Phụ lục I, KHÔNG cần danh sách enumerated cho KV2/KV3/KV2-NT — chúng được xác định bằng** ***rule-based*** **dựa trên:**

1. **Tỉnh có phải TP TƯ không** (6 TP TƯ post-2025: HN/HP/Huế/ĐN/HCM/CT)
2. **Loại đơn vị xã/phường/đặc khu**

```python
def determine_kv(ward_kind, province_is_tp_tu, in_master_kk_dbkk_list):
    if in_master_kk_dbkk_list:
        return "KV1"
    if province_is_tp_tu:
        if ward_kind == "PHUONG": return "KV3"  # quận nội thành
        else:                     return "KV2"  # ngoại thành/đảo
    else:  # tỉnh thường
        if ward_kind == "PHUONG": return "KV2"  # thị xã/TP thuộc tỉnh
        elif ward_kind == "DAC_KHU":
            return "KV2-NT"  # default; verify nếu đặc khu khó khăn
        else:
            return "KV2-NT"  # rural default
```

**Đắk Lắk demonstration**: 102 wards → 79 KV1 (canonical từ MOET) + 5 KV2 (Phường tỉnh default) + 18 KV2-NT (Xã tỉnh default) + 0 KV3 (vì là tỉnh, không có quận nội thành).
