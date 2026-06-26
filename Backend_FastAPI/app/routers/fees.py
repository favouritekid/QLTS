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
    require_finance_staff,
)
from app.core.rate_limits import limiter, RateLimits
from app.models.finance import FeeTypeEnum
from app.schemas import finance as finance_schemas
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.repositories.fee_repository import FeeRepository
from app.repositories.payment_repository import PaymentRepository
from app.utils.admission_status import is_fee_eligible
from app.utils.id_helpers import format_profile_code
from app.utils.masking import mask_citizen_id
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
    * Profile must be in a fee-eligible state: ``submitted`` / ``resubmitted``
      (fast-track prepay / hold-spot — C2; resubmitted = submitted after an
      officer re-submit) plus the post-decision states
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
    # + ``submitted`` / ``resubmitted`` (C2 fast-track prepay / giữ chỗ) for
    # single-path OR a multi-NV profile with EXACTLY ONE NV. A multi-NV profile
    # with ≥2 NVs qualifies only after publish → ``admitted``. Earlier states
    # (draft) stay blocked.
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

        # #7/#9: pricing is resolved ONCE, UNDER THE ROW LOCK, inside
        # calculate_fee. Pass base_amount/discount_policy_ids = None so the
        # service derives BOTH the amount and the discount policies from a single
        # resolve_fee_academic_info held under the lock — removing the pre-lock
        # resolve here (no double resolve) and closing the race where the router
        # resolved discount pre-lock while the service resolved amount post-lock
        # (a concurrent waitlist-promote could have mismatched the two ngành).
        fee, post_commit = await fee_service.calculate_fee(
            admission_profile_id=data.admission_profile_id,
            fee_type=data.fee_type,
            base_amount=None,
            academic_year=profile.academic_year,
            discount_policy_ids=None,
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


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/calculable-profiles",
    response_model=finance_schemas.CalculableProfilesResponse,
    summary="Search profiles for the Tính phí picker (finance-scoped)",
)
async def list_calculable_profiles(
    request: Request,
    search: str = Query(..., min_length=2, max_length=100),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """Minimal admission-profile search for the workspace "Tính phí" picker.

    Finance staff (admin/manager/accountant). Accountant is DENIED
    ``/api/admissions`` by design (separation of duties), so this finance-scoped
    lookup returns just id + name + phone to pick a profile to calculate a fee
    for. Declared BEFORE ``/{fee_id}`` so the literal path wins the route match.
    Unit-scoped via ``finance_scope_unit_id`` like the rest of the finance module.
    """
    fee_service = FeeCalculationService(db)
    unit_id = finance_scope_unit_id(current_user)
    profiles = await fee_service.search_calculable_profiles(search, unit_id)
    return finance_schemas.CalculableProfilesResponse(
        profiles=[
            finance_schemas.CalculableProfileItem(
                id=p.id,
                full_name=p.lead.full_name if p.lead else None,
                phone=p.lead.phone if p.lead else None,
            )
            for p in profiles
        ]
    )


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

    # Pending/overdue via the SAME derived predicate as the collection drawer
    # (issued|partial; derived-overdue) so the shared ProfileFinanceSummary
    # field is endpoint-independent — not the lagging enum 'overdue' bucket.
    all_invoices = [inv for fee in summary["fees"] for inv in fee.invoices]
    pending_count, overdue_count = _count_pending_overdue(
        all_invoices, date.today()
    )

    return finance_schemas.ProfileFinanceSummary(
        admission_profile_id=profile_id,
        total_fees=summary["total_fees"],
        total_paid=summary["total_paid"],
        total_remaining=_total_remaining_with_penalty(
            summary["fees"], all_invoices
        ),
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


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/collection/{profile_id}",
    response_model=finance_schemas.ProfileCollectionResponse,
    summary="Full collection view for a profile (Thu học phí drawer)",
)
async def get_profile_collection(
    request: Request,
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """The three finance tiers for ONE profile, for the workspace drawer:
    identity + summary + invoices + payments.

    **Security:**
    - ``require_finance_staff`` HARD role gate (admin/manager/accountant) — also
      keeps an officer (read-only on summary) off the collection drawer.
    - IDOR: the profile is resolved UNIT-SCOPED first (``finance_scope_unit_id``)
      and 404s if outside scope. The empty-collection case is NEVER the gate —
      gating on "no fees" would leak identity/existence for an out-of-unit
      profile (``get_fee_summary`` returns an empty summary for any id).
    """
    # Local imports → no router import cycle (fees ↔ invoices ↔ payments). The
    # list builders are reused verbatim so a drawer row matches the spine row.
    from app.routers.invoices import _build_invoice_list_item
    from app.routers.payments import _build_payment_list_item

    fee_service = FeeCalculationService(db)
    unit_id = finance_scope_unit_id(current_user)
    today = date.today()

    profile = await fee_service.get_profile_collection(profile_id, unit_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admission profile not found",
        )

    lead = profile.lead
    officer = lead.assigned_officer if lead else None

    # Flatten the loaded graph: fees → invoices → payments.
    fees = list(profile.fees or [])

    # Ngành/trình độ header đọc TỪ snapshot Fee.resolved_* (khớp list row +
    # filter, đúng NV admitted). Lấy fee đầu tiên có snapshot (mọi fee cùng hồ
    # sơ cùng ngành sau khi hook chạy). NULL → "(chưa chốt ngành)" phía FE.
    _resolved_major = None
    _resolved_degree = None
    for _f in fees:
        if _f.resolved_major_id:
            _resolved_major = _f.__dict__.get("resolved_major")
            _resolved_degree = _f.resolved_degree_level
            break

    identity = finance_schemas.ProfileCollectionIdentity(
        profile_id=profile.id,
        profile_code=format_profile_code(profile.id),
        student_name=lead.full_name if lead else None,
        citizen_id_masked=mask_citizen_id(getattr(profile, "citizen_id", None)),
        program_name=_resolved_major.name if _resolved_major else None,
        degree_level=_resolved_degree,
        officer_name=officer.full_name if officer else None,
        phone=lead.phone if lead else None,
    )
    all_invoices = []
    all_payments = []
    for fee in fees:
        for inv in (fee.invoices or []):
            all_invoices.append(inv)
            all_payments.extend(inv.payments or [])

    # Summary on the already-loaded graph (no extra query): totals + counts.
    # total_remaining INCLUDES invoice penalties (shared helper) so the drawer
    # header agrees with the invoice rows below; counts use the DERIVED overdue
    # predicate so the drawer agrees with the workspace spine, not the lagging
    # enum 'overdue' bucket.
    total_fees = sum((f.final_amount for f in fees), Decimal("0"))
    total_paid = sum((f.paid_amount for f in fees), Decimal("0"))
    total_remaining = _total_remaining_with_penalty(fees, all_invoices)

    pending_count, overdue_count = _count_pending_overdue(all_invoices, today)

    summary = finance_schemas.ProfileFinanceSummary(
        admission_profile_id=profile.id,
        total_fees=total_fees,
        total_paid=total_paid,
        total_remaining=total_remaining,
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
                # Role-aware (route gate): drawer shows "Miễn giảm" only when the
                # waive route would accept it — never a button that 400/403s.
                can_waive=_fee_can_waive(f, current_user.role),
            )
            for f in fees
        ],
        pending_invoices=pending_count,
        overdue_invoices=overdue_count,
    )

    # Invoices: same enriched list item + role-aware can_* as the workspace list.
    # Actionable-first (derived-overdue → soonest due → id) so the drawer opens
    # on the row most likely to need a "Thu tiền".
    invoice_items = [
        _build_invoice_list_item(inv, current_user.role, today)
        for inv in all_invoices
    ]
    invoice_items.sort(key=lambda it: (not it.is_overdue, it.due_date, it.id))

    # Nguồn thu "import": prefetch các payment.id của hồ sơ nằm trong
    # PaymentImportRow.payment_ids (JSONB) — 1 query repo (anti-N+1, harden
    # jsonb). intent_id → online, còn lại → manual (xem _build_payment_list_item).
    imported_payment_ids = await PaymentRepository(db).get_imported_payment_ids(
        [p.id for p in all_payments]
    )

    # Payments: newest first (history), enriched + role-aware maker-checker flags.
    all_payments.sort(key=lambda p: p.created_at, reverse=True)
    payment_items = [
        _build_payment_list_item(
            pmt, current_user.id, current_user.role,
            imported_payment_ids=imported_payment_ids,
        )
        for pmt in all_payments
    ]

    return finance_schemas.ProfileCollectionResponse(
        identity=identity,
        summary=summary,
        invoices=invoice_items,
        payments=payment_items,
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

def _inv_status_value(inv):
    """Normalize an invoice status to its string value (Enum or str)."""
    return inv.status.value if hasattr(inv.status, "value") else inv.status


def _count_pending_overdue(invoices, today):
    """Pending/overdue counts via the derived predicate the workspace spine +
    collection drawer use: pending = issued|partial, overdue =
    _invoice_is_overdue (derived superset of the lagging enum 'overdue').
    One formula so ProfileFinanceSummary.{pending,overdue}_invoices is
    endpoint-independent."""
    from app.routers.invoices import _invoice_is_overdue

    pending = sum(
        1 for inv in invoices if _inv_status_value(inv) in ("issued", "partial")
    )
    overdue = sum(1 for inv in invoices if _invoice_is_overdue(inv, today))
    return pending, overdue


def _total_remaining_with_penalty(fees, invoices):
    """Amount still owed = principal + outstanding penalty.

    Principal = Σ fee.remaining_amount (final-paid-waived) — already correct
    for waivers AND fees not yet invoiced. We do NOT sum invoice.remaining:
    waive_fee bumps fee.waived but leaves invoice.amount untouched, so
    Σ invoice.remaining (amount+penalty-paid) would OVER-state the header by
    the waived amount. Penalties live on the invoice (not the fee), so add the
    penalty of non-terminal invoices on top."""
    principal = sum((f.remaining_amount for f in fees), Decimal("0"))
    penalty = sum(
        (
            inv.penalty_amount
            for inv in invoices
            if _inv_status_value(inv) not in ("paid", "cancelled")
        ),
        Decimal("0"),
    )
    # Clamp ≥ 0: fee.paid_amount absorbs the penalty portion of a payment
    # (record_payment allows paying up to invoice.remaining = amount+penalty,
    # verify_payment adds it ALL to fee.paid) while fee.final excludes penalty,
    # so a fully-paid penalised fee drives fee.remaining negative. Never surface
    # a negative "Còn phải thu". (Root cause is the payment layer; this keeps the
    # displayed total honest. Clamping the TOTAL — not per-fee — preserves the
    # penalty-paid-in-part case where a negative principal correctly offsets a
    # still-counted penalty on a 'partial' invoice.)
    return max(Decimal("0"), principal + penalty)


_FEE_TERMINAL_STATUSES = {"paid", "cancelled", "waived"}


def _fee_can_waive(fee, current_user_role: str = None) -> bool:
    """Role-aware waive capability for a fee — SINGLE source for the detail
    ``FeeResponse`` and the collection drawer's ``FeeSummaryResponse``.

    Mirrors the route gate exactly (``RequireManager`` → admin/manager only;
    accountant is intentionally excluded — separation of duties): not terminal
    AND remaining > 0 AND role in [admin, manager]. Keeping the flag aligned with
    the route is the thin-client contract — a True flag the route would 403 is a
    broken button.
    """
    status_value = fee.status.value if hasattr(fee.status, "value") else fee.status
    is_terminal = status_value in _FEE_TERMINAL_STATUSES
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]
    return not is_terminal and fee.remaining_amount > 0 and is_manager_or_admin


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

    # P1: Compute permission flags based on status, amounts, AND role.
    # can_waive shares _fee_can_waive with the collection drawer (single source).
    # can_cancel is admin-only (RequireAdmin); can_recalculate is manager+ — both
    # kept aligned with their route gate (thin-client: no button the route 403s).
    status_value = fee.status.value if hasattr(fee.status, "value") else fee.status
    is_terminal = status_value in _FEE_TERMINAL_STATUSES
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]
    is_admin = current_user_role == UserRole.ADMIN

    can_waive = _fee_can_waive(fee, current_user_role)
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
