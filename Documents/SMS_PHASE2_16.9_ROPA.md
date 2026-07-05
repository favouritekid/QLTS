# SMS Phase 2 — Bản ghi hoạt động xử lý dữ liệu / mini-DPIA (§16.9)

> ⚠️ **Không phải tư vấn pháp lý.** Đây là bản ghi kỹ thuật hỗ trợ tuân thủ; nội
> dung pháp lý (câu chữ, đủ/thiếu) cần luật sư/DPO rà. Trách nhiệm cuối thuộc
> người vận hành (chủ dự án). Ngày lập: 2026-07-05.

## 1. Hoạt động xử lý
Đo mức "quan tâm ngành" của người dùng qua hành vi trên landing tuyển sinh: khi
khách bấm link tư vấn (consult) hoặc link chiến dịch (campaign) rồi xem trang
ngành, hệ thống ghi **thời lượng xem (dwell)** theo từng ngành và tổng hợp thành
`interest_score(contact, ngành)`.

## 2. Mục đích & bản chất
- **Mục đích**: khảo sát để tư vấn tuyển sinh phù hợp hơn cho từng liên hệ.
- **Bản chất**: lập hồ sơ hành vi gắn đích danh (profiling) theo `contact` (khóa
  = số điện thoại đã chuẩn hóa). KHÔNG bán/chia sẻ; chỉ officer/admin nội bộ xem.

## 3. Dữ liệu xử lý (tối thiểu hóa)
| Trường | Ghi chú |
|---|---|
| `contact_id` (theo phone) | định danh liên hệ |
| ngành đã xem + `dwell_seconds` | tín hiệu quan tâm |
| `interest_score` (aggregate) | điểm tổng hợp §18.F |
| `ip_hash` = HMAC-SHA256(IP) | **KHÔNG lưu IP thô** |
| `session_token_hash`, `user_agent` | kỹ thuật/chống gian lận |
KHÔNG thu thập nội dung nhạy cảm, KHÔNG dữ liệu ngoài phạm vi trên.

## 4. Chủ thể dữ liệu
Khách/phụ huynh đã được officer gửi link tư vấn hoặc nhận link chiến dịch (đã có
quan hệ tuyển sinh) và tự bấm vào link.

## 5. Lưu trữ (retention)
- **Event chi tiết** (`sms_landing_session`, `sms_program_view`): **dọn tự động
  sau 365 ngày** (`SMS_INTEREST_EVENT_RETENTION_DAYS`, Celery beat 04:00 hằng
  ngày — `cleanup_sms_interest_events_task`).
- **Aggregate** (`sms_contact_program_interest`): giữ dài hạn (profile). Được
  recompute theo **cửa sổ retention** (chỉ view trong N ngày gần nhất) → xoá
  event ngoài cửa sổ KHÔNG làm lệch số liệu kể cả khi khách tương tác lại sau dọn.

## 6. Biện pháp giảm thiểu rủi ro
- IP băm (không IP thô) · dữ liệu tối thiểu (chỉ tên ngành + thời lượng) ·
  suppression opt-out toàn cục theo phone · loại bot khỏi số liệu · token chỉ lưu
  hash · retention 365 ngày cho event chi tiết.

## 7. Quyết định vận hành (chủ dự án, 2026-07-05)
Chủ dự án chọn **ghi nhận mặc định (default-on), landing đơn giản, KHÔNG hiển thị
thông báo riêng và KHÔNG nút từ chối riêng cho tracking**, xem đây là **khảo sát**
nội bộ phục vụ tư vấn. Chủ dự án **nhận rủi ro** này.

> **Đã được cảnh báo (ghi nhận):** Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 (hiệu
> lực 01-01-2026) + NĐ 356/2025 nghiêng về **đồng ý trước (opt-in) + minh bạch**
> khi lập hồ sơ hành vi người xác định danh tính. Phương án "default-on không
> thông báo" là rủi ro hơn "notice + opt-out". Nếu muốn hạ rủi ro sau này: thêm 1
> dòng thông báo minh bạch + tôn trọng opt-out cho tracking (đã có sẵn hạ tầng).

## 8. Bên thứ ba
Không chia sẻ dữ liệu interest cho bên thứ ba. (Gửi tin quảng cáo Phase 1 qua nhà
mạng là luồng riêng, có hợp đồng/attestation riêng — không thuộc phạm vi bản ghi
này.)

## 9. Cơ sở tham chiếu luật (nguồn nhà nước)
- Luật BVDLCN 91/2025/QH15 (01-01-2026) · NĐ 356/2025/NĐ-CP · NĐ 91/2020/NĐ-CP
  (chống tin rác, opt-out). Xem §17 `SMS_MARKETING_MODULE_DESIGN.md`.
