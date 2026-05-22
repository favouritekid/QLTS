# Phase E.4 — Bức tranh toàn cảnh nghiệp vụ

**Mục đích tài liệu:** Giải thích Phase E.4 cho stakeholder, manager, training officer — không kỹ thuật. Đi kèm với spec dev: `PHASE_E4_PRIORITY_WORKBENCH_SPEC_V3_FINAL.md`.

**Ngày:** 2026-05-19
**Branch:** `feat/phase-e4-priority-workbench`

---

## Bối cảnh nghiệp vụ

Hệ thống QLTS đang xử lý **tuyển sinh giáo dục nghề nghiệp** theo Thông tư 05/2021. Mỗi hồ sơ ứng viên có **điểm cộng ưu tiên** dựa 2 yếu tố:

1. **Khu vực ưu tiên (KV)** — cộng 0/0.25/0.50/0.75 điểm tùy vùng candidate học THPT
   - KV1 (+0.75đ) — vùng miền núi, dân tộc thiểu số, biên giới, hải đảo
   - KV2-NT (+0.50đ) — nông thôn không thuộc KV1
   - KV2 (+0.25đ) — thành phố thuộc tỉnh, phường ngoại thành TP trực thuộc TƯ
   - KV3 (không cộng) — nội thành TP trực thuộc TƯ (Hà Nội, HCM...)

2. **Đối tượng ưu tiên (UT)** — cộng 0.5–2 điểm tùy diện candidate thuộc
   - UT01 Anh hùng LLVTND (+2.00đ)
   - UT02 Thương binh ≥81% (+2.00đ)
   - UT04 Con thương binh, con liệt sĩ (+1.00đ)
   - UT06 Dân tộc thiểu số rất ít người (+0.50đ)
   - UT07 Hộ nghèo (+0.50đ)
   - … (catalog 7 diện, mỗi diện cần minh chứng riêng)

Hai loại này cộng dồn → ảnh hưởng trực tiếp **điểm xét tuyển**. Một hồ sơ có thể được cộng tới **+2.75 điểm** — đủ để thay đổi kết quả đậu/trượt.

→ Cán bộ tuyển sinh (officer) phải xác minh **chính xác**, có **căn cứ pháp lý rõ**, và lưu **audit trail đầy đủ** vì điểm cộng ảnh hưởng cạnh tranh.

---

## 😣 Hiện trạng — Officer đang phải làm gì

Tưởng tượng officer Mai phụ trách 50 hồ sơ/ngày. Hiện tại quy trình xác minh ưu tiên của 1 hồ sơ là:

### Bước 1 — Mở Step 4 "Trình độ & Ưu tiên" để check KV

- Officer thấy engine tự tính KV1 (+0.75đ) — **nhưng không biết vì sao**. Hệ thống chỉ hiện kết quả KV, không giải thích "engine dựa vào đâu" hay "luật nào".
- Officer phải mở Thông tư 05/2021 file PDF ngoài để cross-check → tốn thời gian.
- Nếu candidate thuộc trường hợp đặc biệt (PTDT nội trú, dự bị đại học, quân nhân…) → officer phải nhớ bật toggle thủ công. UI hiện tại là cái switch đơn giản, dễ bỏ sót.
- Nếu engine không quyết định được (vd candidate học 2 trường ngang nhau ở 2 KV khác) → engine flag nhưng officer **không biết phải làm gì tiếp theo** — phải tự override KV. Quy trình mơ hồ.

### Bước 2 — Nhảy sang Step 8 "Duyệt UT" để verify đối tượng ưu tiên

- Tab Step 8 nằm tách rời Step 4 → context switch giữa 2 tab cho cùng 1 nghiệp vụ ưu tiên.
- Tab này list các diện UT officer đã ghi nhận vào hệ thống (vd UT04 con thương binh, UT07 hộ nghèo) với nút [Duyệt] [Từ chối].
- **Vấn đề lớn:** officer verify mà **không có cách gắn file minh chứng** vào audit log. Hệ thống không truy được "officer dựa vào giấy nào để duyệt UT04". Officer phải đối chiếu hồ sơ giấy candidate đem đến rồi tự duyệt — quy trình OK nhưng audit trail không lưu lại được giấy cụ thể.
- Khi có thanh tra sau này: audit log chỉ ghi "officer X verified UT04 lúc Y" — **không biết dựa vào giấy nào**.

### Bước 3 — Mở Step 6 "Giấy tờ"

- Tab này chỉ list **giấy tờ bắt buộc của ngành** (CCCD, học bạ, ảnh 3x4, giấy khám sức khoẻ).
- **Giấy minh chứng UT KHÔNG có chỗ chính thức ở đây.** Officer scan giấy chứng nhận con thương binh thì… không biết upload vào đâu trong hệ thống → phải lưu vào folder Google Drive riêng hoặc chỉ giữ hồ sơ giấy vật lý.
- → **Disconnect nghiêm trọng:** officer ghi nhận UT04 trên hồ sơ điện tử nhưng giấy chứng nhận không nằm chung file → quản lý phân tán giữa hệ thống + Drive + tủ giấy.

### Bước 4 — Officer bấm submit hồ sơ

- Officer hoàn tất nhập liệu, bấm submit. Hệ thống cho qua **dù officer quên scan giấy minh chứng UT** vào hệ thống.
- → Rủi ro: hồ sơ submit, được duyệt, vào danh sách trúng tuyển → sau đó thanh tra phát hiện ghi nhận UT04 mà không có file scan trong hệ thống → phải truy file giấy ngoài → quản lý chứng cứ phân tán.
- Đây là vấn đề **data quality của officer**, không phải candidate cheating — candidate đã đem giấy đến nhưng officer chưa kịp scan vào hệ thống.

### Tóm tắt nỗi đau hiện tại

| Vấn đề | Tác động |
|---|---|
| KV + UT tách 2 tab (Step 4 + Step 8) | Officer nhảy qua nhảy lại, dễ quên 1 trong 2 |
| Engine KV không giải thích lý do | Officer mất thời gian cross-check luật, không tin tưởng kết quả |
| Verify UT không gắn file | Audit không truy được, rủi ro thanh tra |
| Giấy minh chứng UT không có chỗ upload | Quản lý phân tán, lưu Google Drive riêng |
| Submit không cảnh báo khi officer thiếu scan giấy UT | Audit trail không đầy đủ, truy file thanh tra khó |
| Layout phức tạp, nhiều click | 50 hồ sơ/ngày tốn nhiều thời gian, mệt mỏi |

---

## ✨ Sau Phase E.4 — Officer sẽ làm như thế nào

Cùng officer Mai, cùng 50 hồ sơ/ngày. Quy trình mới:

### Mở Step 4 "Ưu tiên tuyển sinh" — TẤT CẢ ở 1 chỗ

Mai mở hồ sơ. Step 4 hiển thị **dòng tóm tắt ở đầu**:

> 🟢 *Tạm tính: KV1 + UT04 = +1.75đ · UT07 chờ duyệt*

→ Mai biết ngay kết quả trước khi scroll. Quyết định "có cần can thiệp không" trong 2 giây.

### Phần 1 — Trình độ + Trường hợp đặc biệt

Hai dropdown khai trình độ văn hóa + nghề. Switch trường hợp đặc biệt (nếu có) với label rõ "PTDT nội trú, dự bị ĐH, lớp tạo nguồn, quân nhân/CAND".

→ Officer biết chính xác nhóm nào áp dụng, không đoán mò.

### Phần 2 — Khu vực ưu tiên (KV) — **5 trạng thái rõ ràng**

Tùy tình huống hồ sơ, hệ thống hiển thị **một trong 5 trạng thái** với màu sắc + nhãn rõ:

| Trạng thái | Khi nào | Mai làm gì |
|---|---|---|
| 🟢 **Engine OK** | Engine tự tính được KV1 +0.75đ | Đọc lý do "3/3 năm cấp 3 tại THPT Bảo Lộc (Lâm Đồng — vùng miền núi)" + căn cứ "TT 05/2021 Phụ lục 01 Mục 5.b" → tin tưởng → scroll xuống |
| 🟠 **Cần xác minh thủ công** | Engine không quyết định được (vd 2 trường ngang nhau) | Click "Chọn KV thủ công" → dialog → chọn KV + nhập lý do → submit |
| ⚠ **Thiếu data** | Officer chưa ghi nhận trình độ vào hệ thống | Quay lên Phần 1 fill dropdown |
| 🔒 **Đã chốt** | Hồ sơ đã submit, KV đã frozen | Read-only, không can thiệp được (trừ admin) |
| 🔧 **Cán bộ đã ấn định** | Admin đã override KV thủ công | Thấy thông tin "ai override, khi nào, vì sao" → audit minh bạch |

→ Mai **không cần mở luật ngoài** — căn cứ pháp lý hiện ngay trong card. Tin tưởng nhanh.

### Phần 3 — Đối tượng ưu tiên (UT) — **verify gắn file**

Mai thấy 2 thẻ:
- **UT04** "Con thương binh" +1.00đ — ✅ đã duyệt bởi đồng nghiệp + file `hosp_42.pdf` [Xem PDF]
- **UT07** "Hộ nghèo" +0.50đ — ⏳ chờ duyệt + file `ho_ngheo_xacnhan.pdf` [Xem PDF] + nút [Duyệt] [Từ chối]

Mai click [Xem PDF] mở giấy chứng nhận hộ nghèo ngay trong browser → đối chiếu thông tin candidate (data subject) → click [Duyệt]. **Verify xong, audit log tự ghi: ai duyệt + lúc nào + file nào.**

Nếu officer chưa scan giấy cho UT đã ghi nhận: thẻ hiện cảnh báo "⚠ Chưa scan minh chứng" + link "→ Mở tab Giấy tờ để upload". Officer có thể verify ngay với flag "Hồ sơ giấy" khi giấy chưa scan kịp — đây là **phần lớn hồ sơ** trong nghiệp vụ VN hiện tại, audit log vẫn ghi đủ để thanh tra truy được.

### Phần 4 — Tóm tắt + Tiếp tục

Mai thấy tổng "+1.75đ" + nút [Tiếp tục →]. Một Enter, sang Step 5. **Xong 1 hồ sơ trong ~17 giây** (vs 30-40s trước đây).

---

## 📁 Step 6 "Giấy tờ" — 1 nơi quản lý mọi giấy tờ

Đây là thay đổi quan trọng **gián tiếp** giúp Step 4 chạy mượt:

**Trước:** Step 6 chỉ list giấy bắt buộc của ngành (CCCD, học bạ, ảnh 3x4). Giấy minh chứng UT phải lưu Google Drive riêng.

**Sau:** Step 6 list **2 nhóm**:

```
Giấy tờ bắt buộc (từ ngành tuyển sinh):
  ✓ Học bạ THPT             [Đã upload]
  ✓ CCCD                    [Đã upload]
  ✗ Bằng tốt nghiệp THPT    [Chưa upload]
  ✗ Ảnh 3x4                 [Chưa upload]

Giấy tờ minh chứng ưu tiên (từ UT đã khai):
  ✓ Giấy chứng nhận con thương binh (UT04)   [Đã upload]
  ⏳ Giấy chứng nhận hộ nghèo (UT07)          [Đã upload, chờ duyệt]
  ✗ Giấy xác nhận chất độc hóa học (UT08)    [Chưa upload]

Tổng kết:
  Bắt buộc: 2/4 đã upload
  Ưu tiên:  2/3 đã upload — thiếu UT08
```

→ Officer **biết ngay** thiếu giấy gì. Upload 1 chỗ. Quản lý 1 chỗ.

---

## 🛡️ Cảnh báo data quality — Officer không quên scan giấy UT

**Trước:** Officer ghi nhận UT04 vào hệ thống nhưng quên scan giấy chứng nhận con thương binh. Submit hồ sơ → không có cảnh báo nào → khi thanh tra mở hệ thống, không thấy file → phải đi tìm file giấy ngoài.

**Sau:** Hệ thống check `priority_object_codes` của hồ sơ vs documents đã upload. Officer ghi nhận UT04 mà chưa scan → tab Step 4 §3 hiện inline warning màu cam "⚠ Thiếu minh chứng cho UT04. Mở tab Giấy tờ để upload." Warning refresh **realtime** sau mỗi lần upload file vào tab Giấy tờ (BE re-compute trên mỗi GET profile), không cần save profile để biết thiếu gì.

→ Officer **tự kỷ luật** trước khi submit. Audit trail đầy đủ trong hệ thống, giảm rủi ro truy file giấy ngoài khi thanh tra.

**Lưu ý:** Đây là **cảnh báo UX, không phải gate cứng**. Officer vẫn có thể submit nếu hồ sơ giấy đầy đủ nhưng chưa kịp scan — verify với flag "Hồ sơ giấy" trong audit log. Đây là **phần lớn hồ sơ** trong nghiệp vụ VN hiện tại, không phải exception. Tỷ lệ thực tế cần đo post-launch.

---

## 📊 So sánh trước — sau

| Khía cạnh | Hiện tại | Sau Phase E.4 |
|---|---|---|
| **Số tab officer dùng cho ưu tiên** | 2 tab (Step 4 KV + Step 8 UT) | 1 tab (Step 4 gộp) |
| **Thời gian xử lý/hồ sơ** | ~30-40 giây | ~17 giây |
| **Lý do KV engine quyết định** | Không hiển thị | Hiển thị trong card + căn cứ pháp lý |
| **File minh chứng UT** | Lưu ngoài (Google Drive) | Quản lý trong tab Giấy tờ |
| **Verify UT gắn file** | Không bắt buộc | Có file binding (tracked) |
| **Submit khi thiếu scan giấy UT** | Cho qua, không cảnh báo | Cảnh báo inline ngay tại §3 UT card (UX) |
| **Audit log** | Chỉ ghi action | Ghi action + actor + lý do + file ref + paper_only flag |
| **Override KV** | UI mơ hồ, 3 cách edit | 1 dialog duy nhất với lý do + version check |
| **Trải nghiệm 50 hồ sơ/ngày** | Tốn nhiều click, dễ sai sót | Tab → Enter → Continue, streamline |

---

## 🎁 Giá trị mang lại

### Cho officer
- **Nhanh hơn:** ước lượng tiết kiệm ~50% thời gian Step 4 — base time hiện tại ~30-40s/hồ sơ × 50 hồ sơ = 25-33 phút/ngày → cắt còn ~17s/hồ sơ × 50 = 14 phút/ngày. Tiết kiệm **~12-19 phút/officer/ngày**. _Note: Con số là **estimate dựa trên UX click-count + tab switch reduction**, chưa có baseline đo được. Cần Sentry/log analytics post-launch để confirm — xem `Documents/reports/officer_daily_activity_60d.csv` baseline raw data nếu cần đối chiếu._
- **Tin tưởng hơn:** engine giải thích rõ → không phải tra luật ngoài
- **Ít lỗi hơn:** 5 trạng thái KV rõ ràng → không bỏ sót trường hợp đặc biệt
- **Audit trail đầy đủ:** khi có thanh tra, mọi quyết định đều có dấu vết

### Cho candidate (gián tiếp qua officer)

> Candidate KHÔNG trực tiếp tương tác hệ thống — toàn bộ nhập liệu do officer thực hiện từ hồ sơ giấy candidate đem đến. Magic-link chỉ có 4 action đơn giản (submit/resubmit/confirm/withdraw), không có "khai UT". Giá trị cho candidate gián tiếp:

- **Minh bạch hơn:** officer giải thích được tại sao KV1 +0.75đ, dựa luật nào — candidate hỏi là officer trả lời được ngay
- **Hồ sơ không thất lạc giấy:** giấy minh chứng UT được scan vào hệ thống, không phụ thuộc folder Google Drive cá nhân officer
- **Công bằng:** override KV cần lý do + audit → tránh thiên vị giữa các officer khác nhau

### Cho tổ chức (compliance + risk)
- **Giảm rủi ro thanh tra:** mọi UT verified đều có file minh chứng đính kèm hoặc flag "Hồ sơ giấy" rõ ràng → kiểm tra được
- **Giảm rủi ro mất audit trail:** inline warning khi officer chưa scan → officer tự discipline trước submit
- **Trace minh bạch:** mọi override admin có lý do + version + thời gian
- **Pháp lý future-proof:** căn cứ "TT 05/2021" lưu trong DB → khi Luật GDNN 2025 ban hành thông tư mới, chỉ cần thay 1 chỗ

---

## ⚖️ Trade-off (cái mất khi đổi)

- **Officer phải học UI mới** — 5 trạng thái KV, các disclosure ẩn, untick UT confirm dialog. Training cost ~1 giờ/officer.
- **Officer workflow update** — giờ phải scan giấy minh chứng UT vào tab Giấy tờ thay vì chỉ ghi nhận UT code. Cần training script + tooltip.
- **Phát triển ~22-26 giờ** — 3-3.5 ngày làm việc (gồm dev + CI cycle + debug + smoke test). Tăng so với estimate cũ vì cycle 5 review phát hiện thêm: BE step model 7-step phải renumber lên 8-step (Step 4 = Priority sau Phase E.4 gộp), schema write/display tách rời để tránh leak, Casbin policy bổ sung 2 entries, partial unique indexes thay full unique trong migration.
- **Migration nhẹ** — thêm 2 cột vào bảng documents (instant DDL trên Postgres 16, không cần downtime). Migration `category` + `priority_sub_code` cùng partial index.

---

## 🚀 Kết luận

Phase E.4 không phải feature mới — đây là **redesign quy trình hiện tại** để:

1. **Gộp 2 tab thành 1** → giảm context switch
2. **Engine giải thích kết quả** → tăng độ tin cậy
3. **Gắn file minh chứng vào UT verify** → audit trail (kèm flag "Hồ sơ giấy" cho default case)
4. **Centralize document management** → giảm phân tán
5. **Inline warning data quality** → officer tự discipline, không cần gate cứng

→ Tóm lại: **"officer làm nhanh hơn (estimate ~50%, cần measure post-launch), audit trail đầy đủ hơn cho thanh tra, candidate được officer giải thích minh bạch hơn"**. Đầu tư ~22-26h dev (3-3.5 ngày làm việc) để tiết kiệm ~12-19 phút/officer/ngày (estimate) + giảm rủi ro thanh tra dài hạn.

---

## Tài liệu liên quan

- **Spec dev (kỹ thuật chi tiết):** `PHASE_E4_PRIORITY_WORKBENCH_SPEC_V3_FINAL.md`
- **Legal audit (cơ sở pháp lý):** Memory `q9-07-legal-audit-2026-05-18` (TT 05/2021 + 27/2017 + Luật GDNN 2025 + Luật Cư trú 2020)
- **WIP commit Foundation:** `16f9126b` trên branch `feat/phase-e4-priority-workbench`

---

**End of business overview.**
