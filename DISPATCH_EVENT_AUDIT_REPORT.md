# 📊 BÁO CÁO KIỂM TRA DISPATCH EVENTS - QLTS System

**Ngày kiểm tra:** 2025-12-02
**Người kiểm tra:** Claude Code Agent
**Mục đích:** Rà soát toàn bộ 27 events đã định nghĩa và xác minh tình trạng dispatch

---

## 🚨 PHÁT HIỆN LỖI NGHIÊM TRỌNG

### ❌ Bug #1: APPLICATION_SUBMITTED không tồn tại

**Vị trí lỗi:** `app/routers/applications.py:67`

```python
await dispatch(
    db=db,
    event=SystemEvents.APPLICATION_SUBMITTED,  # ❌ Event này KHÔNG TỒN TẠI!
    payload={...}
)
```

**Nguyên nhân:**
- Code đang sử dụng `SystemEvents.APPLICATION_SUBMITTED`
- Nhưng trong `app/core/events.py` chỉ có `APPLICATION_CREATED`, không có `APPLICATION_SUBMITTED`
- Lỗi này khiến dispatch sẽ **FAIL** khi chạy

**Giải pháp:**
```python
# Sửa tại app/routers/applications.py:67
event=SystemEvents.APPLICATION_CREATED,  # ✅ Đúng event name
```

---

## ✅ EVENTS ĐÃ DISPATCH (8/27 = 29.6%)

| # | Event Name | File Location | Line | Status |
|---|------------|---------------|------|--------|
| 1 | LEAD_ASSIGNED | app/routers/leads.py | 317 | ✅ OK |
| 2 | LEAD_STATUS_CHANGED | app/routers/leads.py | 181 | ✅ OK |
| 3 | LEAD_DELETED | app/routers/leads.py | 237 | ✅ OK |
| 4 | CONSULTATION_CREATED | app/routers/leads.py | 280 | ✅ OK |
| 5 | ~~APPLICATION_SUBMITTED~~ | app/routers/applications.py | 67 | ❌ BUG |
| 6 | APPLICATION_STATUS_CHANGED | app/routers/applications.py | 180 | ✅ OK |
| 7 | APPLICATION_DELETED | app/routers/applications.py | 263 | ✅ OK |
| 8 | USER_DEACTIVATED | app/routers/admin/users.py | 904 | ✅ OK |

**Lưu ý:** Thực tế chỉ có **7 events hoạt động đúng**, còn 1 event bị lỗi.

---

## ❌ EVENTS CHƯA DISPATCH (19/27 = 70.4%)

### 🔴 PRIORITY 1 - CẦN LÀM NGAY (Core Business Logic)

#### 1. LEAD_CREATED
- **File:** `app/routers/leads.py`
- **Function:** `create_new_lead()` (line 26)
- **Trigger:** Khi tạo lead mới
- **Tại sao quan trọng:** Đây là điểm khởi đầu của toàn bộ sales funnel
- **Recipients:** Unit managers, admins

**Code cần thêm:**
```python
# app/routers/leads.py:39 (sau return)
async def create_new_lead(...):
    result = await lead_service.create_lead(db, lead_in, created_by=current_user)

    # ✅ THÊM DISPATCH
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.LEAD_CREATED,
            payload={
                "lead_id": result.id,
                "unit_id": result.unit_id,
                "lead_name": result.full_name or result.email,
                "source": result.source,
                "actor_id": current_user.id,
            },
            dedupe_key=f"lead_created:{result.id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch LEAD_CREATED", error=str(e))

    return result
```

---

#### 2. USER_ROLE_CHANGED ⚠️ **ĐÂY LÀ CÂU HỎI CỦA BẠN!**
- **File:** `app/routers/admin/users.py`
- **Function:** `update_user()` (line ~815-823 xử lý unit_id, line ~808-809 xử lý role)
- **Trigger:** Khi admin thêm nhân viên vào unit HOẶC thay đổi role
- **Tại sao quan trọng:** Audit trail cho việc phân quyền, thông báo user về thay đổi
- **Recipients:** User bị thay đổi role/unit

**Trả lời câu hỏi:**
> "Khi thêm nhân viên mới vào unit đã có trigger cho sự kiện này chưa?"

❌ **CHƯA CÓ!** Hiện tại chỉ có dispatch cho `USER_DEACTIVATED` (line 904), không có dispatch cho việc thay đổi role/unit.

**Code cần thêm:**
```python
# app/routers/admin/users.py:898 (sau log activity, trước USER_DEACTIVATED check)

# ✅ Dispatch USER_ROLE_CHANGED if role or unit changed
if "role" in changes or "unit_id" in changes:
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.USER_ROLE_CHANGED,
            payload={
                "user_id": updated_user.id,
                "old_role": changes.get("role", {}).get("old", updated_user.role),
                "new_role": changes.get("role", {}).get("new", updated_user.role),
                "old_unit_id": changes.get("unit_id", {}).get("old"),
                "new_unit_id": changes.get("unit_id", {}).get("new", updated_user.unit_id),
                "actor_id": current_admin.id,
            },
            dedupe_key=f"user_role_changed:{updated_user.id}:{updated_user.role}"
        )
        log.info(
            "User role/unit change notification dispatched",
            target_user_id=updated_user.id,
            admin_id=current_admin.id,
        )
    except Exception as e:
        log.error(f"Failed to dispatch USER_ROLE_CHANGED: {e}")
```

---

#### 3. APPLICATION_CREATED (Fix Bug)
- **File:** `app/routers/applications.py`
- **Function:** `create_application_for_lead()` (line 65)
- **Action:** Sửa event name từ APPLICATION_SUBMITTED → APPLICATION_CREATED

**Code sửa lỗi:**
```python
# app/routers/applications.py:67
await dispatch(
    db=db,
    event=SystemEvents.APPLICATION_CREATED,  # ✅ SỬA: Từ APPLICATION_SUBMITTED
    payload={
        "application_id": application.id,
        "lead_id": application.lead_id,  # ✅ SỬA: Từ applicant_id
        "officer_id": application.officer_id,
        "major_program_name": None,  # Will be updated later
        "actor_id": current_user.id,
    },
    dedupe_key=f"application_created:{application.id}"
)
```

---

#### 4. CONSULTATION_UPDATED
- **File:** Chưa xác định được endpoint update consultation
- **Status:** ⚠️ CẦN TÌM KIẾM hoặc TẠO MỚI endpoint
- **Action Required:**
  1. Tìm endpoint `PUT/PATCH /consultations/{id}`
  2. Hoặc tạo endpoint mới nếu chưa có
  3. Thêm dispatch vào endpoint đó

**Code mẫu:**
```python
@router.put("/consultations/{consultation_id}")
async def update_consultation(...):
    old_status = consultation.consultation_status_id
    updated = await consultation_service.update_consultation(...)

    if old_status != updated.consultation_status_id:
        await dispatch(
            db=db,
            event=SystemEvents.CONSULTATION_UPDATED,
            payload={
                "consultation_id": updated.id,
                "lead_id": updated.lead_id,
                "officer_id": updated.lead.assigned_officer_id,
                "old_status_id": old_status,
                "new_status_id": updated.consultation_status_id,
                "actor_id": current_user.id,
            }
        )
    return updated
```

---

#### 5. CONSULTATION_REMINDER
- **File:** Chưa có Celery task
- **Status:** ⚠️ CẦN TẠO MỚI Celery Beat task
- **Trigger:** Scheduled task chạy mỗi 15 phút, kiểm tra consultations sắp tới trong 30 phút
- **Recipients:** Officer có lịch hẹn

**Code mẫu (Celery task):**
```python
# app/tasks/consultation_tasks.py
from celery import shared_task
from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch

@shared_task
def send_consultation_reminders():
    """Run every 15 minutes to send reminders for upcoming consultations."""
    from app.database import SessionLocal
    from app import models
    from datetime import datetime, timedelta

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        remind_window = now + timedelta(minutes=30)

        consultations = db.query(models.Consultation).filter(
            models.Consultation.scheduled_at.between(now, remind_window),
            models.Consultation.reminder_sent == False
        ).all()

        for consultation in consultations:
            asyncio.run(dispatch(
                db=db,
                event=SystemEvents.CONSULTATION_REMINDER,
                payload={
                    "consultation_id": consultation.id,
                    "lead_id": consultation.lead_id,
                    "lead_name": consultation.lead.full_name,
                    "lead_phone": consultation.lead.phone_number,
                    "officer_id": consultation.lead.assigned_officer_id,
                    "scheduled_at": consultation.scheduled_at.isoformat(),
                    "minutes_until": int((consultation.scheduled_at - now).total_seconds() / 60)
                }
            ))
            consultation.reminder_sent = True

        db.commit()
    finally:
        db.close()
```

---

### 🟡 PRIORITY 2 - Quan trọng nhưng có thể chờ

#### 6. LEAD_ASSIGNMENT_FAILED
- **File:** `app/services/lead_service.py` (auto-assignment logic)
- **Trigger:** Khi auto-assignment thất bại do không có officer available
- **Use case:** Error handling, alert managers

#### 7. LEAD_REASSIGNED
- **File:** `app/routers/leads.py` (nếu có endpoint transfer lead)
- **Trigger:** Khi transfer lead sang unit khác
- **Status:** ⚠️ Cần xác minh có endpoint này chưa

#### 8. APPLICATION_DOCUMENTS_UPDATED
- **File:** Chưa xác định endpoint upload documents
- **Status:** ⚠️ CẦN TÌM hoặc TẠO endpoint

#### 9. CONSULTATION_DELETED
- **File:** Chưa xác định endpoint delete consultation
- **Status:** ⚠️ CẦN TÌM hoặc TẠO endpoint

#### 10. PIPELINE_CONFIG_UPDATED
- **File:** `app/routers/admin/pipeline.py`
- **Trigger:** Khi admin update pipeline stages/statuses
- **Use case:** Audit trail cho config changes

#### 11. OFFICER_AVAILABILITY_CHANGED
- **File:** `app/routers/officer.py` (nếu có endpoint update status)
- **Trigger:** Khi officer đổi trạng thái available/busy
- **Use case:** Workload management, auto-assignment optimization

---

### 🔵 PRIORITY 3 - Future Modules (Chưa có router)

Các events sau đây thuộc các module chưa được implement:

#### Finance Events (3 events)
- DORM_FEE_CREATED
- PAYMENT_RECEIVED
- PAYMENT_OVERDUE

**Status:** ⏸️ Chờ implement finance module

#### Dorm Events (2 events)
- DORM_ROOM_ASSIGNED
- DORM_MAINTENANCE_REQUEST

**Status:** ⏸️ Chờ implement dorm module

#### Asset Events (2 events)
- ASSET_MAINTENANCE_ALERT
- ASSET_CHECKED_OUT

**Status:** ⏸️ Chờ implement asset module

#### System Events (2 events)
- SYSTEM_ALERT
- SYSTEM_ANNOUNCEMENT

**Status:** ⏸️ Chờ implement admin announcement feature

---

## 📈 TỔNG KẾT

| Chỉ số | Số lượng | Tỷ lệ |
|--------|----------|-------|
| **Tổng Events** | 27 | 100% |
| **Đã dispatch (hoạt động)** | 7 | 25.9% |
| **Đã dispatch (lỗi)** | 1 | 3.7% |
| **Chưa dispatch** | 19 | 70.4% |
| ├─ Priority 1 (cần ngay) | 5 | 18.5% |
| ├─ Priority 2 (có thể chờ) | 6 | 22.2% |
| └─ Priority 3 (future) | 8 | 29.6% |

---

## 🎯 ROADMAP IMPLEMENTATION

### Sprint 1 - Critical Fixes (1-2 ngày)
- [x] Fix Bug: APPLICATION_SUBMITTED → APPLICATION_CREATED
- [ ] Add LEAD_CREATED dispatch
- [ ] Add USER_ROLE_CHANGED dispatch
- [ ] Add APPLICATION_CREATED dispatch (fixed)

### Sprint 2 - Core Features (3-5 ngày)
- [ ] Add CONSULTATION_UPDATED endpoint + dispatch
- [ ] Add CONSULTATION_DELETED endpoint + dispatch
- [ ] Create CONSULTATION_REMINDER Celery task
- [ ] Add LEAD_ASSIGNMENT_FAILED dispatch

### Sprint 3 - Enhanced Features (1 tuần)
- [ ] Add LEAD_REASSIGNED dispatch (nếu có endpoint)
- [ ] Add APPLICATION_DOCUMENTS_UPDATED endpoint + dispatch
- [ ] Add PIPELINE_CONFIG_UPDATED dispatch
- [ ] Add OFFICER_AVAILABILITY_CHANGED dispatch

### Sprint 4+ - Future Modules
- [ ] Finance events (chờ module)
- [ ] Dorm events (chờ module)
- [ ] Asset events (chờ module)
- [ ] System announcements (chờ feature)

---

## 🛠️ HƯỚNG DẪN IMPLEMENTATION

### Bước 1: Fix Bug ngay lập tức
```bash
# Sửa file applications.py
sed -i 's/APPLICATION_SUBMITTED/APPLICATION_CREATED/g' app/routers/applications.py

# Cập nhật payload keys cho đúng với schema
# Xem chi tiết ở section "APPLICATION_CREATED (Fix Bug)" ở trên
```

### Bước 2: Thêm dispatch theo thứ tự Priority
1. LEAD_CREATED (dễ, 10 phút)
2. USER_ROLE_CHANGED (dễ, 15 phút)
3. APPLICATION_CREATED fix (dễ, 5 phút)
4. CONSULTATION_UPDATED (trung bình, 30 phút - cần tìm/tạo endpoint)
5. CONSULTATION_REMINDER (khó, 1-2 giờ - cần setup Celery)

### Bước 3: Testing
```bash
# Test mỗi event sau khi thêm
pytest tests/integration/api/test_notifications.py -k "test_event_name"

# Test end-to-end
pytest tests/integration/api/ -v
```

---

## 📝 CHECKLIST VALIDATION

Sau khi implement mỗi event, kiểm tra:

- [ ] Event name đúng với định nghĩa trong `events.py`
- [ ] Payload keys đúng với schema đã documented
- [ ] Có try-except wrapper (không để dispatch làm crash main flow)
- [ ] Có logging khi dispatch fail
- [ ] Có dedupe_key hợp lý (nếu cần)
- [ ] Test case coverage >= 80%
- [ ] Manual test trên staging environment

---

## 🔗 FILES LIÊN QUAN

- **Events Definition:** `app/core/events.py` (500 lines)
- **Dispatcher Service:** `app/services/notification_dispatcher.py`
- **Routers:**
  - `app/routers/leads.py` (958 lines)
  - `app/routers/applications.py` (263 lines)
  - `app/routers/admin/users.py` (~1000 lines)

---

**Người tạo báo cáo:** Claude Code Agent
**Version:** 1.0
**Last Updated:** 2025-12-02
