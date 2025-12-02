# 🚀 KẾ HOẠCH IMPLEMENTATION - PRIORITY 1 EVENTS

**Tổng quan:** Implement 4 events quan trọng nhất trong vòng 1 ngày

**⚠️ Cập nhật:** CONSULTATION_REMINDER đã được implement (celery_utils.py:558-692)

---

## 📋 DANH SÁCH TASKS

### ✅ Task 1: Fix Bug APPLICATION_SUBMITTED → APPLICATION_CREATED
**Thời gian:** 5-10 phút
**Độ khó:** ⭐ Dễ
**File:** `app/routers/applications.py`

**Chi tiết:**
1. Đổi event name từ `APPLICATION_SUBMITTED` → `APPLICATION_CREATED` (line 67)
2. Cập nhật payload keys cho đúng schema:
   - `applicant_id` → `lead_id`
   - `applicant_name` → Không cần (không có trong schema)
   - `applicant_email` → Không cần (không có trong schema)
   - Thêm `major_program_name` (có thể null)

**Code:**
```python
# app/routers/applications.py:65-82
await dispatch(
    db=db,
    event=SystemEvents.APPLICATION_CREATED,  # ✅ Fixed
    payload={
        "application_id": application.id,
        "lead_id": application.lead_id,      # ✅ Fixed
        "officer_id": application.officer_id,
        "major_program_name": None,          # ✅ Added
        "actor_id": current_user.id,
    },
    dedupe_key=f"application_created:{application.id}"
)
```

**Test:**
```bash
# Test tạo application
pytest tests/integration/api/test_applications.py::test_create_application -v

# Verify notification được tạo
pytest tests/integration/api/test_notifications.py -k "application_created"
```

---

### ✅ Task 2: Add LEAD_CREATED dispatch
**Thời gian:** 10-15 phút
**Độ khó:** ⭐ Dễ
**File:** `app/routers/leads.py`

**Chi tiết:**
Thêm dispatch sau khi tạo lead thành công tại function `create_new_lead()`

**Code:**
```python
# app/routers/leads.py:26-39
@router.post("", response_model=schemas.Lead, status_code=status.HTTP_201_CREATED)
async def create_new_lead(
    lead_in: schemas.LeadCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Tạo một Lead mới."""
    result = await lead_service.create_lead(db, lead_in, created_by=current_user)

    # ✅ THÊM: Dispatch LEAD_CREATED event
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.LEAD_CREATED,
            payload={
                "lead_id": result.id,
                "unit_id": result.unit_id,
                "lead_name": result.full_name or result.email or f"Lead #{result.id}",
                "source": result.source,
                "actor_id": current_user.id,
            },
            dedupe_key=f"lead_created:{result.id}"
        )
        log.info(
            "LEAD_CREATED notification dispatched",
            lead_id=result.id,
            actor_id=current_user.id
        )
    except Exception as e:
        log.warning("Failed to dispatch LEAD_CREATED notification", error=str(e))

    return result
```

**Import cần thêm (nếu chưa có):**
```python
# Ở đầu file leads.py
import structlog
log = structlog.get_logger(__name__)
```

**Test:**
```bash
pytest tests/integration/api/leads/test_leads_crud.py::test_create_lead -v
```

---

### ✅ Task 3: Add USER_ROLE_CHANGED dispatch
**Thời gian:** 15-20 phút
**Độ khó:** ⭐⭐ Trung bình
**File:** `app/routers/admin/users.py`

**Chi tiết:**
Thêm dispatch vào function `update_user()` sau khi log activity, kiểm tra nếu role hoặc unit_id thay đổi

**Vị trí chèn code:** Sau line 897 (sau log_admin_activity), trước line 899 (trước check USER_DEACTIVATED)

**Code:**
```python
# app/routers/admin/users.py:898 (insert here)

    # ✅ THÊM: Dispatch USER_ROLE_CHANGED if role or unit changed
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
                    "old_unit_id": int(changes.get("unit_id", {}).get("old")) if changes.get("unit_id", {}).get("old") and changes.get("unit_id", {}).get("old") != "None" else None,
                    "new_unit_id": updated_user.unit_id,
                    "actor_id": current_admin.id,
                },
                dedupe_key=f"user_role_changed:{updated_user.id}:{datetime.utcnow().isoformat()}"
            )
            log.info(
                "USER_ROLE_CHANGED notification dispatched",
                target_user_id=updated_user.id,
                admin_id=current_admin.id,
                changes=list(changes.keys())
            )
        except Exception as e:
            log.error(
                "Failed to dispatch USER_ROLE_CHANGED notification",
                error=str(e),
                target_user_id=updated_user.id
            )

    # Dispatch USER_DEACTIVATED notification if status changed to inactive
    # (existing code continues...)
```

**Test:**
```bash
# Test update user role
pytest tests/integration/api/admin/test_users_api.py::test_update_user_role -v

# Test update user unit
pytest tests/integration/api/admin/test_users_api.py::test_update_user_unit -v
```

---

### ✅ Task 4: Tìm và add CONSULTATION_UPDATED dispatch
**Thời gian:** 30-45 phút
**Độ khó:** ⭐⭐⭐ Khó (cần tìm endpoint)

**Bước 1: Tìm endpoint update consultation**
```bash
# Search trong codebase
grep -rn "def.*update.*consultation" app/routers/
grep -rn "@router.put\|@router.patch" app/routers/ | grep consultation
```

**Bước 2: Nếu không có endpoint, tạo mới**

Có 2 options:
- **Option A:** Tạo endpoint riêng `app/routers/consultations.py`
- **Option B:** Thêm vào `app/routers/leads.py` (vì consultation thuộc về lead)

**Khuyến nghị:** Option B (đơn giản hơn, consistent với CONSULTATION_CREATED)

**Code mẫu (nếu cần tạo endpoint):**
```python
# app/routers/leads.py

@router.put(
    "/{lead_id}/consultations/{consultation_id}",
    response_model=schemas.Consultation
)
async def update_consultation_record(
    lead_id: int,
    consultation_id: int,
    consultation_update: schemas.ConsultationUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Update consultation record."""

    # Get existing consultation
    consultation = await db.get(models.Consultation, consultation_id)
    if not consultation or consultation.lead_id != lead_id:
        raise ResourceNotFoundError(detail="Consultation not found")

    # Store old status
    old_status = consultation.consultation_status_id

    # Update consultation
    for key, value in consultation_update.dict(exclude_unset=True).items():
        setattr(consultation, key, value)

    await db.commit()
    await db.refresh(consultation)

    # ✅ Dispatch CONSULTATION_UPDATED if status changed
    if old_status != consultation.consultation_status_id:
        try:
            from app.services.notification_dispatcher import dispatch
            from app.core.events import SystemEvents
            await dispatch(
                db=db,
                event=SystemEvents.CONSULTATION_UPDATED,
                payload={
                    "consultation_id": consultation.id,
                    "lead_id": lead_id,
                    "officer_id": consultation.lead.assigned_officer_id,
                    "old_status_id": old_status,
                    "new_status_id": consultation.consultation_status_id,
                    "actor_id": current_user.id,
                },
                dedupe_key=f"consultation_updated:{consultation.id}:{consultation.consultation_status_id}"
            )
        except Exception as e:
            log.warning("Failed to dispatch CONSULTATION_UPDATED", error=str(e))

    return consultation
```

**Bước 3: Tạo schema nếu chưa có**
```python
# app/schemas.py (hoặc schemas/consultation.py)

class ConsultationUpdate(BaseModel):
    consultation_status_id: Optional[str] = None
    notes: Optional[str] = None
    scheduled_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

**Test:**
```bash
pytest tests/integration/api/test_consultations.py::test_update_consultation -v
```

---

### ✅ ~~Task 5: Tạo CONSULTATION_REMINDER Celery task~~ (ĐÃ CÓ)

**Status:** ✅ **ĐÃ ĐƯỢC IMPLEMENT**

**Vị trí:** `app/celery_utils.py` (line 558-692)

**Chi tiết implementation:**
- Celery task: `check_consultation_reminders_task`
- Beat schedule: Chạy mỗi 60 giây (line 700-704)
- Event dispatch: SystemEvents.CONSULTATION_REMINDER (line 644)
- Database field: `reminder_sent` có sẵn trong Consultation model
- Logic: Tìm consultations trong 15 phút tiếp theo, dispatch reminder, mark reminder_sent=True
- Error handling: Try-catch per consultation + auto retry (max 2 retries)
- Timezone: Dùng pytz + settings.TIMEZONE

**Verification:**
```bash
# Xem task code
cat app/celery_utils.py | sed -n '558,692p'

# Check beat schedule
grep -A 5 "beat_schedule" app/celery_utils.py
```

**Không cần làm gì thêm** - Task này đã hoàn chỉnh và production-ready.


## 🧪 TESTING CHECKLIST

Sau khi hoàn thành tất cả 4 tasks cần implement (Task 5 đã có sẵn):

### Unit Tests
```bash
# Test individual events
pytest tests/unit/test_notification_dispatcher.py -v
```

### Integration Tests
```bash
# Test full flow
pytest tests/integration/api/test_notifications.py -v

# Test specific events
pytest -k "test_lead_created" -v
pytest -k "test_user_role_changed" -v
pytest -k "test_application_created" -v
pytest -k "test_consultation_updated" -v
pytest -k "test_consultation_reminder" -v  # ✅ Đã có task
```

### Manual Tests
1. **LEAD_CREATED:**
   - Tạo lead mới qua API
   - Check notifications table
   - Check notification rules được trigger

2. **USER_ROLE_CHANGED:**
   - Admin update user role
   - Admin assign user to unit
   - Check user nhận notification

3. **APPLICATION_CREATED:**
   - Tạo application cho lead
   - Check officer nhận notification

4. **CONSULTATION_UPDATED:**
   - Update consultation status
   - Check notification

5. **CONSULTATION_REMINDER:** ✅ **Đã có task**
   - Tạo consultation trong 15 phút tiếp theo
   - Wait for Celery Beat (max 60s)
   - Check reminder notification

---

## 📊 EXPECTED RESULTS

Sau khi hoàn thành Priority 1:

| Metric | Before | After |
|--------|--------|-------|
| Events dispatched | 8/27 (29.6%) | 12/27 (44.4%) |
| Bug count | 1 | 0 |
| Core business coverage | 70% | 95% |

**Lưu ý:** CONSULTATION_REMINDER đã được implement, nên số liệu Before đã bao gồm event này (8/27 thay vì 7/27).

---

## 🚨 POTENTIAL ISSUES

### Issue 1: Celery Dependencies
**Problem:** Celery cần Redis/RabbitMQ
**Solution:**
- Dev: Dùng Redis local (docker)
- Production: Setup Redis cluster

### Issue 2: Consultation model thiếu field
**Problem:** `reminder_sent` field không tồn tại
**Solution:** ✅ Field đã có sẵn trong model (models/lead.py:110)

### Issue 3: Performance
**Problem:** Dispatch quá nhiều notifications có thể chậm
**Solution:**
- Đã có try-except để không block main flow
- Consider async dispatch với background tasks

---

## 📝 COMMIT MESSAGES

Mẫu commit message cho từng task:

```bash
# Task 1
git commit -m "fix: Change APPLICATION_SUBMITTED to APPLICATION_CREATED

- Fix bug where APPLICATION_SUBMITTED event doesn't exist
- Update payload to match APPLICATION_CREATED schema
- Remove unnecessary fields from payload"

# Task 2
git commit -m "feat: Add LEAD_CREATED event dispatch

- Dispatch LEAD_CREATED when new lead is created
- Notify unit managers about new leads
- Add error handling for dispatch failures"

# Task 3
git commit -m "feat: Add USER_ROLE_CHANGED event dispatch

- Dispatch when user role changes
- Dispatch when user unit assignment changes
- Notify affected user about changes"

# Task 4
git commit -m "feat: Add CONSULTATION_UPDATED endpoint and dispatch

- Create PUT endpoint for updating consultations
- Dispatch CONSULTATION_UPDATED on status change
- Add ConsultationUpdate schema"

# Task 5 - ĐÃ CÓ SẴN
# ✅ CONSULTATION_REMINDER đã được implement (celery_utils.py:558-692)
# Không cần commit gì thêm
```

---

**Tác giả:** Claude Code Agent
**Version:** 1.0
**Last Updated:** 2025-12-02
