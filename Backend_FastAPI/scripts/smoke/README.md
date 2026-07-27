# Bộ kịch bản smoke — Admission ↔ Finance

⚠️ **Công cụ phá hoại dữ liệu.** Bộ này đặt lại mật khẩu tài khoản, ghi đè học
phí học kỳ và sửa cấu hình ưu đãi. Chỉ chạy trên DB dùng-một-lần.

## Chốt chặn

`smoke_lib` từ chối chạy nếu thiếu bất kỳ điều kiện nào — không có giá trị mặc
định để "lỡ tay":

| Biến | Vì sao bắt buộc |
|---|---|
| `SMOKE_ALLOW_DESTRUCTIVE=1` | Người chạy phải nói rõ mình chấp nhận mất dữ liệu |
| `SMOKE_BASE` | Đoán `backend:8000` là bắn nhầm vào hệ thống thật |
| `SMOKE_PASSWORD` | Mật khẩu cứng trong mã = mật khẩu admin công khai trên mọi DB từng chạy |

Thêm một lớp nữa: từ chối khi `APP_ENV` hoặc `DATABASE_URL` trông giống
production/staging, **kể cả khi ba biến trên đã đặt đúng** — vì một stack dev
trỏ nhầm sang DB thật vẫn có `APP_ENV=development`.

Bộ này **không nằm trong image production** (`.dockerignore` loại
`scripts/smoke/`); chạy qua bind-mount ở stack dev.

## Chạy

```bash
docker compose -p qlts-mc -f docker-compose.yml -f docker-compose.smoke.yml \
  run --rm --no-deps \
  -e SMOKE_ALLOW_DESTRUCTIVE=1 \
  -e SMOKE_BASE=http://backend:8000 \
  -e SMOKE_PASSWORD='<chuỗi dùng-một-lần>' \
  --entrypoint python backend scripts/smoke/smoke_seed.py   # gieo dữ liệu trước

# rồi từng mục, ví dụ:
... --entrypoint python backend scripts/smoke/smoke_m9_doinganh.py
```

**Mã thoát phản ánh kết quả**: 0 khi mọi mục PASS, 1 khi có mục FAIL. Mỗi kịch
bản phải `return tong_ket(NHAN)` và kết thúc bằng `chay(main)`; nếu quên
`return`, `chay()` báo lỗi thay vì im lặng báo xanh.

## Các mục

| File | Nội dung |
|---|---|
| `smoke_seed.py` | Gieo tài khoản 7 vai, 2 ngành, chính sách ưu đãi |
| `smoke_m2_rbac.py` | Phân quyền / IDOR |
| `smoke_m3_m4_m8.py` | Hồ sơ · yêu cầu sửa/từ chối · thu online |
| `smoke_m3_magiclink.py` | Thí sinh tự phục vụ qua magic-link |
| `smoke_m5_preview.py` | Xem trước ưu đãi học phí |
| `smoke_m6_m7.py` | Khoản phí · hoá đơn · maker-checker |
| `smoke_m6b_m10.py` | Rút hồ sơ · hoàn tiền |
| `smoke_m8_import.py` | Nhập lô Excel (7 loại dòng, đảo lô) |
| `smoke_m9_doinganh.py` | Đổi ngành sau khi đã thu tiền |
| `smoke_m11_ketoan.py` | Kế toán · báo cáo kỳ |
