# RUNBOOK — Hoàn thiện DOT_2 kỳ tuyển sinh 2026 (production)

> **Thực thi qua Admin UI (Chrome MCP) trên `https://qlts.tnpc.edu.vn`, kiêm smoke test production.**
> Soạn 2026-06-02. Tài khoản: `admin`. Round DOT_2 đang mở (01/04–30/06), 0 hồ sơ.

## ⏸️ TRẠNG THÁI THỰC THI (cập nhật 2026-06-03 — GĐ1/2/3 DONE, còn GĐ4/5)
- ✅ **GĐ1 DONE (prod):** method `201 "Xét học bạ THCS"` đã tạo qua UI (Xét điểm môn ✓, GPA ✗). `default_bonus_rule` CHƯA set ở method — đã thay bằng per-path bonus override (xem GĐ3).
- ✅ **GĐ2 DONE (prod, 2026-06-03):** 4 tổ hợp đã đủ môn (8 dòng `subject_group_subject` gán qua UI). BLOCKER route BE đã GỠ (PR #371 deploy 06-03). Verify UI: 1132 TV=math(1)+literature(2); 1133 VA=literature(1)+english(2); 1134 TT=math(1)+informatics(2); 1135 TK=math(1)+natural_science(2).
- ✅ **GĐ3 DONE (prod, 2026-06-03):** 7 đường THCS active đã tạo qua ma trận chỉ tiêu (path id 210-216). Mỗi đường: Tiêu chí (Điểm trung bình, N=2, min GPA 5.0, thang 10, tổ hợp đúng) · Định danh (Phạm vi=**Công khai (storefront)**, fee **70000**) · Chỉ tiêu trống · Nâng cao (applicable_to=**POST_THCS** + bonus override khu vực+đối tượng, trần **2.75**) · Vòng đời=**Đang hoạt động**. Mapping: 210 Kế toán(oai86,TV) · 211 QTKD vận tải(87,TV) · 212 QL&KD du lịch(85,VA) · 213 CNTT ƯDPM(82,TT) · 214 Công nghệ ô tô(81,TK) · 215 Chăn nuôi-Thú y(84,TK) · 216 KT chế biến món ăn(83,TK). **Verify storefront** `?audience=POST_THCS`: 7/7 ngành TC trả admission_methods chứa code 201; Y sỹ đa khoa TC chỉ 200 (đúng). (Method 200 còn lẫn vào POST_THCS do applicable_to cũ NULL → dọn ở GĐ4.)
- ✅ **GĐ4 DONE (prod, 2026-06-03):** 32 đường active cập nhật xong — fee=70000 + applicable_to=POST_THPT cho cả 32; 24 đường CĐ chia admit_quota 80:20 (verify quota khớp 100% bảng). **Verify storefront:** POST_THCS giờ chỉ trả 7 ngành TC (mỗi ngành chỉ method 201); POST_THPT trả 20 ngành (12 CĐ method 100+200 + 8 TC method 200), không lẫn 201 → phân luồng audience hoàn hảo. **Lưu ý cơ chế:** lưu tab Nâng cao trên path "Đang hoạt động" bật dialog "Lưu thay đổi trên phương thức đang hoạt động?" → BẮT BUỘC bấm "Vẫn lưu" (tab Chỉ tiêu/Định danh lưu thẳng, không dialog).
- ⬜ **GĐ5:** CHƯA bắt đầu — xóa/deactivate 20 draft "Xét tuyển thẳng" (301). Chờ user duyệt.
- **UI note:** dialog tạo path chỉ có Tên hiển thị + thứ tự; PathDetailDrawer mở sau đó với 6 tab, **mỗi nút "Lưu <tab>" đóng drawer** → mở lại path qua URL `...&tab=<criteria|identity|advanced|lifecycle>&pathId=<id>`. academicInfo param = oai id.
- **Trạng thái prod an toàn:** 7 đường THCS active đã lên storefront cho thí sinh THCS; chưa ảnh hưởng các đường THPT đang chạy.

## Mục tiêu
Bổ sung phương thức/đường tuyển sinh cho thí sinh **TN THCS vào hệ Trung cấp** (gap phát hiện khi audit), đồng thời dọn DOT_2: chia chỉ tiêu, đặt lệ phí, đặt đối tượng (audience routing), xóa đường tuyển thẳng chưa dùng.

## Quyết định đã chốt
- TN THCS xét TC: **TB 2 môn lớp 9, theo từng ngành**, sàn **5.0**, thang 10.
- Lệ phí xét tuyển: **70.000đ** tất cả đường active.
- Chỉ tiêu: **CĐ chia 80:20** (Học bạ:THPT QG); **TC không chia** (THCS & THPT dùng chung chỉ tiêu ngành → admit_quota NULL).
- Đối tượng (`applicable_to`): CĐ + TC học bạ THPT → `POST_THPT`; đường THCS mới → `POST_THCS`.
- Xóa 20 đường draft "Xét tuyển thẳng" (301).

## Cơ chế đã verify (vì sao làm vậy)
- Storefront lọc đường theo `applicable_to` (`?audience=...`, `@>` containment; NULL = mọi đối tượng). Hiện **NULL hết** → THCS đang thấy cả ngành CĐ → phải set lại.
- UNIQUE `(round, major, method)` → **bắt buộc tạo method mới** cho đường THCS (không thể trùng method 200).
- Submit **không** validate audience → `applicable_to` chỉ ảnh hưởng hiển thị storefront.
- Tiêu chí (criteria) **không có CRUD riêng** → cấu hình trong PathDetailDrawer › tab Tiêu chí.
- Xóa path **không có UI** → dùng SQL (1 câu, có guard).

---

## GIAI ĐOẠN 1 — Phương thức "Xét học bạ THCS"
**UI:** `/admin/admission-config` › Giai đoạn 1 › "Phương thức Tuyển sinh" › Thêm.
- [ ] code = `201`, name = `Xét học bạ THCS`, requires_gpa = off, requires_subject_scores = **on**, display_order = sau 301.
- [x] **Bonus rule** (area+object, max 2.75): form method KHÔNG có field này. **CHỐT: dùng per-path `bonus_rule_override` ở GĐ3 tab Nâng cao** (option b) — vì SQL write bị auto-mode chặn (chỉ làm qua UI). Mỗi đường THCS sẽ bật override area+object 2.75.
- Verify: method 201 xuất hiện trong danh mục + làm 1 hàng trong ma trận GĐ3.

## GIAI ĐOẠN 2 — Tổ hợp 2 môn lớp 9 (4 tổ hợp) ✅ DONE 2026-06-03
**UI:** Giai đoạn 1 › "Môn học & Tổ hợp xét tuyển" › Tab 2 (tạo tổ hợp) + Tab 3 (gán môn).
Môn dùng (đã có sẵn): `math` Toán, `literature` Ngữ văn, `english` Ngoại ngữ, `informatics` Tin học, `natural_science` KHTN.
- [x] `THCS_TV` (1132) → math, literature
- [x] `THCS_VA` (1133) → literature, english
- [x] `THCS_TT` (1134) → math, informatics
- [x] `THCS_TK` (1135) → math, natural_science

## GIAI ĐOẠN 3 — Tạo 7 đường THCS mới (active) ✅ DONE 2026-06-03 (path id 210-216)
**UI:** Giai đoạn 3 › "Cấu hình chỉ tiêu" › Theo ngành › chọn ngành › ô (Xét học bạ THCS × DOT_2) › "+ Tạo" › PathDetailDrawer cấu hình:
- tab **Tiêu chí**: tổ hợp = cặp môn của ngành, scoring = `average`, required_subject_count = 2, min_gpa = **5.0**, max 10.
- tab **Định danh**: application_fee = **70000**, display_name "<Ngành> 2026 – TC – Học bạ THCS".
- tab **Chỉ tiêu**: admit_quota = **để trống** (không chia).
- tab **Nâng cao**: applicable_to = ✅ `POST_THCS`; bonus override area+object (nếu chọn cách (b)).
- tab **Vòng đời**: **Kích hoạt**.

| # | oai | Ngành TC | Mã | Tổ hợp | path id | ✅ |
|---|-----|----------|-----|--------|---------|----|
| 1 | 86 | Kế toán | 5340301 | THCS_TV | 210 | ✅ |
| 2 | 87 | QTKD vận tải đường bộ | 5340407 | THCS_TV | 211 | ✅ |
| 3 | 85 | Quản lý & KD du lịch | 5340421 | THCS_VA | 212 | ✅ |
| 4 | 82 | CNTT (ứng dụng phần mềm) | 5480202 | THCS_TT | 213 | ✅ |
| 5 | 81 | Công nghệ ô tô (TC) | 5510216 | THCS_TK | 214 | ✅ |
| 6 | 84 | Chăn nuôi - Thú y (TC) | 5620120 | THCS_TK | 215 | ✅ |
| 7 | 83 | Kỹ thuật chế biến món ăn | 5810207 | THCS_TK | 216 | ✅ |

## GIAI ĐOẠN 4 — Cập nhật 32 đường active hiện tại ✅ DONE 2026-06-03
**UI:** Giai đoạn 3 › click từng ô có path › PathDetailDrawer. (Mở nhanh qua URL `?...&tab=<identity|advanced>&pathId=<id>`; nút "Lưu nâng cao" path active → bấm tiếp "Vẫn lưu" ở dialog.)
- [x] **Tất cả 32**: Định danh › application_fee = **70000**; Nâng cao › applicable_to = ✅ `POST_THPT`.
- [x] **12 ngành CĐ**: Chỉ tiêu › admit_quota theo bảng 80:20 (verify khớp 100%):

| Ngành CĐ | THPT QG (path=qty) | Học bạ (path=qty) |
|---|---|---|
| Y sỹ đa khoa | 167=14 | 158=56 |
| Chăn nuôi-Thú y | 205=7 | 187=28 |
| Điều dưỡng | 206=15 | 188=60 |
| Công nghệ ô tô | 207=45 | 189=180 |
| Dược | 159=21 | 190=84 |
| Hướng dẫn du lịch | 209=7 | 191=28 |
| Y học cổ truyền | 160=14 | 192=56 |
| CNTT | 161=8 | 193=32 |
| QTKD | 162=7 | 194=28 |
| QTVP | 163=4 | 208=16 |
| Kế toán | 164=7 | 195=28 |
| Tiếng Anh | 166=6 | 196=24 |

- [x] **8 đường TC học bạ THPT** (197,198,199,200,201*,202,203,204 — *path id 201, không nhầm với method code): admit_quota để trống (không chia); fee 70k; applicable_to `POST_THPT`. (Y sỹ TC = path 204, chỉ THPT.) ✅

## GIAI ĐOẠN 5 — Xử lý 20 đường draft "Xét tuyển thẳng" (⏳ CHỜ PR ARCHIVE)
> **Cập nhật 2026-06-03:** 20 draft 301 VÔ HẠI (verify storefront: cả POST_THCS lẫn POST_THPT đều KHÔNG chứa method 301). Phát hiện khi định dọn:
> - **(a) UI deactivate BẤT KHẢ THI cho draft**: tab Vòng đời path draft CHỈ có nút "Kích hoạt" (disabled), KHÔNG có "Vô hiệu hoá". BE `deactivate_path()` chỉ nhận `active→inactive`; draft không deactivate được.
> - **Cách đúng = ARCHIVE** (`draft/inactive → archived`). BE `archive_path()` ĐÃ CÓ logic (chặn active/already-archived) nhưng CHƯA wire endpoint + FE + nút UI = **nợ tính năng**.
> - **✅ Đã code PR wire archive** (branch `feat/admission-path-archive-draft`, commit `af2a1d99`, CHƯA push — chờ user review): `POST /paths/{id}/archive` (+require_admin) + FE client `archiveAdmissionPath` + hook + nút "Lưu trữ" trong LifecycleTab + 7 unit test. Test local PASS (7 archive + type-check tsc + flake8 net-zero). **Resume GĐ5 sau khi PR merge+deploy:** archive 20 draft 301 qua nút "Lưu trữ" (mở từng ô tuyển thẳng DOT_2 → Vòng đời → Lưu trữ). path id 301 DOT_2: 165,168-178 (CĐ 69-80) + 179-186 (TC 81-88).
> - **(b) SQL xóa cứng** (thay thế, cần approve riêng): câu lệnh dưới.

```sql
DELETE FROM admission_path p
WHERE p.status='draft' AND p.admission_method_id=3   -- 301 Xét tuyển thẳng
  AND p.admission_round_id=(SELECT id FROM offering_admission_round WHERE round_code='DOT_2')
  AND NOT EXISTS (SELECT 1 FROM admission_profile_choice c WHERE c.admission_path_id=p.id)
  AND NOT EXISTS (SELECT 1 FROM path_subject_group_config s WHERE s.admission_path_id=p.id)
  AND NOT EXISTS (SELECT 1 FROM document_group d WHERE d.admission_path_id=p.id)
RETURNING id;   -- kỳ vọng 20 dòng
```
<!-- legacy block below kept for reference -->
### (chi tiết SQL — chỉ chạy nếu chọn (b))
```sql
DELETE FROM admission_path p
WHERE p.status='draft' AND p.admission_method_id=3   -- 301 Xét tuyển thẳng
  AND p.admission_round_id=(SELECT id FROM offering_admission_round WHERE round_code='DOT_2')
  AND NOT EXISTS (SELECT 1 FROM admission_profile_choice c WHERE c.admission_path_id=p.id)
  AND NOT EXISTS (SELECT 1 FROM path_subject_group_config s WHERE s.admission_path_id=p.id)
  AND NOT EXISTS (SELECT 1 FROM document_group d WHERE d.admission_path_id=p.id)
RETURNING id;   -- kỳ vọng 20 dòng
```

---

## VERIFY cuối (DB prod)
- [ ] method 201 tồn tại + default_bonus_rule có area+object.
- [ ] 7 đường THCS active, applicable_to={POST_THCS}, fee=70000, criteria 2 môn min 5.0.
- [ ] 32 đường cũ: fee=70000, applicable_to={POST_THPT}; 12 CĐ admit_quota tổng = chỉ tiêu ngành.
- [ ] document_group id 12 applicable_audience có POST_THCS (để hồ sơ THCS resolve đúng).
- [ ] 0 đường draft 301 còn lại ở DOT_2.
- [ ] Storefront: `/api/public/admissions/programs?audience=POST_THCS` chỉ trả TC THCS; `?audience=POST_THPT` trả CĐ + TC THPT.

## Rollback
- Path mới tạo nhầm: deactivate (Vòng đời) + DELETE SQL.
- applicable_to/quota/fee: PATCH lại giá trị cũ (cũ = NULL).
- Không động vào hồ sơ (0 hồ sơ nên an toàn tuyệt đối).
