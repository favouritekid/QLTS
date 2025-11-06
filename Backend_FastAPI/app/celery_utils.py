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


# Email task (Giữ nguyên là sync)
@celery_app.task(
    name="send_password_reset_email_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_password_reset_email_task(email_to: str, reset_url: str, username: str):
    """Sync Celery task để gửi email reset password."""
    task_log = logging.getLogger("send_password_reset_email_task")
    task_log.info(f"Task started for recipient: {email_to}")

    body = f"""
    <html><body><p>Xin chào {username},</p><p>Bạn đã yêu cầu...</p>
    <p><a href="{reset_url}">{reset_url}</a></p><p>Nếu bạn không yêu cầu...</p>
    </body></html>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[Celery] Yêu cầu Đặt lại Mật khẩu"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to
        html_part = MIMEText(body, "html")
        msg.attach(html_part)
        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)
        task_log.info(f"Email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to}
    except Exception as e:
        task_log.error(f"Failed to send email to {email_to}", exc_info=True)
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
    anomalies: dict = None,  # ✅ NEW: Anomaly details
):
    """Sync Celery task to send login alert email for suspicious activity."""
    task_log = logging.getLogger("send_login_alert_email_task")
    task_log.info(f"Login alert task started for recipient: {email_to}")

    from datetime import datetime, timezone  # ✅ SỬA LỖI (F821): Thêm `timezone`

    login_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # Build anomaly warnings
    anomaly_warnings = ""
    if anomalies:
        warnings = []
        if anomalies.get("new_ip"):
            warnings.append("⚠️ Địa chỉ IP mới chưa từng sử dụng")
        if anomalies.get("new_device"):
            warnings.append("⚠️ Thiết bị/trình duyệt mới")
        if anomalies.get("impossible_travel"):
            warnings.append("⚠️ Đăng nhập từ vị trí khác thường trong thời gian ngắn")
        if anomalies.get("excessive_sessions"):
            warnings.append("⚠️ Số lượng phiên đăng nhập đồng thời cao bất thường")
        if anomalies.get("unusual_time"):
            warnings.append("⚠️ Đăng nhập vào thời gian bất thường")

        if warnings:
            anomaly_warnings = f"""
            <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #856404;">🚨 Cảnh báo Bảo mật</h3>
                <ul style="margin-bottom: 0;">
                    {''.join(f'<li>{w}</li>' for w in warnings)}
                </ul>
            </div>
            """

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #d32f2f;">🔐 Cảnh báo Đăng nhập Đáng ngờ</h2>
            <p>Xin chào <strong>{username}</strong>,</p>
            <p>Chúng tôi phát hiện một hoạt động đăng nhập đáng ngờ vào tài khoản của bạn:</p>

            {anomaly_warnings}

            <h3>Chi tiết Đăng nhập:</h3>
            <table style="border-collapse: collapse; margin: 20px 0; width: 100%;">
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Thời gian:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{login_time}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Địa chỉ IP:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{ip_address}</td>
                </tr>
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Thiết bị:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{device_type.capitalize()}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Trình duyệt:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{browser}</td>
                </tr>
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Hệ điều hành:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{os}</td>
                </tr>
            </table>

            <div style="background-color: #e8f5e9; border-left: 4px solid #4caf50; padding: 15px; margin: 20px 0;">
                <p style="margin: 0;"><strong>✅ Nếu đây là bạn:</strong> Không cần làm gì cả. Bạn có thể bỏ qua email này.</p>
            </div>

            <div style="background-color: #ffebee; border-left: 4px solid #f44336; padding: 15px; margin: 20px 0;">
                <p style="margin-top: 0;"><strong>❌ Nếu đây KHÔNG phải là bạn:</strong></p>
                <ol style="margin-bottom: 0;">
                    <li><strong>Đổi mật khẩu ngay lập tức</strong></li>
                    <li>Kiểm tra và revoke các phiên đăng nhập đáng ngờ trong cài đặt tài khoản</li>
                    <li>Bật xác thực hai yếu tố (2FA) nếu chưa có</li>
                    <li>Liên hệ với bộ phận hỗ trợ nếu bạn nghi ngờ tài khoản bị xâm nhập</li>
                </ol>
            </div>

            <p style="color: #666; font-size: 12px; margin-top: 30px; border-top: 1px solid #ddd; padding-top: 15px;">
                Email này được gửi tự động từ hệ thống Lead Management System.<br>
                Vui lòng không trả lời email này.
            </p>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🚨 Cảnh báo Bảo mật: Phát hiện hoạt động đăng nhập đáng ngờ"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to
        html_part = MIMEText(body, "html")
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Login alert email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "ip_address": ip_address}
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
):
    """
    Send email notification after successful password reset.

    Security: Notifies user that their password was changed. If user didn't
    initiate the reset, they can take immediate action.
    """
    task_log = logging.getLogger("send_password_reset_confirmation_email_task")
    task_log.info(f"Password reset confirmation task started for recipient: {email_to}")

    # Format location if available
    location_info = ""
    if location:
        location_info = f"""
        <tr>
            <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Location:</td>
            <td style="padding: 10px; border: 1px solid #ddd;">{location}</td>
        </tr>
        """

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2e7d32;">🔐 Your Password Has Been Reset</h2>
            <p>Hi <strong>{username}</strong>,</p>
            <p>This email confirms that your password was successfully reset.</p>

            <h3>Reset Details:</h3>
            <table style="border-collapse: collapse; margin: 20px 0; width: 100%;">
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Time:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{reset_time}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">IP Address:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{ip_address or 'Unknown'}</td>
                </tr>
                {location_info}
            </table>

            <div style="background-color: #e3f2fd; border-left: 4px solid #2196f3; padding: 15px; margin: 20px 0;">
                <p style="margin: 0;"><strong>ℹ️ Important Security Information:</strong></p>
                <ul style="margin-bottom: 0;">
                    <li>All your active sessions have been logged out for security</li>
                    <li>You'll need to log in again with your new password</li>
                </ul>
            </div>

            <div style="background-color: #e8f5e9; border-left: 4px solid #4caf50; padding: 15px; margin: 20px 0;">
                <p style="margin: 0;"><strong>✅ If this was you:</strong> You can safely ignore this email.</p>
            </div>

            <div style="background-color: #ffebee; border-left: 4px solid #f44336; padding: 15px; margin: 20px 0;">
                <p style="margin-top: 0;"><strong>❌ If you did NOT reset your password:</strong></p>
                <p><strong>Your account may be compromised!</strong> Take these steps immediately:</p>
                <ol style="margin-bottom: 0;">
                    <li><strong>Reset your password again</strong> using a secure device</li>
                    <li>Check your email account security (someone may have access)</li>
                    <li>Enable Two-Factor Authentication (2FA) if available</li>
                    <li>Contact support immediately if you suspect unauthorized access</li>
                </ol>
            </div>

            <div style="text-align: center; margin: 30px 0;">
                <p style="margin-bottom: 10px;">Need help securing your account?</p>
                <a href="{settings.FRONTEND_URL}/settings/security"
                   style="display: inline-block; padding: 12px 24px; background-color: #2196f3; color: white; text-decoration: none; border-radius: 4px; font-weight: bold;">
                    Review Security Settings
                </a>
            </div>

            <p style="color: #666; font-size: 12px; margin-top: 30px; border-top: 1px solid #ddd; padding-top: 15px;">
                This email was sent automatically from QLTS Lead Management System.<br>
                Please do not reply to this email.
            </p>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🔐 Your Password Has Been Reset Successfully"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to
        html_part = MIMEText(body, "html")
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Password reset confirmation email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to}
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
