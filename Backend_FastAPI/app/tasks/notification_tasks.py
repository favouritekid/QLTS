# app/tasks/notification_tasks.py
"""
Notification-related Celery tasks.

Handles broadcasting notifications via Socket.IO/Email and consultation reminders.
"""
import logging
from datetime import datetime, timedelta, timezone

from ..celery_app import celery_app
from ..config import settings
from .utils import task_db_session, run_async_task, validate_result


# ============================================================================
# Broadcast Notification Task
# ============================================================================
@celery_app.task(
    name="broadcast_notification_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=30,
)
def broadcast_notification_task(
    self,
    notification_ids: list,
    channels: list,
    event: str = "notification"
):
    """
    Celery task to broadcast notifications via Socket.IO and Email.

    Uses standardized error handling. Idempotent: checks if already sent.
    """
    task_name = "broadcast_notification_task"
    task_log = logging.getLogger(task_name)
    task_log.info(
        f"Broadcast task started: {len(notification_ids)} notifications, "
        f"channels={channels}, event={event}"
    )

    async def _run_broadcast():
        from sqlalchemy import select
        from .. import models
        from ..services.email_service import EmailService

        sent_count = 0
        email_count = 0
        failed_count = 0

        async with task_db_session() as session:
            result = await session.execute(
                select(models.Notification)
                .where(models.Notification.id.in_(notification_ids))
            )
            notifications = result.scalars().all()

            if not notifications:
                task_log.warning(f"No notifications found for IDs: {notification_ids}")
                return {"sent": 0, "email": 0, "failed": 0}

            for notification in notifications:
                try:
                    user = await session.get(models.User, notification.user_id)
                    if not user:
                        task_log.warning(f"User {notification.user_id} not found")
                        failed_count += 1
                        continue

                    # ✅ FIX Bug #5: Skip notifications for inactive users
                    if user.status != "active":
                        task_log.debug(f"User {notification.user_id} is inactive, skipping")
                        continue

                    notification_data = notification.data or {}
                    if notification_data.get("_broadcast_sent"):
                        task_log.debug(f"Notification {notification.id} already broadcast")
                        continue

                    if "browser" in channels:
                        sent_count += await _emit_socket_notification(notification)

                    if "email" in channels:
                        email_count += await _send_email_notification(
                            session, user, notification, notification_data
                        )

                    if notification.data is None:
                        notification.data = {}
                    notification.data["_broadcast_sent"] = True
                    notification.data["_broadcast_at"] = datetime.now(timezone.utc).isoformat()

                except Exception as e:
                    task_log.error(f"Failed to process notification {notification.id}: {e}")
                    failed_count += 1

            await session.commit()

        return {"sent": sent_count, "email": email_count, "failed": failed_count}

    # Run with standardized error handling
    result = run_async_task(
        async_func=_run_broadcast,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["sent", "email", "failed"]
    )

    task_log.info(
        f"Broadcast task completed: sent={result['sent']}, "
        f"email={result['email']}, failed={result['failed']}"
    )
    return result


async def _emit_socket_notification(notification) -> int:
    """Emit notification via Socket.IO. Returns 1 if success, 0 otherwise."""
    task_log = logging.getLogger("broadcast_notification_task")
    try:
        from ..socket_manager import sio

        room_name = f"user_room_{notification.user_id}"
        await sio.emit(
            "notification",
            {
                "id": notification.id,
                "type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "link": notification.link,
                "data": notification.data,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
                "is_read": notification.is_read,
            },
            room=room_name
        )
        return 1
    except Exception as e:
        task_log.error(f"Socket emit failed for notification {notification.id}: {e}")
        return 0


async def _send_email_notification(session, user, notification, notification_data) -> int:
    """Send email notification based on user preferences. Returns 1 if sent, 0 otherwise."""
    task_log = logging.getLogger("broadcast_notification_task")
    try:
        from sqlalchemy import select
        from .. import models
        from ..services.email_service import EmailService

        pref_result = await session.execute(
            select(models.NotificationPreference)
            .where(models.NotificationPreference.user_id == user.id)
        )
        pref = pref_result.scalar_one_or_none()

        should_send_email = True
        if pref:
            if not pref.email_enabled:
                should_send_email = False
            if notification_data.get("group"):
                group_prefs = (pref.type_preferences or {}).get(notification_data["group"], {})
                if group_prefs.get("email") is False:
                    should_send_email = False

        if should_send_email and user.email:
            email_service = EmailService()
            if email_service.send_notification_email(
                user.email,
                user.full_name or user.username,
                notification
            ):
                return 1
    except Exception as e:
        task_log.error(f"Email failed for notification {notification.id}: {e}")
    return 0


# ============================================================================
# Consultation Reminder Task (Celery Beat)
# ============================================================================
@celery_app.task(
    name="check_consultation_reminders_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def check_consultation_reminders_task(self):
    """
    Celery Beat periodic task to check and send consultation reminders.

    Uses standardized error handling. Runs every minute.
    """
    import pytz
    
    task_name = "check_consultation_reminders_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting consultation reminder check...")

    async def _run_reminder_check() -> dict:
        from sqlalchemy import and_, select
        from ..core.events import SystemEvents
        from ..models.lead import Consultation, Lead
        from ..services import notification_dispatcher
        from ..services.notification_payloads import EventPayload

        result = {"checked": 0, "sent": 0, "failed": 0}
        post_commit_callbacks = []

        async with task_db_session() as session:
            app_tz = pytz.timezone(settings.TIMEZONE)
            now = datetime.now(timezone.utc).astimezone(app_tz)
            reminder_window = now + timedelta(minutes=15)

            query = (
                select(Consultation, Lead)
                .join(Lead, Consultation.lead_id == Lead.id)
                .where(
                    and_(
                        Lead.deleted_at.is_(None),
                        Consultation.deleted_at.is_(None),
                        Consultation.scheduled_at.isnot(None),
                        Consultation.scheduled_at > now,
                        Consultation.scheduled_at <= reminder_window,
                        Consultation.reminder_sent == False,
                    )
                )
            )

            db_result = await session.execute(query)
            consultations_with_leads = db_result.all()
            result["checked"] = len(consultations_with_leads)

            for consultation, lead in consultations_with_leads:
                try:
                    scheduled = consultation.scheduled_at
                    if scheduled.tzinfo is None:
                        scheduled = app_tz.localize(scheduled)

                    time_diff = scheduled - now
                    minutes_until = max(0, int(time_diff.total_seconds() / 60))

                    _, notif_cb = await notification_dispatcher.dispatch(
                        db=session,
                        event=SystemEvents.CONSULTATION_REMINDER,
                        payload=EventPayload.for_consultation_reminder(
                            consultation, lead, minutes_until=minutes_until,
                        ),
                    )
                    if notif_cb:
                        post_commit_callbacks.append(notif_cb)

                    consultation.reminder_sent = True
                    result["sent"] += 1
                    await session.flush()

                    from ..services.lead_service import update_lead_next_activity
                    await update_lead_next_activity(session, lead.id)
                    await _emit_lead_updated(lead.id)

                except Exception as e:
                    task_log.error(f"Failed to send reminder for consultation #{consultation.id}: {e}")
                    result["failed"] += 1

            await session.commit()
            for cb in post_commit_callbacks:
                await cb()

        return result

    # Run with standardized error handling
    result = run_async_task(
        async_func=_run_reminder_check,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["checked", "sent", "failed"]
    )

    task_log.info(
        f"Reminder check completed: checked={result['checked']}, "
        f"sent={result['sent']}, failed={result['failed']}"
    )
    return result


async def _emit_lead_updated(lead_id: int):
    """Emit lead_updated event to refresh frontend."""
    try:
        from ..socket_manager import sio
        await sio.emit("lead_updated", {
            "lead_id": lead_id,
            "updated_fields": ["next_activity_at"],
            "status_changed": False,
            "updated_by": "system",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logging.getLogger("check_consultation_reminders_task").warning(
            f"Failed to emit lead_updated: {e}"
        )


# ============================================================================
# Cleanup Old Notifications Task
# ============================================================================
@celery_app.task(
    name="cleanup_old_notifications_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def cleanup_old_notifications_task(self):
    """
    Periodic task to clean up old notifications.
    Retention period defaults to 30 days if not configured.
    """
    task_name = "cleanup_old_notifications_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting notification cleanup task...")
    
    async def _run_cleanup():
        from sqlalchemy import delete
        from .. import models
        
        # Default 30 days retention
        retention_days = getattr(settings, "NOTIFICATION_RETENTION_DAYS", 30)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        
        async with task_db_session() as session:
            # Delete old notifications
            result = await session.execute(
                delete(models.Notification)
                .where(models.Notification.created_at < cutoff_date)
            )
            deleted_count = result.rowcount
            await session.commit()
            
        return {"deleted": deleted_count, "cutoff": cutoff_date.isoformat()}

    # Run with standardized error handling
    result = run_async_task(
        async_func=_run_cleanup,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["deleted", "cutoff"]
    )
    
    task_log.info(f"Cleanup completed: deleted {result.get('deleted')} notifications older than {result.get('cutoff')}")
    return result

