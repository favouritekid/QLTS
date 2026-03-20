# app/services/email_service.py
"""
Email service for rendering and sending professional email templates.

Uses Jinja2 for template rendering with support for:
- HTML and plain text versions
- Internationalization (i18n)
- Responsive design
- Consistent branding
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape as html_escape
from pathlib import Path
from typing import Dict, Any, Optional

import structlog
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import FileSystemLoader, select_autoescape

from ..config import settings
from .. import models

log = structlog.get_logger(__name__)


# Path to email templates directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"

# Initialize Jinja2 sandboxed environment
# ✅ SECURITY: SandboxedEnvironment prevents template injection attacks
# by restricting access to unsafe attributes and methods
jinja_env = SandboxedEnvironment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_email_template(
    template_name: str,
    context: Dict[str, Any],
    lang: str = "vi",
) -> tuple[str, str]:
    """
    Render email template to HTML and plain text.

    Args:
        template_name: Template filename without extension (e.g., "password_reset_request")
        context: Template variables
        lang: Language code (vi, en)

    Returns:
        Tuple of (html_body, text_body)

    Example:
        html, text = render_email_template(
            "password_reset_confirmation",
            {
                "username": "John Doe",
                "reset_time": "2025-11-06 10:30:00 UTC",
                "ip_address": "192.168.1.1",
            },
            lang="vi"
        )
    """
    # Add common variables to context
    context.update({
        "lang": lang,
        "app_name": "QLTS Lead Management",
        "company_name": "Your Company Name",
        "support_email": "support@example.com",
        "current_year": "2025",
    })

    # Render HTML version
    html_template = jinja_env.get_template(f"{template_name}.html")
    html_body = html_template.render(**context)

    # Render plain text version (if exists)
    try:
        text_template = jinja_env.get_template(f"{template_name}.txt")
        text_body = text_template.render(**context)
    except Exception:
        # Fallback to simple text version
        text_body = _generate_simple_text(context)

    return html_body, text_body


def _generate_simple_text(context: Dict[str, Any]) -> str:
    """
    Generate simple plain text version from context.
    Fallback when .txt template doesn't exist.
    """
    lines = ["QLTS Lead Management System", "=" * 40, ""]

    for key, value in context.items():
        if key not in ["lang", "app_name", "company_name", "support_email", "current_year"]:
            lines.append(f"{key.replace('_', ' ').title()}: {value}")

    lines.extend(["", "=" * 40, "This is an automated email. Please do not reply."])

    return "\n".join(lines)


def get_email_subject(template_name: str, lang: str = "vi") -> str:
    """
    Get localized email subject for template.

    Args:
        template_name: Template name
        lang: Language code

    Returns:
        Email subject line
    """
    subjects = {
        "vi": {
            "password_reset_request": "Yêu cầu Đặt lại Mật khẩu",
            "password_reset_confirmation": "🔐 Mật khẩu đã được Đặt lại Thành công",
            "login_alert": "🚨 Cảnh báo Bảo mật: Phát hiện Đăng nhập Đáng ngờ",
            "welcome": "Chào mừng bạn đến với QLTS!",
        },
        "en": {
            "password_reset_request": "Password Reset Request",
            "password_reset_confirmation": "🔐 Your Password Has Been Reset Successfully",
            "login_alert": "🚨 Security Alert: Suspicious Login Detected",
            "welcome": "Welcome to QLTS!",
        },
    }

    return subjects.get(lang, {}).get(template_name, "QLTS Notification")


# ============================================
# EMAIL SENDING SERVICE
# ============================================


class EmailService:
    """Service for sending emails via SMTP."""

    def __init__(self):
        self.smtp_host = settings.MAIL_SERVER
        self.smtp_port = settings.MAIL_PORT
        self.smtp_user = settings.MAIL_USERNAME
        self.smtp_password = settings.MAIL_PASSWORD
        self.from_email = settings.MAIL_FROM
        self.from_name = getattr(settings, "FROM_NAME", "QLTS Notification")

    def _create_connection(self):
        """Create SMTP connection. Supports both SSL/TLS (port 465) and STARTTLS (port 587)."""
        try:
            use_ssl = getattr(settings, "MAIL_SSL_TLS", False)
            use_starttls = getattr(settings, "MAIL_STARTTLS", True)

            if use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.ehlo()
                if use_starttls:
                    server.starttls()
                    server.ehlo()

            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            return server
        except Exception as e:
            log.error("Failed to create SMTP connection", error=str(e))
            raise

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
    ) -> bool:
        """
        Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML email body
            text_body: Plain text email body (optional)

        Returns:
            bool: True if sent successfully, False otherwise
        """
        # Skip if SMTP not configured
        if not self.smtp_user or not self.smtp_password:
            log.warning(
                "SMTP not configured, skipping email",
                to_email=to_email,
                subject=subject,
            )
            return False

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email
            msg["Subject"] = subject

            # Add plain text version
            if text_body:
                part1 = MIMEText(text_body, "plain")
                msg.attach(part1)

            # Add HTML version
            part2 = MIMEText(html_body, "html")
            msg.attach(part2)

            # Send email
            server = self._create_connection()
            server.send_message(msg)
            server.quit()

            log.info("Email sent successfully", to_email=to_email, subject=subject)
            return True

        except Exception as e:
            log.error(
                "Failed to send email", to_email=to_email, subject=subject, error=str(e)
            )
            return False

    def send_notification_email(
        self, user_email: str, user_name: str, notification: models.Notification
    ) -> bool:
        """
        Send notification as email.

        Args:
            user_email: User's email address
            user_name: User's name
            notification: Notification object

        Returns:
            bool: True if sent successfully
        """
        subject = f"[QLTS] {notification.title}"

        # Create HTML body
        html_body = self._render_notification_html(user_name, notification)

        # Create plain text version
        text_body = f"""
{notification.title}

{notification.message}

Type: {notification.type}

{f'View details: {notification.link}' if notification.link else ''}

---
You received this email because you have notifications enabled in your QLTS account.
To manage your notification preferences, visit your Settings page.
"""

        return self.send_email(user_email, subject, html_body, text_body)

    def _render_notification_html(
        self, user_name: str, notification: models.Notification
    ) -> str:
        """Render notification email HTML.

        SECURITY: All user-controlled inputs are HTML-escaped to prevent XSS.
        """
        # ✅ SECURITY FIX (M6): Escape all user-controlled inputs
        safe_name = html_escape(user_name)
        safe_type = html_escape(notification.type)
        safe_title = html_escape(notification.title)
        safe_message = html_escape(notification.message)
        safe_link = html_escape(notification.link) if notification.link else ""

        link_html = ""
        if safe_link:
            link_html = f'<a href="{safe_link}" class="button">View Details</a>'

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #4F46E5; color: white; padding: 20px; text-align: center; }}
        .content {{ background-color: #f9fafb; padding: 30px; border-radius: 8px; margin-top: 20px; }}
        .notification-type {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            margin-bottom: 15px;
        }}
        .type-admin_update {{ background-color: #DBEAFE; color: #1E40AF; }}
        .type-success {{ background-color: #D1FAE5; color: #065F46; }}
        .type-error {{ background-color: #FEE2E2; color: #991B1B; }}
        .type-warning {{ background-color: #FEF3C7; color: #92400E; }}
        .type-info {{ background-color: #E0E7FF; color: #3730A3; }}
        .title {{ font-size: 24px; font-weight: bold; margin-bottom: 15px; }}
        .message {{ font-size: 16px; margin-bottom: 20px; }}
        .button {{
            display: inline-block;
            background-color: #4F46E5;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            margin-top: 20px;
        }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 12px; color: #6B7280; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>QLTS Notification</h1>
        </div>
        <div class="content">
            <p>Hi {safe_name},</p>
            <span class="notification-type type-{safe_type}">{safe_type.upper()}</span>
            <div class="title">{safe_title}</div>
            <div class="message">{safe_message}</div>
            {link_html}
        </div>
        <div class="footer">
            <p>You received this email because you have notifications enabled in your QLTS account.</p>
            <p>To manage your notification preferences, visit your Settings page.</p>
        </div>
    </div>
</body>
</html>
"""


# Create singleton instance
email_service = EmailService()
