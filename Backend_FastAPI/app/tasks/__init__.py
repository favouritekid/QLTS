# app/tasks/__init__.py
"""
Celery Tasks Package.

This package organizes Celery tasks by functionality:
- email_tasks: Password reset, login alerts, etc.
- assignment_tasks: Automatic lead assignment
- notification_tasks: Broadcast notifications, reminders
- cache_tasks: Lead cache recalculation, KPI sync

Usage:
    from app.tasks import send_password_reset_email_task
    send_password_reset_email_task.delay(email, url, username)
"""

# Re-export all tasks for convenient imports
from .email_tasks import (
    send_password_reset_email_task,
    send_login_alert_email_task,
    send_password_reset_confirmation_email_task,
)
from .assignment_tasks import process_automatic_lead_assignment_task
from .notification_tasks import (
    broadcast_notification_task,
    check_consultation_reminders_task,
)
from .cache_tasks import (
    recalculate_lead_caches_task,
    sync_kpi_ytd_task,
)
from .session_tasks import cleanup_idle_sessions_task
from .delivery_tasks import (
    execute_notification_delivery,
    sweep_retry_deliveries,
    reconcile_stale_deliveries,
)
from .finance_tasks import check_overdue_invoices_task
from .collaborator_tasks import (
    check_ctv_attribution_expiry_task,
    send_ctv_weekly_summary_task,
)

__all__ = [
    # Email tasks
    "send_password_reset_email_task",
    "send_login_alert_email_task",
    "send_password_reset_confirmation_email_task",
    # Assignment tasks
    "process_automatic_lead_assignment_task",
    # Notification tasks
    "broadcast_notification_task",
    "check_consultation_reminders_task",
    # Cache tasks
    "recalculate_lead_caches_task",
    "sync_kpi_ytd_task",
    # Session tasks
    "cleanup_idle_sessions_task",
    # Delivery tasks (Phase C1+C2)
    "execute_notification_delivery",
    "sweep_retry_deliveries",
    "reconcile_stale_deliveries",
    # Finance tasks
    "check_overdue_invoices_task",
    # Collaborator tasks
    "check_ctv_attribution_expiry_task",
    "send_ctv_weekly_summary_task",
]
