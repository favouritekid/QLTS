# app/celery_utils.py
import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

# Lấy logger chuẩn của Python
log = logging.getLogger(__name__)

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND_URL,
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
)

# ==================================================================
# === ✅ HELPER: Create async engine inside event loop context ===
# ==================================================================


def _create_task_async_engine():
    """
    Create a new async engine for use within a task's event loop.

    This must be called INSIDE asyncio.run() context to avoid the
    "Future attached to a different loop" error with asyncpg.
    """
    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=3,  # Small pool for single task
        max_overflow=5,
        pool_timeout=30,
    )


def _create_task_session_maker(engine):
    """Create a sessionmaker bound to the given engine."""
    return sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@worker_process_init.connect
def init_worker(**kwargs):
    """
    Initialize logging when worker process starts.
    Note: Async engine is now created per-task to avoid event loop issues.
    """
    print("INFO [celery_utils.py/init_worker]: Initializing worker process...")
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s [%(levelname)-5.5s] [%(name)s] %(message)s",
    )
    log.info(f"Root logger level set to {settings.LOG_LEVEL.upper()}")
    print("INFO [celery_utils.py/init_worker]: Worker logging configured.")


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """Cleanup when worker shuts down."""
    log.info("Shutting down worker process...")


# ==================================================================
# === Tasks ===
# ==================================================================


# ✅ Password reset request email task (forgot password)
@celery_app.task(
    name="send_password_reset_email_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_password_reset_email_task(
    email_to: str,
    reset_url: str,
    username: str,
    lang: str = "vi",
):
    """
    Send password reset request email (forgot password flow).

    Security: Includes 1-hour expiration notice and security warnings.
    """
    task_log = logging.getLogger("send_password_reset_email_task")
    task_log.info(f"Password reset request task started for recipient: {email_to}")

    try:
        # Import email service
        from .services.email_service import render_email_template, get_email_subject

        # Render email from professional template
        html_body, text_body = render_email_template(
            "password_reset_request",
            {
                "username": username,
                "reset_url": reset_url,
            },
            lang=lang,
        )

        subject = get_email_subject("password_reset_request", lang=lang)

        # Send email with both HTML and plain text versions
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to

        # Attach both versions
        text_part = MIMEText(text_body, "plain", "utf-8")
        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Password reset request email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send password reset request email to {email_to}", exc_info=True)
        raise e


# ✅ NEW: Login alert email task
@celery_app.task(
    name="send_login_alert_email_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_login_alert_email_task(
    email_to: str,
    username: str,
    ip_address: str,
    user_agent: str,
    device_type: str,
    browser: str,
    os: str,
    anomalies: dict = None,
    location: str = None,
    lang: str = "vi",
):
    """
    Send login alert email for suspicious activity.

    Security: Alerts user when anomalous login patterns are detected (new IP,
    impossible travel, excessive sessions, unusual time, etc.).
    """
    task_log = logging.getLogger("send_login_alert_email_task")
    task_log.info(f"Login alert task started for recipient: {email_to}")

    try:
        from datetime import datetime, timezone
        from .services.email_service import render_email_template, get_email_subject

        login_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Render email from professional template
        html_body, text_body = render_email_template(
            "login_alert",
            {
                "username": username,
                "login_time": login_time,
                "ip_address": ip_address,
                "location": location,
                "device_type": device_type,
                "browser": browser,
                "os": os,
                "anomalies": anomalies or {},
            },
            lang=lang,
        )

        subject = get_email_subject("login_alert", lang=lang)

        # Send email with both HTML and plain text versions
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to

        # Attach both versions
        text_part = MIMEText(text_body, "plain", "utf-8")
        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Login alert email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "ip_address": ip_address, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send login alert email to {email_to}", exc_info=True)
        raise e


# ✅ NEW: Password reset confirmation email task
@celery_app.task(
    name="send_password_reset_confirmation_email_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_password_reset_confirmation_email_task(
    email_to: str,
    username: str,
    reset_time: str,
    ip_address: str = None,
    location: str = None,
    lang: str = "vi",
):
    """
    Send email notification after successful password reset.

    Security: Notifies user that their password was changed. If user didn't
    initiate the reset, they can take immediate action.
    """
    task_log = logging.getLogger("send_password_reset_confirmation_email_task")
    task_log.info(f"Password reset confirmation task started for recipient: {email_to}")

    try:
        # Import email service
        from .services.email_service import render_email_template, get_email_subject

        # Render email from professional template
        html_body, text_body = render_email_template(
            "password_reset_confirmation",
            {
                "username": username,
                "reset_time": reset_time,
                "ip_address": ip_address,
                "location": location,
                "frontend_url": settings.FRONTEND_URL,
            },
            lang=lang,
        )

        subject = get_email_subject("password_reset_confirmation", lang=lang)

        # Send email with both HTML and plain text versions
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to

        # Attach both versions (email clients will use HTML if supported, fallback to text)
        text_part = MIMEText(text_body, "plain", "utf-8")
        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Password reset confirmation email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send password reset confirmation email to {email_to}", exc_info=True)
        raise e


# Auto-assignment task
@celery_app.task(
    name="process_automatic_lead_assignment_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=30,
)
def process_automatic_lead_assignment_task(self, lead_id: int):
    """
    Celery task for automatic lead assignment.

    Creates async engine INSIDE asyncio.run() to avoid event loop issues.
    """
    task_log = logging.getLogger("process_automatic_lead_assignment_task")
    task_log.info(f"Task received for lead_id: {lead_id}")

    async def _run_async_assignment():
        async_task_log = logging.getLogger("assignment_task_async")

        # Import locally to avoid circular imports
        from .services import assignment_service

        # Create engine INSIDE async context (fixes event loop issue)
        engine = _create_task_async_engine()
        session_maker = _create_task_session_maker(engine)

        try:
            async_task_log.info(f"Creating session for lead_id: {lead_id}")
            async with session_maker() as session:
                async_task_log.debug(
                    f"Session created, calling service for lead_id: {lead_id}"
                )
                await assignment_service.automatically_assign_lead(
                    lead_id, session, logger=async_task_log
                )
                async_task_log.debug(
                    f"Service call finished, committing for lead_id: {lead_id}"
                )
                await session.commit()
                async_task_log.debug(f"Transaction committed for lead_id: {lead_id}")

        finally:
            # Dispose engine after task completes
            await engine.dispose()
            async_task_log.debug(f"Engine disposed for lead_id: {lead_id}")

    try:
        asyncio.run(_run_async_assignment())
        result = {"status": "assigned", "lead_id": lead_id}
        task_log.info(f"Task success for lead_id: {lead_id}. Result: {result}")
        return result
    except Exception as e:
        task_log.error(f"Task failed for lead_id: {lead_id}", exc_info=True)
        raise e


# ==================================================================
# === NEW: Broadcast Notification Task (Event-Driven Architecture) ===
# ==================================================================

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

    This task is called by the notification dispatcher after notifications
    are committed to the database. It handles the actual delivery.

    Args:
        notification_ids: List of notification IDs to broadcast
        channels: List of channels to use (browser, email, sms)
        event: Event name for logging/metrics

    Flow:
        1. Query notifications from database
        2. For each notification:
            a. Emit via Socket.IO (if browser channel)
            b. Send email (if email channel enabled)
        3. Update sent_attempts and last_sent_at
        4. Idempotent: check if already sent before sending

    Returns:
        Dict with status and counts
    """
    task_log = logging.getLogger("broadcast_notification_task")
    task_log.info(
        f"Broadcast task started: {len(notification_ids)} notifications, "
        f"channels={channels}, event={event}"
    )

    async def _run_broadcast():
        from sqlalchemy import select
        from datetime import datetime, timezone
        from . import models
        from .services.email_service import EmailService

        # Create engine INSIDE async context (fixes event loop issue)
        engine = _create_task_async_engine()
        session_maker = _create_task_session_maker(engine)

        sent_count = 0
        email_count = 0
        failed_count = 0

        try:
            async with session_maker() as session:
                # Fetch notifications
                result = await session.execute(
                    select(models.Notification)
                    .where(models.Notification.id.in_(notification_ids))
                )
                notifications = result.scalars().all()

                if not notifications:
                    task_log.warning(f"No notifications found for IDs: {notification_ids}")
                    return {"sent": 0, "email": 0, "failed": 0}

                # Process each notification
                for notification in notifications:
                    try:
                        # Get user info for email
                        user = await session.get(models.User, notification.user_id)
                        if not user:
                            task_log.warning(f"User {notification.user_id} not found")
                            failed_count += 1
                            continue

                        # Check if already sent (idempotency via data field)
                        notification_data = notification.data or {}
                        if notification_data.get("_broadcast_sent"):
                            task_log.debug(f"Notification {notification.id} already broadcast")
                            continue

                        # === Browser/Socket.IO Channel ===
                        if "browser" in channels:
                            try:
                                # Import here to avoid circular imports
                                from .socket_manager import sio

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
                                        "created_at": notification.created_at.isoformat()
                                        if notification.created_at else None,
                                        "is_read": notification.is_read,
                                    },
                                    room=room_name
                                )
                                sent_count += 1
                                task_log.debug(
                                    f"Socket emit success for notification {notification.id} "
                                    f"to room {room_name}"
                                )
                            except Exception as e:
                                task_log.error(
                                    f"Socket emit failed for notification {notification.id}: {e}"
                                )

                        # === Email Channel ===
                        if "email" in channels:
                            try:
                                # Check user preference for email
                                pref_result = await session.execute(
                                    select(models.NotificationPreference)
                                    .where(
                                        models.NotificationPreference.user_id == user.id
                                    )
                                )
                                pref = pref_result.scalar_one_or_none()

                                # Check if email is enabled
                                should_send_email = True
                                if pref:
                                    if not pref.email_enabled:
                                        should_send_email = False
                                    # Check group-specific email preference
                                    if notification_data.get("group"):
                                        group_prefs = (pref.type_preferences or {}).get(
                                            notification_data["group"], {}
                                        )
                                        if group_prefs.get("email") is False:
                                            should_send_email = False

                                if should_send_email and user.email:
                                    email_service = EmailService()
                                    email_sent = email_service.send_notification_email(
                                        user.email,
                                        user.full_name or user.username,
                                        notification
                                    )
                                    if email_sent:
                                        email_count += 1
                                        task_log.debug(
                                            f"Email sent for notification {notification.id}"
                                        )
                            except Exception as e:
                                task_log.error(
                                    f"Email failed for notification {notification.id}: {e}"
                                )

                        # Mark as broadcast (idempotency)
                        if notification.data is None:
                            notification.data = {}
                        notification.data["_broadcast_sent"] = True
                        notification.data["_broadcast_at"] = datetime.now(
                            timezone.utc
                        ).isoformat()

                    except Exception as e:
                        task_log.error(
                            f"Failed to process notification {notification.id}: {e}"
                        )
                        failed_count += 1

                # Commit changes
                await session.commit()

        finally:
            # Dispose engine after task completes
            await engine.dispose()

        return {"sent": sent_count, "email": email_count, "failed": failed_count}

    try:
        result = asyncio.run(_run_broadcast())
        task_log.info(
            f"Broadcast task completed: sent={result['sent']}, "
            f"email={result['email']}, failed={result['failed']}"
        )
        return result
    except Exception as e:
        task_log.error(f"Broadcast task failed: {e}", exc_info=True)
        raise e
