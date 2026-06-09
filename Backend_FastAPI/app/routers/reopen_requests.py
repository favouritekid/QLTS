# app/routers/reopen_requests.py
"""Reopen request inbox (Phase B) — duyệt/từ chối/hủy yêu cầu mở lại lead.

Đăng ký với prefix ``/api/reopen-requests`` (main.py). Casbin (migration
leadreopen_b) gate role per-endpoint; IDOR approve/reject qua
``get_reopen_request_for_user`` (unit-scope theo lead hiện tại). Xem
Documents/LEAD_REOPEN_WORKFLOW_PLAN.md §7.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core.deps import CasbinAuth, get_reopen_request_for_user
from ..core.rate_limits import limiter, RateLimits
from ..services import lead_reopen_service

router = APIRouter(tags=["reopen-requests"])

ReopenRequestDep = Depends(get_reopen_request_for_user)


def _name(user: Optional[models.User]) -> Optional[str]:
    if user is None:
        return None
    return user.full_name or user.username


def _serialize(
    req: models.LeadReopenRequest,
    *,
    lead_name: Optional[str] = None,
    requested_by_name: Optional[str] = None,
    reviewed_by_name: Optional[str] = None,
) -> schemas.LeadReopenRequestOut:
    return schemas.LeadReopenRequestOut(
        id=req.id,
        lead_id=req.lead_id,
        requested_by_id=req.requested_by_id,
        reason=req.reason,
        status=req.status,
        reviewed_by_id=req.reviewed_by_id,
        review_note=req.review_note,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
        unit_id=req.unit_id,
        lead_name=lead_name,
        requested_by_name=requested_by_name,
        reviewed_by_name=reviewed_by_name,
    )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=List[schemas.LeadReopenRequestOut])
async def list_requests(
    request: Request,
    status: Optional[str] = None,
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """Inbox duyệt (manager/admin). Manager scope theo ``lead.unit_id`` hiện tại; admin
    toàn hệ thống. ``status`` lọc tùy chọn (vd 'pending')."""
    reqs = await lead_reopen_service.list_reopen_requests(
        db, current_user, status=status
    )
    return [
        _serialize(
            r,
            lead_name=r.lead.full_name if r.lead else None,
            requested_by_name=_name(r.requested_by),
            reviewed_by_name=_name(r.reviewed_by),
        )
        for r in reqs
    ]


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/{request_id}/approve", response_model=schemas.LeadReopenRequestOut)
async def approve_request(
    request: Request,
    body: schemas.ReopenReviewBody,
    reopen_request: models.LeadReopenRequest = ReopenRequestDep,
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """Manager/admin DUYỆT → gọi lõi reopen (lead về sts04)."""
    result, callback = await lead_reopen_service.approve_reopen(
        db, reopen_request.id, current_user, note=body.note
    )
    await db.commit()
    if callback:
        await callback()
    return _serialize(result, reviewed_by_name=_name(current_user))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/{request_id}/reject", response_model=schemas.LeadReopenRequestOut)
async def reject_request(
    request: Request,
    body: schemas.ReopenReviewBody,
    reopen_request: models.LeadReopenRequest = ReopenRequestDep,
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """Manager/admin TỪ CHỐI (note bắt buộc, validate ở service); lead giữ sts20."""
    result, callback = await lead_reopen_service.reject_reopen(
        db, reopen_request.id, current_user, note=body.note or ""
    )
    await db.commit()
    if callback:
        await callback()
    return _serialize(result, reviewed_by_name=_name(current_user))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{request_id}", response_model=schemas.LeadReopenRequestOut)
async def cancel_request(
    request: Request,
    request_id: int = Path(..., description="ID reopen request"),
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """Officer HỦY yêu cầu pending của CHÍNH mình (service check ownership → 404)."""
    result = await lead_reopen_service.cancel_reopen(db, request_id, current_user)
    await db.commit()
    return _serialize(result)
