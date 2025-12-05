# app/tasks.py
"""
Tasks Facade Module - Re-exports Celery tasks for cleaner imports.

This module provides a clean interface for importing Celery tasks throughout
the application, following the Facade Pattern to decouple routers/services
from the underlying Celery implementation.

Architecture Benefits:
- Cleaner imports: `from app.tasks import send_email_task`
- Easier testing: Can mock `app.tasks` instead of `app.celery_utils`
- Separation of concerns: Routers don't need to know about Celery internals
- Single source of truth for all available background tasks

Usage:
    from app.tasks import process_automatic_lead_assignment_task

    # Dispatch task
    process_automatic_lead_assignment_task.delay(lead_id)
"""

# Re-export all Celery tasks from celery_utils
from .celery_utils import (
    broadcast_notification_task,
    check_consultation_reminders_task,
    process_automatic_lead_assignment_task,
    send_login_alert_email_task,
    send_password_reset_confirmation_email_task,
    send_password_reset_email_task,
)

# Explicit __all__ for better IDE support and clarity
__all__ = [
    # Email tasks
    "send_password_reset_email_task",
    "send_login_alert_email_task",
    "send_password_reset_confirmation_email_task",
    # Lead assignment task
    "process_automatic_lead_assignment_task",
    # Notification tasks
    "broadcast_notification_task",
    # Scheduled tasks
    "check_consultation_reminders_task",
]
