# app/tasks/email_tasks.py
"""
Email-related Celery tasks.

All tasks in this module handle sending emails:
- Password reset requests
- Login alerts
- Password reset confirmations
"""
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from ..celery_app import celery_app
from ..config import settings


# ============================================================================
# Password Reset Request Email
# ============================================================================
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
        from ..services.email_service import render_email_template, get_email_subject

        html_body, text_body = render_email_template(
            "password_reset_request",
            {"username": username, "reset_url": reset_url},
            lang=lang,
        )
        subject = get_email_subject("password_reset_request", lang=lang)
        
        _send_email(email_to, subject, html_body, text_body)

        task_log.info(f"Password reset request email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send password reset request email to {email_to}", exc_info=True)
        raise e


# ============================================================================
# Login Alert Email
# ============================================================================
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

    Security: Alerts user when anomalous login patterns are detected.
    """
    task_log = logging.getLogger("send_login_alert_email_task")
    task_log.info(f"Login alert task started for recipient: {email_to}")

    try:
        from ..services.email_service import render_email_template, get_email_subject

        login_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

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
                "frontend_url": settings.FRONTEND_URL,
            },
            lang=lang,
        )
        subject = get_email_subject("login_alert", lang=lang)
        
        _send_email(email_to, subject, html_body, text_body)

        task_log.info(f"Login alert email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "ip_address": ip_address, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send login alert email to {email_to}", exc_info=True)
        raise e


# ============================================================================
# Password Reset Confirmation Email
# ============================================================================
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

    Security: Notifies user that their password was changed.
    """
    task_log = logging.getLogger("send_password_reset_confirmation_email_task")
    task_log.info(f"Password reset confirmation task started for recipient: {email_to}")

    try:
        from ..services.email_service import render_email_template, get_email_subject

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
        
        _send_email(email_to, subject, html_body, text_body)

        task_log.info(f"Password reset confirmation email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send password reset confirmation email to {email_to}", exc_info=True)
        raise e


# ============================================================================
# Admission Magic-Link Confirmation Email
# ============================================================================
@celery_app.task(
    name="send_magic_link_confirmation_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_magic_link_confirmation_task(
    email_to: str,
    confirm_url: str,
    lead_name: str,
    expires_at_iso: str,
    expires_days: int,
    lang: str = "vi",
):
    """
    Send magic-link confirmation email to the admission applicant (lead).

    Applicant clicks the link → lands on /confirm/{token} → enters last 4 CCCD
    digits → status transitions to 'confirmed'.
    """
    task_log = logging.getLogger("send_magic_link_confirmation_task")
    if not email_to:
        task_log.warning("No email_to; skipping magic link send")
        return {"status": "skipped", "reason": "no_email"}

    task_log.info(f"Magic link confirmation task started for recipient: {email_to}")

    try:
        from ..services.email_service import render_email_template, get_email_subject

        # Convert UTC timestamp to the configured local timezone (Asia/Ho_Chi_Minh)
        # before formatting — applicants must see the deadline in their own time,
        # not UTC (off by 7 hours for VN users).
        expires_at_dt = datetime.fromisoformat(expires_at_iso)
        expires_at_local = expires_at_dt.astimezone(ZoneInfo(settings.TIMEZONE))
        expires_at_display = expires_at_local.strftime("%d/%m/%Y %H:%M")

        html_body, text_body = render_email_template(
            "admission_confirmation",
            {
                "lead_name": lead_name,
                "confirm_url": confirm_url,
                "expires_at_display": expires_at_display,
                "expires_days": expires_days,
            },
            lang=lang,
        )
        subject = get_email_subject("admission_confirmation", lang=lang)

        _send_email(email_to, subject, html_body, text_body)

        task_log.info(f"Magic link confirmation email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send magic link confirmation email to {email_to}", exc_info=True)
        raise e


# ============================================================================
# Admission Confirmed Success Notification
# ============================================================================
@celery_app.task(
    name="send_admission_confirmed_notification_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_admission_confirmed_notification_task(
    email_to: str,
    lead_name: str,
    confirmed_at_iso: str,
    lang: str = "vi",
):
    """
    Send post-confirmation success email to the applicant.

    Sent after the applicant successfully verifies via magic-link + CCCD,
    letting them know next steps (school will contact within 3 business days).
    """
    task_log = logging.getLogger("send_admission_confirmed_notification_task")
    if not email_to:
        task_log.warning("No email_to; skipping confirmation success notification")
        return {"status": "skipped", "reason": "no_email"}

    task_log.info(f"Admission confirmed notification task started for recipient: {email_to}")

    try:
        from ..services.email_service import render_email_template, get_email_subject

        # Same timezone-aware handling as the magic-link task: applicants see
        # the confirmation timestamp in local (Asia/Ho_Chi_Minh) time.
        confirmed_at_dt = datetime.fromisoformat(confirmed_at_iso)
        confirmed_at_local = confirmed_at_dt.astimezone(ZoneInfo(settings.TIMEZONE))
        confirmed_at_display = confirmed_at_local.strftime("%d/%m/%Y %H:%M")

        html_body, text_body = render_email_template(
            "admission_confirmed_success",
            {
                "lead_name": lead_name,
                "confirmed_at_display": confirmed_at_display,
            },
            lang=lang,
        )
        subject = get_email_subject("admission_confirmed_success", lang=lang)

        _send_email(email_to, subject, html_body, text_body)

        task_log.info(f"Admission confirmed notification sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "lang": lang}
    except Exception as e:
        task_log.error(f"Failed to send admission confirmed notification to {email_to}", exc_info=True)
        raise e


# ============================================================================
# Private Helper Functions
# ============================================================================
def _send_email(to: str, subject: str, html_body: str, text_body: str):
    """
    Send email with both HTML and plain text versions.
    
    Extracted from task functions to reduce duplication.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.MAIL_FROM
    msg["To"] = to

    text_part = MIMEText(text_body, "plain", "utf-8")
    html_part = MIMEText(html_body, "html", "utf-8")
    msg.attach(text_part)
    msg.attach(html_part)

    if settings.MAIL_SSL_TLS:
        # Port 465: implicit SSL/TLS connection
        with smtplib.SMTP_SSL(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)
    else:
        # Port 587: plaintext then upgrade via STARTTLS
        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)
