# app/routers/admin/audit_logs.py
"""
Entity Audit Log Router

Provides endpoints to query audit logs for any entity in the system.
Admin/Manager only access.
"""
from typing import Optional, List
from datetime import datetime

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Request,
    Query,
)
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import database, models
from app.core.deps import require_admin_or_manager
from app.core.rate_limits import limiter, RateLimits

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Admin - Audit Logs"])


# ============================================================================
# SCHEMAS FOR AUDIT LOGS
# ============================================================================


class AuditLogActorSummary(BaseModel):
    """Summary of the actor who performed an action."""
    id: int
    username: str
    full_name: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogEntry(BaseModel):
    """Single audit log entry."""
    id: int
    entity_type: str
    entity_id: int
    action: str
    actor: Optional[AuditLogActorSummary] = None
    field_name: Optional[str] = None
    old_value: Optional[dict | str | int | list] = None
    new_value: Optional[dict | str | int | list] = None
    changes: Optional[dict] = None
    reason: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated list of audit log entries."""
    items: List[AuditLogEntry]
    total: int
    page: int
    page_size: int
    has_more: bool


# ============================================================================
# ENDPOINTS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 500/hour
@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="List audit logs with filters",
)
async def list_audit_logs(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
    # Filters
    entity_type: Optional[str] = Query(None, description="Filter by entity type (Lead, Consultation, etc.)"),
    entity_id: Optional[int] = Query(None, description="Filter by specific entity ID"),
    action: Optional[str] = Query(None, description="Filter by action (created, updated, deleted, restored)"),
    actor_id: Optional[int] = Query(None, description="Filter by actor user ID"),
    field_name: Optional[str] = Query(None, description="Filter by field name"),
    # Date range
    from_date: Optional[datetime] = Query(None, description="Filter from date (inclusive)"),
    to_date: Optional[datetime] = Query(None, description="Filter to date (inclusive)"),
    # Pagination
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
):
    """
    List audit logs with optional filters.

    Admin/Manager only. Returns most recent entries first.

    Supported entity types: Lead, Consultation, AdmissionProfile, etc.
    Supported actions: created, updated, deleted, restored, status_changed
    """
    # Build base query
    query = (
        select(models.EntityAuditLog)
        .options(selectinload(models.EntityAuditLog.actor))
        .order_by(desc(models.EntityAuditLog.created_at))
    )

    # Apply filters
    if entity_type:
        query = query.where(models.EntityAuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(models.EntityAuditLog.entity_id == entity_id)
    if action:
        query = query.where(models.EntityAuditLog.action == action)
    if actor_id:
        query = query.where(models.EntityAuditLog.actor_user_id == actor_id)
    if field_name:
        query = query.where(models.EntityAuditLog.field_name == field_name)
    if from_date:
        query = query.where(models.EntityAuditLog.created_at >= from_date)
    if to_date:
        query = query.where(models.EntityAuditLog.created_at <= to_date)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    audit_logs = result.scalars().all()

    # Build response
    items = []
    for log_entry in audit_logs:
        actor_summary = None
        if log_entry.actor:
            actor_summary = AuditLogActorSummary(
                id=log_entry.actor.id,
                username=log_entry.actor.username,
                full_name=log_entry.actor.full_name,
            )

        items.append(AuditLogEntry(
            id=log_entry.id,
            entity_type=log_entry.entity_type,
            entity_id=log_entry.entity_id,
            action=log_entry.action,
            actor=actor_summary,
            field_name=log_entry.field_name,
            old_value=log_entry.old_value,
            new_value=log_entry.new_value,
            changes=log_entry.changes,
            reason=log_entry.reason,
            source=log_entry.source,
            created_at=log_entry.created_at,
        ))

    log.info(
        "Listed audit logs",
        user_id=current_user.id,
        filters={"entity_type": entity_type, "entity_id": entity_id, "action": action},
        total=total,
        returned=len(items),
    )

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < total,
    )


@limiter.limit(RateLimits.ADMIN_READ)  # 500/hour
@router.get(
    "/audit-logs/entity/{entity_type}/{entity_id}",
    response_model=AuditLogListResponse,
    summary="Get audit log history for a specific entity",
)
async def get_entity_audit_history(
    request: Request,
    entity_type: str,
    entity_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
):
    """
    Get the complete audit history for a specific entity.

    Useful for viewing the full change history of a Lead, Consultation, etc.
    Returns entries in reverse chronological order (newest first).
    """
    # Build query for specific entity
    query = (
        select(models.EntityAuditLog)
        .options(selectinload(models.EntityAuditLog.actor))
        .where(
            models.EntityAuditLog.entity_type == entity_type,
            models.EntityAuditLog.entity_id == entity_id,
        )
        .order_by(desc(models.EntityAuditLog.created_at))
    )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    audit_logs = result.scalars().all()

    # Build response
    items = []
    for log_entry in audit_logs:
        actor_summary = None
        if log_entry.actor:
            actor_summary = AuditLogActorSummary(
                id=log_entry.actor.id,
                username=log_entry.actor.username,
                full_name=log_entry.actor.full_name,
            )

        items.append(AuditLogEntry(
            id=log_entry.id,
            entity_type=log_entry.entity_type,
            entity_id=log_entry.entity_id,
            action=log_entry.action,
            actor=actor_summary,
            field_name=log_entry.field_name,
            old_value=log_entry.old_value,
            new_value=log_entry.new_value,
            changes=log_entry.changes,
            reason=log_entry.reason,
            source=log_entry.source,
            created_at=log_entry.created_at,
        ))

    log.info(
        "Retrieved entity audit history",
        user_id=current_user.id,
        entity_type=entity_type,
        entity_id=entity_id,
        total=total,
    )

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < total,
    )


@limiter.limit(RateLimits.ADMIN_READ)
@router.get(
    "/audit-logs/summary",
    summary="Get audit log summary statistics",
)
async def get_audit_summary(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
):
    """
    Get summary statistics for audit logs.

    Returns counts by entity type and action type.
    """
    # Base query for counts by entity type
    entity_type_query = (
        select(
            models.EntityAuditLog.entity_type,
            func.count(models.EntityAuditLog.id).label("count")
        )
        .group_by(models.EntityAuditLog.entity_type)
    )

    # Base query for counts by action
    action_query = (
        select(
            models.EntityAuditLog.action,
            func.count(models.EntityAuditLog.id).label("count")
        )
        .group_by(models.EntityAuditLog.action)
    )

    # Apply date filters
    if from_date:
        entity_type_query = entity_type_query.where(
            models.EntityAuditLog.created_at >= from_date
        )
        action_query = action_query.where(
            models.EntityAuditLog.created_at >= from_date
        )
    if to_date:
        entity_type_query = entity_type_query.where(
            models.EntityAuditLog.created_at <= to_date
        )
        action_query = action_query.where(
            models.EntityAuditLog.created_at <= to_date
        )

    # Execute queries
    entity_result = await db.execute(entity_type_query)
    action_result = await db.execute(action_query)

    # Get total count
    total_query = select(func.count(models.EntityAuditLog.id))
    if from_date:
        total_query = total_query.where(models.EntityAuditLog.created_at >= from_date)
    if to_date:
        total_query = total_query.where(models.EntityAuditLog.created_at <= to_date)
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    # Build response
    by_entity_type = {row.entity_type: row.count for row in entity_result}
    by_action = {row.action: row.count for row in action_result}

    return {
        "total": total,
        "by_entity_type": by_entity_type,
        "by_action": by_action,
    }
