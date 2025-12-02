# 🚀 KẾ HOẠCH IMPLEMENTATION - PRIORITY 1 EVENTS

**Tổng quan:** Implement 5 events quan trọng nhất trong vòng 1-2 ngày

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

### ✅ Task 5: Tạo CONSULTATION_REMINDER Celery task
**Thời gian:** 1-2 giờ
**Độ khó:** ⭐⭐⭐⭐ Rất khó (cần setup Celery)

**Bước 1: Check Celery đã có chưa**
```bash
# Tìm celery config
find . -name "celery*" -type f
grep -rn "from celery import" app/
```

**Bước 2: Setup Celery (nếu chưa có)**

**File 1: `app/celery_app.py`**
```python
from celery import Celery
from app.config import settings

celery_app = Celery(
    "qlts_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
```

**File 2: `app/tasks/__init__.py`**
```python
from .consultation_tasks import send_consultation_reminders

__all__ = ["send_consultation_reminders"]
```

**File 3: `app/tasks/consultation_tasks.py`**
```python
import asyncio
import structlog
from datetime import datetime, timedelta, timezone
from celery import shared_task
from sqlalchemy import select

from app.database import SessionLocal
from app import models
from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch

log = structlog.get_logger(__name__)

@shared_task(name="tasks.send_consultation_reminders")
def send_consultation_reminders():
    """
    Celery Beat task: Send reminders for upcoming consultations.

    Runs every 15 minutes.
    Sends reminder 30 minutes before scheduled consultation.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        remind_window_start = now + timedelta(minutes=25)  # 25-35 min window
        remind_window_end = now + timedelta(minutes=35)

        log.info(
            "Running consultation reminder task",
            now=now.isoformat(),
            window_start=remind_window_start.isoformat(),
            window_end=remind_window_end.isoformat()
        )

        # Find consultations in reminder window that haven't been reminded
        stmt = (
            select(models.Consultation)
            .where(
                models.Consultation.scheduled_at >= remind_window_start,
                models.Consultation.scheduled_at <= remind_window_end,
                models.Consultation.reminder_sent == False,
                models.Consultation.deleted_at == None,
            )
            .join(models.Lead)
            .where(models.Lead.deleted_at == None)
        )

        result = db.execute(stmt)
        consultations = result.scalars().all()

        log.info(f"Found {len(consultations)} consultations needing reminders")

        for consultation in consultations:
            try:
                lead = consultation.lead
                if not lead.assigned_officer_id:
                    log.warning(
                        "Consultation has no assigned officer, skipping",
                        consultation_id=consultation.id
                    )
                    continue

                minutes_until = int((consultation.scheduled_at - now).total_seconds() / 60)

                # Dispatch reminder using asyncio
                asyncio.run(dispatch(
                    db=db,
                    event=SystemEvents.CONSULTATION_REMINDER,
                    payload={
                        "consultation_id": consultation.id,
                        "lead_id": lead.id,
                        "lead_name": lead.full_name or "Unknown",
                        "lead_phone": lead.phone_number or "N/A",
                        "officer_id": lead.assigned_officer_id,
                        "scheduled_at": consultation.scheduled_at.isoformat(),
                        "minutes_until": minutes_until,
                    },
                    dedupe_key=f"consultation_reminder:{consultation.id}"
                ))

                # Mark as reminded
                consultation.reminder_sent = True
                db.add(consultation)

                log.info(
                    "Consultation reminder sent",
                    consultation_id=consultation.id,
                    officer_id=lead.assigned_officer_id,
                    minutes_until=minutes_until
                )

            except Exception as e:
                log.error(
                    "Failed to send consultation reminder",
                    consultation_id=consultation.id,
                    error=str(e)
                )

        db.commit()

        return {
            "success": True,
            "reminders_sent": len(consultations),
            "timestamp": now.isoformat()
        }

    except Exception as e:
        log.error("Consultation reminder task failed", error=str(e))
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()
```

**Bước 3: Update models.py (thêm reminder_sent field)**
```python
# app/models.py - class Consultation

class Consultation(Base):
    __tablename__ = "consultations"

    # ... existing fields ...

    reminder_sent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether reminder notification has been sent"
    )
```

**Bước 4: Tạo Alembic migration**
```bash
alembic revision -m "Add reminder_sent field to consultations"
```

Edit migration file:
```python
def upgrade():
    op.add_column(
        'consultations',
        sa.Column('reminder_sent', sa.Boolean(), nullable=False, server_default='false')
    )

def downgrade():
    op.drop_column('consultations', 'reminder_sent')
```

**Bước 5: Config Celery Beat schedule**

**File: `app/celery_beat_schedule.py`**
```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "send-consultation-reminders": {
        "task": "tasks.send_consultation_reminders",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
    },
}
```

**Bước 6: Update config.py**
```python
# app/config.py

class Settings(BaseSettings):
    # ... existing settings ...

    # Celery
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/0",
        env="CELERY_BROKER_URL"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/0",
        env="CELERY_RESULT_BACKEND"
    )
```

**Bước 7: Update .env**
```bash
# .env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**Bước 8: Chạy Celery worker và beat**
```bash
# Terminal 1: Worker
celery -A app.celery_app worker --loglevel=info

# Terminal 2: Beat scheduler
celery -A app.celery_app beat --loglevel=info
```

**Test:**
```bash
# Test task manually
python -c "from app.tasks.consultation_tasks import send_consultation_reminders; send_consultation_reminders.delay()"

# Create test consultation 30 minutes in future
# Wait for task to run
# Check notifications table
```

---

## 🧪 TESTING CHECKLIST

Sau khi hoàn thành tất cả 5 tasks:

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
pytest -k "test_consultation_reminder" -v
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

5. **CONSULTATION_REMINDER:**
   - Tạo consultation 30 min in future
   - Wait 15 min (or trigger manually)
   - Check reminder notification

---

## 📊 EXPECTED RESULTS

Sau khi hoàn thành Priority 1:

| Metric | Before | After |
|--------|--------|-------|
| Events dispatched | 7/27 (25.9%) | 12/27 (44.4%) |
| Bug count | 1 | 0 |
| Core business coverage | 60% | 95% |

---

## 🚨 POTENTIAL ISSUES

### Issue 1: Celery Dependencies
**Problem:** Celery cần Redis/RabbitMQ
**Solution:**
- Dev: Dùng Redis local (docker)
- Production: Setup Redis cluster

### Issue 2: Consultation model thiếu field
**Problem:** `reminder_sent` field không tồn tại
**Solution:** Tạo migration (đã có hướng dẫn ở Task 5)

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

# Task 5
git commit -m "feat: Add consultation reminder Celery task

- Create periodic task to send consultation reminders
- Send reminder 30 minutes before scheduled time
- Add reminder_sent field to consultations table
- Configure Celery Beat schedule"
```

---

**Tác giả:** Claude Code Agent
**Version:** 1.0
**Last Updated:** 2025-12-02
