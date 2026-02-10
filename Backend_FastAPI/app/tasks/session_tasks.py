# app/tasks/session_tasks.py
"""
Session-related Celery tasks.

Handles idle session cleanup to enforce IDLE_SESSION_TIMEOUT_DAYS.
"""
import logging
from datetime import datetime, timedelta, timezone

from ..celery_app import celery_app
from ..config import settings
from .utils import task_db_session, run_async_task

log = logging.getLogger(__name__)


# ============================================================================
# Idle Session Cleanup Task (M1: Session Timeout)
# ============================================================================
@celery_app.task(
    name="cleanup_idle_sessions_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def cleanup_idle_sessions_task(self):
    """
    Revoke sessions that have been idle longer than IDLE_SESSION_TIMEOUT_DAYS.

    Runs daily at 03:00 via Celery Beat.
    Cleans up both database records and Redis session keys.
    """
    async def _cleanup():
        from sqlalchemy import and_, select, func
        from app.models import UserSession
        from app.database import safe_redis_delete

        idle_cutoff = datetime.now(timezone.utc) - timedelta(
            days=settings.IDLE_SESSION_TIMEOUT_DAYS
        )

        async with task_db_session() as db:
            # Find idle sessions: not revoked, last activity before cutoff
            result = await db.execute(
                select(UserSession).where(
                    and_(
                        UserSession.revoked_at.is_(None),
                        UserSession.last_activity_at < idle_cutoff,
                    )
                )
            )
            idle_sessions = list(result.scalars().all())

            if not idle_sessions:
                log.info("cleanup_idle_sessions: No idle sessions found")
                return {"revoked_count": 0}

            now = datetime.now(timezone.utc)
            revoked_count = 0

            for session in idle_sessions:
                session.revoked_at = now
                db.add(session)

                # Clean up Redis session key
                try:
                    await safe_redis_delete(f"session:{session.refresh_jti}")
                except Exception as redis_err:
                    log.warning(
                        f"cleanup_idle_sessions: Failed to delete Redis key for session {session.id}: {redis_err}"
                    )

                revoked_count += 1

            await db.commit()

            log.info(
                f"cleanup_idle_sessions: Revoked {revoked_count} idle sessions "
                f"(idle > {settings.IDLE_SESSION_TIMEOUT_DAYS} days, cutoff={idle_cutoff.isoformat()})"
            )

            return {"revoked_count": revoked_count}

    return run_async_task(_cleanup, "cleanup_idle_sessions_task", log)
