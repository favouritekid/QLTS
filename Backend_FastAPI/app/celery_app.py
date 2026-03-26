# app/celery_app.py
"""
Celery Application Configuration.

This module contains ONLY the Celery app instance and its configuration.
All tasks are defined in app/tasks/ modules.

Usage:
    from app.celery_app import celery_app

Production deployment:
    # Option 1: All-in-one (suitable for small deployments)
    celery -A app.celery_app worker --beat --concurrency=4 --loglevel=info

    # Option 2: Separated workers (recommended for production)
    # Beat scheduler (run on ONE machine only)
    celery -A app.celery_app beat --loglevel=info

    # General worker
    celery -A app.celery_app worker -Q default,celery --concurrency=4

    # Email worker (dedicated, optional)
    celery -A app.celery_app worker -Q email --concurrency=2

    # Assignment worker (dedicated, optional)
    celery -A app.celery_app worker -Q assignment --concurrency=2
"""
import os
import tempfile

from celery import Celery
from celery.schedules import crontab

from .config import settings

# =============================================================================
# CELERY APPLICATION INSTANCE
# =============================================================================

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND_URL,
)

# =============================================================================
# CORE CONFIGURATION
# =============================================================================

celery_app.conf.update(
    # --- Task Serialization ---
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],  # Security: reject pickle and other formats

    # --- Task Tracking ---
    task_track_started=True,  # Track task status in Redis

    # --- Worker Settings ---
    worker_prefetch_multiplier=1,   # No prefetching - prevents task starvation
    worker_max_tasks_per_child=50,  # Recycle worker after 50 tasks (memory safety)

    # --- Result Backend ---
    result_expires=86400,  # 24 hours - prevents Redis memory growth

    # --- Task Time Limits (safety nets) ---
    task_time_limit=600,       # 10 minutes hard limit (SIGKILL)
    task_soft_time_limit=580,  # 9.5 minutes soft limit (SoftTimeLimitExceeded)

    # --- Broker Connection Resilience ---
    broker_connection_retry_on_startup=True,  # Retry on initial connection failure
    broker_connection_retry=True,              # Retry lost connections
    broker_connection_max_retries=10,          # Max retry attempts

    # --- Security ---
    task_reject_on_worker_lost=True,  # Reject task if worker crashes mid-execution
)

# =============================================================================
# TASK QUEUE ROUTING (Optional - for dedicated workers)
# =============================================================================
# Uncomment and configure when using dedicated workers in production
#
# celery_app.conf.task_routes = {
#     # Email tasks -> dedicated email queue
#     "send_password_reset_email_task": {"queue": "email"},
#     "send_login_alert_email_task": {"queue": "email"},
#     "send_password_reset_confirmation_email_task": {"queue": "email"},
#
#     # Assignment tasks -> dedicated assignment queue
#     "process_automatic_lead_assignment_task": {"queue": "assignment"},
#
#     # Notification tasks -> default queue (or dedicated if needed)
#     "broadcast_notification_task": {"queue": "default"},
#     "execute_notification_delivery": {"queue": "notifications"},  # Phase C1
#     "check_consultation_reminders_task": {"queue": "default"},
#     "cleanup_old_notifications_task": {"queue": "default"},
#
#     # Cache tasks -> default queue
#     "recalculate_lead_caches_task": {"queue": "default"},
#     "sync_kpi_ytd_task": {"queue": "default"},
# }

# =============================================================================
# CELERY BEAT SCHEDULE (Periodic Tasks)
# =============================================================================

celery_app.conf.beat_schedule = {
    # --- High Frequency: Time-sensitive reminders ---
    "check-consultation-reminders-every-minute": {
        "task": "check_consultation_reminders_task",
        "schedule": 60.0,  # Every 60 seconds
        "options": {"queue": "default"},
    },

    # --- Nightly Maintenance Tasks ---
    "recalculate-lead-caches-nightly": {
        "task": "recalculate_lead_caches_task",
        "schedule": crontab(hour=0, minute=5),  # Runs at 00:05 daily
        "options": {"queue": "default"},
    },
    "sync-kpi-ytd-daily": {
        "task": "sync_kpi_ytd_task",
        "schedule": crontab(hour=1, minute=0),  # Runs at 01:00 daily
        "options": {"queue": "default"},
    },
    "sync-kpi-plan-monthly": {
        "task": "sync_kpi_plan_monthly_task",
        "schedule": crontab(hour=2, minute=0, day_of_month=1),  # Day 1, 02:00 AM (spec §6)
        "options": {"queue": "default"},
    },
    "cleanup-old-notifications-daily": {
        "task": "cleanup_old_notifications_task",
        "schedule": crontab(hour=2, minute=30),  # Shifted to 02:30 (was 02:00, now taken by plan sync)
        "options": {"queue": "default"},
    },

    # --- KPI Plan Daily Actuals Sync (P4) ---
    "sync-kpi-plan-actuals-daily": {
        "task": "sync_kpi_plan_actuals_daily_task",
        "schedule": crontab(hour=3, minute=15),  # 03:15 AM daily
        "options": {"queue": "default"},
    },

    # --- Session Maintenance (M1: Idle Session Timeout) ---
    "cleanup-idle-sessions-daily": {
        "task": "cleanup_idle_sessions_task",
        "schedule": crontab(hour=3, minute=0),  # Runs at 03:00 daily
        "options": {"queue": "default"},
    },

    # --- CTV Attribution Expiry (Phase 2) ---
    "check-ctv-attribution-expiry-daily": {
        "task": "check_ctv_attribution_expiry_task",
        "schedule": crontab(hour=4, minute=0),  # Runs at 04:00 daily
        "options": {"queue": "default"},
    },

    # --- Holiday Calendar Yearly Check (Phase A9) ---
    "check-next-year-holidays": {
        "task": "check_next_year_holidays_task",
        "schedule": crontab(hour=9, minute=0, day_of_month=1, month_of_year=11),  # Nov 1, 09:00
        "options": {"queue": "default"},
    },

    # --- CTV Weekly Summary (Phase 2) ---
    "send-ctv-weekly-summary": {
        "task": "send_ctv_weekly_summary_task",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),  # Monday 09:00
        "options": {"queue": "default"},
    },

    # --- Phase C2: Delivery retry sweep ---
    "sweep-retry-deliveries": {
        "task": "sweep_retry_deliveries",
        "schedule": 120,  # Every 2 minutes
        "options": {"queue": "default"},
    },

    # --- Phase C2: Stale delivery reconciliation ---
    "reconcile-stale-deliveries": {
        "task": "reconcile_stale_deliveries",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
        "options": {"queue": "default"},
    },

    # --- Phase D1: Quota sync ---
    "sync-notification-quotas": {
        "task": "sync_notification_quotas",
        "schedule": crontab(minute=0, hour="*/6"),  # Every 6 hours
        "options": {"queue": "default"},
    },

    # --- Phase D3: Notification alert checks ---
    "check-notification-alerts": {
        "task": "check_notification_alerts",
        "schedule": 300,  # Every 5 minutes
        "options": {"queue": "default"},
    },
}

# =============================================================================
# TIMEZONE CONFIGURATION
# =============================================================================

celery_app.conf.timezone = settings.TIMEZONE  # Default: Asia/Ho_Chi_Minh
celery_app.conf.enable_utc = False  # Use local timezone for beat schedule

# =============================================================================
# BEAT SCHEDULE FILE LOCATION
# =============================================================================
# Store beat schedule file outside the watched directory
# This prevents uvicorn --reload from detecting changes to this file
# and causing unnecessary server restarts during development

beat_schedule_dir = os.path.join(tempfile.gettempdir(), "celery-beat")
os.makedirs(beat_schedule_dir, exist_ok=True)
celery_app.conf.beat_schedule_filename = os.path.join(
    beat_schedule_dir, "celerybeat-schedule"
)

# =============================================================================
# TASK AUTODISCOVERY
# =============================================================================

celery_app.autodiscover_tasks(["app.tasks"])
