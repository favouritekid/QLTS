# app/tasks/collaborator_tasks.py
"""
Collaborator (CTV) Celery Tasks:
1. Attribution expiry: Clear referrer_id after 90 days, with 7-day warning
2. Weekly summary: Send weekly stats email to CTVs
"""
import logging
from datetime import datetime, timedelta, timezone

from ..celery_app import celery_app
from .utils import task_db_session, run_async_task

log = logging.getLogger(__name__)

# Attribution expiry config
ATTRIBUTION_EXPIRE_DAYS = 90
ATTRIBUTION_WARNING_DAYS = 7  # Start warning N days before expiry


# ============================================================================
# Task 5.1: Attribution Expiry
# ============================================================================

@celery_app.task(
    name="check_ctv_attribution_expiry_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,
)
def check_ctv_attribution_expiry_task(self):
    """
    Daily task: Check CTV lead attributions and expire them after 90 days.

    Schedule: 04:00 AM daily
    Logic:
    1. Day 83-89: Send warning notification (idempotent)
    2. Day 90+: Clear referrer_id, cancel pending commissions, log event
    """

    async def _run():
        from sqlalchemy import select, and_
        from app import models
        from app.models.collaborator import Collaborator, LeadClaim
        from app.services.notification_dispatcher import safe_dispatch
        from app.core.events import SystemEvents
        from app.services import commission_service

        now = datetime.now(timezone.utc)
        expire_cutoff = now - timedelta(days=ATTRIBUTION_EXPIRE_DAYS)
        warning_cutoff = now - timedelta(days=ATTRIBUTION_EXPIRE_DAYS - ATTRIBUTION_WARNING_DAYS)

        expired_count = 0
        warned_count = 0

        async with task_db_session() as db:
            # Query leads with approved claims that may be expiring
            result = await db.execute(
                select(
                    LeadClaim.id,
                    LeadClaim.collaborator_id,
                    LeadClaim.lead_id,
                    LeadClaim.reviewed_at,
                    models.Lead.referrer_id,
                    models.Lead.status,
                    Collaborator.user_id,
                )
                .join(models.Lead, LeadClaim.lead_id == models.Lead.id)
                .join(Collaborator, LeadClaim.collaborator_id == Collaborator.id)
                .where(
                    LeadClaim.status == "approved",
                    LeadClaim.reviewed_at.isnot(None),
                    LeadClaim.reviewed_at < warning_cutoff,
                    models.Lead.referrer_id.isnot(None),
                    models.Lead.deleted_at.is_(None),
                    models.Lead.status != "converted",  # Don't expire converted leads
                    Collaborator.deleted_at.is_(None),
                )
            )
            rows = result.all()

            for row in rows:
                days_since_review = (now - row.reviewed_at).days

                if days_since_review >= ATTRIBUTION_EXPIRE_DAYS:
                    # EXPIRE: Clear referrer_id + cancel commissions
                    lead = await db.get(models.Lead, row.lead_id)
                    if lead and lead.referrer_id:
                        lead.referrer_id = None
                        await db.flush()

                        # Cancel pending commissions
                        await commission_service.cancel_commissions_for_lead(
                            db, row.lead_id,
                            reason="Attribution expired (90 days)",
                        )

                        # Update collaborator abuse tracking
                        collaborator = await db.get(Collaborator, row.collaborator_id)
                        if collaborator:
                            collaborator.expired_attribution_count = (
                                getattr(collaborator, "expired_attribution_count", 0) or 0
                            ) + 1
                            if collaborator.expired_attribution_count >= 5:
                                collaborator.is_flagged = True
                            await db.flush()

                        # Notify CTV
                        if row.user_id:
                            await safe_dispatch(
                                db=db,
                                event=SystemEvents.CTV_ATTRIBUTION_EXPIRED,
                                payload={
                                    "collaborator_id": row.collaborator_id,
                                    "lead_id": row.lead_id,
                                    "user_id": row.user_id,
                                    "actor_id": 0,
                                },
                                dedupe_key=f"ctv_attribution_expired:{row.lead_id}",
                            )

                        expired_count += 1

                elif days_since_review >= (ATTRIBUTION_EXPIRE_DAYS - ATTRIBUTION_WARNING_DAYS):
                    # WARNING: Notify CTV about upcoming expiry
                    days_remaining = ATTRIBUTION_EXPIRE_DAYS - days_since_review
                    if row.user_id:
                        await safe_dispatch(
                            db=db,
                            event=SystemEvents.CTV_ATTRIBUTION_EXPIRING,
                            payload={
                                "collaborator_id": row.collaborator_id,
                                "lead_id": row.lead_id,
                                "days_remaining": days_remaining,
                                "user_id": row.user_id,
                                "actor_id": 0,
                            },
                            dedupe_key=f"ctv_attribution_expiring:{row.lead_id}:{days_remaining}",
                        )
                    warned_count += 1

            await db.commit()

        return {
            "status": "success",
            "expired": expired_count,
            "warned": warned_count,
        }

    return run_async_task(_run, "check_ctv_attribution_expiry", log)


# ============================================================================
# Task 6.1: Weekly Summary (scheduled Monday 09:00)
# ============================================================================

@celery_app.task(
    name="send_ctv_weekly_summary_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,
)
def send_ctv_weekly_summary_task(self):
    """
    Weekly task: Send summary stats to all active CTVs.
    Schedule: Monday 09:00 AM
    """

    async def _run():
        from sqlalchemy import select, func
        from app.models.collaborator import Collaborator
        from app.models.commission import CommissionRecord
        from app import models
        from app.core.events import SystemEvents
        from app.services.notification_dispatcher import safe_dispatch

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        sent_count = 0

        async with task_db_session() as db:
            # Get all active collaborators with user accounts
            result = await db.execute(
                select(Collaborator).where(
                    Collaborator.status == "active",
                    Collaborator.user_id.isnot(None),
                    Collaborator.deleted_at.is_(None),
                )
            )
            collaborators = result.scalars().all()

            for collab in collaborators:
                # Aggregate stats for this week using SQLAlchemy expressions (EC-7)
                leads_result = await db.execute(
                    select(func.count(models.Lead.id)).where(
                        models.Lead.referrer_id == collab.id,
                        models.Lead.created_at >= week_ago,
                        models.Lead.deleted_at.is_(None),
                    )
                )
                new_leads = leads_result.scalar_one_or_none() or 0

                commission_result = await db.execute(
                    select(
                        func.count(CommissionRecord.id).label("count"),
                        func.coalesce(func.sum(CommissionRecord.amount), 0).label("total"),
                    ).where(
                        CommissionRecord.collaborator_id == collab.id,
                        CommissionRecord.triggered_at >= week_ago,
                    )
                )
                commission_row = commission_result.one()

                stats = {
                    "new_leads_this_week": new_leads,
                    "commissions_this_week": commission_row.count,
                    "commission_amount_this_week": str(commission_row.total),
                }

                await safe_dispatch(
                    db=db,
                    event=SystemEvents.CTV_WEEKLY_SUMMARY,
                    payload={
                        "collaborator_id": collab.id,
                        "user_id": collab.user_id,
                        "stats": stats,
                        "actor_id": 0,
                    },
                    dedupe_key=f"ctv_weekly_summary:{collab.id}:{now.isocalendar()[1]}",
                )
                sent_count += 1

            await db.commit()

        return {"status": "success", "sent": sent_count}

    return run_async_task(_run, "send_ctv_weekly_summary", log)
