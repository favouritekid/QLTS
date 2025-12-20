# app/tasks/cache_tasks.py
"""
Cache-related Celery tasks.

Handles cache recalculation and data synchronization tasks.
"""
import asyncio
import logging
from datetime import datetime, timezone

from ..celery_app import celery_app
from .utils import task_db_session


# ============================================================================
# Lead Cache Recalculation Task (Nightly)
# ============================================================================
@celery_app.task(
    name="recalculate_lead_caches_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,  # 5 minutes between retries
)
def recalculate_lead_caches_task(self):
    """
    Celery Beat nightly task to recalculate lead insight caches.
    
    Runs at 00:05 daily to update:
    - is_overdue (time-sensitive, needs daily recalc)
    - cached_urgency_score (depends on is_overdue)
    """
    task_log = logging.getLogger("recalculate_lead_caches_task")
    task_log.info("Starting nightly lead cache recalculation...")

    async def _run_recalculation() -> dict:
        from sqlalchemy import select, func
        from .. import models
        from ..services.lead_cache_service import update_lead_cache

        result = {"total": 0, "updated": 0, "errors": 0}

        async with task_db_session() as session:
            # Get count of active leads
            count_result = await session.execute(
                select(func.count(models.Lead.id))
                .where(models.Lead.deleted_at.is_(None))
            )
            result["total"] = count_result.scalar() or 0
            
            if result["total"] == 0:
                task_log.info("No leads to recalculate")
                return result
            
            # Get all lead IDs
            ids_result = await session.execute(
                select(models.Lead.id)
                .where(models.Lead.deleted_at.is_(None))
                .order_by(models.Lead.id)
            )
            lead_ids = [row[0] for row in ids_result.all()]
            
            # Process in batches
            batch_size = 100
            for i in range(0, len(lead_ids), batch_size):
                batch = lead_ids[i:i + batch_size]
                
                for lead_id in batch:
                    try:
                        await update_lead_cache(session, lead_id)
                        result["updated"] += 1
                    except Exception as e:
                        task_log.warning(f"Error updating lead {lead_id}: {e}")
                        result["errors"] += 1
                
                # Commit after each batch
                await session.commit()
                
                progress = min(i + batch_size, len(lead_ids))
                task_log.info(f"Progress: {progress}/{result['total']}")

        return result

    try:
        result = asyncio.run(_run_recalculation())
        task_log.info(
            f"Nightly recalculation completed: total={result['total']}, "
            f"updated={result['updated']}, errors={result['errors']}"
        )
        return result
    except Exception as e:
        task_log.error(f"Nightly recalculation failed: {e}", exc_info=True)
        raise e


# ============================================================================
# KPI YTD Sync Task (Daily)
# ============================================================================
@celery_app.task(
    name="sync_kpi_ytd_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,  # 5 minutes between retries
)
def sync_kpi_ytd_task(self):
    """
    Celery Beat daily task to sync KPI Year-to-Date progress for all officers.
    
    Runs at 01:00 daily to update:
    - achieved_ytd for each officer's annual targets
    - last_sync_at timestamp
    """
    task_log = logging.getLogger("sync_kpi_ytd_task")
    task_log.info("Starting KPI YTD sync...")

    async def _run_ytd_sync() -> dict:
        from sqlalchemy import select
        from .. import models
        from ..services import kpi_service

        result = {"officers": 0, "synced": 0, "errors": 0}
        fiscal_year = datetime.now(timezone.utc).year

        async with task_db_session() as session:
            # Get all active officers
            officers_result = await session.execute(
                select(models.User.id)
                .where(
                    models.User.role == "officer",
                    models.User.status == "active",
                )
            )
            officer_ids = [row[0] for row in officers_result.all()]
            result["officers"] = len(officer_ids)

            if result["officers"] == 0:
                task_log.info("No active officers to sync")
                return result

            task_log.info(f"Syncing YTD for {result['officers']} officers")

            # Sync each officer
            for officer_id in officer_ids:
                try:
                    await kpi_service.sync_officer_ytd(session, officer_id, fiscal_year)
                    result["synced"] += 1
                except Exception as e:
                    task_log.warning(f"Error syncing officer {officer_id}: {e}")
                    result["errors"] += 1

            # Commit all changes
            await session.commit()

        return result

    try:
        result = asyncio.run(_run_ytd_sync())
        task_log.info(
            f"KPI YTD sync completed: officers={result['officers']}, "
            f"synced={result['synced']}, errors={result['errors']}"
        )
        return result
    except Exception as e:
        task_log.error(f"KPI YTD sync failed: {e}", exc_info=True)
        raise e
