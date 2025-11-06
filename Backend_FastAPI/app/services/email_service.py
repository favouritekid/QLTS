# app/services/email_service.py
"""
Email service for rendering and sending professional email templates.

Uses Jinja2 for template rendering with support for:
- HTML and plain text versions
- Internationalization (i18n)
- Responsive design
- Consistent branding
"""
from pathlib import Path
from typing import Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape


# Path to email templates directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"

# Initialize Jinja2 environment
jinja_env = Environment(
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
