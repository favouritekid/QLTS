# app/tasks/enrollment_letter_tasks.py
"""
Celery task: enforce retention on official "Giấy báo nhập học" PDFs.

For any EnrollmentLetter whose ``expires_at`` has passed:
  - delete its on-disk PDF, AND
  - SCRUB the PII out of ``data_snapshot`` (name / dob / permanent address /
    phone), keeping only non-PII fields + a ``_purged`` marker. This closes the
    data-minimization gap: purging the file but leaving the same PII in the row
    would only half-enforce retention. (The row itself is kept for its issuance
    audit — generated_by / generated_at / dates.)

Then two disk sweeps (best-effort, never fail the task on isolated I/O errors):
  - ORPHAN — final ``*.pdf`` files under the storage dir that no letter row
    references (a commit-failure leftover), older than a grace period so a
    just-issued file is never reaped. Staging crumbs are excluded (they belong
    to the staging sweep, not counted as leaked letters).
  - STAGING — ``.staging.*`` crumbs from a mid-write crash (reuses the SMS
    sweeper, keyed on the shared STAGING_PREFIX).

All disk I/O is offloaded via ``to_thread`` (consistent with the service).
Runs daily via Celery Beat.
"""
import logging
import os
import time

from anyio import to_thread
from sqlalchemy import select

from ..celery_app import celery_app
from ..config import settings
from ..utils.sms_export import STAGING_PREFIX
from .sms_tasks import _sweep_staging_orphans
from .utils import run_async_task, task_db_session

log = logging.getLogger(__name__)

# A final .pdf younger than this with no DB row is assumed to be an in-flight
# issuance (row not yet committed), NOT an orphan — protects against a
# read-then-sweep race with a concurrent POST.
_ORPHAN_MAX_AGE_SECONDS = 3600

# data_snapshot keys scrubbed on retention (candidate PII).
_PII_KEYS = frozenset({"full_name", "dob", "permanent_address", "phone"})


def _scrub_snapshot(snapshot: dict) -> dict:
    """Strip candidate PII from a ``data_snapshot`` on retention, keeping the
    non-PII fields (major/degree/fee) + a ``_purged`` marker so re-runs skip it."""
    return {
        k: v for k, v in (snapshot or {}).items() if k not in _PII_KEYS
    } | {"_purged": True}


def _delete_files(paths) -> int:
    """Best-effort delete a list of files. SYNC → call via to_thread."""
    removed = 0
    for p in paths:
        try:
            if p and os.path.isfile(p):
                os.remove(p)
                removed += 1
        except OSError:
            continue
    return removed


def _norm(path: str) -> str:
    """Dạng chuẩn hoá để so khớp path DB với path quét được trên đĩa.

    So sánh chuỗi thô là không đủ: cùng một file có thể mang hai cách viết
    (dấu '/' cuối, thành phần './', symlink của mount). realpath trước, và chỉ
    lùi về normpath nếu realpath lỗi (đường dẫn không tồn tại).
    """
    if not path:
        return ""
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.normpath(path)


def _sweep_orphan_pdfs(base_dir: str, known_paths: set) -> int:
    """Delete final *.pdf files not referenced by any letter row + older than
    the grace period (commit-failure leftovers). Staging crumbs are skipped
    (handled by the staging sweep). Best-effort. SYNC → call via to_thread.

    ⚠️ CHỐT AN TOÀN: nếu quét ra file .pdf nhưng ``known_paths`` KHÔNG khớp lấy
    một cái nào, đó gần như chắc chắn là lệch cấu hình chứ không phải cả thư
    mục đều mồ côi — ví dụ ops đổi ``ENROLLMENT_LETTER_STORAGE_DIR`` sang mount
    mới rồi copy file sang, khiến mọi row vẫn trỏ đường dẫn cũ. Không có chốt
    này thì lượt beat kế tiếp XOÁ SẠCH mọi giấy báo chính thức đang sống. Trong
    tình huống đó ta bỏ qua lượt quét và log cảnh báo để người vận hành xử lý.
    """
    if not base_dir or not os.path.isdir(base_dir):
        return 0
    known = {_norm(p) for p in known_paths if p}
    cutoff = time.time() - _ORPHAN_MAX_AGE_SECONDS

    candidates: list[str] = []
    matched = 0
    for root, _dirs, files in os.walk(base_dir):
        for fn in files:
            if fn.startswith(STAGING_PREFIX) or not fn.endswith(".pdf"):
                continue
            path = os.path.join(root, fn)
            if _norm(path) in known:
                matched += 1
                continue
            candidates.append(path)

    if candidates and matched == 0 and known:
        log.warning(
            "cleanup_enrollment_letter: BỎ QUA quét mồ côi — %s file .pdf dưới "
            "%s nhưng KHÔNG file nào khớp %s đường dẫn trong DB. Nghi lệch "
            "ENROLLMENT_LETTER_STORAGE_DIR; kiểm tra trước khi để job xoá.",
            len(candidates),
            base_dir,
            len(known),
        )
        return 0

    removed = 0
    for path in candidates:
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


@celery_app.task(
    name="cleanup_enrollment_letter_files_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
)
def cleanup_enrollment_letter_files_task(self):
    """Purge expired PDFs + scrub expired PII, sweep orphans. Daily via Beat."""

    async def _cleanup():
        from datetime import datetime, timezone

        from ..models import EnrollmentLetter

        now = datetime.now(timezone.utc)
        known_paths: set = set()
        to_delete: list = []
        scrubbed = 0

        async with task_db_session() as db:
            letters = (
                await db.execute(select(EnrollmentLetter))
            ).scalars().all()
            for letter in letters:
                if letter.file_path:
                    known_paths.add(letter.file_path)
                if letter.expires_at is not None and letter.expires_at < now:
                    if letter.file_path:
                        to_delete.append(letter.file_path)
                    snap = letter.data_snapshot or {}
                    if not snap.get("_purged"):
                        letter.data_snapshot = _scrub_snapshot(snap)
                        scrubbed += 1
            deleted = await to_thread.run_sync(_delete_files, to_delete)
            await db.commit()

        base_dir = settings.ENROLLMENT_LETTER_STORAGE_DIR
        orphans = await to_thread.run_sync(_sweep_orphan_pdfs, base_dir, known_paths)
        staging = await to_thread.run_sync(_sweep_staging_orphans, base_dir)
        log.info(
            "cleanup_enrollment_letter: expired_files=%s scrubbed=%s "
            "orphan_pdfs=%s staging=%s",
            deleted,
            scrubbed,
            orphans,
            staging,
        )
        return {
            "expired_files": deleted,
            "scrubbed": scrubbed,
            "orphan_pdfs": orphans,
            "staging_orphans": staging,
        }

    return run_async_task(_cleanup, "cleanup_enrollment_letter_files_task", log)
