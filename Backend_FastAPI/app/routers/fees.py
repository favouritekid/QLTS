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
    PermissionDeniedError,
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
    - Miễn/giảm học phí thủ công (``target_final_amount``): FIELD-LEVEL AUTHZ —
      chỉ admin/manager/accountant (officer vẫn calculate thường + down-payment).
    """
    # Field-level authz (Pha 2): officer được calculate + down-payment, nhưng
    # KHÔNG được tự miễn/giảm học phí (đổi nghĩa vụ tiền). Gate Ở ROUTER (deps có
    # role) TRƯỚC service; cùng role-set với require_finance_staff. PermissionDenied
    # → 403 qua global handler (KHÔNG nằm trong except BadRequest dưới).
    if data.target_final_amount is not None and current_user.role not in (
        UserRole.ADMIN, UserRole.MANAGER, UserRole.ACCOUNTANT,
    ):
        raise PermissionDeniedError(
            detail="Chỉ kế toán/quản lý/admin được miễn/giảm học phí thủ công."
        )

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

        # Lịch thu "đóng trước" (Pha 1): KHÔNG gắn kế hoạch trả góp — hóa đơn do
        # generate_invoices_for_fee tạo theo 2 đợt tùy chỉnh (đợt đầu + còn lại).
        # plan_id=None để fee không gắn plan (tránh lệch "plan 1 đợt nhưng 2 HĐ").
        if data.collection_schedule_mode == "down_payment":
            plan_id = None
        else:
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
            target_final_amount=data.target_final_amount,
            manual_discount_reason=data.manual_discount_reason,
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
        # Lịch thu "đóng trước" (Pha 1): truyền 2 đợt tùy chỉnh xuống service —
        # GIỮ nghĩa vụ (final), chỉ chia thành đợt đầu + còn lại; cả hai auto-issue
        # (tuition) → công nợ đợt 2 có hạn cụ thể. None = luồng kế hoạch như cũ.
        invoices, invoice_cb = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=current_user.id,
            unit_id=unit_id,
            auto_issue=(data.fee_type == FeeTypeEnum.tuition),
            anchor_date=invoice_anchor,
            down_payment=data.down_payment,
            down_payment_due=data.down_payment_due,
            remainder_due=data.remainder_due,
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


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/tuition-preview",
    response_model=finance_schemas.TuitionPreviewResponse,
    summary="Preview giá chuẩn học phí (base / giảm giá / dự kiến phải thu)",
)
async def preview_tuition(
    request: Request,
    admission_profile_id: int = Query(..., gt=0, description="ID hồ sơ tuyển sinh"),
    # le=12: chặn semester_no ngoài int32 → asyncpg DataError → 500 (cùng lớp
    # int32-guard codebase đã áp ở các route khác). HK thực tế ≤ 12.
    semester_no: int = Query(1, ge=1, le=12, description="Số học kỳ (HK1=1)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Giá chuẩn học phí (base / giảm giá / dự kiến phải thu) cho dialog "Tính
    phí" — hiển để đối chiếu khi chọn lịch thu (vd "đóng trước + còn lại").
    Read-only, KHÔNG ghi DB.

    Auth giống ``POST /api/fees/calculate``: ``_get_profile`` unscoped rồi
    ``_fee_calc_authorized`` → 404 nếu ngoài scope (không leak existence). Khai
    báo literal ``/tuition-preview`` TRƯỚC ``/{fee_id}`` để route match đúng (một
    segment đặt sau ``/{fee_id}`` sẽ bị nuốt thành ``fee_id`` → 422). Cùng quy
    ước với ``/calculable-profiles``.
    """
    fee_service = FeeCalculationService(db)

    try:
        profile = await fee_service._get_profile(admission_profile_id, unit_id=None)
        if not profile or not _fee_calc_authorized(profile, current_user):
            # 404 not 403: no existence leak beyond scope (same as calculate_fee).
            raise ResourceNotFoundError("Admission profile not found")

        base_amount, total_discount, final_amount = await fee_service.preview_tuition(
            profile, semester_no
        )
        return finance_schemas.TuitionPreviewResponse(
            base_amount=base_amount,
            total_discount=total_discount,
            final_amount=final_amount,
            semester_no=semester_no,
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

        response = _build_fee_detail_response(
            fee, invoices, current_user_role=current_user.role
        )
        # Đổi ngành: enrich A→B + còn phải thu cho dialog kế toán (review #2 — 3
        # field này _build_fee_response để None; router async resolve tên ngành).
        if response.awaiting_accountant_confirmation:
            await _enrich_major_change_display(db, fee, response)
        return response

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
            awaiting_accountant_confirmation=getattr(
                f, "awaiting_accountant_confirmation", False
            ),
            can_confirm_major_change=_fee_can_confirm_major_change(
                f, current_user.role
            ),
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
                has_payable_invoice=any(
                    _invoice_is_payable(inv) for inv in (f.invoices or [])
                ),
                awaiting_accountant_confirmation=getattr(
                    f, "awaiting_accountant_confirmation", False
                ),
                can_confirm_major_change=_fee_can_confirm_major_change(
                    f, current_user.role
                ),
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
        # Full CCCD for the drawer's copy button (display stays masked). DELIBERATE
        # PII exposure to finance staff INCLUDING accountant — accountant is denied
        # /api/admissions (PII minimization) but legitimately needs the full buyer
        # CCCD + address to issue a VAT invoice (hóa đơn GTGT) from the collection
        # workspace. This is an accepted business need, not an oversight.
        citizen_id_full=getattr(profile, "citizen_id", None),
        program_name=_resolved_major.name if _resolved_major else None,
        degree_level=_resolved_degree,
        officer_name=officer.full_name if officer else None,
        phone=lead.phone if lead else None,
        permanent_address=_format_permanent_address(profile),
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
                has_payable_invoice=any(
                    _invoice_is_payable(inv) for inv in (f.invoices or [])
                ),
                # Role-aware (route gate): drawer shows each fee action only when
                # the matching route would accept it. Same single-source helpers as
                # the detail FeeResponse. CAVEAT: can_cancel mirrors only the
                # role + paid==0 gate; cancel_fee ALSO blocks on a pending payment
                # / active online intent (data not loaded here) — those rare cases
                # surface as a graceful 400 with a clear message, not a silent fail.
                can_waive=_fee_can_waive(f, current_user.role),
                can_recalculate=_fee_can_recalculate(f, current_user.role),
                can_cancel=_fee_can_cancel(f, current_user.role),
                # base_amount prefills the drawer's "Tính lại" dialog.
                base_amount=f.base_amount,
                # Đổi ngành: cờ để drawer/worklist đánh dấu "chờ xác nhận" + bật
                # nút confirm (review #5 — explicit-kwargs bypass from_attributes).
                awaiting_accountant_confirmation=getattr(
                    f, "awaiting_accountant_confirmation", False
                ),
                can_confirm_major_change=_fee_can_confirm_major_change(
                    f, current_user.role
                ),
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


# ⚠️ THỨ TỰ ĐÚNG: @router.put TRƯỚC @limiter.limit (bottom-up decorator) — nếu
# đặt ngược như recalculate/waive/cancel trong file này thì limiter KHÔNG chạy
# (nợ slowapi-limiter-decorator-order-debt). Route MỚI nên làm đúng.
@router.put(
    "/{fee_id}/confirm-major-change",
    response_model=finance_schemas.FeeResponse,
    summary="Kế toán xác nhận đổi ngành (đã reprice)",
)
@limiter.limit(RateLimits.DATA_WRITE)
async def confirm_major_change(
    request: Request,
    fee_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Kế toán (hoặc admin) xác nhận học phí đổi ngành đã reprice → clear cờ chờ,
    mở lại xuất giấy/approve, báo officer.

    **Auth**: ``CasbinAuth`` — chỉ ``role:accountant`` được grant (migration
    majchg1c) + admin qua wildcard ``/*``. Manager/officer deny-by-default.
    KHÔNG dùng ``require_finance_staff`` (nó cho cả manager).

    **Business**: fee phải đang ``awaiting_accountant_confirmation`` (409 nếu
    không). Bất biến hoá đơn (=final−waived) đã đúng từ reprice — confirm chỉ rà
    phòng thủ, KHÔNG reconcile.
    """
    fee_service = FeeCalculationService(db)
    unit_id = finance_scope_unit_id(current_user)

    try:
        fee, callback = await fee_service.confirm_major_change(
            fee_id,
            actor_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
        if callback:
            await callback()

        log.info(
            "fee_major_change_confirmed_via_api",
            fee_id=fee_id,
            user_id=current_user.id,
        )

        fresh = await fee_service.fee_repo.get_by_id_with_relations(
            fee_id, unit_id
        )
        return _build_fee_response(
            fresh or fee, current_user_role=current_user.role
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _inv_status_value(inv):
    """Normalize an invoice status to its string value (Enum or str)."""
    return inv.status.value if hasattr(inv.status, "value") else inv.status


def _fee_status_value(fee):
    """Normalize a fee status to its string value (Enum or str)."""
    return fee.status.value if hasattr(fee.status, "value") else fee.status


def _invoice_is_payable(inv) -> bool:
    """Hóa đơn còn THU ĐƯỢC: đã phát hành (issued/partial/overdue) và còn dư nợ
    (inv.remaining_amount = amount + penalty - paid > 0, GỒM penalty). Khớp
    ``isInvoicePayable`` phía FE — nguồn cho FeeSummaryResponse.has_payable_invoice
    (draft/cancelled/paid đều loại: draft chưa phát hành, paid/cancelled dư nợ=0)."""
    return (
        _inv_status_value(inv) in ("issued", "partial", "overdue")
        and inv.remaining_amount > 0
    )


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
    # Exclude CANCELLED fees: a cancelled fee (e.g. one auto-voided when a
    # withdrawn profile's tuition was refunded) carries a non-zero
    # remaining_amount (final − paid − waived) but is void — counting it would
    # surface a phantom "Còn nợ" on a settled/withdrawn profile.
    principal = sum(
        (
            f.remaining_amount
            for f in fees
            if _fee_status_value(f) != "cancelled"
        ),
        Decimal("0"),
    )
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


def _fee_can_recalculate(fee, current_user_role: str = None) -> bool:
    """Role-aware recalculate capability — SINGLE source for the detail
    ``FeeResponse`` and the collection drawer's ``FeeSummaryResponse``.

    Mirrors the recalculate route gate (``RequireManager`` → admin/manager):
    not terminal AND paid == 0 AND role in [admin, manager]. paid == 0 because
    recomputing the base after money has come in would desync the ledger.
    """
    status_value = fee.status.value if hasattr(fee.status, "value") else fee.status
    is_terminal = status_value in _FEE_TERMINAL_STATUSES
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]
    return not is_terminal and fee.paid_amount == 0 and is_manager_or_admin


def _fee_can_cancel(fee, current_user_role: str = None) -> bool:
    """Role-aware cancel capability — SINGLE source for the detail
    ``FeeResponse`` and the collection drawer's ``FeeSummaryResponse``.

    Mirrors the cancel route gate (``RequireAdmin`` → admin only — stricter than
    waive/recalculate by design): not terminal AND paid == 0 AND role == admin.
    """
    status_value = fee.status.value if hasattr(fee.status, "value") else fee.status
    is_terminal = status_value in _FEE_TERMINAL_STATUSES
    is_admin = current_user_role == UserRole.ADMIN
    return not is_terminal and fee.paid_amount == 0 and is_admin


def _fee_can_confirm_major_change(fee, current_user_role: str = None) -> bool:
    """Quyền bấm "Xác nhận đổi ngành" — mirror route gate confirm-major-change
    (accountant + admin; manager/officer deny). Chỉ khi cờ đang bật.
    """
    return bool(
        getattr(fee, "awaiting_accountant_confirmation", False)
    ) and current_user_role in (UserRole.ACCOUNTANT, UserRole.ADMIN)


def _format_permanent_address(profile) -> Optional[str]:
    """Join the profile's stored permanent-address parts into ONE readable line
    (số nhà/đường → tổ/thôn → xã/phường → quận/huyện → tỉnh) for the drawer.

    Displays the stored free-text as-is — no GSO re-resolve (that legacy
    ward-jump handling belongs to the admissions display, out of scope here).
    Returns None when nothing is filled.
    """
    parts = [
        getattr(profile, "permanent_street_address", None),
        getattr(profile, "permanent_residential_group", None),
        getattr(profile, "permanent_ward", None),
        getattr(profile, "permanent_district", None),
        getattr(profile, "permanent_province", None),
    ]
    cleaned = [p.strip() for p in parts if p and p.strip()]
    return ", ".join(cleaned) or None


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

    # P1: Compute permission flags based on status, amounts, AND role — all three
    # share their helper with the collection drawer (single source). Each mirrors
    # its route gate (thin-client: no button the route 403s).
    can_waive = _fee_can_waive(fee, current_user_role)
    can_cancel = _fee_can_cancel(fee, current_user_role)
    can_recalculate = _fee_can_recalculate(fee, current_user_role)

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
        # Đổi ngành: cờ (từ model) + quyền confirm (role-aware). A→B + delta là
        # display giàu hơn, enrich ở endpoint detail có DB (mặc định None ở đây).
        awaiting_accountant_confirmation=getattr(
            fee, "awaiting_accountant_confirmation", False
        ),
        can_confirm_major_change=_fee_can_confirm_major_change(
            fee, current_user_role
        ),
    )


async def _enrich_major_change_display(db, fee, response) -> None:
    """Resolve tên ngành CŨ (major_change_from_academic_info_id) + MỚI
    (resolved_major_id) + số còn phải thu, gán vào response cho dialog kế toán
    (review #2). Best-effort: field nào không tra được để None (dialog fallback)."""
    from sqlalchemy import select as _select

    async def _major_name_by_ai(ai_id):
        if ai_id is None:
            return None
        return (
            await db.execute(
                _select(models.MajorProgram.name)
                .select_from(models.OfferingAcademicInfo)
                .join(
                    models.ProgramOffering,
                    models.ProgramOffering.id
                    == models.OfferingAcademicInfo.offering_id,
                )
                .join(
                    models.MajorProgram,
                    models.MajorProgram.id == models.ProgramOffering.program_id,
                )
                .where(models.OfferingAcademicInfo.id == ai_id)
            )
        ).scalar_one_or_none()

    response.major_change_from_major_name = await _major_name_by_ai(
        fee.major_change_from_academic_info_id
    )
    # Ngành MỚI: resolved_major_id đã trỏ ngành mới (reprice resnapshot force).
    if fee.resolved_major_id is not None:
        response.major_change_to_major_name = (
            await db.execute(
                _select(models.MajorProgram.name).where(
                    models.MajorProgram.id == fee.resolved_major_id
                )
            )
        ).scalar_one_or_none()
    # Còn phải thu = final − paid − waived (đã chặn sinh dư nên >= 0). Raw decimal
    # string — FE formatVND tự format (khớp zod z.string()).
    outstanding = fee.final_amount - fee.paid_amount - fee.waived_amount
    response.major_change_delta_amount = str(outstanding)


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
