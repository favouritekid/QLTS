# app/celery_app.py
"""
Celery Application Configuration.

This module contains ONLY the Celery app instance and its configuration.
All tasks are defined in app/tasks/ modules.

Usage:
    from app.celery_app import celery_app
"""
from celery import Celery
from celery.schedules import crontab

from .config import settings

# Create Celery app instance
celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND_URL,
)

# Basic configuration
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
)

# Celery Beat Schedule
celery_app.conf.beat_schedule = {
    "check-consultation-reminders-every-minute": {
        "task": "check_consultation_reminders_task",
        "schedule": 60.0,  # Every 60 seconds
    },
    "recalculate-lead-caches-nightly": {
        "task": "recalculate_lead_caches_task",
        "schedule": crontab(hour=0, minute=5),  # Runs at 00:05 daily
    },
    "sync-kpi-ytd-daily": {
        "task": "sync_kpi_ytd_task",
        "schedule": crontab(hour=1, minute=0),  # Runs at 01:00 daily
    },
    "cleanup-old-notifications-daily": {
        "task": "cleanup_old_notifications_task",
        "schedule": crontab(hour=2, minute=0),  # Runs at 02:00 daily
    },
}

# Timezone configuration
celery_app.conf.timezone = settings.TIMEZONE
celery_app.conf.enable_utc = False

# Autodiscover tasks from app.tasks package
celery_app.autodiscover_tasks(["app.tasks"])
