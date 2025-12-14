# Nhận Định & Đánh Giá: Kế Hoạch Nâng Cấp Lead Insights

**Ngày đánh giá:** 2024-12-13  
**Người đánh giá:** AI Assistant (Antigravity)  
**Tài liệu tham chiếu:** `Documents/lead-insights-upgrade-plan.md`

---

## 1. Tổng Quan
Bản kế hoạch **Lead Insights Upgrade** được xây dựng rất bài bản, giải quyết đúng "nỗi đau" của người dùng (Officer) là thiếu thông tin định lượng để ưu tiên công việc.

Giải pháp kỹ thuật đề xuất sử dụng chiến lược **Caching (Denormalization)** là hoàn toàn chính xác. Việc tính toán `Urgency Score` hay `Engagement Score` realtime mỗi khi load danh sách Lead (với hàng nghìn records) sẽ gây overload database. Việc lưu cache kết quả vào bảng `Lead` giúp việc sort/filter trở nên cực nhanh.

## 2. Điểm Mạnh
- **Chiến lược tối ưu hiệu năng:** Sử dụng cột `cached_...` giúp giảm tải query phức tạp khi xem danh sách.
- **Tính thực tế cao:** Các metric như `days_since_contact` hay `overdue` phản ánh đúng nhu cầu quản lý.
- **Backfill Strategy:** Có plan cho việc migrate dữ liệu cũ (Phase 1.5).
- **Frontend/Backend đồng bộ:** Xác định rõ thay đổi ở cả API và UI.

## 3. Các Vấn Đề Cần Lưu Ý (Critical Review)

### 3.1. Tuân thủ Kiến trúc (Architecture Compliance)
*Vấn đề:* Trong mục **4.4 Cache Update Service**, code mẫu đang sử dụng trực tiếp `db.execute(select(...))` để query dữ liệu Consultation.
*Đánh giá:* Điều này vi phạm quy tắc **Repository Pattern** mà dự án đang hướng tới (đã refactor `LeadService`, `AdmissionService`...).
*Khuyến nghị:*
- Logic truy vấn database (Aggregate count, Max date...) cần được đưa vào `LeadRepository` hoặc `ConsultationRepository`.
- `LeadCacheService` chỉ nên gọi Repository để lấy số liệu, sau đó thực hiện logic tính toán business.

**Ví dụ refactor:**
```python
# Trong LeadRepository
async def get_consultation_stats(self, lead_id: int):
    stmt = select(...)
    result = await self.session.execute(stmt)
    return result.one()
    
# Trong LeadCacheService
stats = await lead_repo.get_consultation_stats(lead_id)
lead.last_consultation_at = stats.last_date
```

### 3.2. Quản lý Transaction & Race Conditions
*Vấn đề:* Việc cập nhật cache xảy ra khi "Tạo/Sửa Consultation". Nếu không cẩn thận, việc update Lead trong khi đang update Consultation có thể gây lock hoặc conflict nếu không dùng chung session.
*Khuyến nghị:*
- Đảm bảo `update_lead_cache` nhận vào `db_session` hiện tại của transaction đang xử lý Consultation đó.
- Code mẫu hiện tại `async def update_lead_cache(db: AsyncSession, ...)` là đúng hướng, cần đảm bảo nó được gọi **trước khi commit** transaction chính của `add_consultation` hoặc `update_consultation`.

### 3.3. Urgency Score Logic
*Vấn đề:* Công thức `days_since_contact` đang tính `now - last_consultation_at`.
- Nếu officer vừa log consultation xong -> `days_since = 0`.
- Tuy nhiên, một số loại consultation (như "Gọi điện - Không nghe máy") có thể không nên reset "tính khẩn cấp" hoàn toàn về 0 như "Gặp mặt trực tiếp".
*Khuyến nghị:* (Optional) Cân nhắc trọng số reset dựa trên `consultation_result`. Tuy nhiên, để giữ đơn giản cho version 1, logic hiện tại là chấp nhận được.

### 3.4. Trigger Update
*Vấn đề:* Plan liệt kê các trigger:
- *Cập nhật `next_activity_at`*: Cần hook vào `LeadService.update_lead`.
- *Cập nhật `lead_score`*: Cần hook vào `Service` tính lead score.
*Khuyến nghị:* Sử dụng một hàm wrapper hoặc Event Listener (SQLAlchemy Events) để đảm bảo không bỏ sót case nào. Tuy nhiên, gọi explicit trong Service method (như cách hiện tại) dễ debug hơn.

## 4. Kết luận & Đề xuất hành động

**Trạng thái:** ✅ **SẴN SÀNG TRIỂN KHAI** (với điều chỉnh nhỏ về Repository).

**Các bước điều chỉnh plan:**
1.  **Refactor Design 4.4:** Chuyển query SQL vào `LeadRepository`.
2.  **Implementation:**
    - Tạo migration thêm cột.
    - Implement `LeadRepository` methods.
    - Implement `LeadCacheService` (business logic).
    - Inject service này vào `ConsultationService` và `LeadService`.

Bạn có muốn tôi bắt đầu thực hiện **Phase 1: Backend** (Tạo migration và update Model) ngay bây giờ không?
