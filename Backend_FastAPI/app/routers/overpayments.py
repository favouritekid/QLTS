"""Overpayment resolution API."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.constants import UserRole
from app.core.deps import CasbinAuth
from app.core.rate_limits import RateLimits, limiter
from app.schemas import finance as finance_schemas
from app.services.overpayment_service import OverpaymentService
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ResourceNotFoundError,
)


router = APIRouter(prefix="/overpayments", tags=["Finance - Overpayments"])


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "",
    response_model=finance_schemas.OverpaymentsPage,
    summary="List overpayments",
)
async def list_overpayments(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    profile_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    service = OverpaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id
    overpayments, total = await service.list_overpayments(
        skip=(page - 1) * page_size,
        limit=page_size,
        unit_id=unit_id,
        statuses=_parse_status_filter(status_filter),
        profile_id=profile_id,
    )
    return finance_schemas.OverpaymentsPage(
        items=[
            _build_overpayment_response(overpayment, current_user.role)
            for overpayment in overpayments
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{overpayment_id}",
    response_model=finance_schemas.OverpaymentRecordResponse,
    summary="Get overpayment detail",
)
async def get_overpayment(
    request: Request,
    overpayment_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    service = OverpaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id
    try:
        overpayment = await service.get_overpayment(overpayment_id, unit_id)
        return _build_overpayment_response(overpayment, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{overpayment_id}/apply",
    response_model=finance_schemas.OverpaymentRecordResponse,
    summary="Apply overpayment to another invoice",
)
async def apply_overpayment(
    request: Request,
    overpayment_id: int,
    data: finance_schemas.OverpaymentApplyRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    if data.overpayment_id != overpayment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="overpayment_id in body must match path",
        )

    service = OverpaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id
    try:
        overpayment, callback = await service.apply_to_invoice(
            overpayment_id=overpayment_id,
            target_invoice_id=data.target_invoice_id,
            amount=data.amount,
            notes=data.notes,
            user_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        overpayment = await service.get_overpayment(overpayment.id, unit_id)
        return _build_overpayment_response(overpayment, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BadRequest, BusinessRuleViolation) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{overpayment_id}/refund",
    response_model=finance_schemas.OverpaymentRecordResponse,
    summary="Create refund request for overpayment",
)
async def refund_overpayment(
    request: Request,
    overpayment_id: int,
    data: finance_schemas.OverpaymentRefundRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    if data.overpayment_id != overpayment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="overpayment_id in body must match path",
        )

    service = OverpaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id
    try:
        overpayment, callback = await service.refund_overpayment(
            overpayment_id=overpayment_id,
            notes=data.notes,
            user_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        overpayment = await service.get_overpayment(overpayment.id, unit_id)
        return _build_overpayment_response(overpayment, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BadRequest, BusinessRuleViolation) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{overpayment_id}/write-off",
    response_model=finance_schemas.OverpaymentRecordResponse,
    summary="Write off overpayment",
)
async def write_off_overpayment(
    request: Request,
    overpayment_id: int,
    data: finance_schemas.OverpaymentWriteOffRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    if data.overpayment_id != overpayment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="overpayment_id in body must match path",
        )

    service = OverpaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id
    try:
        overpayment, callback = await service.write_off(
            overpayment_id=overpayment_id,
            reason=data.reason,
            user_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()
        overpayment = await service.get_overpayment(overpayment.id, unit_id)
        return _build_overpayment_response(overpayment, current_user.role)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BadRequest, BusinessRuleViolation) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _parse_status_filter(status_filter: Optional[str]) -> Optional[List[str]]:
    if not status_filter:
        return None
    return [part.strip() for part in status_filter.split(",") if part.strip()]


def _build_overpayment_response(
    overpayment,
    current_user_role: str,
) -> finance_schemas.OverpaymentRecordResponse:
    status_value = (
        overpayment.status.value
        if hasattr(overpayment.status, "value")
        else overpayment.status
    )
    is_pending = status_value == "pending"
    # Mirror Casbin maker-checker: apply/refund are accountant finance actions,
    # write-off is a manager action; admin can do all three via wildcard.
    is_finance = current_user_role in [UserRole.ACCOUNTANT, UserRole.ADMIN]
    is_manager_admin = current_user_role in [UserRole.MANAGER, UserRole.ADMIN]
    can_apply = is_pending and is_finance
    can_refund = is_pending and is_finance
    can_write_off = is_pending and is_manager_admin
    can_resolve = can_apply or can_refund or can_write_off

    return finance_schemas.OverpaymentRecordResponse(
        id=overpayment.id,
        payment_id=overpayment.payment_id,
        invoice_id=overpayment.invoice_id,
        admission_profile_id=overpayment.admission_profile_id,
        overpayment_amount=overpayment.overpayment_amount,
        currency=overpayment.currency,
        status=overpayment.status,
        resolution_type=overpayment.resolution_type,
        resolved_at=overpayment.resolved_at,
        resolved_by_id=overpayment.resolved_by_id,
        resolution_notes=overpayment.resolution_notes,
        applied_to_invoice_id=overpayment.applied_to_invoice_id,
        applied_amount=overpayment.applied_amount,
        refund_request_id=overpayment.refund_request_id,
        created_at=overpayment.created_at,
        updated_at=overpayment.updated_at,
        can_resolve=can_resolve,
        can_apply=can_apply,
        can_refund=can_refund,
        can_write_off=can_write_off,
    )
