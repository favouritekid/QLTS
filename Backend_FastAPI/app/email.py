# app/email.py
import traceback  # <-- Dùng structlog thay logging

import structlog
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema

from .config import settings

log = structlog.get_logger(__name__)  # <-- Khởi tạo logger structlog

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)

fm = FastMail(conf)


async def send_password_reset_email(email_to: str, reset_url: str, username: str):
    """Gửi email chứa link reset mật khẩu."""
    body = f"""
    <p>Xin chào {username},</p>
    <p>Bạn đã yêu cầu đặt lại mật khẩu. Vui lòng nhấn vào liên kết dưới đây để tiếp tục:</p>
    <p><a href="{reset_url}">{reset_url}</a></p>
    <p>Nếu bạn không yêu cầu điều này, vui lòng bỏ qua email này.</p>
    """
    message = MessageSchema(
        subject="Yêu cầu Đặt lại Mật khẩu",
        recipients=[email_to],
        body=body,
        subtype="html",
    )

    try:
        log.info("Attempting to send password reset email", recipient=email_to)
        await fm.send_message(message)
        log.info("Password reset email task completed", recipient=email_to)
    except Exception as e:
        # === BỔ SUNG LOG CHI TIẾT HƠN ===
        # Ghi lại cả traceback để biết lỗi xảy ra ở đâu
        detailed_error = traceback.format_exc()
        log.error(
            "Failed to send password reset email background task",
            recipient=email_to,
            error=str(e),
            traceback=detailed_error,
            exc_info=False,  # Không cần exc_info nữa vì đã có traceback
        )  # Log khi hoàn thành (không đảm bảo thành công 100%)
