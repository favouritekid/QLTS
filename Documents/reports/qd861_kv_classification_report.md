# Bảng phân loại Khu vực ưu tiên tuyển sinh (KV1) theo 3 văn bản canonical DTTS

**Ngày báo cáo**: 2026-05-18
**Scope điều tra**: QĐ 861/QĐ-TTg 2021 + QĐ 612/QĐ-UBDT 2021 + QĐ 497/QĐ-UBDT 2024
**Mục đích**: Lookup canonical KV ưu tiên tuyển sinh ĐH/CĐ năm 2026 cho candidate đăng ký vào QLTS
**Status**: Phần I (Quy tắc + Hierarchy) đầy đủ. Phần II (Master dataset 3,434 xã) chưa extract — cần multi-chunk WebFetch hoặc download PDF

---

## I. Quy tắc cốt lõi (canonical, đã verify)

### I.1 Mapping rule QĐ 861 → KV tuyển sinh

Theo **Thông tư 06/2026/TT-BGDĐT Phụ lục I** (trích nguyên văn):

> "**KV1**: Các xã khu vực I, II, III và các xã có thôn đặc biệt khó khăn thuộc vùng dân tộc và miền núi; các xã đặc biệt khó khăn vùng bãi ngang ven biển và hải đảo; các xã đặc biệt khó khăn, xã biên giới, xã an toàn khu vào diện đầu tư của Chương trình 135"

| QĐ 861 zone | Áp KV tuyển sinh | Điểm cộng |
|-------------|------------------|-----------|
| KV I (xã miền núi DTTS bước đầu phát triển) | **KV1** | +0.75 |
| KV II (xã miền núi DTTS còn khó khăn) | **KV1** | +0.75 |
| KV III (xã miền núi DTTS đặc biệt khó khăn) | **KV1** | +0.75 |
| Xã có **thôn ĐBKK** thuộc QĐ 612/497 | **KV1** | +0.75 |

**Critical**: Cả 3 KV I/II/III của QĐ 861 đều áp **KV1 tuyển sinh** (0.75đ). KHÔNG phải mapping 1↔KV1, 2↔KV2, 3↔KV3 như misconception thường gặp.

### I.2 Bảng KV ưu tiên tuyển sinh đầy đủ (TT 06/2026)

| KV tuyển sinh | Định nghĩa | Bonus | Source xác định |
|--------------|------------|-------|----------------|
| **KV1** | Xã KV I/II/III DTTS + xã có thôn ĐBKK + xã ĐBKK bãi ngang + xã biên giới + xã ATK + xã CT 135 + xã đảo | +0.75 | QĐ 861/612/497 + QĐ 353/2023 + QĐ 2405 + 14 QĐ đảo + 10 QĐ ATK |
| **KV2-NT** | Xã/Phường không thuộc KV1, KV2, KV3 (nông thôn nói chung) | +0.50 | Default fallback |
| **KV2** | Thị xã, thành phố trực thuộc tỉnh; thị xã/huyện ngoại thành của TP TƯ (trừ xã KV1) | +0.25 | place_type='Thành phố' của tỉnh hoặc Phường tỉnh; ngoại thành TP TƯ |
| **KV3** | Quận nội thành của thành phố trực thuộc Trung ương | 0 | Phường + nội thành 6 TP TƯ (HN/HP/Huế/ĐN/HCM/CT) |

### I.3 Quy tắc post-sáp nhập 2025 (Công văn 389/UBDT-CSDT 30/3/2020 + CV 2457/BGDĐT/2025)

- **CV 389/UBDT**: "Đơn vị mới sau sáp nhập áp chính sách CAO NHẤT của các đơn vị trước sắp xếp" → KV1 + KV3 sáp nhập → áp KV1
- **CV 2457/BGDĐT 19/5/2025**: KV của candidate xác định theo **trường THPT pre-merger** (`vn_school_kv_assignment`), KHÔNG theo xã thường trú sau sáp nhập → bảng `vn_commune_area_map` chỉ phục vụ **4 special cases TT 05/2021** (PT DTNT/lớp dự bị/quân nhân/xuất ngũ)

---

## II. Vai trò của 3 văn bản canonical

| Văn bản | Ngày | Cấp | Số đơn vị | Status hiệu lực 2026 | Vai trò trong KV1 |
|---------|------|-----|-----------|---------------------|------------------|
| **QĐ 861/QĐ-TTg** | 04/6/2021 | **Cấp XÃ** | 3,434 xã KV I/II/III + 51 tỉnh pre-2025 | Hiệu lực 2021-2025 (chưa có QĐ thay thế cho 2026) | **Primary** — gốc 100% xã DTTS đều KV1 |
| **QĐ 612/QĐ-UBDT** | 16/9/2021 | **Cấp THÔN** | 13,222 thôn ĐBKK + ~52 tỉnh | Hiệu lực 2021-2025 | **Supplement** — thôn cụ thể trong xã KV II/I + xã có thôn DTTS |
| **QĐ 497/QĐ-UBDT** | 30/7/2024 | **Cấp THÔN** | Amend QĐ 612: xóa 440 thôn ở 163 xã + thêm 141 thôn ở 98 xã + đổi tên + thêm mới 755 thôn ở 460 xã | Hiệu lực 2024-2025 | **Amendment** — patch QĐ 612 do sáp nhập/giải thể/đổi tên |

**⚠ Critical**: QĐ 497 amend QĐ 612 (cấp thôn), **KHÔNG** amend QĐ 861 (cấp xã). Phần xã KV I/II/III của QĐ 861 vẫn nguyên trạng (chưa có amendment cấp xã chính thức cho giai đoạn 2021-2025).

---

## III. Cấu trúc data extract được (partial)

### III.1 QĐ 861 — Phụ lục I

- 1 phụ lục duy nhất: "TỔNG HỢP DANH SÁCH CÁC XÃ KHU VỰC III, II, I VÙNG DTTS GIAI ĐOẠN 2021-2025"
- 51 bảng con (mỗi tỉnh 1 bảng), sắp xếp theo Tỉnh → Huyện → Xã
- Cột "Thuộc khu vực" hiển thị I / II / III
- KHÔNG có mã định danh (mã tỉnh/mã xã) → cần fuzzy match với BNV codes
- **3,434 xã**: 1,673 KV I + 210 KV II + 1,551 KV III

**Sample 20 row đầu (An Giang + Bắc Giang) — đã extract:**

| Tỉnh (2021) | Huyện (2021) | Xã (2021) | Khu vực |
|------------|-------------|----------|---------|
| An Giang | Tri Tôn | Thị trấn Tri Tôn | I |
| An Giang | Tri Tôn | Xã An Tức | III |
| An Giang | Tri Tôn | Xã Ô Lâm | III |
| An Giang | Tri Tôn | Xã Cô Tô | I |
| An Giang | Tri Tôn | Xã Châu Lăng | III |
| An Giang | Tri Tôn | Xã Lương Phi | I |
| An Giang | Tri Tôn | Xã Lê Tri | III |
| An Giang | Tri Tôn | Xã Núi Tô | III |
| An Giang | Tịnh Biên | Xã An Cư | III |
| An Giang | Tịnh Biên | Xã Văn Giáo | III |
| An Giang | Tịnh Biên | Xã An Hảo | I |
| An Giang | Tịnh Biên | Xã Tân Lợi | I |
| An Giang | Tịnh Biên | Xã Vĩnh Trung | I |
| An Giang | An Phú | Xã Nhơn Hội | I |
| An Giang | Thị Xã Tân Châu | Xã Châu Phong | I |
| An Giang | Thoại Sơn | Thị trấn Óc Eo | I |
| Bắc Giang | Lạng Giang | Xã Hương Sơn | I |
| Bắc Giang | Lạng Giang | Xã Yên Mỹ | I |
| Bắc Giang | Lạng Giang | Xã Hương Lạc | I |
| Bắc Giang | Sơn Động | Thị trấn An Châu | II |

**Thứ tự 51 tỉnh xuất hiện (cho extraction batching):**

1. Vĩnh Phúc, 2. Hà Nội, 3. Quảng Ninh, 4. Hải Dương, 5. Ninh Bình, 6. Hà Giang, 7. Cao Bằng, 8. Bắc Kạn, 9. Tuyên Quang, 10. Lào Cai, 11. Yên Bái, 12. Thái Nguyên, 13. Lạng Sơn, 14. Bắc Giang, 15. Phú Thọ, 16. Điện Biên, 17. Lai Châu, 18. Sơn La, 19. Hòa Bình, 20. Thanh Hóa, 21. Nghệ An, 22. Quảng Bình, 23. Quảng Trị, 24. Thừa Thiên Huế, 25. Đà Nẵng, 26. Quảng Nam, 27. Quảng Ngãi, 28. Bình Định, 29. Phú Yên, 30. Khánh Hòa, 31. Ninh Thuận, 32. Bình Thuận, 33. Kon Tum, 34. Gia Lai, 35. Đắk Lắk, 36. Đắk Nông, 37. Lâm Đồng, 38. Bình Dương, 39. Bình Phước, 40. Tây Ninh, 41. Đồng Nai, 42. Bà Rịa - Vũng Tàu, 43. Trà Vinh, 44. Vĩnh Long, 45. An Giang, 46. Kiên Giang, 47. Cần Thơ, 48. Hậu Giang, 49. Sóc Trăng, 50. Bạc Liêu, 51. Cà Mau

### III.2 QĐ 612 — Phụ lục cấp thôn

⚠ **Limitation từ thuvienphapluat HTML**: Chỉ hiển thị **bảng tổng hợp cấp tỉnh** (tỉnh × tổng thôn), KHÔNG hiển thị 13,222 thôn cụ thể. Full data 13k thôn phải lấy từ file PDF gốc.

**Sample 20 tỉnh đầu (đã extract — cấp tổng hợp):**

| TT | Tỉnh | Tổng thôn | Thôn ở xã DTTS&MN | Thôn ở xã KV I | Thôn ở xã KV II | Thôn ở xã KV III |
|----|-----|-----------|-------------------|---------------|----------------|------------------|
| 1 | Quảng Ninh | 12 | 0 | 12 | 0 | 0 |
| 2 | Hà Giang | 1,353 | 0 | 46 | 35 | 1,272 |
| 3 | Cao Bằng | 996 | 0 | 28 | 19 | 949 |
| 4 | Bắc Kạn | 648 | 0 | 35 | 30 | 583 |
| 5 | Tuyên Quang | 570 | 1 | 56 | 63 | 450 |
| 6 | Lào Cai | 605 | 3 | 103 | 24 | 475 |
| 7 | Yên Bái | 382 | 0 | 30 | 25 | 327 |
| 8 | Thái Nguyên | 142 | 1 | 22 | 27 | 92 |
| 9 | Lạng Sơn | 644 | 0 | 84 | 24 | 536 |
| 10 | Bắc Giang | 244 | 0 | 25 | 41 | 178 |
| 11 | Phú Thọ | 240 | 4 | 37 | 29 | 170 |
| 12 | Điện Biên | 954 | 0 | 37 | 20 | 897 |
| 13 | Lai Châu | 559 | 0 | 87 | 14 | 458 |
| 14 | Sơn La | 1,449 | 0 | 66 | 38 | 1,345 |
| 15 | Hòa Bình | 507 | 0 | 38 | 48 | 421 |
| 16 | Thanh Hóa | 318 | 1 | 101 | 84 | 132 |
| 17 | Nghệ An | 588 | 6 | 32 | 0 | 550 |
| 18 | Hà Tĩnh | 2 | 2 | 0 | 0 | 0 |
| 19 | Quảng Bình | 102 | 3 | 0 | 5 | 94 |
| 20 | Quảng Trị | 187 | 9 | 3 | 4 | 171 |

### III.3 QĐ 497 — 4 phụ lục amendment

| Phụ lục | Tên | Quy mô |
|---------|-----|--------|
| **PL I** | Điều chỉnh xóa thôn | 440 thôn ở 163 xã (do sáp nhập/giải thể hoặc thoát ĐBKK) |
| **PL II** | Bổ sung thôn mới | 141 thôn ở 98 xã (do chia tách, sáp nhập, thành lập mới) |
| **PL III** | Hiệu chỉnh tên | Đổi tên thôn (vd "Ấp Tô An"→"Khóm Tô An", "Bản Sin Chải"→"Bản Xin Chải") |
| **PL IV** | Phê duyệt mới | 755 thôn ở 460 xã thuộc vùng DTTS&MN |

**Tỉnh ảnh hưởng nhiều**:
- Sơn La: 85 xã / 264 thôn xóa + 60 xã / 93 thôn thêm
- Đắk Lắk: 37 xã / 90 thôn xóa + 19 xã / 24 thôn thêm
- Lạng Sơn: 27 xã / 53 thôn xóa + 12 xã / 17 thôn thêm

---

## IV. Gap chưa được 3 link cover (cần thêm văn bản khác cho KV1 đầy đủ)

3 văn bản user cho là **scope DTTS miền núi**. KV1 tuyển sinh còn bao gồm 3 nhóm khác **chưa có canonical source trong 3 link**:

| Nhóm KV1 | Văn bản canonical | Note |
|---------|-------------------|------|
| **Bãi ngang ven biển + hải đảo** | QĐ 353/QĐ-TTg 15/3/**2023** (54 xã) + 14 QĐ công nhận xã đảo riêng từng tỉnh (Kiên Giang QĐ 2311/2015, QĐ 164/2021; Hải Phòng QĐ 1859/2017; Khánh Hòa QĐ 2312/2015...) | Liên quan trực tiếp Đặc khu hiện tại |
| **Xã biên giới + CT 135** | QĐ 2405/QĐ-TTg 10/12/2013 + QĐ 900/QĐ-TTg 20/6/2017 (giai đoạn 2017-2020) | Có thể overlap với QĐ 861 |
| **Xã An toàn khu (ATK)** | 10 QĐ riêng từng tỉnh (QĐ 121/2018 Ninh Bình; QĐ 2475/2016 Lạng Sơn; QĐ 235/2019 Sóc Trăng; QĐ 1614/2018 Ninh Thuận; QĐ 164/2017 Quảng Nam; QĐ 164/2021 Kiên Giang; QĐ 270/2023 Sóc Trăng; QĐ 1803/2019 Bắc Kạn) | Subset nhỏ, ~100-200 xã |

---

## V. Strategy extract full master dataset 3,434 xã từ QĐ 861

### V.1 Source options ranked theo reliability

| Source | URL | Reliability | Free | Bottleneck |
|--------|-----|------------|------|-----------|
| vanban.chinhphu.vn `861.signed.pdf` | https://vanban.chinhphu.vn/?pageid=27160&docid=203373 | ★★★★★ (canonical) | ✅ | PDF image — cần OCR/pdfplumber |
| thuvienphapluat HTML | (đã fetch) | ★★★★ (mirror, có quảng cáo) | ✅ | Truncate sau ~5 tỉnh/fetch |
| luatvietnam DOC | https://luatvietnam.vn/...203245-d1.html | ★★★ (mirror) | ❌ paywall login | DOC file |
| accgroup.vn HTML | https://accgroup.vn/phu-luc-quyet-dinh-861-qd-ttg | ★★ (unofficial) | ✅ | Unverified transcription |

### V.2 Approach đề xuất (theo effort)

**Approach A — Multi-chunk thuvienphapluat (8-12h)**:
1. Spawn 5-7 parallel agents, mỗi agent fetch 1 chunk ~10 tỉnh
2. Mỗi agent dùng prompt khác nhau (anchor by province name) để force WebFetch trả different segment
3. Reconcile output thành single CSV ~3,434 rows
4. Risk: HTML mirror có thể có transcription errors so với PDF gốc

**Approach B — Download PDF + pdfplumber (4-6h)**:
1. Download `861.signed.pdf` từ vanban.chinhphu.vn (free, no login)
2. Local Python script: pdfplumber extract tables → CSV
3. Manual cleanup ~5% edge cases (merged cells, footnotes)
4. Risk: PDF có thể image-based → cần OCR (Tesseract) → diacritics accuracy drop

**Approach C — Hybrid (6-8h, RECOMMENDED)**:
1. Download PDF từ vanban.chinhphu.vn (master truth)
2. Parallel: extract HTML từ thuvienphapluat (cross-check)
3. Compare 2 sources → flag discrepancies → manual reconcile
4. Output: high-confidence CSV với `source_verified` column (T nếu match cả 2)

### V.3 Output schema dự kiến

```csv
commune_code_2021, province_2021, district_2021, ward_2021, zone_qd861, source_decision, effective_from, notes
```

Sau crosswalk với BNV codes 2025 + apply MAX-rank rule:

```csv
commune_code_2025, province_2025, ward_2025, area_code, sources, effective_from, fuzzy_match_confidence
```

Where `sources` = JSON list (vd `["QĐ 861/2021 KV I", "Sáp nhập merge 3 xã"]`)

---

## VI. Recommend next step (chờ user quyết định)

1. **Decide scope final**: Chỉ DTTS (3 link user cho) hay extend → bao gồm bãi ngang + biên giới + ATK?
2. **Decide approach extraction**: A (HTML chunks) vs B (PDF) vs C (hybrid)
3. **Decide priority**: Stage 1A (heuristic CSV draft) DISCARD ngay, hay keep làm reference cho fuzzy match?
4. **Decide schema**: bảng `vn_commune_area_map` (4 special cases TT 05/2021) là target chính, HOẶC chuyển sang ưu tiên `vn_school_kv_assignment` (Phase B.1 MOET schools cho candidate thường)?

---

## Citations

- QĐ 861/QĐ-TTg 04/6/2021: https://thuvienphapluat.vn/van-ban/van-hoa-xa-hoi/quyet-dinh-861-qd-ttg-2021-danh-sach-cac-xa-iii-ii-i-vung-dong-bao-dan-toc-thieu-so-mien-nui-476885.aspx
- QĐ 612/QĐ-UBDT 16/9/2021: https://thuvienphapluat.vn/van-ban/van-hoa-xa-hoi/quyet-dinh-612-qd-ubdt-2021-danh-sach-cac-thon-dac-biet-kho-khan-vung-dong-bao-dan-toc-thieu-so-489509.aspx
- QĐ 497/QĐ-UBDT 30/7/2024: https://thuvienphapluat.vn/van-ban/van-hoa-xa-hoi/quyet-dinh-497-qd-ubdt-2024-dieu-chinh-va-hieu-chinh-ten-huyen-xa-thon-dac-biet-kho-khan-620013.aspx
- TT 06/2026/TT-BGDĐT 15/2/2026: https://thuvienphapluat.vn/phap-luat/khu-vuc-uu-tien-la-gi-ky-hieu-khu-vuc-uu-tien-2026-cac-khu-vuc-duoc-cong-diem-uu-tien-2026-theo-tho-690650-265089.html
- CV 389/UBDT-CSDT 30/3/2020: https://thuvienphapluat.vn/cong-van/van-hoa-xa-hoi/cong-van-389-ubdt-csdt-2020-huong-dan-thuc-hien-che-do-chinh-sach-dan-toc-438967.aspx
