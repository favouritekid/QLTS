# app/tasks/cache_tasks.py
"""
Cache-related Celery tasks.

Handles cache recalculation and data synchronization tasks.
"""
import logging
from datetime import datetime, timezone

from ..celery_app import celery_app
from ..core.constants import UserRole
from .utils import task_db_session, run_async_task


# ============================================================================
# Lead Cache Recalculation Task (Nightly)
# ============================================================================
@celery_app.task(
    name="recalculate_lead_caches_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,
)
def recalculate_lead_caches_task(self):
    """
    Celery Beat nightly task to recalculate lead insight caches.
    
    Uses standardized error handling. Runs at 00:05 daily.
    """
    task_name = "recalculate_lead_caches_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting nightly lead cache recalculation...")

    async def _run_recalculation() -> dict:
        from sqlalchemy import select, func
        from .. import models
        from ..services.lead_cache_service import update_lead_cache

        result = {"total": 0, "updated": 0, "errors": 0}

        async with task_db_session() as session:
            count_result = await session.execute(
                select(func.count(models.Lead.id))
                .where(models.Lead.deleted_at.is_(None))
            )
            result["total"] = count_result.scalar() or 0
            
            if result["total"] == 0:
                task_log.info("No leads to recalculate")
                return result
            
            ids_result = await session.execute(
                select(models.Lead.id)
                .where(models.Lead.deleted_at.is_(None))
                .order_by(models.Lead.id)
            )
            lead_ids = [row[0] for row in ids_result.all()]
            
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
                
                await session.commit()
                progress = min(i + batch_size, len(lead_ids))
                task_log.info(f"Progress: {progress}/{result['total']}")

        return result

    # Run with standardized error handling
    result = run_async_task(
        async_func=_run_recalculation,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["total", "updated", "errors"]
    )

    task_log.info(
        f"Nightly recalculation completed: total={result['total']}, "
        f"updated={result['updated']}, errors={result['errors']}"
    )
    return result


# ============================================================================
# KPI YTD Sync Task (Daily)
# ============================================================================
@celery_app.task(
    name="sync_kpi_ytd_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,
)
def sync_kpi_ytd_task(self):
    """
    Celery Beat daily task to sync KPI Year-to-Date progress for all officers.
    
    Uses standardized error handling. Runs at 01:00 daily.
    """
    task_name = "sync_kpi_ytd_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting KPI YTD sync...")

    async def _run_ytd_sync() -> dict:
        from sqlalchemy import select
        from .. import models
        from ..services import kpi_service

        result = {"officers": 0, "synced": 0, "errors": 0}
        fiscal_year = datetime.now(timezone.utc).year

        async with task_db_session() as session:
            officers_result = await session.execute(
                select(models.User.id)
                .where(
                    models.User.role == UserRole.OFFICER,
                    models.User.status == "active",
                )
            )
            officer_ids = [row[0] for row in officers_result.all()]
            result["officers"] = len(officer_ids)

            if result["officers"] == 0:
                task_log.info("No active officers to sync")
                return result

            task_log.info(f"Syncing YTD for {result['officers']} officers")

            for officer_id in officer_ids:
                try:
                    await kpi_service.sync_officer_ytd(session, officer_id, fiscal_year)
                    result["synced"] += 1
                except Exception as e:
                    task_log.warning(f"Error syncing officer {officer_id}: {e}")
                    result["errors"] += 1

            await session.commit()

        return result

    # Run with standardized error handling
    result = run_async_task(
        async_func=_run_ytd_sync,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["officers", "synced", "errors"]
    )

    task_log.info(
        f"KPI YTD sync completed: officers={result['officers']}, "
        f"synced={result['synced']}, errors={result['errors']}"
    )
    return result


# ============================================================================
# KPI Plan Monthly Sync Task (spec §6 Job 1 — Day 1 of month, 02:00 AM)
# ============================================================================
@celery_app.task(
    name="sync_kpi_plan_monthly_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,
)
def sync_kpi_plan_monthly_task(self):
    """
    Celery Beat monthly task — push KPI plan targets into KpiConfig/KpiTarget.

    Runs on day 1 of each month at 02:00 AM (after all T-1 transactions settle).
    For each active KpiPlan (current fiscal year):
      1. Sync current month's targets → KpiConfig (7 KPIs per officer)
      2. Sync annual target → KpiTarget (1 per officer)
    Commits per plan (isolation — 1 plan failure doesn't block others).
    """
    task_name = "sync_kpi_plan_monthly_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting KPI plan monthly sync...")

    async def _run_plan_sync() -> dict:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from ..models.config import KpiPlan
        from ..services import kpi_planning_service

        # P1 fix: use Asia/Ho_Chi_Minh (matches Celery timezone config)
        from zoneinfo import ZoneInfo
        VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
        now_local = datetime.now(VN_TZ)
        fiscal_year = now_local.year
        current_month = now_local.month

        result = {"plans": 0, "synced": 0, "errors": 0, "total_officers": 0}

        # Find ALL active plans for current fiscal year (unit + officer plans)
        async with task_db_session() as session:
            plans_result = await session.execute(
                select(KpiPlan)
                .options(selectinload(KpiPlan.months))
                .where(
                    KpiPlan.is_active == True,  # noqa: E712
                    KpiPlan.fiscal_year == fiscal_year,
                )
            )
            all_plans = list(plans_result.scalars().unique().all())

            # Separate unit plans and officer plans
            unit_plans = [p for p in all_plans if p.officer_id is None]
            officer_plans = [p for p in all_plans if p.officer_id is not None]
            result["plans"] = len(all_plans)

            if result["plans"] == 0:
                task_log.info("No active plans found for fiscal year %d", fiscal_year)
                return result

            task_log.info(
                "Found %d active plans (%d unit, %d officer) for fiscal year %d",
                result["plans"], len(unit_plans), len(officer_plans), fiscal_year,
            )

        # Collect unit_ids covered by unit plans (officer plans already resolved inside sync)
        covered_unit_ids = {p.unit_id for p in unit_plans}

        # Officer plans whose unit has NO unit plan — sync these directly per officer
        orphan_officer_plans = [
            p for p in officer_plans if p.unit_id not in covered_unit_ids
        ]
        if orphan_officer_plans:
            task_log.info(
                "%d orphan officer plans (unit has no unit plan) — will sync directly",
                len(orphan_officer_plans),
            )

        # Process: unit plans first (covers most officers), then orphan officer plans
        plans_to_process = unit_plans + orphan_officer_plans
        for plan in plans_to_process:
            try:
                async with task_db_session() as session:
                    # Re-load plan in this session (detached from previous session)
                    plan_result = await session.execute(
                        select(KpiPlan)
                        .options(selectinload(KpiPlan.months))
                        .where(KpiPlan.id == plan.id)
                    )
                    fresh_plan = plan_result.scalar_one_or_none()
                    if fresh_plan is None or not fresh_plan.is_active:
                        continue

                    # Orphan officer plans: sync only that officer
                    target_officer = fresh_plan.officer_id  # None for unit plans
                    stats = await kpi_planning_service.sync_plan_to_kpi_config(
                        session, fresh_plan, current_month,
                        target_officer_id=target_officer,
                    )
                    await session.commit()

                    result["synced"] += 1
                    result["total_officers"] += stats.get("officers_synced", 0)
                    task_log.info(
                        "Plan %d synced: %d officers, %d configs",
                        plan.id,
                        stats.get("officers_synced", 0),
                        stats.get("configs_upserted", 0),
                    )

            except Exception as e:
                result["errors"] += 1
                task_log.error(
                    "Error syncing plan %d: %s", plan.id, e, exc_info=True,
                )

        return result

    result = run_async_task(
        async_func=_run_plan_sync,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["plans", "synced", "errors"],
    )

    task_log.info(
        "KPI plan monthly sync completed: plans=%d, synced=%d, errors=%d, officers=%d",
        result["plans"], result["synced"], result["errors"],
        result.get("total_officers", 0),
    )
    return result
