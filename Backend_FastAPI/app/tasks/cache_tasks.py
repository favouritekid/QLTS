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
    Celery Beat monthly task — enhanced 4-step pipeline (Phase B5).

    Runs on day 1 of each month at 02:00 AM.
    For each active KpiPlan (current fiscal year):
      Step 1: fill_month_actuals(prev_month) — populate actuals for last month
      Step 2: recalibrate_factors(current_month) — EMA + damping for future months
      Step 3: generate_monthly_kpis(plan_id) — regenerate derived KPIs
      Step 4: sync_plan_to_kpi_config(current_month) — push targets to KpiConfig

    Commit-per-plan isolation: 1 plan failure doesn't block others.
    January edge case: fills December actuals from previous year's plans.
    """
    task_name = "sync_kpi_plan_monthly_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting KPI plan monthly sync (B5 enhanced)...")

    async def _run_plan_sync() -> dict:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from ..models.config import KpiPlan
        from ..services import kpi_planning_service

        from zoneinfo import ZoneInfo
        VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
        now_local = datetime.now(VN_TZ)
        fiscal_year = now_local.year
        current_month = now_local.month

        # Previous month for actuals fill
        if current_month == 1:
            prev_month = 12
            prev_fiscal_year = fiscal_year - 1
        else:
            prev_month = current_month - 1
            prev_fiscal_year = fiscal_year

        result = {
            "plans": 0, "synced": 0, "errors": 0,
            "total_officers": 0, "actuals_filled": 0,
        }

        # --- Discover plans ---
        # Current year plans (for steps 2-4)
        # Previous year plans too (for step 1 January edge case)
        years_to_query = {fiscal_year}
        if prev_fiscal_year != fiscal_year:
            years_to_query.add(prev_fiscal_year)

        async with task_db_session() as session:
            plans_result = await session.execute(
                select(KpiPlan)
                .options(selectinload(KpiPlan.months))
                .where(
                    KpiPlan.is_active == True,  # noqa: E712
                    KpiPlan.fiscal_year.in_(years_to_query),
                )
            )
            all_plans = list(plans_result.scalars().unique().all())

        current_year_plans = [p for p in all_plans if p.fiscal_year == fiscal_year]

        # Plans that need actuals filled (prev month — from prev fiscal year)
        plans_for_actuals = [p for p in all_plans if p.fiscal_year == prev_fiscal_year]

        # Steps 2-3 (recalibrate + regenerate): ALL current-year plans (unit + officer)
        plans_to_recalibrate = current_year_plans

        # Step 4 (sync to KpiConfig): unit plans + orphan officer plans only
        # (unit plan sync already resolves officer plans internally)
        unit_plans_current = [p for p in current_year_plans if p.officer_id is None]
        officer_plans_current = [p for p in current_year_plans if p.officer_id is not None]
        covered_unit_ids = {p.unit_id for p in unit_plans_current}
        orphan_officer_plans = [p for p in officer_plans_current if p.unit_id not in covered_unit_ids]
        plans_to_sync = unit_plans_current + orphan_officer_plans

        result["plans"] = len(set(
            p.id for p in plans_for_actuals + plans_to_recalibrate + plans_to_sync
        ))

        if result["plans"] == 0:
            task_log.info("No active plans found for years %s", years_to_query)
            return result

        task_log.info(
            "Plans discovered: %d actuals (year=%d, month=%d), "
            "%d recalibrate, %d sync (year=%d, month=%d)",
            len(plans_for_actuals), prev_fiscal_year, prev_month,
            len(plans_to_recalibrate), len(plans_to_sync),
            fiscal_year, current_month,
        )

        # --- Step 1: Fill actuals for previous month ---
        for plan in plans_for_actuals:
            try:
                async with task_db_session() as session:
                    await kpi_planning_service.fill_month_actuals(
                        session, plan.id, prev_month,
                    )
                    await session.commit()
                    result["actuals_filled"] += 1
                    task_log.info("Plan %d: actuals filled for month %d", plan.id, prev_month)
            except Exception as e:
                result["errors"] += 1
                task_log.warning("Plan %d: actuals fill failed for month %d: %s", plan.id, prev_month, e)

        # --- Steps 2-3: Recalibrate + regenerate (ALL current-year plans) ---
        failed_plan_ids: set = set()
        for plan in plans_to_recalibrate:
            try:
                async with task_db_session() as session:
                    await kpi_planning_service.recalibrate_factors(
                        session, plan.id, current_month,
                    )
                    await kpi_planning_service.generate_monthly_kpis(session, plan.id)
                    await session.commit()
                    task_log.info("Plan %d: recalibrated + regenerated", plan.id)
            except Exception as e:
                failed_plan_ids.add(plan.id)
                result["errors"] += 1
                task_log.error("Plan %d: recalibrate/regenerate failed: %s", plan.id, e, exc_info=True)

        # --- Step 4: Sync to KpiConfig/KpiTarget (skip plans that failed steps 2-3) ---
        for plan in plans_to_sync:
            if plan.id in failed_plan_ids:
                task_log.warning("Plan %d: skipping sync (steps 2-3 failed)", plan.id)
                continue
            try:
                async with task_db_session() as session:
                    plan_result = await session.execute(
                        select(KpiPlan)
                        .options(selectinload(KpiPlan.months))
                        .where(KpiPlan.id == plan.id)
                    )
                    fresh_plan = plan_result.scalar_one_or_none()
                    if fresh_plan is None or not fresh_plan.is_active:
                        continue

                    target_officer = fresh_plan.officer_id
                    stats = await kpi_planning_service.sync_plan_to_kpi_config(
                        session, fresh_plan, current_month,
                        target_officer_id=target_officer,
                    )
                    await session.commit()

                    result["synced"] += 1
                    result["total_officers"] += stats.get("officers_synced", 0)
                    task_log.info(
                        "Plan %d: sync complete (%d officers, %d configs)",
                        plan.id, stats.get("officers_synced", 0),
                        stats.get("configs_upserted", 0),
                    )
            except Exception as e:
                result["errors"] += 1
                task_log.error("Plan %d: sync failed: %s", plan.id, e, exc_info=True)

        return result

    result = run_async_task(
        async_func=_run_plan_sync,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["plans", "synced", "errors"],
    )

    task_log.info(
        "KPI plan monthly sync completed: plans=%d, synced=%d, errors=%d, "
        "officers=%d, actuals_filled=%d",
        result["plans"], result["synced"], result["errors"],
        result.get("total_officers", 0), result.get("actuals_filled", 0),
    )
    return result


# ============================================================================
# Holiday Calendar Yearly Check (spec §7 — Nov 1st, Phase A9)
# ============================================================================
@celery_app.task(
    name="check_next_year_holidays_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=1,
    default_retry_delay=3600,
)
def check_next_year_holidays_task(self):
    """
    Celery Beat yearly task — check if holiday_calendar is seeded for next year.

    Runs on November 1st (2 months before new year) to give admin time to
    configure lunar holidays (Tết Nguyên Đán, Giỗ Tổ Hùng Vương).
    Logs warning if calendar is incomplete.
    """
    task_name = "check_next_year_holidays_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting next-year holiday calendar check...")

    async def _run_check() -> dict:
        from zoneinfo import ZoneInfo
        from ..services.calendar_service import get_holiday_status
        from ..services.notification_dispatcher import dispatch
        from ..core.events import SystemEvents

        VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
        next_year = datetime.now(VN_TZ).year + 1

        async with task_db_session() as session:
            status = await get_holiday_status(session, next_year)

            # Dispatch admin notification if calendar incomplete
            if not status["is_complete"]:
                try:
                    _, cb = await dispatch(
                        db=session,
                        event=SystemEvents.SYSTEM_ALERT,
                        payload={
                            "severity": "warning",
                            "message": status.get("warning", f"Lịch lễ năm {next_year} chưa đầy đủ"),
                            "action_url": f"/admin/kpi-planning/holidays/status/{next_year}",
                            "actor_id": 0,
                            "actor_name": "System",
                        },
                        dedupe_key=f"holiday_incomplete:{next_year}",
                        skip_preference_check=True,
                    )
                    await session.commit()
                    if cb:
                        await cb()
                except Exception as e:
                    task_log.warning("Failed to dispatch holiday notification: %s", e)

        return status

    result = run_async_task(
        async_func=_run_check,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["year", "total_holidays", "is_complete"],
    )

    if not result["is_complete"]:
        task_log.warning(
            "HOLIDAY CALENDAR INCOMPLETE for year %d: %s "
            "(total=%d, lunar=%s). Admin action required.",
            result["year"],
            result.get("warning", ""),
            result["total_holidays"],
            result["has_lunar_holidays"],
        )
    else:
        task_log.info(
            "Holiday calendar OK for year %d: %d holidays, lunar=%s",
            result["year"], result["total_holidays"], result["has_lunar_holidays"],
        )

    return result
