# app/routers/fees.py
"""
Router for Fee Management (Finance Module Phase 4).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- Transaction Management: Router calls db.commit() after service returns
- RBAC: All endpoints protected by CasbinAuth dependency
- Error Handling: Convert custom exceptions to HTTPException
- IDOR Protection: Unit-based access control via service layer

Endpoints:
- POST /api/fees/calculate - Calculate fee for admission profile
- GET /api/fees/{fee_id} - Get fee details
- GET /api/fees/by-profile/{profile_id} - Get all fees for profile
- GET /api/fees/summary/{profile_id} - Get financial summary for profile
- POST /api/fees/{fee_id}/waive - Waive fee amount (admin only)
- POST /api/fees/{fee_id}/cancel - Cancel fee (admin only)
- POST /api/fees/{fee_id}/recalculate - Recalculate fee amount
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models, schemas
from app.core import deps
from app.core.deps import CasbinAuth, RequireAdmin, RequireManager
from app.core.rate_limits import limiter, RateLimits
from app.models.finance import FeeTypeEnum
from app.schemas import finance as finance_schemas
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.repositories.fee_repository import FeeRepository
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/fees", tags=["Finance - Fees"])


def get_client_ip(request: Request) -> str:
    """Helper for rate limiting key generation."""
    return request.client.host if request.client else "unknown"


# ==============================================================================
# FEE LIST
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "",
    response_model=finance_schemas.FeesPage,
    summary="List fees with pagination and filters",
)
async def list_fees(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status (comma-separated)"),
    fee_type: Optional[str] = Query(None, description="Filter by fee type (comma-separated)"),
    profile_id: Optional[int] = Query(None, description="Filter by profile ID"),
    academic_year: Optional[str] = Query(None, description="Filter by academic year"),
    has_outstanding: Optional[bool] = Query(None, description="Filter by outstanding balance > 0"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List fees with pagination and filters.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'fees:read' permission
    """
    fee_repo = FeeRepository(db)
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    # Convert page/page_size to skip/limit
    skip = (page - 1) * page_size
    limit = min(page_size, 100)

    # Parse comma-separated values
    statuses: Optional[List[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    fee_types: Optional[List[str]] = None
    if fee_type:
        fee_types = [f.strip() for f in fee_type.split(",") if f.strip()]

    fees, total = await fee_repo.get_filtered_with_count(
        skip=skip,
        limit=limit,
        unit_id=unit_id,
        statuses=statuses,
        fee_types=fee_types,
        has_outstanding=has_outstanding,
        profile_id=profile_id,
        academic_year=academic_year,
    )

    # Build response items with profile name
    items = []
    for fee in fees:
        profile_name = None
        due_date = None

        # Get profile name from relationship
        if fee.admission_profile:
            profile_name = fee.admission_profile.lead.full_name if fee.admission_profile.lead else None

        # Get first invoice due date
        if fee.invoices:
            sorted_invoices = sorted(fee.invoices, key=lambda x: x.due_date)
            if sorted_invoices:
                due_date = sorted_invoices[0].due_date

        items.append(finance_schemas.FeeListItem(
            id=fee.id,
            fee_type=fee.fee_type,
            academic_year=f"{fee.academic_year}-{fee.academic_year + 1}",
            final_amount=fee.final_amount,
            paid_amount=fee.paid_amount,
            remaining_amount=fee.remaining_amount,
            status=fee.status,
            profile_name=profile_name,
            due_date=due_date,
        ))

    return finance_schemas.FeesPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ==============================================================================
# FEE CALCULATION
# ==============================================================================

@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/calculate",
    response_model=finance_schemas.FeeDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Calculate fee for admission profile",
)
async def calculate_fee(
    request: Request,
    data: finance_schemas.FeeCalculateRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Calculate fee for an approved admission profile.

    **Business Rules:**
    - Profile must be in approved status
    - Only one fee per (profile, type, academic_year)
    - Discounts are calculated based on applicable policies
    - Invoices are auto-generated based on installment plan

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'fees:create' permission
    """
    fee_service = FeeCalculationService(db)
    invoice_service = InvoiceService(db)

    # Determine unit_id for IDOR protection
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    try:
        # Get installment plan by code
        plan = await fee_service.fee_repo.get_installment_plan_by_code(data.installment_plan_code)
        plan_id = plan.id if plan else None

        # Get base amount from offering (or use provided amount)
        # For now, we'll need the profile to get the base amount
        profile = await fee_service._get_profile(data.admission_profile_id, unit_id)
        if not profile:
            raise ResourceNotFoundError("Admission profile not found")

        # Get base amount from offering's tuition fee
        base_amount = Decimal("0")
        academic_info = None
        oac = profile.offering_admission_config
        if oac and oac.academic_info:
            academic_info = oac.academic_info

        # Fallback: lookup via applied_rules.academic_info_id (for profiles created before OAC linkage)
        if not academic_info and profile.applied_rules:
            ai_id = profile.applied_rules.get("academic_info_id")
            if ai_id:
                from app.models.offering_academic_info import OfferingAcademicInfo
                ai_result = await db.execute(
                    sa.select(OfferingAcademicInfo).where(OfferingAcademicInfo.id == int(ai_id))
                )
                academic_info = ai_result.scalars().first()

        if academic_info:
            base_amount = academic_info.tuition_fee_per_year or Decimal("0")

        if base_amount <= 0:
            raise BadRequest("Cannot calculate fee: No tuition fee configured for this offering")

        # Get applicable discount policy IDs
        discount_policy_ids = []
        if academic_info:
            discount_policy_ids = academic_info.applied_discount_policy_ids or []

        # Calculate fee
        fee, post_commit = await fee_service.calculate_fee(
            admission_profile_id=data.admission_profile_id,
            fee_type=data.fee_type,
            base_amount=base_amount,
            academic_year=profile.academic_year,
            discount_policy_ids=discount_policy_ids,
            installment_plan_id=plan_id,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        # Generate invoices based on installment plan
        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=current_user.id,
            unit_id=unit_id,
            auto_issue=False,
        )

        await db.commit()

        # Execute post-commit callback
        if post_commit:
            await post_commit()

        # Refresh to load relationships
        await db.refresh(fee)

        log.info(
            "fee_calculated_via_api",
            fee_id=fee.id,
            profile_id=data.admission_profile_id,
            fee_type=data.fee_type.value,
            final_amount=str(fee.final_amount),
            invoice_count=len(invoices),
            user_id=current_user.id,
        )

        # Build response with nested data
        return _build_fee_detail_response(
            fee, invoices, current_user_role=current_user.role
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# FEE RETRIEVAL
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{fee_id}",
    response_model=finance_schemas.FeeDetailResponse,
    summary="Get fee details",
)
async def get_fee(
    request: Request,
    fee_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get fee details including invoices and applied discounts.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'fees:read' permission
    """
    fee_service = FeeCalculationService(db)
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    try:
        fee = await fee_service.get_fee(fee_id, unit_id)

        # Get invoices for this fee
        invoice_repo = fee_service.invoice_repo
        invoices = await invoice_repo.get_by_fee_id(fee_id)

        return _build_fee_detail_response(
            fee, invoices, current_user_role=current_user.role
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/by-profile/{profile_id}",
    response_model=List[finance_schemas.FeeSummaryResponse],
    summary="Get all fees for admission profile",
)
async def get_fees_by_profile(
    request: Request,
    profile_id: int,
    fee_type: Optional[str] = Query(None, description="Filter by fee type"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get all fees for an admission profile.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'fees:read' permission
    """
    fee_service = FeeCalculationService(db)
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    fees = await fee_service.get_fees_for_profile(profile_id, unit_id, fee_type)

    return [
        finance_schemas.FeeSummaryResponse(
            id=f.id,
            fee_type=f.fee_type,
            academic_year=f.academic_year,
            final_amount=f.final_amount,
            paid_amount=f.paid_amount,
            remaining_amount=f.remaining_amount,
            status=f.status,
        )
        for f in fees
    ]


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/summary/{profile_id}",
    response_model=finance_schemas.ProfileFinanceSummary,
    summary="Get financial summary for profile",
)
async def get_profile_finance_summary(
    request: Request,
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get complete financial summary for an admission profile.

    **Returns:**
    - Total fees, paid amount, remaining balance
    - List of all fees with status
    - Count of pending and overdue invoices
    """
    fee_service = FeeCalculationService(db)
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    summary = await fee_service.get_fee_summary(profile_id, unit_id)

    # Count pending and overdue invoices
    pending_count = 0
    overdue_count = 0
    for fee in summary["fees"]:
        for invoice in fee.invoices:
            if invoice.status == "issued":
                pending_count += 1
            elif invoice.status == "overdue":
                overdue_count += 1

    return finance_schemas.ProfileFinanceSummary(
        admission_profile_id=profile_id,
        total_fees=summary["total_fees"],
        total_paid=summary["total_paid"],
        total_remaining=summary["total_remaining"],
        fees=[
            finance_schemas.FeeSummaryResponse(
                id=f.id,
                fee_type=f.fee_type,
                academic_year=f.academic_year,
                final_amount=f.final_amount,
                paid_amount=f.paid_amount,
                remaining_amount=f.remaining_amount,
                status=f.status,
            )
            for f in summary["fees"]
        ],
        pending_invoices=pending_count,
        overdue_invoices=overdue_count,
    )


# ==============================================================================
# FEE LIFECYCLE
# ==============================================================================

@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{fee_id}/waive",
    response_model=finance_schemas.FeeResponse,
    summary="Waive fee amount",
)
async def waive_fee(
    request: Request,
    fee_id: int,
    data: finance_schemas.FeeWaiveRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireManager,
):
    """
    Waive part or all of a fee amount.

    **Business Rules:**
    - Waive amount cannot exceed remaining balance (H5)
    - Requires manager or admin role
    - Reason is required for audit

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Role enforced via RequireManager dependency
    """
    fee_service = FeeCalculationService(db)
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    try:
        fee, _ = await fee_service.waive_fee(
            fee_id=fee_id,
            waive_amount=data.waive_amount,
            reason=data.reason,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "fee_waived_via_api",
            fee_id=fee_id,
            waive_amount=str(data.waive_amount),
            user_id=current_user.id,
        )

        await db.refresh(fee)
        return _build_fee_response(fee, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{fee_id}/cancel",
    response_model=finance_schemas.FeeResponse,
    summary="Cancel fee",
)
async def cancel_fee(
    request: Request,
    fee_id: int,
    reason: str = Query(..., min_length=1, max_length=500, description="Cancellation reason"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireAdmin,
):
    """
    Cancel a fee (only if no payments made).

    **Business Rules:**
    - Cannot cancel fee with existing payments
    - Requires admin role
    - Reason is required for audit

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Role enforced via RequireAdmin dependency
    """
    fee_service = FeeCalculationService(db)
    unit_id = None  # Admin can access all units

    try:
        fee, _ = await fee_service.cancel_fee(
            fee_id=fee_id,
            reason=reason,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "fee_cancelled_via_api",
            fee_id=fee_id,
            reason=reason,
            user_id=current_user.id,
        )

        await db.refresh(fee)
        return _build_fee_response(fee, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{fee_id}/recalculate",
    response_model=finance_schemas.FeeResponse,
    summary="Recalculate fee amount",
)
async def recalculate_fee(
    request: Request,
    fee_id: int,
    new_base_amount: Decimal = Query(..., gt=0, description="New base amount"),
    reason: str = Query(..., min_length=1, max_length=500, description="Recalculation reason"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireManager,
):
    """
    Recalculate fee with new base amount.

    **Business Rules:**
    - Cannot recalculate if any payment has been made (M10)
    - Requires manager or admin role
    - Reason is required for audit

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Role enforced via RequireManager dependency
    """
    fee_service = FeeCalculationService(db)
    unit_id = None if current_user.role == "admin" else current_user.unit_id

    try:
        fee, _ = await fee_service.recalculate_fee(
            fee_id=fee_id,
            new_base_amount=new_base_amount,
            reason=reason,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "fee_recalculated_via_api",
            fee_id=fee_id,
            new_base_amount=str(new_base_amount),
            reason=reason,
            user_id=current_user.id,
        )

        await db.refresh(fee)
        return _build_fee_response(fee, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _build_fee_response(
    fee, first_due_date=None, current_user_role: str = None
) -> finance_schemas.FeeResponse:
    """
    Build FeeResponse from Fee model.

    Args:
        fee: Fee ORM model
        first_due_date: Optional first invoice due date for quick reference (P3)
        current_user_role: Current user's role for role-aware permission flags

    Permission Flags Logic (Role-Aware):
        - can_waive: status not terminal AND remaining > 0 AND role in [admin, manager]
        - can_cancel: status not terminal AND paid == 0 AND role == admin
        - can_recalculate: status not terminal AND paid == 0 AND role in [admin, manager]
    """
    applied_discounts = []
    for ad in fee.applied_discounts:
        snapshot = ad.calculation_snapshot or {}
        applied_discounts.append(
            finance_schemas.FeeAppliedDiscountResponse(
                id=ad.id,
                policy_id=ad.policy_id or 0,
                policy_name=snapshot.get("policy_name", "Unknown"),
                discount_type=snapshot.get("discount_type", "unknown"),
                discount_value=Decimal(str(snapshot.get("discount_value", 0))),
                discount_amount=ad.discount_amount,
                application_order=ad.application_order,
            )
        )

    # P1: Compute permission flags based on status, amounts, AND role
    terminal_statuses = {"paid", "cancelled", "waived"}
    status_value = fee.status.value if hasattr(fee.status, "value") else fee.status
    is_terminal = status_value in terminal_statuses

    # Role-aware permission computation
    is_manager_or_admin = current_user_role in ["admin", "manager"]
    is_admin = current_user_role == "admin"

    can_waive = not is_terminal and fee.remaining_amount > 0 and is_manager_or_admin
    can_cancel = not is_terminal and fee.paid_amount == 0 and is_admin
    can_recalculate = not is_terminal and fee.paid_amount == 0 and is_manager_or_admin

    return finance_schemas.FeeResponse(
        id=fee.id,
        admission_profile_id=fee.admission_profile_id,
        installment_plan_id=fee.installment_plan_id,
        fee_type=fee.fee_type,
        academic_year=f"{fee.academic_year}-{fee.academic_year + 1}",
        base_amount=fee.base_amount,
        total_discount=fee.total_discount,
        final_amount=fee.final_amount,
        paid_amount=fee.paid_amount,
        waived_amount=fee.waived_amount,
        remaining_amount=fee.remaining_amount,
        status=fee.status,
        notes=fee.notes,
        version=fee.version,
        created_at=fee.created_at,
        updated_at=fee.updated_at,
        applied_discounts=applied_discounts,
        # P1: Permission flags
        can_waive=can_waive,
        can_cancel=can_cancel,
        can_recalculate=can_recalculate,
        # P3: First invoice due date
        due_date=first_due_date,
    )


def _build_fee_detail_response(
    fee, invoices, current_user_role: str = None
) -> finance_schemas.FeeDetailResponse:
    """Build FeeDetailResponse from Fee model with invoices."""
    # P3: Get first invoice due date for quick reference
    first_due_date = None
    if invoices:
        sorted_invoices = sorted(invoices, key=lambda x: x.due_date)
        first_due_date = sorted_invoices[0].due_date if sorted_invoices else None

    base_response = _build_fee_response(
        fee, first_due_date=first_due_date, current_user_role=current_user_role
    )

    invoice_summaries = [
        finance_schemas.InvoiceSummaryResponse(
            id=inv.id,
            invoice_number=inv.invoice_number,
            installment_no=inv.installment_no,
            amount=inv.amount,
            paid_amount=inv.paid_amount,
            remaining_amount=inv.amount - inv.paid_amount,
            due_date=inv.due_date,
            status=inv.status,
        )
        for inv in invoices
    ]

    plan_response = None
    if fee.installment_plan:
        plan = fee.installment_plan
        plan_response = finance_schemas.InstallmentPlanResponse(
            id=plan.id,
            code=plan.code,
            name=plan.name,
            installment_count=plan.installment_count,
            schedule=[
                finance_schemas.InstallmentScheduleItem(**item)
                for item in plan.schedule
            ],
            penalty_rate=plan.penalty_rate,
            is_active=plan.is_active,
            created_at=plan.created_at,
        )

    return finance_schemas.FeeDetailResponse(
        **base_response.model_dump(),
        invoices=invoice_summaries,
        installment_plan=plan_response,
    )
