# Phụ Lục Bổ Sung: Lead Insights Upgrade Plan
**Trạng thái:** Critical Updates Required
**Ngày:** 2024-12-13

Tài liệu này tổng hợp các điều chỉnh **BẮT BUỘC** phải thực hiện so với bản kế hoạch gốc `lead-insights-upgrade-plan.md`, dựa trên kết quả review kiến trúc và phân tích logic.

---

## 1. Điều chỉnh Kiến Trúc (Architecture & Database)

### 1.1. Tuân thủ Repository Pattern (Bắt buộc)
**Vấn đề:** Plan gốc đề xuất viết query trực tiếp trong `LeadCacheService`.
**Thay đổi:**
- **Không** viết SQL trực tiếp trong Service.
- Di chuyển logic query vào `LeadRepository`.

```python
# app/repositories/lead_repository.py
async def get_consultation_stats(self, lead_id: int) -> dict:
    """
    Lấy thống kê tư vấn để tính cache.
    Trả về: {last_date, count, min_scheduled_future, ...}
    """
    stmt = select(...)
    # ... implementation ...
```

### 1.2. Transaction Management & Anti-Locking
**Vấn đề:** Update Cache chạy song song hoặc tách biệt có thể gây Deadlock/Race Condition khi người dùng thao tác nhanh.
**Thay đổi:**
- `LeadCacheService.update_lead_cache` **PHẢI** chấp nhận `db_session` từ transaction cha (Consultation creation context).
- **CHẠY SYNCHRONOUS TRONG TRANSACTION:** Không offload việc tính toán cache sang background task (Celery) nếu muốn UI cập nhật tức thì. Vì tính toán chỉ mất vài ms, nên chạy ngay trong transaction `add_consultation` là an toàn nhất để đảm bảo Consistency.

**Flow an toàn:**
```
BEGIN TRANSACTION
  1. Create Consultation
  2. Flush (để có ID)
  3. Call LeadCacheService.update_lead_cache(session, lead_id)
     -> Query stats (dùng session hiện tại)
     -> Update Lead columns
  4. Create Log / History
COMMIT
```

---

## 2. Điều chỉnh Logic Nghiệp Vụ (Critical Logic Fixes)

### 2.1. Sửa lỗi `next_activity_at` (Quan trọng)
**Hiện trạng:** Logic hiện tại `scheduled_at >= now` đang tự động xóa các task quá hạn khỏi hệ thống, làm sai lệch đánh giá Urgency.

**Logic Mới:**
1.  **Mục tiêu:** Tìm "Hành động tiếp theo" (Next Action) chưa hoàn thành.
2.  **Filter Condition:**
    - `lead_id` = match
    - `scheduled_at` IS NOT NULL
    - `consultation_status` IN ('planned', 'confirmed')  *(Hoặc các trạng thái mang nghĩa "Chưa xong")*
    - **TUYỆT ĐỐI KHÔNG** filter theo time (`>= now`). Task quá khứ chưa xong vẫn là Next Action (nhưng là Overdue).
    - **TUYỆT ĐỐI KHÔNG** dùng `reminder_sent`.

### 2.2. Logic `Cached Urgency Score`
Cập nhật công thức tính based on logic `next_activity_at` mới:
```python
# Nếu next_activity_at nằm trong quá khứ
days_overdue = (now - lead.next_activity_at).days if lead.next_activity_at < now else 0
urgency_score += min(days_overdue * 5, 30)
```

### 2.3. Quy tắc Follow-up & Cadence (1-3-5-7-14)
**Yêu cầu:** Áp dụng quy tắc "1-3-5-7-14" để gợi ý lịch chăm sóc, tránh Lead bị nguội lạnh.

**Cơ chế hoạt động:**
Khi Officer hoàn thành một Consultation (VD: Gọi điện nhưng khách không nghe), hệ thống sẽ **Tự động gợi ý** `next_activity_at` dựa trên số lần đã tương tác (`consultation_count`).

| Lần tương tác (Touchpoint) | Thời gian chờ (Cadence) | Gợi ý Next Activity |
|---------------------------|-------------------------|---------------------|
| Mới tạo (0) | Ngay lập tức (Day 1) | `created_at` + 15 mins |
| Lần 1 (Day 1) | +2 ngày (Day 3) | `last_consultation_at` + 2 days |
| Lần 2 (Day 3) | +2 ngày (Day 5) | `last_consultation_at` + 2 days |
| Lần 3 (Day 5) | +2 ngày (Day 7) | `last_consultation_at` + 2 days |
| Lần 4 (Day 7) | +7 ngày (Day 14) | `last_consultation_at` + 7 days |
| Sau Day 14 | +30 ngày (Nurturing) | `last_consultation_at` + 30 days |

**Logic Implementation:**
- Nếu `next_activity_at` do Officer set tay -> Ưu tiên dùng.
- Nếu `next_activity_at` là NULL -> Hệ thống hiển thị "Gợi ý: Gọi lại vào [Ngày tính theo bảng trên]" (Soft Reminder).


---

## 3. Checklist Thực Hiện (Updated)

### Phase 1: Core Logic Fixes (Ưu tiên cao nhất)
- [ ] Refactor `LeadRepository`: Thêm phương thức `get_consultation_aggregates`.
- [ ] Fix `update_lead_next_activity`: Loại bỏ điều kiện `>= now` và `reminder_sent`.
- [ ] Database Migration: Thêm các cột cached (như plan gốc).

### Phase 2: Service Layer
- [ ] Implement `LeadCacheService` sử dụng `LeadRepository`.
- [ ] Inject `LeadCacheService` vào `ConsultationService`.
- [ ] Đảm bảo Transaction Propagation (dùng chung session).

### Phase 3: UI Integration
- [ ] Update API response schema.
- [ ] Frontend: Hiển thị Badge Urgency.

---
**Kết luận:** Cần thực hiện **Phase 1** ngay để fix logic dữ liệu nền tảng trước khi làm UI đẹp.
