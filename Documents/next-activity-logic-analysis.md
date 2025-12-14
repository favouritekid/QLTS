# Phân Tích Sâu: Trường `next_activity_at`

Dựa trên yêu cầu của bạn, tôi đã kiểm tra lại source code (cụ thể là hàm `update_lead_next_activity` trong `lead_service.py`) và phát hiện ra một số vấn đề quan trọng về cách trường này đang hoạt động. Nhận định của bạn là chính xác, và đánh giá trong kế hoạch cần được điều chỉnh.

## 1. Cơ chế hiện tại của `next_activity_at`

Hiện tại, giá trị này được cập nhật tự động mỗi khi Consultation thay đổi.
**Logic Code (`lead_service.py`):**
```python
stmt = (
    select(func.min(models.Consultation.scheduled_at))
    .where(
        and_(
            models.Consultation.lead_id == lead_id,
            models.Consultation.scheduled_at.isnot(None),
            models.Consultation.scheduled_at >= now,  # <--- VẤN ĐỀ NẰM Ở ĐÂY
            models.Consultation.reminder_sent == False,
        )
    )
)
```

## 2. Các vấn đề phát hiện

### Vấn đề 1: Tự động "ẩn" các task quá hạn (Critical)
Dòng code `models.Consultation.scheduled_at >= now` đồng nghĩa với việc hệ thống **chỉ quan tâm đến tương lai**.
- **Kịch bản:** Bạn có một lịch hẹn vào 9:00 sáng hôm qua (quá hạn). Lead chưa có lịch mới.
- **Hành vi:**
    - Nếu không ai đụng vào Lead: `next_activity_at` vẫn là 9:00 hôm qua (Hiển thị Overdue đúng).
    - **NHƯNG**, nếu Officer vào sửa SĐT hoặc Email của Lead (trigger update): Hệ thống chạy lại hàm trên -> Thấy lịch 9:00 hôm qua < `now` -> Loại bỏ -> `next_activity_at` trở thành `NULL`.
    => **Lead bị mất dấu hiệu Overdue chỉ vì Officer cập nhật thông tin khác.**

### Vấn đề 2: Dựa vào `reminder_sent` thay vì trạng thái task
Query đang dùng `reminder_sent == False` để xác định task "còn hiệu lực". Điều này rủi ro vì:
- Reminder thường được gửi bởi Cronjob trước giờ hẹn (VD: trước 15p).
- Nếu Reminder đã gửi -> `reminder_sent = True` -> Task bị loại khỏi việc tính `next_activity_at` ngay cả khi giờ hẹn chưa đến hoặc Officer chưa thực hiện.

### Vấn đề 3: Chưa được dùng trong Urgency Score (Đúng như Plan nhận định)
Mặc dù `next_activity_at` tồn tại, nhưng file `insights_service.py` hiện tại hoàn toàn **không đọc** giá trị này để tính điểm khẩn cấp. Do đó, một Lead bị trễ hẹn 5 ngày vẫn có điểm Urgency thấp.

## 3. Kết luận & Đề xuất điều chỉnh Plan

Trong bản kế hoạch nâng cấp, cần bổ sung task: **Fix logic tính toán `next_activity_at` trước, sau đó mới dùng nó để tính điểm.**

**Logic đề xuất (Cần update vào `lead_service.py`):**
1. Tìm `scheduled_at` nhỏ nhất.
2. Điều kiện: Trạng thái Consultation **chưa hoàn thành** (VD: status thuộc nhóm "Pending/Scheduled").
3. **BỎ điều kiện** `scheduled_at >= now` (Để chấp nhận cả task quá hạn).
4. **BỎ điều kiện** `reminder_sent` (Vì không liên quan đến việc task hoàn thành hay chưa).

Khi logic này đúng, cột `is_overdue` trong Plan mới hoạt động chính xác được.
