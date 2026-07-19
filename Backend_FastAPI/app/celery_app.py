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
    # `include` is the canonical way to ensure the worker entrypoint
    # `celery -A app.celery_app worker/beat` loads our task modules. The
    # `autodiscover_tasks(["app.tasks"])` call below is lazy (waits for
    # `app.finalize()`); `include` runs at finalize too but binds an
    # explicit module list — no reliance on Celery's package-walking
    # heuristic for `related_name`. T0-4a verified via subprocess test that
    # without `include` here, importing only `app.celery_app` (the worker's
    # entrypoint module) registers ZERO business tasks until something
    # else triggers `app.finalize()` or imports `app.tasks` directly.
    include=["app.tasks"],
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

    # --- ADM-028 (2026-04-29): magic-link expiry reminders ---
    # 30 min cadence: worst-case lag between an applicant crossing
    # the 24h-before-expiry boundary and getting the reminder is 30
    # minutes. Acceptable for a 7-day token; tighter cadence wastes
    # beat cycles for a low-volume table.
    "check-admission-confirmation-reminders": {
        "task": "check_admission_confirmation_reminders_task",
        "schedule": 30 * 60,  # Every 30 minutes
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
    # --- SMS Marketing export retention (PR-4) ---
    "cleanup-sms-export-files-daily": {
        "task": "cleanup_sms_export_files_task",
        "schedule": crontab(hour=3, minute=45),  # 03:45 — dọn export hết hạn
        "options": {"queue": "default"},
    },
    # --- SMS Phase 2 interest-event retention (§16.9 data-minimization) ---
    "cleanup-sms-interest-events-daily": {
        "task": "cleanup_sms_interest_events_task",
        # 04:15 — 04:00 đã có check_ctv_attribution_expiry; giữ staggering
        "schedule": crontab(hour=4, minute=15),
        "options": {"queue": "default"},
    },
    # --- Giấy báo nhập học PDF retention (xoá file hết hạn + orphan) ---
    "cleanup-enrollment-letter-files-daily": {
        "task": "cleanup_enrollment_letter_files_task",
        "schedule": crontab(hour=4, minute=45),  # 04:45 — staggered slot
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

    # --- Lead Lifecycle SLA: auto-close stale rejected (sts04 -> sts20) ---
    # 03:30 chosen so it runs after the lead cache recalc (00:05) — keeping
    # last_consultation_at fresh — and is staggered off the 03:00 idle-session
    # cleanup and 03:15 KPI actuals scans to spread nightly DB load.
    "auto-close-stale-rejected-leads-daily": {
        "task": "auto_close_stale_rejected_leads_task",
        "schedule": crontab(hour=3, minute=30),
        "options": {"queue": "default"},
    },

    # --- CTV Attribution Expiry (Phase 2) ---
    "check-ctv-attribution-expiry-daily": {
        "task": "check_ctv_attribution_expiry_task",
        "schedule": crontab(hour=4, minute=0),  # Runs at 04:00 daily
        "options": {"queue": "default"},
    },

    # --- Overdue Invoice Check (PR 8 — ADR-002) ---
    "check-overdue-invoices-daily": {
        "task": "check_overdue_invoices_task",
        "schedule": crontab(hour=5, minute=0),  # Runs at 05:00 daily
        "options": {"queue": "default"},
    },

    # --- Admission Survey Due (Phase E — ZNS 426903) ---
    # Fires APPLICATION_SURVEY_DUE for profiles approved ≥30 days ago.
    # 07:00 VN chosen to stagger off the 04:00/05:00 heavy scans.
    "check-admission-surveys-due-daily": {
        "task": "check_admission_surveys_due_task",
        "schedule": crontab(hour=7, minute=0),
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
    # M3: Ensure quota row exists at midnight for new day
    "sync-notification-quotas-midnight": {
        "task": "sync_notification_quotas",
        "schedule": crontab(minute=1, hour=0),  # 00:01 daily
        "options": {"queue": "default"},
    },

    # --- Phase D3: Notification alert checks ---
    "check-notification-alerts": {
        "task": "check_notification_alerts",
        "schedule": 300,  # Every 5 minutes
        "options": {"queue": "default"},
    },

    # --- T0-4a admission outbox skeleton (cold cutover prerequisite) ---
    # Registered BEFORE the outbox table/model exist so the beat schedule is
    # stable during the refactor window. The current task body is a no-op
    # in `app/tasks/notification_outbox_tasks.py`. T0-4b (gated on B2 +
    # M-1-19a) will replace the body with the real claim/dispatch/finalize
    # worker without touching this entry. See RUNBOOK §3.5 T0-4a/4b.
    "dispatch-pending-outbox": {
        "task": "dispatch_pending_outbox",
        "schedule": 30.0,  # Every 30 seconds (per RUNBOOK §3.5 T0-4 acceptance)
        "options": {"queue": "default"},
    },

    # --- Wave 5-B / M-1-19d: weekly outbox archive sweep (90-day retention) ---
    # PLAN line 168-178 P1 fix #8: outbox table grows toward 60-180k rows over
    # 5 years; worker SELECT FOR UPDATE SKIP LOCKED scan slows + coverage
    # script DB query slows. Move dispatched rows older than 90d into
    # `_archived_notification_outbox` (created by `phase1_17`). Sunday 02:00 VN
    # — low-traffic window, no conflict with daily KPI / cleanup ticks above.
    "archive-outbox-dispatched": {
        "task": "archive_outbox_dispatched_task",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
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

# =============================================================================
# EAGER TASK MODULE IMPORT (T0-4a fix verified by user-review)
# =============================================================================
# `autodiscover_tasks` and `conf.include` only fire when the worker calls
# `loader.import_default_modules()` at boot. Anything that imports
# `app.celery_app` outside of the worker entrypoint — pytest collection
# helpers, the FastAPI process pulling in `celery_utils` for `.delay()`
# calls, ad-hoc REPL inspection — would see an EMPTY task registry and
# silently miss new tasks.
#
# Importing the `app.tasks` package at the bottom of this module is the
# cheapest fix: the package's `__init__.py` imports every task module,
# whose `@celery_app.task` decorators run and register against the app
# we just built above. Placement at the bottom avoids the circular
# import that would happen at the top (task modules import
# `from ..celery_app import celery_app`).
#
# A subprocess regression test in
# `tests/unit/test_outbox_skeleton.py::test_worker_entrypoint_registers_outbox_task_without_explicit_app_tasks_import`
# locks this in: a fresh interpreter that does only
# `from app.celery_app import celery_app` must see the outbox task already
# registered, not after a manual finalize call.
import app.tasks  # noqa: E402, F401  — must come AFTER `celery_app` is built
