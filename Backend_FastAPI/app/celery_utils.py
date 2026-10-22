# app/celery_utils.py
"""
Celery Utilities - BACKWARD COMPATIBILITY LAYER

✅ REFACTORED: This file now serves as a backward compatibility layer.
All tasks have been moved to app/tasks/ modules following best practices.

For new code, import from:
- app.celery_app (for celery_app instance)
- app.tasks (for task functions)

This file re-exports everything for existing imports to continue working.
"""
import asyncio

# Re-export celery_app from new location
from .celery_app import celery_app

# Re-export tasks from new locations for backward compatibility
from .tasks.email_tasks import (
    send_password_reset_email_task,
    send_login_alert_email_task,
    send_password_reset_confirmation_email_task,
    send_magic_link_confirmation_task,
    send_admission_confirmed_notification_task,
)
from .tasks.assignment_tasks import process_automatic_lead_assignment_task
from .tasks.notification_tasks import (
    broadcast_notification_task,
    check_consultation_reminders_task,
    cleanup_old_notifications_task,
)
from .tasks.cache_tasks import (
    recalculate_lead_caches_task,
    sync_kpi_ytd_task,
)

# Keep utility functions for backward compat (used by some tasks)
from .tasks.utils import (
    _create_task_async_engine,
    _create_task_session_maker,
    task_db_session,
)


# V6: hai hook `worker_process_init` / `worker_process_shutdown` từng nằm ở
# đây đã được GỠ. Chúng là hook CHẾT: lệnh worker `celery -A app.celery_app`
# không bao giờ nạp module này (chỉ web/router/service import nó để `.delay()`),
# nên "nơi cấu hình log của worker" này trông như đang chạy mà không chạy.
# Cấu hình log của worker/beat nay nằm ở `app/celery_app.py` (tín hiệu
# `setup_logging` → `app.core.log_redaction.configure_logging`).


# Export all for backward compatibility
__all__ = [
    # Celery app
    "celery_app",
    # Email tasks
    "send_password_reset_email_task",
    "send_login_alert_email_task",
    "send_password_reset_confirmation_email_task",
    "send_magic_link_confirmation_task",
    "send_admission_confirmed_notification_task",
    # Assignment tasks
    "process_automatic_lead_assignment_task",
    # Notification tasks
    # Notification tasks
    "broadcast_notification_task",
    "check_consultation_reminders_task",
    "cleanup_old_notifications_task",
    # Cache tasks
    "recalculate_lead_caches_task",
    "sync_kpi_ytd_task",
    # Utilities
    "_create_task_async_engine",
    "_create_task_session_maker",
    "task_db_session",
]
