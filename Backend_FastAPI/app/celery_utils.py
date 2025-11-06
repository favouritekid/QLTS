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
# === ✅ KHAI BÁO BIẾN TOÀN CỤC CHO WORKER PROCESS ===
# ==================================================================
celery_async_engine = None
CeleryScopedSessionMaker = None
# ==================================================================


@worker_process_init.connect
def init_worker(**kwargs):
    """
    ✅ Khởi tạo Engine và SessionMaker MỘT LẦN
    khi worker process khởi động.
    """
    global celery_async_engine, CeleryScopedSessionMaker

    print("INFO [celery_utils.py/init_worker]: Initializing worker process...")
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s [%(levelname)-5.5s] [%(name)s] %(message)s",
    )
    log.info(f"Root logger level set to {settings.LOG_LEVEL.upper()}")

    try:
        celery_async_engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,  # Giảm pool size cho worker
            max_overflow=10,
            pool_timeout=30,
        )

        CeleryScopedSessionMaker = sessionmaker(
            bind=celery_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        print(
            "INFO [celery_utils.py/init_worker]: DB Engine & SessionMaker CREATED for worker."
        )
    except Exception as e:
        print(
            f"CRITICAL [celery_utils.py/init_worker]: FAILED to create DB Engine. Error: {e}"
        )
        # Nếu không tạo được engine, các task sẽ fail, điều này là chấp nhận được


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """Hủy Engine khi worker tắt."""
    # ✅ SỬA LỖI (F824): Xóa `global` vì biến này chỉ được đọc, không bị gán.
    # global celery_async_engine
    if celery_async_engine:
        print("INFO [celery_utils.py/shutdown_worker]: Disposing DB Engine...")
        # Chạy dispose trong một event loop tạm thời nếu cần
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(celery_async_engine.dispose())
            else:
                loop.run_until_complete(celery_async_engine.dispose())
            print("INFO [celery_utils.py/shutdown_worker]: DB Engine disposed.")
        except Exception as e:
            print(
                f"ERROR [celery_utils.py/shutdown_worker]: Failed to dispose engine. Error: {e}"
            )

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


# Auto-assignment task (QUAY LẠI HÀM SYNC `def`)
@celery_app.task(
    name="process_automatic_lead_assignment_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=30,
)
def process_automatic_lead_assignment_task(self, lead_id: int):  # <--- QUAY LẠI `def`
    """
    Sync Celery task. Sử dụng Engine/Session CÓ SẴN.
    """
    task_log = logging.getLogger("process_automatic_lead_assignment_task")
    task_log.info(f"Task received for lead_id: {lead_id}")

    # ✅ KIỂM TRA NẾU SESSIONMAKER CHƯA SẴN SÀNG
    if not CeleryScopedSessionMaker:
        task_log.error("CeleryScopedSessionMaker not initialized. Retrying task...")
        # Yêu cầu task thử lại sau 10 giây
        raise self.retry(exc=Exception("DB Engine not ready"), countdown=10)

    async def _run_async_assignment_with_engine():
        # Lấy logger chuẩn bên trong hàm async
        async_task_log = logging.getLogger("assignment_task_async")

        # ✅ IMPORT CỤC BỘ (Sửa lỗi Circular Import)
        from .services import assignment_service

        # 1. & 2. ✅ SỬ DỤNG LẠI SESSIONMAKER TOÀN CỤC
        # (Không cần tạo engine/sessionmaker mới)

        try:
            async_task_log.info(
                f"Engine exists. Creating session for lead_id: {lead_id}"
            )
            async with CeleryScopedSessionMaker() as session:  # <--- Dùng SessionMaker đã tạo
                async_task_log.debug(
                    f"Session created, calling service for lead_id: {lead_id}"
                )
                # Truyền logger vào service
                await assignment_service.automatically_assign_lead(
                    lead_id, session, logger=async_task_log
                )
                async_task_log.debug(
                    f"Service call finished, committing for lead_id: {lead_id}"
                )

                # === BƯỚC QUAN TRỌNG ĐÃ SỬA TỪ LỖI TIMEOUT TRƯỚC ===
                await session.commit()
                # ===================================================

                async_task_log.debug(f"Transaction committed for lead_id: {lead_id}")

        finally:
            # 3. ✅ KHÔNG CẦN HỦY ENGINE Ở ĐÂY
            async_task_log.debug(
                f"Task finished, session closed for lead_id: {lead_id}"
            )

    try:
        # Chạy hàm async
        asyncio.run(_run_async_assignment_with_engine())
        result = {"status": "assigned", "lead_id": lead_id}
        task_log.info(f"Task success for lead_id: {lead_id}. Result: {result}")
        return result
    except Exception as e:
        task_log.error(f"Task failed for lead_id: {lead_id}", exc_info=True)
        raise e
