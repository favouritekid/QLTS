# app/routers/admin/deleted_items.py
"""
Deleted Items Admin Router

Handles viewing and restoring soft-deleted items:
- Deleted Leads
- Deleted Consultations

Admin only access.
"""
from typing import Optional, List
from datetime import datetime

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Request,
    Query,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import database, models, schemas
from app.core.constants import UserRole
from app.core.deps import get_lead_for_user, require_admin_or_manager
from app.core.events import SystemEvents
from app.core.rate_limits import limiter, RateLimits
from app.repositories.organization_repository import OrganizationRepository
from app.services import lead_service
from app.services.notification_dispatcher import rooms_for_lead, safe_dispatch
from app.services.notification_payloads import EventPayload

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Admin - Deleted Items"])


async def _resolve_deleted_items_unit_scope(
    db: AsyncSession,
    current_user: models.User,
) -> Optional[List[int]]:
    """Đơn vị mà user được phép thấy trong màn "Deleted Items".

    Returns:
        None  -> toàn hệ thống (admin).
        list  -> giới hạn theo cây đơn vị (manager). Rỗng = không thấy gì.

    Manager chưa gán đơn vị (``unit_id`` NULL) trả ``[]`` — fail-closed, cùng
    hướng với ``get_lead_for_user`` (deps.py: manager không unit_id -> 404).
    """
    if current_user.role == UserRole.ADMIN:
        return None

    if current_user.unit_id is None:
        return []

    org_repo = OrganizationRepository(db)
    return await org_repo.get_descendant_unit_ids(current_user.unit_id)


# ============================================================================
# SCHEMAS FOR DELETED ITEMS
# ============================================================================


class DeletedLeadSummary(BaseModel):
    """Summary of a deleted lead for list view."""
    id: int
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    deleted_at: datetime
    deleted_by_name: Optional[str] = None
    consultation_count: int = 0

    class Config:
        from_attributes = True


class DeletedConsultationSummary(BaseModel):
    """Summary of a deleted consultation for list view."""
    id: int
    lead_id: int
    lead_name: str
    consultation_status_name: Optional[str] = None
    consultation_date: Optional[datetime] = None
    deleted_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class DeletedItemsResponse(BaseModel):
    """Response containing lists of deleted items."""
    deleted_leads: List[DeletedLeadSummary]
    deleted_consultations: List[DeletedConsultationSummary]
    total_leads: int
    total_consultations: int


# ============================================================================
# ENDPOINTS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 500/hour
@router.get(
    "/deleted-items",
    response_model=DeletedItemsResponse,
    summary="List all deleted items (leads and consultations)",
)
async def list_deleted_items(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
    limit: int = Query(50, ge=1, le=200, description="Max items per category"),
    search: Optional[str] = Query(None, description="Search by name/phone/email"),
):
    """
    List all soft-deleted leads and consultations.

    Admin: toàn hệ thống. Manager: CHỈ trong cây đơn vị của mình.

    Unit-scope phải áp cho MỌI phần (rows + counts + search) — lọc rows mà
    bỏ counts thì manager vẫn suy ra được SỐ LƯỢNG lead/consultation của
    đơn vị khác.
    """
    allowed_unit_ids = await _resolve_deleted_items_unit_scope(db, current_user)

    def _scope_leads(stmt):
        """Giới hạn theo unit của Lead. None = admin, không giới hạn."""
        if allowed_unit_ids is None:
            return stmt
        return stmt.where(models.Lead.unit_id.in_(allowed_unit_ids))

    def _scope_consultations(stmt):
        """Giới hạn theo unit của Lead mà consultation thuộc về."""
        if allowed_unit_ids is None:
            return stmt
        return stmt.where(
            models.Consultation.lead.has(
                models.Lead.unit_id.in_(allowed_unit_ids)
            )
        )

    # ========== DELETED LEADS ==========
    leads_query = _scope_leads(
        select(models.Lead)
        .where(models.Lead.deleted_at.isnot(None))
        .order_by(models.Lead.deleted_at.desc())
        .limit(limit)
    )

    if search:
        search_pattern = f"%{search}%"
        leads_query = leads_query.where(
            (models.Lead.full_name.ilike(search_pattern)) |
            (models.Lead.phone.ilike(search_pattern)) |
            (models.Lead.email.ilike(search_pattern))
        )

    leads_result = await db.execute(leads_query)
    deleted_leads_raw = leads_result.scalars().all()

    # Count total deleted leads
    total_leads_result = await db.execute(
        _scope_leads(
            select(func.count(models.Lead.id))
            .where(models.Lead.deleted_at.isnot(None))
        )
    )
    total_leads = total_leads_result.scalar() or 0

    # Build lead summaries
    deleted_leads = []
    for lead in deleted_leads_raw:
        # Count consultations for this lead
        consult_count_result = await db.execute(
            select(func.count(models.Consultation.id))
            .where(models.Consultation.lead_id == lead.id)
        )
        consult_count = consult_count_result.scalar() or 0

        deleted_leads.append(DeletedLeadSummary(
            id=lead.id,
            full_name=lead.full_name,
            phone=lead.phone,
            email=lead.email,
            deleted_at=lead.deleted_at,
            deleted_by_name=None,  # Could be enhanced to track who deleted
            consultation_count=consult_count,
        ))

    # ========== DELETED CONSULTATIONS ==========
    consultations_query = _scope_consultations(
        select(models.Consultation)
        .options(
            selectinload(models.Consultation.lead),
            selectinload(models.Consultation.consultation_status),
        )
        .where(
            models.Consultation.deleted_at.isnot(None),
            # Only show consultations from active leads (not cascade deleted)
            models.Consultation.lead.has(models.Lead.deleted_at.is_(None)),
        )
        .order_by(models.Consultation.deleted_at.desc())
        .limit(limit)
    )

    if search:
        consultations_query = consultations_query.where(
            models.Consultation.lead.has(
                models.Lead.full_name.ilike(f"%{search}%")
            )
        )

    consultations_result = await db.execute(consultations_query)
    deleted_consultations_raw = consultations_result.scalars().all()

    # Count total deleted consultations (from active leads only)
    total_consultations_result = await db.execute(
        _scope_consultations(
            select(func.count(models.Consultation.id))
            .where(
                models.Consultation.deleted_at.isnot(None),
                models.Consultation.lead.has(models.Lead.deleted_at.is_(None)),
            )
        )
    )
    total_consultations = total_consultations_result.scalar() or 0

    # Build consultation summaries
    deleted_consultations = []
    for consultation in deleted_consultations_raw:
        deleted_consultations.append(DeletedConsultationSummary(
            id=consultation.id,
            lead_id=consultation.lead_id,
            lead_name=consultation.lead.full_name if consultation.lead else "Unknown",
            consultation_status_name=(
                consultation.consultation_status.name
                if consultation.consultation_status else None
            ),
            consultation_date=consultation.consultation_date,
            deleted_at=consultation.deleted_at,
            notes=consultation.notes[:100] if consultation.notes else None,  # Truncate
        ))

    log.info(
        "Listed deleted items",
        user_id=current_user.id,
        deleted_leads_count=len(deleted_leads),
        deleted_consultations_count=len(deleted_consultations),
    )

    return DeletedItemsResponse(
        deleted_leads=deleted_leads,
        deleted_consultations=deleted_consultations,
        total_leads=total_leads,
        total_consultations=total_consultations,
    )


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/deleted-items/leads/{lead_id}/restore",
    response_model=schemas.Lead,
    summary="Restore a deleted lead",
)
async def restore_deleted_lead(
    request: Request,
    lead_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Restore a soft-deleted lead and its related consultations.

    Admin only. Also restores consultations deleted at the same time as the lead.
    """
    await lead_service.restore_lead(db, lead_id, current_user)
    await db.commit()

    # Re-fetch with eager loading to avoid lazy load issues
    result = await db.execute(
        select(models.Lead)
        .where(models.Lead.id == lead_id)
        .options(
            selectinload(models.Lead.offering),
            selectinload(models.Lead.unit),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            selectinload(models.Lead.admission_profiles),
        )
    )
    lead = result.scalar_one()

    # ✅ NOTIFICATION: Dispatch LEAD_RESTORED — mirror leads.py:796 pattern.
    # Without this, restoring via "Deleted Items" admin screen skips
    # realtime/notification sync — other tabs viewing lead list never
    # see the restored lead reappear until manual reload (UX inconsistency
    # vs the /leads/{id}/restore path which does emit). Filed as task #42
    # in 2026-05-25 session triage.
    await safe_dispatch(
        db=db,
        event=SystemEvents.LEAD_RESTORED,
        payload=EventPayload.for_lead_restored(lead, current_user),
        dedupe_key=EventPayload.dedupe_key("lead_restored", lead.id),
        rooms=rooms_for_lead(lead),
    )

    log.info(
        "Lead restored via admin API",
        lead_id=lead_id,
        restored_by=current_user.id,
    )

    return lead


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/deleted-items/consultations/{consultation_id}/restore",
    response_model=schemas.Consultation,
    summary="Restore a deleted consultation",
)
async def restore_deleted_consultation(
    request: Request,
    consultation_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Restore a soft-deleted consultation.

    Admin: mọi consultation. Manager: CHỈ trong cây đơn vị của mình.

    Updates lead status if restored consultation is the most recent.

    Thu hẹp có chủ đích: consultation thuộc lead ĐÃ BỊ XÓA nay trả 404
    (get_lead_for_user bỏ qua lead soft-deleted) — trước đây admin restore
    được. Không luồng nào vỡ: list ở trên chỉ trả consultation của lead còn
    sống, nên UI không có đường dẫn tới chúng; và restore lẻ một consultation
    của lead đã xóa là vô nghĩa vì lead vẫn ẩn. Đường đúng để khôi phục là
    restore LEAD — nó tự kéo consultation theo (lead_service.restore_lead).
    """
    # First find the consultation to get lead_id
    consultation_result = await db.execute(
        select(models.Consultation)
        .where(
            models.Consultation.id == consultation_id,
            models.Consultation.deleted_at.isnot(None),
        )
    )
    consultation = consultation_result.scalar_one_or_none()

    if not consultation:
        from app.utils.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError(
            detail=f"Deleted consultation with id {consultation_id} not found."
        )

    lead_id = consultation.lead_id

    # Ép unit-scope: lead_id lấy TỪ CHÍNH row người gọi chỉ định, nên filter
    # lead_id bên trong restore_consultation luôn khớp và không cản được gì.
    # get_lead_for_user là chốt IDOR duy nhất ở đây (manager ngoài cây đơn vị
    # -> 404; manager chưa gán đơn vị -> fail-closed 404).
    # Phải gọi bằng KEYWORD: các tham số có Path()/Depends() làm default.
    await get_lead_for_user(lead_id=lead_id, db=db, current_user=current_user)

    # Restore it
    await lead_service.restore_consultation(
        db, lead_id, consultation_id, current_user
    )
    await db.commit()

    # Re-fetch with eager loading to avoid lazy load issues.
    # ``officer`` PHẢI eager-load: response_model schemas.Consultation có
    # ``officer: Optional[User]``; khi người restore KHÁC officer tạo
    # consultation (vd manager restore cuộc do officer ghi — đúng ca S1 mở),
    # officer không nằm sẵn identity-map → serialize lazy-load → MissingGreenlet
    # (500). Trước đây lọt vì không test nào chạy success-path này.
    result = await db.execute(
        select(models.Consultation)
        .where(models.Consultation.id == consultation_id)
        .options(
            selectinload(models.Consultation.consultation_status)
            .selectinload(models.ConsultationStatus.stage),
            selectinload(models.Consultation.lead),
            selectinload(models.Consultation.officer),
        )
    )
    restored = result.scalar_one()

    log.info(
        "Consultation restored via admin API",
        consultation_id=consultation_id,
        lead_id=lead_id,
        restored_by=current_user.id,
    )

    return restored
