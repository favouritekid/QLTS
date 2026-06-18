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
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models, schemas
from app.core import deps
from app.core.constants import UserRole
from app.core.deps import (
    CasbinAuth,
    RequireAdmin,
    RequireManager,
    finance_scope_unit_id,
)
from app.core.rate_limits import limiter, RateLimits
from app.models.finance import FeeTypeEnum
from app.schemas import finance as finance_schemas
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.repositories.fee_repository import FeeRepository
from app.utils.admission_status import is_fee_eligible
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/fees", tags=["Finance - Fees"])


# H1 cleanup (2026-05-14): the local ``def get_client_ip`` previously
# living here was dead code — never used as a slowapi ``key_func`` in
# this file. Canonical helper lives in ``app.core.client_ip``.


# ==============================================================================
# PR #7 — per-profile authorization for POST /fees/calculate
# ==============================================================================

def _fee_calc_authorized(
    profile: models.AdmissionProfile,
    user: models.User,
) -> bool:
    """Return True if `user` may create an official Fee for `profile`.

    Mirrors the ``calculate_fee`` key in ``_compute_permissions`` exactly —
    any drift will surface as "FE hides button / API 404s" or vice versa.

    Rules:
    * Profile must be in a fee-eligible state: ``submitted`` (fast-track
      prepay / hold-spot — C2) plus the post-decision states
      (``approved`` | ``confirmed`` | ``enrolled``). Earlier states
      (``draft`` etc.) would create a fee prematurely.
    * admin / accountant: any profile. Both are central finance roles; Casbin
      grants accountant ``/api/fees/calculate`` with no unit qualifier, so a
      central accountant must be able to raise fees for every unit.
    * manager: profile whose lead is in the user's unit.
    * officer: lead in the user's unit AND assigned to the user — matches
      the existing ``get_admission_for_user`` IDOR convention so officers
      can't spin up invoices for profiles they don't own.
    * everyone else: denied.
    """
    # Fee-eligible states gate — shared with the ``calculate_fee`` permission
    # flag in ``admission_service._compute_frontend_fields`` via the single
    # ``is_fee_eligible`` helper (anti-drift): admitted-like + confirmed/enrolled
    # + ``submitted`` for SINGLE-PATH profiles only (C2 fast-track prepay / giữ
    # chỗ). A multi-NV profile at ``submitted`` qualifies only after publish →
    # ``admitted``. Earlier states (draft) stay blocked.
    if not is_fee_eligible(profile):
        return False

    if user.role in (UserRole.ADMIN, UserRole.ACCOUNTANT):
        return True

    lead = profile.lead
    if lead is None or lead.unit_id is None:
        return False

    if user.role == UserRole.MANAGER:
        return lead.unit_id == user.unit_id

    if user.role == UserRole.OFFICER:
        return (
            lead.unit_id == user.unit_id
            and lead.assigned_officer_id is not None
            and lead.assigned_officer_id == user.id
        )

    return False


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
    unit_id = finance_scope_unit_id(current_user)

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
            semester_no=fee.semester_no,
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

    try:
        # PR #7 — unscoped eager-load first so we can run authz on the actual
        # profile/lead attributes, then decide 404 explicitly. The old
        # prefilter unit_id = None|user.unit_id bundled authz into the query
        # and narrowed too wide for officers (same-unit but not assigned).
        # Authorization runs BEFORE plan-code validation so unauthorized
        # callers get a uniform 404 and can't distinguish "valid plan but
        # not my profile" from "invalid plan".
        profile = await fee_service._get_profile(data.admission_profile_id, unit_id=None)
        if not profile or not _fee_calc_authorized(profile, current_user):
            # 404 not 403: no existence leak beyond scope, same as other IDOR sites.
            raise ResourceNotFoundError("Admission profile not found")

        # Get installment plan by code. PR #7 review: reject unknown or
        # inactive codes explicitly instead of falling through to plan_id=None
        # (which InvoiceService silently downgrades to a single-payment
        # invoice). Previously the dialog could post INSTALLMENT (not a real
        # seed code) and the user would still see the fee created but with a
        # single-installment schedule — actively misleading.
        plan = await fee_service.fee_repo.get_installment_plan_by_code(data.installment_plan_code)
        if plan is None:
            raise BadRequest(
                f"Kế hoạch thanh toán '{data.installment_plan_code}' không tồn tại "
                "hoặc không còn hoạt động."
            )
        if getattr(plan, "is_active", True) is False:
            raise BadRequest(
                f"Kế hoạch thanh toán '{data.installment_plan_code}' đã ngừng hoạt động."
            )
        plan_id = plan.id

        # Service-layer unit_id kept for downstream IDOR inside
        # calculate_fee / generate_invoices_for_fee — admin skips, everyone
        # else passes their unit. This mirrors what the function did before;
        # only the profile lookup is unscoped now.
        unit_id = finance_scope_unit_id(current_user)

        # Resolve academic_info via the SHARED resolver (single source of truth
        # with FeeCalculationService) so the discount ngành matches the ngành the
        # service prices the tuition against — handles legacy single-path AND
        # multi-NV (admitted-choice / single-choice). For tuition the service
        # looks up the amount from offering_semester_tuition (PR 3 — ADR-002);
        # the router only needs discount policy IDs. For non-tuition the base
        # amount still comes from academic_info.tuition_fee_per_year.
        from app.services.fee_calculation_service import resolve_fee_academic_info

        academic_info = await resolve_fee_academic_info(db, profile)
        discount_policy_ids = list(academic_info.applied_discount_policy_ids or [])

        base_amount = Decimal("0")
        if data.fee_type != FeeTypeEnum.tuition:
            base_amount = academic_info.tuition_fee_per_year or Decimal("0")
            if base_amount <= 0:
                raise BadRequest(
                    "Cannot calculate fee: No fee amount configured for this offering"
                )

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
            semester_no=data.semester_no,
        )

        # Generate invoices based on installment plan.
        # For tuition fees (PR 3): anchor installment due dates to the
        # profile's approval timestamp when available, so HK1 payment
        # schedules align with the admission timeline rather than the
        # fee-creation date. Non-tuition fees keep the legacy
        # due_date_base = today + 30 days.
        invoice_anchor: date | None = None
        if data.fee_type == FeeTypeEnum.tuition and hasattr(profile, "approved_at"):
            approved_at = getattr(profile, "approved_at", None)
            if approved_at is not None:
                invoice_anchor = approved_at.date() if hasattr(approved_at, "date") else approved_at

        # C2 fast-track (B4): auto-issue tuition invoices so the prepay/
        # hold-spot payment can be collected immediately. Only tuition is
        # auto-issued — other fee types keep the legacy draft->issue-by-hand
        # flow. CAPTURE invoice_cb (was discarded with `_`): the issue path
        # builds an INVOICE_ISSUED post-commit fanout that must be awaited,
        # otherwise the invoice is issued silently with no notification/sync.
        invoices, invoice_cb = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=current_user.id,
            unit_id=unit_id,
            auto_issue=(data.fee_type == FeeTypeEnum.tuition),
            anchor_date=invoice_anchor,
        )

        await db.commit()

        # Execute post-commit callbacks: fee creation (post_commit) AND, when
        # tuition was auto-issued, the INVOICE_ISSUED fanout (invoice_cb).
        # invoice_cb is None for non-auto-issue fee types.
        if post_commit:
            await post_commit()
        if invoice_cb:
            await invoice_cb()

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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

    fees = await fee_service.get_fees_for_profile(profile_id, unit_id, fee_type)

    return [
        finance_schemas.FeeSummaryResponse(
            id=f.id,
            fee_type=f.fee_type,
            academic_year=f"{f.academic_year}-{f.academic_year + 1}",
            semester_no=f.semester_no,
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
    unit_id = finance_scope_unit_id(current_user)

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
                academic_year=f"{f.academic_year}-{f.academic_year + 1}",
                semester_no=f.semester_no,
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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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

    # Role-aware permission computation. Waive + recalculate are gated at the
    # route by RequireManager (admin + manager only); accountant is intentionally
    # NOT admitted (separation of duties — a central accountant verifies/records
    # cash and reads finance org-wide, but does not waive or recalculate fees).
    # Fee cancel is admin-only (RequireAdmin). Keeping these flags aligned with
    # the route gate is the thin-client contract: a True flag the route would 403
    # is a broken button.
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]
    is_admin = current_user_role == UserRole.ADMIN

    can_waive = not is_terminal and fee.remaining_amount > 0 and is_manager_or_admin
    can_cancel = not is_terminal and fee.paid_amount == 0 and is_admin
    can_recalculate = not is_terminal and fee.paid_amount == 0 and is_manager_or_admin

    return finance_schemas.FeeResponse(
        id=fee.id,
        admission_profile_id=fee.admission_profile_id,
        installment_plan_id=fee.installment_plan_id,
        fee_type=fee.fee_type,
        academic_year=f"{fee.academic_year}-{fee.academic_year + 1}",
        semester_no=fee.semester_no,
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
        can_waive=can_waive,
        can_cancel=can_cancel,
        can_recalculate=can_recalculate,
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
