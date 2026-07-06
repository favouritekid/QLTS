# app/tasks/sms_tasks.py
"""
SMS Marketing Celery tasks (PR-4): dọn file export hết hạn (retention → set
purged_at + xoá file) + dọn file staging orphan (sinh dở rồi crash). Chạy
hằng ngày qua Celery Beat. Xem SMS_MARKETING_MODULE_DESIGN.md §8.3 / §11.7.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from ..celery_app import celery_app
from ..config import settings
from ..utils.sms_export import STAGING_PREFIX
from .utils import run_async_task, task_db_session

log = logging.getLogger(__name__)

_STAGING_MAX_AGE_SECONDS = 3600  # staging > 1h = orphan (sinh file thất bại)


def _sweep_staging_orphans(base_dir: str) -> int:
    """Xoá file `.staging.*` cũ (ghi dở rồi crash giữa chừng). Best-effort —
    KHÔNG fail task nếu lỗi I/O lẻ tẻ."""
    removed = 0
    if not base_dir or not os.path.isdir(base_dir):
        return 0
    cutoff = time.time() - _STAGING_MAX_AGE_SECONDS
    for root, _dirs, files in os.walk(base_dir):
        for fn in files:
            if not fn.startswith(STAGING_PREFIX):
                continue
            path = os.path.join(root, fn)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    return removed


@celery_app.task(
    name="cleanup_sms_export_files_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
)
def cleanup_sms_export_files_task(self):
    """Dọn file export quá `expires_at` (xoá file + set purged_at; giữ nhãn
    'handed_off' cho audit, generated/failed → 'purged') + staging orphan.
    Runs daily via Celery Beat."""

    async def _cleanup():
        from app.repositories.sms_export_repository import SmsExportRepository

        now = datetime.now(timezone.utc)
        purged = 0
        async with task_db_session() as db:
            repo = SmsExportRepository(db)
            batches = await repo.list_purgeable_batches(now)
            for b in batches:
                if b.storage_path and os.path.isfile(b.storage_path):
                    try:
                        os.remove(b.storage_path)
                    except OSError as exc:
                        log.warning(
                            "cleanup_sms_export: xoá file batch %s lỗi: %s",
                            b.id,
                            exc,
                        )
                        continue
                b.purged_at = now
                if b.status in ("generated", "failed"):
                    b.status = "purged"
                purged += 1
            await db.commit()

        orphans = _sweep_staging_orphans(settings.SMS_EXPORT_STORAGE_DIR)
        log.info(
            "cleanup_sms_export: purged=%s staging_orphans=%s",
            purged,
            orphans,
        )
        return {"purged": purged, "staging_orphans": orphans}

    return run_async_task(_cleanup, "cleanup_sms_export_files_task", log)


async def _purge_old_interest_events(db, retention_days: int) -> int:
    """Xoá `sms_landing_session` có ``started_at`` cũ hơn ``retention_days``
    ngày; `sms_program_view` đi theo qua FK ``ondelete=CASCADE``. Aggregate
    `sms_contact_program_interest` KHÔNG cascade → GIỮ nguyên. Trả số session
    đã xoá. (Helper tách để test chạy đúng query thật.)"""
    from sqlalchemy import delete

    from app.models.sms import SmsLandingSession

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    res = await db.execute(
        delete(SmsLandingSession).where(SmsLandingSession.started_at < cutoff)
    )
    return res.rowcount or 0


@celery_app.task(
    name="cleanup_sms_interest_events_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
)
def cleanup_sms_interest_events_task(self):
    """Retention §16.9: dọn event tracking chi tiết (`sms_landing_session` +
    `sms_program_view` cascade) cũ hơn ``SMS_INTEREST_EVENT_RETENTION_DAYS``.
    GIỮ aggregate `sms_contact_program_interest` (không cascade). Nhất quán:
    `_recompute_interest` chỉ tính view TRONG cửa sổ retention, nên view bị dọn
    đằng nào cũng đã ngoài cửa sổ → recompute (kể cả khi contact tương tác lại)
    KHÔNG lệch view_count/total_dwell/score. Data-minimization; daily Celery Beat."""

    async def _cleanup():
        retention = settings.SMS_INTEREST_EVENT_RETENTION_DAYS
        async with task_db_session() as db:
            deleted = await _purge_old_interest_events(db, retention)
            await db.commit()
        log.info(
            "cleanup_sms_interest_events: retention=%sd deleted_sessions=%s",
            retention,
            deleted,
        )
        return {"retention_days": retention, "deleted_sessions": deleted}

    return run_async_task(_cleanup, "cleanup_sms_interest_events_task", log)
