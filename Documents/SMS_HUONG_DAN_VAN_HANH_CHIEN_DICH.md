# Hướng dẫn vận hành — Chạy chiến dịch SMS Marketing (Phase 1)

> Dành cho người vận hành (admin). Phase 1 = **quảng cáo qua file Excel bàn giao nhà mạng** —
> hệ thống **KHÔNG tự gửi SMS**. QLTS sinh file danh sách + nội dung đã chuẩn hoá, bạn
> **tải file rồi upload thủ công lên cổng nhà mạng** (Viettel/VinaPhone/MobiFone…).

Truy cập: **Admin → SMS** (menu bên trái, biểu tượng máy bay giấy). URL prod: `https://qlts.tnpc.edu.vn/admin/sms/...`

---

## Toàn cảnh luồng (8 bước)

```
1. Liên hệ + đồng ý (consent)  →  2. Nhóm liên hệ  →  3. Tạo chiến dịch
   →  4. Gắn nhóm  →  5. Build (chốt danh sách + kiểm tra)  →  6. 3 Xác nhận
   →  7. Export Excel (1 file/nhà mạng)  →  8. Tải file → upload nhà mạng → "Đã bàn giao"
```

---

## Bước 1 — Liên hệ + Đồng ý (bắt buộc)
`SMS → Liên hệ SMS → tab "Liên hệ"`
- **Tạo liên hệ** (tên + số điện thoại). Số nhập dạng `09xxxxxxxx`.
- **Ghi nhận đồng ý (consent)**: mở liên hệ → thêm sự kiện consent **"Đồng ý"** kèm căn cứ (form/phiếu/ghi âm) + tham chiếu bằng chứng.
  - ⚠️ **Liên hệ CHƯA "Đã đồng ý" sẽ bị LOẠI khỏi danh sách gửi** (theo NĐ91). Chỉ số có consent granted mới được export.
- Nhập số lượng lớn: dùng **Import** (CSV/xlsx) ở tab Nhóm.

## Bước 2 — Nhóm liên hệ
`SMS → Liên hệ SMS → tab "Nhóm liên hệ"`
- **Tạo nhóm** (đặt tên rõ, vd "Phụ huynh K10 2026").
- Đưa liên hệ vào nhóm: mở nhóm (icon người) → **Import** file danh sách.
  - ⚠️ Ô "Tìm tên/số" trong dialog nhóm = **lọc thành viên đã có**, KHÔNG phải thêm-lẻ. Thêm liên hệ vào nhóm hiện qua **Import**.

## Bước 3 — Tạo chiến dịch
`SMS → Chiến dịch SMS → "Tạo chiến dịch"`
- **Tên chiến dịch** (bắt buộc). Mã tự sinh.
- **Nội dung tin** (bắt buộc): dùng biến `{full_name}` (tên) + `{link}` (link rút gọn có đo click).
  - Ví dụ: `Chao {full_name}, xem tuyen sinh 2026: {link}`
  - ⚠️ **Thiếu `{link}` → chiến dịch KHÔNG đo được click** (vẫn gửi được).
  - 💡 Hệ thống tự thêm `[QC]` đầu tin + hướng dẫn từ chối cuối tin — **không cần tự gõ**.
- **Trang đích**: "Trang đích QLTS" (điền Tiêu đề + Nội dung → hiển thị ở trang `/lp` khi khách bấm link) hoặc "Liên kết ngoài" (nhập URL trong allowlist).

## Bước 4 — Gắn nhóm
Trong trang chiến dịch → mục **Nhóm liên hệ** → chọn nhóm → **Gắn**. Cần ≥1 nhóm.

## Bước 5 — Build (chốt danh sách + preflight)
Bấm **Build**. Hệ thống chốt danh sách gửi + kiểm tra, hiện:
- **Tổng người nhận** / **Gửi được** / **Bản dựng #** / **Đo click**.
- **Loại theo lý do**: chưa đồng ý / đã từ chối / trong DNC / vượt tần suất / **tin vượt 1 đoạn** / thiếu dữ liệu.
- **Phân bố nhà mạng** + **Xem trước tin cuối** (kiểm tra thực tế tin trông thế nào).
- ⚠️ **BẪY thường gặp — "tin vượt 1 đoạn"**: tên có **dấu tiếng Việt** (ễ, ộ…) → mã hoá UCS2 (giới hạn **70 ký tự/đoạn**). Tin dài → vượt 1 đoạn → **bị chặn export**.
  - Cách xử lý: **rút gọn nội dung tin**, hoặc chấp nhận tên không dấu, hoặc rút ngắn danh sách. Tin không dấu (GSM-7) cho **160 ký tự/đoạn** → dễ vừa 1 đoạn hơn.
- Đổi nhóm/nội dung sau khi build → **Build lại** (số liệu cũ sẽ được đánh dấu stale).

## Bước 6 — 3 Xác nhận trước export (bắt buộc)
Mục **Xác nhận trước export**. Phải đủ **3/3**, mỗi cái nhập tham chiếu bằng chứng rồi bấm **Xác nhận**:
1. **Đã có đồng ý (consent)** — đã kiểm danh sách có consent hợp lệ.
2. **Đã lọc danh sách chặn (DNC)** — đã đối chiếu danh sách không-gọi/không-gửi.
3. **Kênh từ chối hoạt động** — kênh opt-out (hotline **0906513555**) đang hoạt động.
- ⚠️ **Build lại sẽ VÔ HIỆU cả 3 xác nhận** → phải xác nhận lại cho bản dựng mới.

## Bước 7 — Export Excel
Mục **Export & bàn giao** → **Export Excel**. Điều kiện: **đủ 3/3 xác nhận + 0 tin-vượt-đoạn + ≥1 gửi được**.
- Sinh **1 file/nhà mạng** (Viettel, VinaPhone…). Mỗi file: cột A = số `84xxx`, cột B = nội dung tin cuối.
- File có **hạn** (14 ngày) — tải + dùng trước khi hết hạn.

## Bước 8 — Tải file → Gửi nhà mạng → Đánh dấu bàn giao
- **Tải** từng file → **upload lên cổng nhà mạng tương ứng** (thao tác NGOÀI QLTS, theo quy trình nhà mạng).
- Sau khi đã upload xong 1 nhà mạng → bấm **"Đã bàn giao"** cho nhà mạng đó.
  - ⚠️ Neo người nhận (chặn build lại) + tính tần suất gửi. **Không hoàn tác.**
  - Khi **mọi nhà mạng đã bàn giao** → chiến dịch tự chuyển **"Đã đóng"**.

---

## Sau chiến dịch
- **Đo click / CTR**: `SMS → Báo cáo SMS` (theo ngày/tháng/năm + dashboard từng chiến dịch). Chỉ có số khi tin dùng `{link}`.
- **Khách từ chối**: bấm link → trang `/lp/{code}` có nút "Huỷ nhận tin" → tự vào danh sách opt-out. Xem/thêm tay ở `SMS → Từ chối nhận tin`.
- Số đã opt-out sẽ **tự bị loại** ở các build sau.

## Nguyên tắc tuân thủ (NĐ91)
- Chỉ gửi cho số **đã đồng ý** (consent granted).
- Tin luôn có `[QC]` + hướng dẫn từ chối (tự động).
- Kênh từ chối (hotline) phải **thật + hoạt động**.
- Tôn trọng số đã từ chối (opt-out/DNC) — hệ thống tự loại.

## Khi gặp lỗi
- **"Chưa export được: còn thiếu N/3 xác nhận"** → làm đủ Bước 6.
- **"tin vượt 1 đoạn — export bị chặn"** → rút gọn nội dung (Bước 5).
- **Không có người gửi được** → kiểm consent (Bước 1) / nhóm rỗng / tất cả bị opt-out.
- Lỗi mạng thoáng qua khi bấm → thử lại sau vài giây.
