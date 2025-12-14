# app/services/lead_cache_service.py
"""
Lead Cache Service - Maintains cached metrics for Lead Insights.

✅ ARCHITECTURE COMPLIANT:
- Uses Repository pattern (no direct DB queries)
- Transaction propagation (accepts session from caller)
- Sync execution within transaction

Called after:
- Consultation create/update/delete
- Lead score update
- Pipeline stage changes
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.lead_repository import LeadRepository


log = structlog.get_logger(__name__)


def calculate_urgency_score(
    days_since_contact: int,
    lead_score: int,
    consultation_count: int,
    overdue_days: int,
    is_final_stage: bool
) -> int:
    """
    Calculate Urgency Score (0-100).
    
    Components:
    - Base: 30
    - Inactivity: days × 3 (max 45)
    - Hot Lead: +15 if score >= 70
    - Never Contacted: +25 if count = 0
    - Overdue: days × 5 (max 30)
    - Final Stage: -50
    
    Args:
        days_since_contact: Days since last consultation
        lead_score: Lead's current score
        consultation_count: Number of consultations
        overdue_days: Days overdue for next_activity_at
        is_final_stage: Whether lead is in final pipeline stage
        
    Returns:
        Urgency score 0-100
    """
    score = 30  # Base
    
    # Inactivity penalty (max +45)
    score += min(days_since_contact * 3, 45)
    
    # Hot lead bonus
    if lead_score >= 70:
        score += 15
    
    # Never contacted penalty
    if consultation_count == 0:
        score += 25
    
    # Overdue penalty (max +30)
    if overdue_days > 0:
        score += min(overdue_days * 5, 30)
    
    # Final stage reduction
    if is_final_stage:
        score -= 50
    
    return max(0, min(score, 100))


async def update_lead_cache(
    db: AsyncSession,
    lead_id: int,
    lead: Optional[models.Lead] = None
) -> None:
    """
    Update cached fields for a lead.
    
    ✅ TRANSACTION SAFE: Uses provided session, no commit.
    Caller is responsible for commit/rollback.
    
    Flow:
    1. Query consultation aggregates via Repository
    2. Calculate urgency score
    3. Update Lead fields
    4. Flush (no commit)
    
    Args:
        db: SQLAlchemy session (from caller's transaction)
        lead_id: Lead ID to update
        lead: Optional pre-loaded Lead object
    """
    repo = LeadRepository(db)
    
    # Get lead if not provided
    if lead is None:
        lead = await db.get(models.Lead, lead_id)
        if not lead:
            log.warning("Lead not found for cache update", lead_id=lead_id)
            return
    
    now = datetime.now(timezone.utc)
    
    # 1. Get consultation aggregates via Repository
    aggregates = await repo.get_consultation_aggregates(lead_id)
    
    last_consultation_at = aggregates["last_consultation_at"]
    consultation_count = aggregates["consultation_count"]
    pending_next_activity = aggregates["pending_next_activity"]
    
    # 2. Calculate days since contact
    if last_consultation_at:
        # Ensure timezone aware
        if last_consultation_at.tzinfo is None:
            last_consultation_at = last_consultation_at.replace(tzinfo=timezone.utc)
        days_since_contact = (now - last_consultation_at).days
    else:
        # Fallback to created_at
        created_at = lead.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        days_since_contact = (now - created_at).days
    
    # 3. Calculate overdue days
    overdue_days = 0
    if pending_next_activity:
        if pending_next_activity.tzinfo is None:
            pending_next_activity = pending_next_activity.replace(tzinfo=timezone.utc)
        if pending_next_activity < now:
            overdue_days = (now - pending_next_activity).days
    
    # 4. Check final stage
    is_final_stage = False
    if lead.pipeline_stage_id:
        # Need to check pipeline_stage.is_final
        # For now, check common final stage IDs
        FINAL_STAGE_IDS = ["stg05", "stg06"]  # Converted, Lost
        is_final_stage = lead.pipeline_stage_id in FINAL_STAGE_IDS
    
    # 5. Calculate urgency score
    urgency_score = calculate_urgency_score(
        days_since_contact=days_since_contact,
        lead_score=lead.lead_score or 0,
        consultation_count=consultation_count,
        overdue_days=overdue_days,
        is_final_stage=is_final_stage
    )
    
    # 6. Update lead cached fields
    lead.last_consultation_at = last_consultation_at
    lead.consultation_count = consultation_count
    lead.cached_urgency_score = urgency_score
    lead.is_hot_lead = (lead.lead_score or 0) >= 70
    lead.is_overdue = overdue_days > 0
    lead.next_activity_at = pending_next_activity
    
    # 7. Flush (no commit - caller handles transaction)
    await db.flush()
    
    log.debug(
        "Lead cache updated",
        lead_id=lead_id,
        urgency_score=urgency_score,
        consultation_count=consultation_count,
        is_hot_lead=lead.is_hot_lead,
        is_overdue=lead.is_overdue,
    )


async def batch_update_lead_caches(
    db: AsyncSession,
    lead_ids: list[int]
) -> int:
    """
    Batch update cached fields for multiple leads.
    
    Used by:
    - Nightly cron job (recalculate all urgency scores)
    - Backfill script
    
    Args:
        db: SQLAlchemy session
        lead_ids: List of Lead IDs to update
        
    Returns:
        Number of leads updated
    """
    updated = 0
    for lead_id in lead_ids:
        try:
            await update_lead_cache(db, lead_id)
            updated += 1
        except Exception as e:
            log.error("Failed to update lead cache", lead_id=lead_id, error=str(e))
    
    await db.commit()
    return updated
