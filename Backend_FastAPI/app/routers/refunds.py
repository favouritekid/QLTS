"""Refund request API."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.constants import UserRole
from app.core.deps import CasbinAuth, finance_scope_unit_id
from app.core.rate_limits import RateLimits, limiter
from app.schemas import finance as finance_schemas
from app.services.payment_service import RefundService
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ResourceNotFoundError,
)


router = APIRouter(prefix="/refunds", tags=["Finance - Refunds"])


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "",
    response_model=finance_schemas.RefundsPage,
    summary="List refund requests",
)
async def list_refunds(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    payment_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    refund_service = RefundService(db)
    unit_id = finance_scope_unit_id(current_user)
    statuses = _parse_status_filter(status_filter)
    refunds, total = await refund_service.list_refunds(
        skip=(page - 1) * page_size,
        limit=page_size,
        unit_id=unit_id,
        statuses=statuses,
        payment_id=payment_id,
    )
    can_create = current_user.role in [
        UserRole.ACCOUNTANT,
        UserRole.ADMIN,
    ]
    return finance_schemas.RefundsPage(
        items=[
            _build_refund_response(refund, current_user.id, current_user.role)
            for refund in refunds
        ],
        total=total,
        page=page,
        page_size=page_size,
        can_create=can_create,
    )


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "",
    response_model=finance_schemas.RefundRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create refund request",
)
async def create_refund(
    request: Request,
    data: finance_schemas.RefundRequestCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    # F1/F12: create is authorized by Casbin alone — POST /api/refunds is granted
    # only to accountant (explicit) + admin (wildcard). Officer was removed from
    # the grant (it leaked to manager via `g, role:manager, role:officer` and had
    # no UI), and manager/officer have no inheritance path to it. The can_create
    # response flag mirrors this for the FE.
    refund_service = RefundService(db)
    unit_id = finance_scope_unit_id(current_user)
    try:
        refund, callback = await refund_service.request_refund(
            payment_id=data.payment_id,
            amount=data.amount,
            reason=data.reason,
            user_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        refund = await refund_service.get_refund(refund.id, unit_id)
        return _build_refund_response(refund, current_user.id, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BadRequest, BusinessRuleViolation) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{refund_id}",
    response_model=finance_schemas.RefundRequestResponse,
    summary="Get refund request detail",
)
async def get_refund(
    request: Request,
    refund_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    refund_service = RefundService(db)
    unit_id = finance_scope_unit_id(current_user)
    try:
        refund = await refund_service.get_refund(refund_id, unit_id)
        return _build_refund_response(refund, current_user.id, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{refund_id}/approve",
    response_model=finance_schemas.RefundRequestResponse,
    summary="Approve refund request",
)
async def approve_refund(
    request: Request,
    refund_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    refund_service = RefundService(db)
    unit_id = finance_scope_unit_id(current_user)
    try:
        refund, callback = await refund_service.approve_refund(
            refund_id=refund_id,
            approver_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        refund = await refund_service.get_refund(refund.id, unit_id)
        return _build_refund_response(refund, current_user.id, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{refund_id}/reject",
    response_model=finance_schemas.RefundRequestResponse,
    summary="Reject refund request",
)
async def reject_refund(
    request: Request,
    refund_id: int,
    data: finance_schemas.RefundRejectRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    refund_service = RefundService(db)
    unit_id = finance_scope_unit_id(current_user)
    try:
        refund, callback = await refund_service.reject_refund(
            refund_id=refund_id,
            reason=data.rejection_reason,
            rejector_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        refund = await refund_service.get_refund(refund.id, unit_id)
        return _build_refund_response(refund, current_user.id, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BadRequest, BusinessRuleViolation) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{refund_id}/process",
    response_model=finance_schemas.RefundRequestResponse,
    summary="Process approved refund",
)
async def process_refund(
    request: Request,
    refund_id: int,
    data: finance_schemas.RefundProcessRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    if data.refund_id != refund_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refund_id in body must match path",
        )

    refund_service = RefundService(db)
    unit_id = finance_scope_unit_id(current_user)
    try:
        refund, callback = await refund_service.process_approved_refund(
            refund_id=refund_id,
            processor_id=current_user.id,
            refund_reference=data.refund_reference,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        refund = await refund_service.get_refund(refund.id, unit_id)
        return _build_refund_response(refund, current_user.id, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _parse_status_filter(status_filter: Optional[str]) -> Optional[List[str]]:
    if not status_filter:
        return None
    return [part.strip() for part in status_filter.split(",") if part.strip()]


def _build_refund_response(
    refund,
    current_user_id: int,
    current_user_role: str,
) -> finance_schemas.RefundRequestResponse:
    status_value = (
        refund.status.value if hasattr(refund.status, "value") else refund.status
    )
    is_pending = status_value == "pending"
    is_approved = status_value == "approved"
    is_manager_or_admin = current_user_role in [UserRole.MANAGER, UserRole.ADMIN]
    is_accountant_or_admin = current_user_role in [UserRole.ACCOUNTANT, UserRole.ADMIN]
    is_different_user = refund.requested_by_id != current_user_id

    return finance_schemas.RefundRequestResponse(
        id=refund.id,
        payment_id=refund.payment_id,
        amount=refund.amount,
        reason=refund.reason,
        status=refund.status,
        requested_at=refund.requested_at,
        requested_by_id=refund.requested_by_id,
        approved_at=refund.approved_at,
        approved_by_id=refund.approved_by_id,
        rejected_at=refund.rejected_at,
        rejected_by_id=refund.rejected_by_id,
        rejection_reason=refund.rejection_reason,
        refunded_at=refund.refunded_at,
        refund_reference=refund.refund_reference,
        created_at=refund.created_at,
        updated_at=refund.updated_at,
        can_approve=is_pending and is_manager_or_admin and is_different_user,
        can_reject=is_pending and is_manager_or_admin and is_different_user,
        can_process=is_approved and is_accountant_or_admin,
    )
