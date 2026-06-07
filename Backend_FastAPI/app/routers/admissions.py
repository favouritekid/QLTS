from app.core.rate_limits import limiter, RateLimits
# app/routers/admissions.py
"""
Router for Admissions (AdmissionProfile workflow).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- Transaction Management: Router calls db.commit() after service returns
- RBAC: All endpoints protected by check_permission dependency
- Error Handling: Convert custom exceptions to HTTPException
- Rate Limiting: Enroll endpoint limited to 10 req/min

Endpoints:
- POST /api/admissions - Create admission profile for lead
- GET /api/admissions/{id} - Get admission profile by ID
- PUT /api/admissions/{id} - Update admission profile (draft only)
- POST /api/admissions/{id}/submit - Submit for auto-evaluation
- POST /api/admissions/{id}/enroll - Enroll student (ACID transaction)
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models, schemas
from ..config import settings
from ..core import deps
from ..core.deps import (
    CasbinAuth,  # ✅ Phase 2.2: Use standard alias
    get_admission_for_manager,
    get_admission_for_fee_collection,
    get_admission_for_user,
    get_admission_for_user_read,
)
from ..services import admission_service
from ..services.magic_link_rate_limit import (
    ATTEMPTS_CAP_PER_WINDOW,
    consume_attempt,
)
from ..services.notification_dispatcher import safe_dispatch, rooms_for_admission, rooms_for_lead
from ..services.user_service import emit_data_updated as _emit_realtime_update
from ..core.events import SystemEvents
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    PermissionDeniedError,
    ConflictError,
    ValidationError,
)
from ..utils.token_logging import token_fingerprint
from ..core.constants import UserRole
from ..schemas.finance import MAX_AMOUNT
from ..utils.csv_helpers import sanitize_csv_row

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admissions", tags=["Admissions"])


# ADM-010: Single source of truth for payment_status enum values shared by
# list, status-counts, and export endpoints. Repository helper silently
# drops anything outside this set, so router-level validation is required
# to keep the contract honest.
ALLOWED_PAYMENT_STATUSES = ("paid", "unpaid", "partial", "no_fee")


def _validate_payment_status(value: Optional[str]) -> None:
    """Raise 400 if ``value`` is set but not in ALLOWED_PAYMENT_STATUSES."""
    if value and value not in ALLOWED_PAYMENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid payment_status. Must be: "
                + ", ".join(ALLOWED_PAYMENT_STATUSES)
            ),
        )


# Hotfix R8: import the X-Forwarded-For aware helper so the
# ``100/day`` per-IP cap on /confirm/{token} keys off the real client
# IP (nginx forwards XFF; the previous ``request.client.host`` returned
# the nginx container IP and collapsed the cap to a prod-wide ceiling).
from ..core.client_ip import get_client_ip  # noqa: E402


# ==============================================================================
# ENDPOINTS
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get(
    "",
    response_model=schemas.AdmissionsPage,
    summary="List admission profiles",
)
async def list_admission_profiles(
    request: Request,
    status: str | None = Query(None, description="Filter by status (comma-separated for multi-select)"),
    search: str | None = Query(None, description="Search by name, email, or citizen ID"),
    major_id: str | None = Query(None, description="Filter by major/program ID (comma-separated)"),
    academic_year: int | None = Query(None, description="Filter by academic year"),
    degree_level: str | None = Query(None, description="Filter by degree level"),
    payment_status: str | None = Query(None, description="Filter by payment status (paid/unpaid/partial/no_fee)"),
    date_from: datetime | None = Query(None, description="Filter from date (created_at)"),
    date_to: datetime | None = Query(None, description="Filter to date (created_at)"),
    sort_by: Literal["created_at", "updated_at", "full_name", "status"] = Query(
        "created_at",
        description="Sort field — repo silently fell back to created_at for invalid values until 2026-05-16 (Q-INFO-1 fix). Mirror FE Zod `AdmissionListParams.sort_by`.",
    ),
    order: Literal["asc", "desc"] = Query(
        "desc",
        description="Sort order — repo defaulted to asc for any non-`desc` value until 2026-05-16. Mirror FE Zod `AdmissionListParams.order`.",
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List AdmissionProfiles accessible to current user with pagination and filters.

    **Security:**
    - Admin: Can see all profiles
    - Officer: Only profiles where lead.unit_id == user.unit_id

    **Returns:**
    - Paginated list of AdmissionProfiles with total count
    """
    # Convert page/page_size to skip/limit
    skip = (page - 1) * page_size
    limit = min(page_size, 100)

    # Parse comma-separated values
    statuses: Optional[List[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    major_ids: Optional[List[int]] = None
    if major_id:
        try:
            major_ids = [int(m.strip()) for m in major_id.split(",") if m.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid major_id format")

    # Validate payment_status (ADM-010: shared helper)
    _validate_payment_status(payment_status)

    profiles, total_count = await admission_service.get_profiles(
        db=db,
        skip=skip,
        limit=limit,
        current_user=current_user,
        search=search,
        statuses=statuses,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        order=order,
    )

    return schemas.AdmissionsPage(
        total_count=total_count,
        page=page,
        page_size=page_size,
        profiles=profiles,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/academic-years",
    response_model=List[int],
    summary="Get distinct academic years with data",
)
async def get_academic_years(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Get list of academic years that have admission profiles. IDOR-filtered."""
    return await admission_service.get_academic_years(db=db, current_user=current_user)


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/status-counts",
    summary="Get profile counts grouped by status",
)
async def get_status_counts(
    request: Request,
    search: str | None = Query(None),
    major_id: str | None = Query(None),
    academic_year: int | None = Query(None),
    degree_level: str | None = Query(None),
    payment_status: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get admission profile counts grouped by status.
    Applies all filters EXCEPT status (to populate tab badges).
    """
    major_ids: Optional[List[int]] = None
    if major_id:
        try:
            major_ids = [int(m.strip()) for m in major_id.split(",") if m.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid major_id format")

    # Validate payment_status (ADM-010: keep parity with list/export)
    _validate_payment_status(payment_status)

    return await admission_service.get_status_counts(
        db=db,
        current_user=current_user,
        search=search or None,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/stats",
    response_model=schemas.AdmissionStats,
    summary="Get aggregate admission statistics",
)
async def get_admission_stats(
    request: Request,
    academic_year: int | None = Query(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Get aggregate statistics (totals, conversion rate, avg completion). IDOR-filtered."""
    return await admission_service.get_admission_stats(
        db=db,
        current_user=current_user,
        academic_year=academic_year,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/pending-diploma",
    response_model=schemas.PendingDiplomaResponse,
    summary="List profiles owing the official diploma (nợ bằng)",
)
async def list_pending_diploma(
    request: Request,
    due_before: date | None = Query(
        None,
        description="Chỉ lấy hồ sơ có hạn bổ sung bằng <= ngày này (YYYY-MM-DD)",
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List admission profiles that submitted a provisional graduation
    certificate and still owe the official diploma ("nợ bằng"), IDOR-scoped to
    the caller (admin all / manager unit / officer assigned).

    Optional ``due_before`` narrows to profiles whose supplement due date has
    passed or is approaching — the reminder query for the officer follow-up.

    **Note:** declared BEFORE ``/{profile_id}`` so FastAPI does not capture
    ``pending-diploma`` as a profile id.
    """
    try:
        items = await admission_service.list_pending_diploma_profiles(
            db=db,
            current_user=current_user,
            due_before=due_before,
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        )
    return schemas.PendingDiplomaResponse(total_count=len(items), items=items)


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "",
    response_model=schemas.AdmissionProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create admission profile for lead",
)
async def create_admission_profile(
    request: Request,
    data: schemas.AdmissionProfileCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Create new AdmissionProfile for a Lead.

    **Workflow:**
    1. Validate Lead exists and user has access (IDOR check)
    2. Snapshot admission_rules from ProgramOffering
    3. Auto-generate documents_checklist from mandatory_docs
    4. Create AdmissionProfile with status='draft'

    **Requirements:**
    - Lead must exist and belong to user's unit
    - Lead must have offering_id (for admission_rules)
    - Lead cannot already have admission_profile
    - ProgramOffering must have admission_rules configured

    **Returns:**
    - Created AdmissionProfile with status='draft'

    **Errors:**
    - 404: Lead or ProgramOffering not found (or IDOR protection)
    - 400: Lead already has profile, or no admission_rules configured
    """
    try:
        # Service layer handles business logic (REFACTORED: now uses AdmissionPath)
        profile = await admission_service.create_profile(
            db=db,
            lead_id=data.lead_id,
            admission_method_id=data.admission_method_id,  # Required for AdmissionPath lookup
            admission_round_id=data.admission_round_id,  # Round contract hardening (plan v4)
            current_user=current_user,
            # Round contract hardening (plan v4): academic_year is now
            # REQUIRED — the service validates the selected round belongs
            # to this year (no first-published / current_intake fallback).
            academic_year=data.academic_year,
        )

        # Transaction commit (Router responsibility)
        await db.commit()
        await db.refresh(profile)

        # Dispatch notification (non-blocking, defensive — must not crash after commit)
        # NOTE: Use explicit db.get() by FK column, NOT relationship access.
        # After commit+refresh, relationship attrs (profile.lead, po.program)
        # trigger lazy loading which raises MissingGreenlet in async context.
        try:
            _lead = await db.get(models.Lead, profile.lead_id)
            _lead_name = _lead.full_name if _lead else "Unknown"
            _prog_name = None
            if _lead and _lead.offering_id:
                _po = await db.get(models.ProgramOffering, _lead.offering_id)
                if _po:
                    _mp = await db.get(models.MajorProgram, _po.program_id)
                    if _mp:
                        _prog_name = f"{_mp.name} - {_po.offering_type}"
                    else:
                        _prog_name = _po.offering_type
        except Exception:
            _lead_name = "Unknown"
            _prog_name = None
        await safe_dispatch(
            db=db,
            event=SystemEvents.APPLICATION_CREATED,
            payload={
                "application_id": profile.id,
                "lead_id": profile.lead_id,
                "lead_name": _lead_name,
                "major_program_name": _prog_name or "Chưa xác định",
                "actor_id": current_user.id,
                "actor_name": current_user.full_name or current_user.username,
            },
            dedupe_key=f"admission_profile_created:{profile.id}",
            rooms=rooms_for_admission(profile),
        )

        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ==============================================================================
# BULK ACTION ENDPOINTS (Manager/Admin only)
# NOTE: Must be registered BEFORE /{profile_id}/* routes to avoid path conflict.
# ==============================================================================


@router.post(
    "/bulk/approve",
    response_model=schemas.BulkActionResponse,
    summary="Bulk approve admission profiles",
    description="""
    Approve multiple admission profiles at once.

    **Permissions:** Manager or Admin only.
    **IDOR:** Only profiles accessible to the user will be processed.

    **Error Handling:**
    - Profiles that fail validation are skipped
    - Returns success/failure counts and details
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)
async def bulk_approve_admissions(
    request: Request,
    body: schemas.BulkApproveRequest,
    current_user: models.User = Depends(deps.require_admin_or_manager),
    db: AsyncSession = Depends(database.get_db),
):
    """Bulk approve multiple admission profiles."""
    # ADM-026 review (Round 2): per-item bypass admin gate + audit live
    # in the service. Router-level pre-gate removed so manager bypass
    # attempts produce an audit row (one per attempted item).
    try:
        result, callback = await admission_service.bulk_approve(
            db=db,
            items=[item.model_dump() for item in body.items],
            approver=current_user,
            notes=body.notes,
        )

        await db.commit()

        if callback:
            await callback()

        return schemas.BulkActionResponse(**result)

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/bulk/reject",
    response_model=schemas.BulkActionResponse,
    summary="Bulk reject admission profiles",
    description="""
    Reject multiple admission profiles at once with a reason.

    **Permissions:** Manager or Admin only.
    **IDOR:** Only profiles accessible to the user will be processed.

    **Error Handling:**
    - Profiles that fail validation are skipped
    - Returns success/failure counts and details
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)
async def bulk_reject_admissions(
    request: Request,
    body: schemas.BulkRejectRequest,
    current_user: models.User = Depends(deps.require_admin_or_manager),
    db: AsyncSession = Depends(database.get_db),
):
    """Bulk reject multiple admission profiles with reason."""
    try:
        result, callback = await admission_service.bulk_reject(
            db=db,
            items=[item.model_dump() for item in body.items],
            rejector=current_user,
            reason=body.reason,
        )

        await db.commit()

        if callback:
            await callback()

        return schemas.BulkActionResponse(**result)

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/bulk/assign",
    response_model=schemas.BulkActionResponse,
    summary="Bulk assign admission profiles to officer",
    description="""
    Assign multiple admission profiles to a specific officer.

    **Permissions:** Manager or Admin only.
    **IDOR:** Only profiles accessible to the user will be processed.

    **Note:** This updates the lead.assigned_officer_id for each profile's lead.
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)
async def bulk_assign_admissions(
    request: Request,
    body: schemas.BulkAssignRequest,
    current_user: models.User = Depends(deps.require_admin_or_manager),
    db: AsyncSession = Depends(database.get_db),
):
    """Bulk assign admission profiles to an officer."""
    try:
        result = await admission_service.bulk_assign(
            db=db,
            profile_ids=body.profile_ids,
            officer_id=body.officer_id,
            assigner=current_user,
        )

        await db.commit()

        return schemas.BulkActionResponse(**result)

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/export",
    summary="Export admissions to CSV",
    description="""
    Export admission profiles to CSV format with optional filters.

    **Permissions:** Any authenticated staff member.
    **Filters:** Same as list endpoint (status, search, major_id, date_from, date_to).
    """,
)
@limiter.limit(RateLimits.DATA_READ)
async def export_admissions_csv(
    request: Request,
    status: str | None = Query(None, description="Filter by status (comma-separated)"),
    search: str | None = Query(None, description="Search by name, email, or citizen ID"),
    major_id: str | None = Query(None, description="Filter by major/program ID (comma-separated)"),
    academic_year: int | None = Query(None, description="Filter by academic year"),
    degree_level: str | None = Query(None, description="Filter by degree level"),
    payment_status: str | None = Query(None, description="Filter by payment status"),
    date_from: datetime | None = Query(None, description="Filter from date"),
    date_to: datetime | None = Query(None, description="Filter to date"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Export admission profiles to CSV format."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    # Parse filters
    statuses = [s.strip() for s in status.split(",")] if status else None
    major_ids = [int(m.strip()) for m in major_id.split(",") if m.strip().isdigit()] if major_id else None

    # Validate payment_status (ADM-010: keep parity with list/status-counts)
    _validate_payment_status(payment_status)

    # Export path: no page cap, lightweight hydration (only completion_percent)
    profiles = await admission_service.get_profiles_for_export(
        db=db,
        current_user=current_user,
        search=search,
        statuses=statuses,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
    )

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "ID",
        "Họ tên",
        "Email",
        "Số điện thoại",
        "CMND/CCCD",
        "Trạng thái",
        "Tiến độ hoàn thiện",
        "Chương trình",
        "Ngày tạo",
        "Ngày cập nhật",
    ])

    # Data rows — sanitize_csv_row guards against formula/DDE injection
    # via lead-controlled fields (full_name, email, phone, citizen_id,
    # program name). See ADM-006 / app/utils/csv_helpers.py.
    for profile in profiles:
        lead = profile.lead
        writer.writerow(sanitize_csv_row([
            profile.id,
            lead.full_name if lead else "",
            lead.email if lead else "",
            lead.phone if lead else "",
            profile.citizen_id or "",
            profile.status,
            f"{getattr(profile, 'completion_percent', 0)}%",
            lead.offering.program.name if lead and lead.offering and lead.offering.program else "",
            profile.created_at.strftime("%Y-%m-%d %H:%M") if profile.created_at else "",
            profile.updated_at.strftime("%Y-%m-%d %H:%M") if profile.updated_at else "",
        ]))

    # Prepare response
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=admissions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get(
    "/{profile_id}",
    response_model=schemas.AdmissionProfileResponse,
    summary="Get admission profile by ID",
)
async def get_admission_profile(
    request: Request,
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get AdmissionProfile by ID.

    **Security:**
    - IDOR: Only accessible to users in same unit (unless admin)

    **Returns:**
    - AdmissionProfile with relationships (lead, student)

    **Errors:**
    - 404: Profile not found (or IDOR protection)
    """
    try:
        profile = await admission_service.get_profile(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put(
    "/{profile_id}",
    response_model=schemas.AdmissionProfileResponse,
    summary="Update admission profile (draft only)",
)
async def update_admission_profile(
    request: Request,
    profile_id: int,
    data: schemas.AdmissionProfileUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Update AdmissionProfile (only when status='draft').

    **Security:**
    - IDOR: Only accessible to users in same unit
    - State Locking: Only draft profiles can be updated

    **Updatable Fields:**
    - citizen_id
    - family_info
    - academic_history
    - admission_scores
    - documents_checklist

    **Returns:**
    - Updated AdmissionProfile

    **Errors:**
    - 404: Profile not found (or IDOR protection)
    - 400: Profile is not in draft status
    """
    try:
        # Convert Pydantic model to dict (exclude None values)
        update_data = data.model_dump(exclude_unset=True)

        profile = await admission_service.update_profile(
            db=db,
            profile_id=profile_id,
            data=update_data,
            current_user=current_user,
        )

        # Transaction commit
        await db.commit()
        await db.refresh(profile)

        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ValidationError as e:
        # Cross-field date invariant violations (candidate state check)
        # surface as ValidationError. Map to 400 like other input errors.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/submit",
    response_model=schemas.AdmissionSubmitResponse,
    summary="Submit admission profile for evaluation",
)
async def submit_admission_profile(
    request: Request,
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Submit AdmissionProfile for review.

    Transitions profile from draft → submitted. Validation checks
    document completeness and data integrity against snapshot rules.

    **On Success:**
    - Profile.status = 'submitted'
    - Returns: { status: "submitted", message: "..." }

    **On Validation Failure:**
    - Profile stays in 'draft'
    - Returns: { status: "draft", validation_errors: ["...", "..."] }

    **Security:**
    - IDOR: Only accessible to users in same unit
    - Snapshot: Validates against applied_rules (never queries ProgramOffering)

    **Errors:**
    - 404: Profile not found (or IDOR protection)
    - 400: Profile is not in draft status
    """
    try:
        result, post_commit = await admission_service.submit_and_evaluate(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        # Transaction commit
        await db.commit()

        # Service-side post_commit fanout (V3 contract) — fires
        # APPLICATION_STATUS_CHANGED + ADMISSION_PROFILE_SUBMITTED
        # captured at flush time. None when validation failed (status=
        # "draft"); the service skips fanout in that case.
        if post_commit is not None:
            await post_commit()

        return result

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# ADM-032 — cross-tab realtime sync for document mutations
#
# Five doc mutation routes (upload / paper-submitted / verify-format /
# reject / reset) broadcast a ``data_updated`` socket event after the DB
# transaction settles so other tabs/officers viewing the same profile
# pick up the change without an F5. Reuses the ``emit_data_updated``
# helper already used for ``user`` / ``lead`` / ``organization``;
# **no** new SystemEvents / notification_rule are introduced — those
# are for persisted notifications, this is purely realtime UI sync.
#
# INVARIANT: emit happens AFTER ``db.commit()`` and (where the route
# stages files via ``finalize``) AFTER ``finalize(True)``. A commit
# failure or a finalize failure must NOT trigger emit — otherwise other
# tabs would refetch and observe rolled-back / orphaned state.
# ---------------------------------------------------------------------------

async def _emit_admission_doc_mutation(
    profile_id: int,
    *,
    document_action: str,
    doc_code: str,
) -> None:
    """Best-effort realtime broadcast for a successful doc mutation.

    Catches exceptions internally — failure to emit must not break the
    HTTP response (the DB write already succeeded). Mirrors the
    fail-soft pattern in ``user_service.emit_data_updated``.
    """
    try:
        await _emit_realtime_update(
            resource_type="admission_profile",
            operation="update",
            resource_id=profile_id,
            data={"document_action": document_action, "doc_code": doc_code},
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning(
            "Realtime data_updated emit failed for admission_profile",
            profile_id=profile_id,
            document_action=document_action,
            doc_code=doc_code,
            error=str(exc),
        )


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/upload",
    response_model=schemas.AdmissionProfileResponse,
    summary="Upload admission document",
    status_code=status.HTTP_200_OK,
)
async def upload_document(
    request: Request,
    profile_id: int,
    doc_code: str,
    file: UploadFile = File(...),
    actual_submission_format: Optional[str] = Form(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Upload a document for an admission profile.

    File will be saved and the profile will be returned with updated validation_summary.

    **Form Fields:**
    - file: Document file (PDF, JPG, PNG, max 10MB)
    - actual_submission_format: Type of document (original | certified_copy | photo)
    """
    try:
        profile, finalize = await admission_service.upload_document(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            file=file,
            current_user=current_user,
            actual_submission_format=actual_submission_format,
        )
        # ADM-007: file is staged on disk; promote/cleanup happens
        # via ``finalize`` only after the commit branch is decided.
        try:
            await db.commit()
        except Exception:
            await finalize(False)
            raise
        await finalize(True)
        await db.refresh(profile)
        # ADM-032: emit AFTER finalize(True) so other tabs only refetch
        # once the file is promoted to its final path.
        await _emit_admission_doc_mutation(
            profile_id, document_action="upload", doc_code=doc_code
        )
        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{profile_id}/documents/{document_id}/download",
    summary="Download an admission document (authed, IDOR-scoped, audited)",
)
async def download_document(
    request: Request,
    document_id: int,
    profile: models.AdmissionProfile = Depends(get_admission_for_user_read),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Stream a ProfileDocument file for staff (admin / manager / officer).

    PR1 Commit 1 (A01/A05/A09). Access is gated by
    ``get_admission_for_user_read`` (3-tier IDOR scope; non-staff and
    out-of-scope callers get a fake 404). The document must belong to the
    authorized profile and have a real file, otherwise 404 (no existence
    leak). A ``downloaded`` audit row is committed before the file streams.
    The public ``/uploads`` static mount was removed in the same commit, so
    this is the ONLY way to read an admission document.
    """
    from fastapi.responses import FileResponse

    try:
        abs_path, safe_basename, media_type = (
            await admission_service.get_document_file_for_download(
                db=db,
                profile=profile,
                document_id=document_id,
                actor_user_id=current_user.id,
                actor_ip=get_client_ip(request),
                actor_user_agent=request.headers.get("user-agent"),
            )
        )
        # Persist the ``downloaded`` audit row before the response streams.
        await db.commit()
    except ResourceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        )
    except PermissionDeniedError:
        # IDOR protection: 404, never 403, to avoid resource enumeration.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        )

    return FileResponse(
        abs_path,
        media_type=media_type,
        filename=safe_basename,
        content_disposition_type="inline",
        headers={
            # PII document: never cache + don't leak the referrer + no MIME
            # sniffing. nginx also sets nosniff globally; this keeps the
            # contract correct when the backend is hit directly (dev/tests).
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/paper-submitted",
    response_model=schemas.AdmissionProfileResponse,
    summary="Mark document as paper submitted (Officer confirms receipt)",
    status_code=status.HTTP_200_OK,
)
async def mark_document_paper_submitted(
    request: Request,
    profile_id: int,
    doc_code: str,
    data: schemas.DocumentSubmissionRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Mark a document as paper submitted (officer confirms receipt).

    For documents where requires_upload=false.
    Only officers/managers/admins can mark paper submitted.

    **Request Body:**
    - actual_submission_format: Type of document received (original | certified_copy | photo)

    **Returns:**
    - Full AdmissionProfileResponse with updated validation_summary
    """
    try:
        profile = await admission_service.mark_paper_submitted(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            current_user=current_user,
            actual_submission_format=data.actual_submission_format,
            graduation_proof_kind=data.graduation_proof_kind,
            supplement_due_date=data.supplement_due_date,
        )
        await db.commit()
        await db.refresh(profile)
        # ADM-032: emit AFTER commit settles.
        await _emit_admission_doc_mutation(
            profile_id, document_action="paper_submitted", doc_code=doc_code
        )
        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/graduation-proof",
    response_model=schemas.AdmissionProfileResponse,
    summary="Update graduation proof kind (provisional cert -> official diploma)",
    status_code=status.HTTP_200_OK,
)
async def update_document_graduation_proof(
    request: Request,
    profile_id: int,
    doc_code: str,
    data: schemas.GraduationProofUpdateRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Update the graduation proof kind for a graduation document (PR #13).

    Use case: a candidate who previously submitted a provisional graduation
    certificate (``provisional_cert``) later brings the official diploma
    (``official_diploma``). The officer records the upgrade WITHOUT changing
    the document status (it stays ``paper_submitted``); ``official_diploma``
    clears the supplement due date so the "nợ bằng" badge disappears.

    Only applies to ``bang_tot_nghiep_thpt``. Casbin admits officer (manager
    + admin inherit, mirror ``paper-submitted``); the service layer enforces
    the IDOR scope via ``get_profile``.

    **Request Body:**
    - kind: official_diploma | provisional_cert

    **Returns:**
    - Full AdmissionProfileResponse with updated validation_summary
    """
    try:
        profile = await admission_service.update_graduation_proof_kind(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            new_kind=data.kind,
            current_user=current_user,
        )
        await db.commit()
        await db.refresh(profile)
        # PR #13 — emit AFTER commit settles (mirror paper-submitted) so the
        # FE refetches and the "nợ bằng" badge + completion stay in sync.
        await _emit_admission_doc_mutation(
            profile_id,
            document_action="graduation_proof_updated",
            doc_code=doc_code,
        )
        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except ValidationError as e:
        # BusinessRuleViolation (non-graduation doc) + ValidationError
        # (invalid kind) are both ValidationError subclasses → 400.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.patch(
    "/{profile_id}/documents/{doc_code}/verify-format",
    response_model=schemas.AdmissionProfileResponse,
    summary="Verify document format and mark as verified",
    status_code=status.HTTP_200_OK,
)
async def verify_document_format_endpoint(
    request: Request,
    profile_id: int,
    doc_code: str,
    data: schemas.DocumentFormatVerifyRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Verify document physical format and mark as verified (Officer action).

    This performs the full verification workflow:
    1. Updates verified_format to 'original', 'certified_copy', or 'photo'
    2. Sets document status to 'verified'
    3. Records verification timestamp and officer
    4. Re-computes validation_summary

    **Request Body:**
    - format: original | certified_copy | photo

    **Returns:**
    - Full AdmissionProfileResponse with updated validation_summary and document status
    """
    try:
        profile = await admission_service.confirm_document_format(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            format_type=data.format,
            current_user=current_user,
        )
        await db.commit()
        await db.refresh(profile)
        # ADM-032: emit AFTER commit settles.
        await _emit_admission_doc_mutation(
            profile_id, document_action="verify", doc_code=doc_code
        )
        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/reject",
    response_model=dict,
    summary="Reject document with reason",
    status_code=status.HTTP_200_OK,
)
async def reject_document_endpoint(
    request: Request,
    profile_id: int,
    doc_code: str,
    data: schemas.DocumentRejectRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Reject a document with reason.
    
    User will need to re-upload or resubmit.
    Only officers/managers/admins can reject documents.
    
    **Request Body:**
    - reason: Rejection reason (required)
    
    **Returns:**
    - { code, status, rejection_reason, rejected_at, rejected_by_id }
    """
    try:
        result, post_commit = await admission_service.reject_document(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            reason=data.reason,
            current_user=current_user,
        )
        await db.commit()
        await post_commit()
        # ADM-032: emit AFTER post_commit so other tabs see the
        # rejected status. Service returns ``dict``, not the profile —
        # ``profile_id`` from the path is the source of truth.
        await _emit_admission_doc_mutation(
            profile_id, document_action="reject", doc_code=doc_code
        )
        return result

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/reset",
    response_model=schemas.AdmissionProfileResponse,
    summary="Reset document to missing status (undo)",
    status_code=status.HTTP_200_OK,
)
async def reset_document_endpoint(
    request: Request,
    profile_id: int,
    doc_code: str,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Reset a document to 'missing' status (undo submission).

    **Use Cases:**
    - User accidentally clicked "Đã nộp"
    - Uploaded wrong file
    - Need to change submission type

    **Permissions:**
    - Officer: Can reset documents for profiles in draft/rejected status
    - Manager/Admin: Can reset any document (except enrolled profiles)

    **What Gets Reset:**
    - Status → "missing"
    - File deleted from disk (if exists)
    - All metadata cleared (timestamps, format, rejection reason)

    **Returns:**
    - Full AdmissionProfileResponse with updated validation_summary
    """
    try:
        profile, finalize = await admission_service.reset_document(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            current_user=current_user,
        )
        # ADM-007: defer the file delete to ``finalize(True)`` so a
        # commit failure leaves the file (and the rolled-back DB
        # reference to it) in place.
        try:
            await db.commit()
        except Exception:
            await finalize(False)
            raise
        await finalize(True)
        await db.refresh(profile)
        # ADM-032: emit AFTER finalize(True) so other tabs see the
        # reset state only once the old file is actually deleted.
        await _emit_admission_doc_mutation(
            profile_id, document_action="reset", doc_code=doc_code
        )
        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/enroll",
    response_model=schemas.EnrollStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll student (ACID transaction)",
)
async def enroll_student(
    request: Request,  # Required for rate limiter
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Enroll student (create Student + StudentDocument records).

    **ACID Transaction Flow:**
    1. Validate profile status (must be 'confirmed' or 'overridden')
    2. Fee Gate: Verify tuition fee is paid/waived (if ENABLE_FEE_VERIFICATION=True)
    3. Generate unique student_code (SV + YYYY + 4-digit random)
    4. Create Student record
    5. Create StudentDocument records (from documents_checklist)
    6. Update AdmissionProfile.status = 'enrolled'
    7. Update Lead.status = 'converted'

    **Security:**
    - IDOR: Only accessible to users in same unit
    - State Check: Only confirmed/overridden profiles can be enrolled
    - Fee Gate: Tuition fee must be paid/waived (when ENABLE_FEE_VERIFICATION=True)
    - Rate Limiting: 10 requests/minute (prevent brute-force student_code)

    **Fee Gate (Phase 6):**
    When ENABLE_FEE_VERIFICATION=True (config):
    - Checks tuition fee status in Fee table
    - Blocks if status not in ('paid', 'waived')
    - Returns 400 with remaining amount if blocked

    **Returns:**
    - { student_id, student_code, enrollment_date }

    **Errors:**
    - 404: Profile not found (or IDOR protection)
    - 400: Profile is not confirmed, or tuition fee not cleared
    - 409: Unique constraint violation (student_code or citizen_id)
    - 429: Rate limit exceeded
    """
    try:
        result, callback = await admission_service.enroll_student(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        # Transaction commit (Router responsibility)
        await db.commit()

        if callback:
            await callback()

        return result

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete admission profile (draft only)",
)
async def delete_admission_profile(
    request: Request,
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Delete AdmissionProfile (only when status='draft').

    **Security:**
    - IDOR: Only accessible to users in same unit (unless admin)
    - State Locking: Only draft profiles can be deleted

    **Errors:**
    - 404: Profile not found (or IDOR protection)
    - 400: Profile is not in draft status
    """
    try:
        # Snapshot lead data before delete (profile will be gone after service call)
        _pre_profile = await db.get(models.AdmissionProfile, profile_id)
        _snapshot_lead_id = _pre_profile.lead_id if _pre_profile else None
        _snapshot_lead_name = "Unknown"
        if _snapshot_lead_id:
            _lead = await db.get(models.Lead, _snapshot_lead_id)
            if _lead:
                _snapshot_lead_name = _lead.full_name

        await admission_service.delete_profile(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        # Transaction commit
        await db.commit()

        # Dispatch APPLICATION_DELETED (profile is gone, use snapshot)
        if _snapshot_lead_id:
            # Lead row still exists (FK was profile→lead, profile gone but lead kept).
            # Fetch it so scoped emit can include unit + assigned officer rooms.
            _deleted_lead = await db.get(models.Lead, _snapshot_lead_id)
            await safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_DELETED,
                payload={
                    "application_id": profile_id,
                    "lead_id": _snapshot_lead_id,
                    "lead_name": _snapshot_lead_name,
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"admission_profile_deleted:{profile_id}",
                rooms=rooms_for_lead(_deleted_lead),
            )

        log.info(
            "Admission profile deleted via API",
            profile_id=profile_id,
            user_id=current_user.id,
        )

        return None

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ==============================================================================
# STATE MACHINE ENDPOINTS (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
# ==============================================================================

# ✅ FIX #8: Assignment Workflow Endpoint
@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/claim",
    response_model=schemas.AdmissionProfileResponse,
    summary="Claim admission profile for review (Manager/Admin)",
)
async def claim_admission_review(
    request: Request,
    profile_id: int,
    data: schemas.ClaimRequest,  # ✅ Fix #8 Bug 3: Request body with version
    current_user: models.User = CasbinAuth,  # Layer 2: RBAC (Manager/Admin)
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # Layer 3: IDOR
    db: AsyncSession = Depends(database.get_db),
):
    """
    Claim a profile for review - Manager/Admin action.
    
    **Architecture Compliance**:
    - Layer 1: Rate limiting
    - Layer 2: RBAC (Manager/Admin only)
    - Layer 3: IDOR (Unit check)
    - Layer 4: Service handles locking logic
    
    **Business Rules**:
    - Status must be 'submitted'
    - Must not be claimed by another user
    - Optimistic locking via version check
    """
    # ✅ FIX #8 Bug 2: Call module-level function directly
    # Was: admission_service = AdmissionService() (Error: Class not found)
    await admission_service.claim_review(
        db=db,
        profile=profile,
        reviewer=current_user,
        expected_version=data.version  # ✅ Fix #8 Bug 3: Version check
    )
    
    # Commit transaction
    await db.commit()
    return profile


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/unclaim",
    response_model=schemas.AdmissionProfileResponse,
    summary="Unclaim admission profile from review (Manager/Admin)",
)
async def unclaim_admission_review(
    request: Request,
    profile_id: int,
    data: schemas.ClaimRequest,
    current_user: models.User = CasbinAuth,
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Unclaim a profile from review - Manager/Admin action.

    **Business Rules**:
    - Profile must have an assigned reviewer
    - Only assigned reviewer can unclaim (Admin can unclaim anyone)
    - Optimistic locking via version check
    """
    await admission_service.unclaim_review(
        db=db,
        profile=profile,
        current_user=current_user,
        expected_version=data.version,
    )

    await db.commit()
    return profile


# ==============================================================================
# APPLICATION FEE ENDPOINTS
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get(
    "/{profile_id}/fee-status",
    summary="Get application fee status",
)
async def get_fee_status(
    request: Request,
    profile: models.AdmissionProfile = Depends(get_admission_for_user_read),  # Layer 3: IDOR
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get application fee status for an admission profile.

    **Authorization (3-tier IDOR via ``get_admission_for_user_read``):**
    - Admin: any profile
    - Manager: profiles in their unit
    - Officer: profiles assigned to them in their unit
    - Returns 404 (fake) for out-of-scope access.

    Returns:
    - requires_fee: Whether this profile requires application fee
    - fee_amount: Fee amount in VND
    - fee_status: "exempt" | "pending" | "paid"
    - can_approve: Whether profile can be approved (fee paid or exempt)
    """
    try:
        result = await admission_service.check_application_fee_status(
            db=db,
            profile_id=profile.id,
        )
        return result
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/record-fee-payment",
    response_model=schemas.AdmissionProfileResponse,
    summary="Record application fee payment",
)
async def record_fee_payment(
    request: Request,
    profile_id: int,
    transaction_id: str = Query(
        ...,
        min_length=6,
        max_length=80,
        description="Payment receipt / transaction ID",
    ),
    amount: Decimal = Query(
        ...,
        gt=0,
        le=MAX_AMOUNT,
        description="Payment amount in VND",
    ),
    payment_method_code: str = Query(
        "cash",
        min_length=1,
        max_length=50,
        description="Payment method code. Application-fee collection is cash-only.",
    ),
    current_user: models.User = CasbinAuth,
    profile: models.AdmissionProfile = Depends(get_admission_for_fee_collection),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Record application fee payment for an admission profile.

    **Authorization:** Officer/Manager/Accountant/Admin via Casbin + IDOR scope

    **Use cases:**
    1. Cash collection by officer/accountant/manager/admin

    **Request Parameters:**
    - transaction_id: Receipt / transaction ID
    - amount: Payment amount in VND
    - payment_method_code: Must be cash

    **Effects:**
    - Creates/reconciles Finance Fee/Invoice/Payment/PaymentTransaction records
    - Updates profile.applied_rules.fee_status to "paid"
    - Syncs lead to sts13 (Đã hoàn lệ phí xét tuyển)

    **Returns:**
    - Updated AdmissionProfile
    """
    try:
        payment_data = {
            "transaction_id": transaction_id,
            "amount": amount,
            "payment_method_code": payment_method_code,
            "paid_at": datetime.now().isoformat(),
            "recorded_by": current_user.id,
        }

        result, callback = await admission_service.record_application_fee_payment(
            db=db,
            profile_id=profile.id,
            payment_data=payment_data,
            recorded_by=current_user,
        )

        await db.commit()
        await db.refresh(result)
        await callback()

        return result

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/approve",
    response_model=schemas.AdmissionProfileResponse,
    summary="Approve admission profile (Manager/Admin)",
)
async def approve_admission(
    request: Request,
    profile_id: int,
    data: schemas.ApproveRequest,
    current_user: models.User = CasbinAuth,  # Code review 2026-05-22: swap
    # inline role check → CasbinAuth dep so 403 fires before Pydantic body
    # validation (was inline check + 422 schema leak risk + anti-pattern
    # "Logic in Router" per CLAUDE.md). Consistent với reject/request_revision.
    db: AsyncSession = Depends(database.get_db),
):
    """
    Approve admission profile - Manager/Admin action.

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1.3):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Manager/Admin only)
    - Layer 3: IDOR via _check_idor_access in service (unit check)
    - Layer 4: Service layer handles business logic

    **State Transition:**
    - From: SUBMITTED or RESUBMITTED
    - To: APPROVED

    **Validation:**
    - State transition via validate_transition()
    - Optimistic locking via version check

    **Request Body:**
    - notes: Optional approval notes (sanitized for XSS)
    - version: Optional version for optimistic locking

    **Returns:**
    - Updated AdmissionProfile with status='approved'

    **Errors:**
    - 400: Invalid state transition or version mismatch
    - 403: Officer/accountant role (Casbin denied before body parse)
    - 404: Profile not found (or IDOR protection)
    """

    # ADM-026 review (Round 2): admin-only bypass + audit are enforced
    # together inside `_assert_quota_or_bypass`. The router pre-gate was
    # removed so that EVERY denied bypass attempt — including manager
    # attempts — flows through the service path that writes the
    # `quota_bypass_denied_*` audit row via a separate session. Audit
    # contract trumps the early-return optimisation here; the lock + count
    # roundtrip on a denied attempt is acceptable since denial is rare.

    try:
        # 1. DELEGATE to Service (Service handles Locking + IDOR + bundle)
        result, callback = await admission_service.approve_profile(
            db=db,
            profile_id=profile_id,
            approver=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT side effects (bundle + commission composed in service)
        if callback:
            await callback()

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/reject",
    response_model=schemas.AdmissionProfileResponse,
    summary="Reject admission profile (Manager/Admin)",
)
async def reject_admission(
    request: Request,
    profile_id: int,
    data: schemas.RejectRequest,
    current_user: models.User = CasbinAuth,  # F10 fix 2026-05-16: swap inline role check → Casbin dep so 403 fires before Pydantic body validation (was 422 schema leak for officer)
    db: AsyncSession = Depends(database.get_db),
):
    """
    Reject admission profile - Manager/Admin action.

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1.3):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Manager/Admin only) — enforced via
      ``Depends(check_permission)`` which runs in `solve_dependencies`
      BEFORE FastAPI parses the Pydantic body, so insufficient-perm
      users get 403 without schema disclosure (F10 fix 2026-05-16).
    - Layer 3: IDOR via service ``_check_idor_access`` (lead.unit_id check)
    - Layer 4: Service layer handles business logic

    **State Transition:**
    - From: SUBMITTED or RESUBMITTED
    - To: REJECTED

    **Validation:**
    - State transition via validate_transition()
    - Reason is mandatory (10+ chars)
    - Optimistic locking via version check
    """
    try:
        # 1. DELEGATE to Service (Service handles Locking + IDOR + bundle)
        result, callback = await admission_service.reject_profile(
            db=db,
            profile_id=profile_id,
            rejector=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT side effects (bundle + commission composed in service)
        if callback:
            await callback()

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/request-revision",
    response_model=schemas.AdmissionProfileResponse,
    summary="Request revision of admission profile (Manager/Admin)",
)
async def request_revision(
    request: Request,
    profile_id: int,
    data: schemas.RevisionRequest,
    current_user: models.User = CasbinAuth,  # F10 fix 2026-05-16 (same pattern as reject_admission)
    db: AsyncSession = Depends(database.get_db),
):
    """
    Request revision of admission profile - Manager/Admin action.

    **State Transition:**
    - From: SUBMITTED or RESUBMITTED
    - To: REVISION_REQUESTED

    **Validation:**
    - State transition via validate_transition()
    - Reason is mandatory (10+ chars)
    - Optimistic locking via version check

    RBAC enforced via CasbinAuth dep (runs before Pydantic body parse,
    so officer/accountant get 403 without schema disclosure).
    """
    try:
        result, callback = await admission_service.request_revision(
            db=db,
            profile_id=profile_id,
            reviewer=current_user,
            data=data.model_dump(),
        )

        await db.commit()
        await db.refresh(result)

        if callback:
            await callback()

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/resubmit",
    response_model=schemas.AdmissionProfileResponse,
    summary="Resubmit admission profile after rejection (Officer)",
)
async def resubmit_admission(
    request: Request,
    profile_id: int,
    data: schemas.ResubmitRequest,
    current_user: models.User = Depends(deps.get_current_active_user),  # ✅ FIX: Strict Active User Check
    # profile: models.AdmissionProfile = Depends(get_admission_for_user),  # REMOVED: Service handles fetching with lock
    db: AsyncSession = Depends(database.get_db),
):
    """
    Resubmit admission profile after rejection - Officer action.

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2.1):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Officer/Manager/Admin)
    - Layer 3: IDOR via get_admission_for_user (assigned officer check)
    - Layer 4: Service layer handles business logic

    **State Transition:**
    - From: REJECTED or REVISION_REQUESTED
    - To: RESUBMITTED

    **Validation:**
    - State transition via validate_transition()
    - Reason is optional
    - Optimistic locking via version check
    """

    # Check Officer/Manager/Admin Role explicitly since we removed CasbinAuth/IDOR dep
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.OFFICER]:
         raise PermissionDeniedError("Only staff can resubmit profiles")

    try:
        # 1. DELEGATE to Service (Service handles bundle + commission)
        result, callback = await admission_service.resubmit_profile(
            db=db,
            profile_id=profile_id,
            officer=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT side effects (bundle + commission composed in service)
        if callback:
            await callback()

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/minor-correction",
    response_model=schemas.AdmissionProfileResponse,
    summary="Apply post-approval minor correction (Officer/Manager/Admin)",
)
async def minor_correction(
    request: Request,
    profile_id: int,
    payload: schemas.MinorCorrectionRequest,
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """Apply a SAFE-catalog-bounded correction to an approved/confirmed profile.

    Three-layer gate before the service runs:
    - **Casbin** admits the route (role:admin/manager/officer have policy
      `/api/admissions/{id}/minor-correction POST` seeded by alembic).
    - **IDOR** via ``get_admission_for_user`` (admin all / manager unit /
      officer unit + assigned). Returns 404 (not 403) on miss to avoid
      leaking profile existence.
    - **Lock** — same dependency uses ``with_for_update`` so concurrent
      corrections on the same profile serialize.

    Service then enforces:
    - Status whitelist (approved/confirmed only)
    - Optimistic version match (409 on mismatch)
    - SAFE catalog ∩ AdmissionPath allowlist (live, not snapshotted)
    - HARD_DENY blocklist (citizen_id, dob, status, etc.)
    - Per-field type + business-rule validation

    Post-commit emits a broadcast-only ``application_minor_corrected``
    socket event scoped to admin + unit + assigned officer rooms — no
    DB notification rule, payload carries field NAMES only (no PII).
    """
    try:
        result, socket_envelope = await admission_service.apply_minor_correction(
            db=db,
            profile=profile,
            payload=payload,
            current_user=current_user,
        )

        await db.commit()

        # Best-effort post-commit fanout. Network/socket glitch never
        # rolls back the business mutation. Rooms are mandatory because
        # the catalog tags this event privacy="sensitive" — dispatcher
        # fail-closed guard would block a no-rooms emit otherwise.
        await safe_dispatch(
            db=db,
            event=SystemEvents.APPLICATION_MINOR_CORRECTED,
            payload=socket_envelope["payload"],
            rooms=socket_envelope["rooms"],
        )

        return result

    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/override",
    response_model=schemas.AdmissionProfileResponse,
    summary="Override normal flow (Admin only - AUDIT LOGGED)",
)
async def override_admission(
    request: Request,
    profile_id: int,
    data: schemas.OverrideRequest,
    current_user: models.User = CasbinAuth,  # Layer 2: RBAC (Admin only)
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # Layer 3: IDOR
    db: AsyncSession = Depends(database.get_db),
):
    """
    Override normal admission flow - Admin action (AUDIT LOGGED).

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4.1):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Admin only)
    - Layer 3: IDOR via get_admission_for_manager
    - Layer 4: Service layer handles business logic + AUDIT LOGGING

    **State Transition:**
    - From: APPROVED
    - To: OVERRIDDEN

    **Validation:**
    - State transition via validate_transition()
    - Optimistic locking via version check
    - Override reason required (min 10 chars)

    **AUDIT LOGGING** (per AUTHORIZATION_DECISIONS.md Decision 11):
    - All override actions logged with: admin_id, admin_email, reason, bypass_rules, timestamp
    - Log level: WARNING (for security monitoring)

    **Request Body:**
    - reason: Override reason (REQUIRED, min 10 chars, max 1000)
    - bypass_rules: List of rules bypassed (optional, for documentation)
    - version: REQUIRED — current profile version for optimistic locking
      (ADM-015). Stale version → 409 Conflict.

    **Returns:**
    - Updated AdmissionProfile with status='overridden'

    **Errors:**
    - 400: Invalid state transition, version mismatch, or invalid reason
    - 404: Profile not found (or IDOR protection)
    """
    try:
        # Capture pre-transition status
        pre_status = profile.status

        # 1. DELEGATE to Service (includes AUDIT LOGGING)
        result, callback = await admission_service.override_profile(
            db=db,
            profile=profile,
            admin=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT Side Effects
        await callback()

        # 4. Dispatch APPLICATION_STATUS_CHANGED only
        # NOTE: No LEAD_STATUS_CHANGED here — lead_admission_sync maps both
        # approved and overridden to sts09, so lead pipeline status does not
        # actually change during override. Emitting LEAD_STATUS_CHANGED would
        # be semantically incorrect.
        if result.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": result.lead_id,
                    "old_status": pre_status,
                    "new_status": "overridden",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"admission_profile_overridden:{profile_id}",
                rooms=rooms_for_admission(result),
            )

        # 5. RETURN Pydantic Model
        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/withdraw",
    response_model=schemas.AdmissionProfileResponse,
    summary="Withdraw admission profile",
)
async def withdraw_admission(
    request: Request,
    profile_id: int,
    data: schemas.WithdrawRequest,
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Withdraw an admission profile.

    **State Transition:**
    - Allowed from: DRAFT, SUBMITTED, REJECTED, RESUBMITTED
    - Target: WITHDRAWN (terminal)

    **Lead pipeline sync:** lead moves to sts08 (Từ chối tư vấn) per
    ``lead_admission_sync``, handled by the service.

    **Security:**
    - RBAC: ``CasbinAuth`` — /withdraw is granted to the officer
      template; manager/admin inherit via diamond inheritance. Regular
      users without a staff role are rejected with 403 by Casbin.
    - IDOR: Service's ``_check_idor_access`` validates the actor can
      act on this specific profile's lead (assigned officer within unit,
      manager within unit, admin unrestricted).

    **Validation:**
    - reason: required, min 5 chars
    - version: optimistic-locking check (409 on mismatch)

    **Errors:**
    - 400: invalid state transition or missing reason
    - 404: profile not found (or IDOR denial)
    - 409: version conflict
    """
    try:
        # 1. DELEGATE to Service (service handles lock + IDOR + bundle)
        result, callback = await admission_service.withdraw_profile(
            db=db,
            profile_id=profile_id,
            actor=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT side effects (bundle composed in service)
        if callback:
            await callback()

        return result

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/finalize",
    response_model=schemas.AdmissionProfileResponse,
    summary="Finalize to enrolled (Admin only)",
)
async def finalize_enrollment(
    request: Request,
    profile_id: int,
    data: schemas.FinalizeRequest,
    current_user: models.User = CasbinAuth,  # Layer 2: RBAC (Admin only)
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # Layer 3: IDOR
    db: AsyncSession = Depends(database.get_db),
):
    """
    Finalize enrollment to ENROLLED status - Admin action.

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4.2):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Admin only)
    - Layer 3: IDOR via get_admission_for_manager
    - Layer 4: Service layer handles business logic

    **State Transition:**
    - From: CONFIRMED or OVERRIDDEN
    - To: ENROLLED (FINAL STATE - no further transitions)

    **Validation:**
    - State transition via validate_transition()
    - Optimistic locking via version check
    - Final state enforcement (no transitions from ENROLLED)

    **Request Body:**
    - version: REQUIRED — current profile version for optimistic locking
      (ADM-015). Stale version → 409 Conflict.

    **Returns:**
    - Updated AdmissionProfile with status='enrolled'

    **Errors:**
    - 400: Invalid state transition or version mismatch
    - 404: Profile not found (or IDOR protection)
    """
    # ADM-026 review (Round 2): bypass admin gate + audit live in
    # ``_assert_quota_or_bypass``. Router pre-gate removed so denied
    # attempts always produce an audit row (manager-bypass would skip
    # the service if pre-gated at router level).
    try:
        # 1. DELEGATE to Service (service handles bundle + commission)
        result, callback = await admission_service.finalize_profile(
            db=db,
            profile=profile,
            admin=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT side effects (bundle + commission composed in service)
        if callback:
            await callback()

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ==============================================================================
# MAGIC LINK CONFIRMATION ENDPOINTS (PUBLIC - No Auth)
# ==============================================================================


@router.get(
    "/confirm/{token}",
    response_model=schemas.ConfirmTokenInfoResponse,
    summary="Get confirmation token info",
    description="""
    Get token info to display confirmation form.

    **PUBLIC ENDPOINT** - No authentication required.
    Token itself serves as the authentication.

    **Returns:**
    - Lead name (for "Xin chào, [Tên]...")
    - Token validity status (valid, expired, locked, already_used)
    - Attempts remaining
    """,
)
@limiter.limit(RateLimits.PUBLIC_READ)  # 100/hour - prevent token enumeration
async def get_confirm_token_info(
    request: Request,
    token: str,
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """Get token info for frontend to display confirmation form."""
    # PR1 Commit 7: the token is in the URL — don't leak it via the Referer
    # header to anything the public confirm page subsequently loads.
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        token_info = await admission_service.get_token_info(db, token)
        return token_info
    
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/confirm/{token}",
    response_model=schemas.ConfirmTokenResponse,
    summary="Confirm admission via magic link",
    description="""
    Lead confirms enrollment via magic link + CCCD verification.
    
    **PUBLIC ENDPOINT** - No authentication required.
    Security via: Token + CCCD verification + Rate limiting.
    
    **Workflow:**
    1. Lead clicks link in email: /confirm/{token}
    2. Frontend calls GET /confirm/{token} to get form info
    3. Lead enters last 4 digits of CCCD
    4. Frontend calls POST /confirm/{token} with CCCD digits
    5. If correct → Profile status changes to 'confirmed'
    
    **Security:**
    - Token is 256-bit random (impossible to guess)
    - CCCD verification prevents unauthorized confirmation
    - Max 5 attempts before token is locked
    - Rate limited: 200/hour globally + 100/day per IP (brute-force protection)
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour global limit
@limiter.limit(  # ✅ FIX #6: IP-based rate limit (brute-force protection)
    "100/day",
    key_func=get_client_ip
)
async def confirm_admission_by_token(
    request: Request,
    token: str,
    verify_data: schemas.ConfirmTokenVerifyRequest,
    db: AsyncSession = Depends(database.get_db),
):
    """Confirm admission via magic link + CCCD verification."""
    # PR-5 (2026-05-28): per-token Redis rate limit (5 attempts / 60s).
    # Defence-in-depth alongside the existing global ``DATA_WRITE`` cap and
    # per-IP 100/day cap. Namespace ``cft:`` is distinct from the multi-
    # action magic-link consume namespace ``mlt:`` so a single token URL
    # used at both endpoints does NOT share quota — each surface gets its
    # own bucket. Fail-closed: Redis breaker → 503; cap exceeded → 429.
    #
    # STATUS-CODE NOTE (PR-5): 503/429 here are the semantically-correct
    # codes — this router raises ``HTTPException`` directly. The v2
    # magic-link consume path (``services/magic_link_service.py``) currently
    # returns 400 for the SAME fail-closed conditions because it runs in the
    # service layer (no ``HTTPException``) and lacks a 429/503 domain
    # exception. That divergence is intentional and preserved for now;
    # normalising magic-link to 429/503 is deferred to a dedicated
    # domain-exception PR (with a magic-link wire test).
    count = await consume_attempt(token, key_namespace="cft:")
    if count is None:
        # Redis down → treat as rate-limited rather than open the door
        # (same defensive stance as the multi-action magic-link consume).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hệ thống đang quá tải, vui lòng thử lại sau ít phút.",
        )
    if count > ATTEMPTS_CAP_PER_WINDOW:
        log.warning(
            "Legacy confirm blocked: per-token rate limit exceeded",
            token_fp=token_fingerprint(token),
            count=count,
            cap=ATTEMPTS_CAP_PER_WINDOW,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Đã thử quá {ATTEMPTS_CAP_PER_WINDOW} lần trong 60 giây. "
                "Vui lòng đợi và thử lại."
            ),
        )

    try:
        # 1. DELEGATE to Service
        profile, callback = await admission_service.verify_and_confirm(
            db=db,
            token_value=token,
            last_digits=verify_data.last_digits_citizen_id,
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(profile)

        # 3. POST-COMMIT Side Effects
        await callback()

        # 4. Dispatch APPLICATION_STATUS_CHANGED only (public flow)
        # NOTE: No LEAD_STATUS_CHANGED here — both "approved" and "confirmed"
        # map to sts09 in ADMISSION_TO_LEAD_STATUS_MAP, so the lead status
        # does not actually change. sync_lead_from_admission() already skips
        # when lead is already at target status.
        if profile.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile.id,
                    "lead_id": profile.lead_id,
                    "old_status": "approved",
                    "new_status": "confirmed",
                    "actor_id": 0,
                    "actor_name": "Ứng viên xác nhận",
                },
                dedupe_key=f"admission_profile_confirmed:{profile.id}",
                rooms=rooms_for_admission(profile),
            )

        # 5. RETURN Response
        return schemas.ConfirmTokenResponse(
            message="Xác nhận nhập học thành công!",
            profile_id=profile.id,
            status=profile.status,
            confirmed_at=profile.confirmed_at,
        )
    
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        # IMPORTANT: Commit to persist attempt_count/locked_at changes
        await db.commit()
        # ADM-023 (2026-04-29): hard-lock branch attaches a notification
        # callback to the exception so operator alerts run AFTER the
        # locked_at + audit row commit (browser realtime + email
        # enqueue must observe the persisted state). Best-effort: a
        # callback failure must not turn a 400 into a 500.
        post_commit = getattr(e, "post_commit_callback", None)
        if post_commit is not None:
            try:
                await post_commit()
            except Exception:
                # Logged inside the callback path; don't escalate.
                pass
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# SEND CONFIRMATION LINK (Manager/Officer action)
# ==============================================================================


@router.post(
    "/{profile_id}/send-confirmation",
    response_model=schemas.SendConfirmationResponse,
    summary="Send confirmation link to Lead",
    description="""
    Generate and send confirmation link to Lead.
    
    **Called by:** Officer/Manager after profile is approved.
    **Action:** Creates token, sends email/SMS with magic link.
    
    **Permissions:**
    - Officer: Can send for profiles in their unit
    - Manager: Can send for profiles in their unit
    - Admin: Can send for any profile
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)
async def send_confirmation_link(
    request: Request,
    profile_id: int,
    current_user: models.User = CasbinAuth,
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    db: AsyncSession = Depends(database.get_db),
):
    """Generate and send confirmation link to Lead."""
    try:
        # 1. DELEGATE to Service
        token_obj, callback = await admission_service.generate_confirmation_token(
            db=db,
            profile=profile,
        )
        
        # 2. COMMIT Transaction
        await db.commit()
        
        # 3. POST-COMMIT Side Effects (send email)
        await callback()
        
        # 4. RETURN Response
        lead = profile.lead
        confirm_url = (
            f"{settings.FRONTEND_URL.rstrip('/')}/confirm/{token_obj.token}"
        )
        phone = lead.phone if lead else None
        return schemas.SendConfirmationResponse(
            message="Đường link xác nhận đã được gửi thành công!",
            token_expires_at=token_obj.expires_at,
            sent_to_email=lead.email if lead else None,
            phone=phone,
            token_value=token_obj.token,
            confirm_url=confirm_url,
        )

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# W2-1 fix Wave 7 (2026-05-16) — Generate magic-link cho 3 actions
# ==============================================================================


@router.post(
    "/{profile_id}/send-magic-link",
    response_model=schemas.SendMagicLinkResponse,
    summary="Generate magic-link cho candidate self-service (submit/resubmit/withdraw)",
    description="""
    Generate magic-link token cho candidate self-service. Mirror
    /send-confirmation pattern nhưng cho 3 actions non-confirm.

    **Called by:** Officer/Manager/Admin to enable candidate tự-service.
    **Action:** Creates token với action_type, returns URL cho officer
                copy + share manual qua Zalo/SMS (như SendConfirmation
                dialog pattern).

    **Permissions:**
    - Officer: profile thuộc unit + assigned
    - Manager: profile thuộc unit
    - Admin: tất cả

    **Body**: `{action: "submit" | "resubmit" | "withdraw"}`

    **404 nếu**: profile không tồn tại / IDOR scope sai
    **400 nếu**: action không hợp lệ / state mismatch (e.g. submit
                cho profile không phải draft)
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)
async def send_magic_link(
    request: Request,
    profile_id: int,
    payload: schemas.SendMagicLinkRequest,
    current_user: models.User = CasbinAuth,
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    db: AsyncSession = Depends(database.get_db),
):
    """W2-1 fix Wave 7 — Generate magic-link cho 3 candidate self-service
    actions. Pattern mirror /send-confirmation nhưng cho non-confirm
    actions."""
    try:
        token_obj = await admission_service.generate_action_magic_link(
            db=db,
            profile=profile,
            action=payload.action,
        )
        await db.commit()

        lead = profile.lead
        # FE landing pages tại /magic-link/{action}/{token} (PR #280
        # đã ship 4 actions). URL pattern matches CONSUME router shape.
        magic_link_url = (
            f"{settings.FRONTEND_URL.rstrip('/')}"
            f"/magic-link/{payload.action}/{token_obj.token}"
        )
        return schemas.SendMagicLinkResponse(
            message=(
                f"Đã tạo liên kết {payload.action}. Sao chép và gửi cho "
                "thí sinh qua Zalo/SMS."
            ),
            action=payload.action,
            token_expires_at=token_obj.expires_at,
            sent_to_email=lead.email if lead else None,
            phone=lead.phone if lead else None,
            token_value=token_obj.token,
            magic_link_url=magic_link_url,
        )

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# DROP STUDENT ENDPOINT
# ==============================================================================


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/{profile_id}/drop",
    response_model=schemas.AdmissionProfileResponse,
    summary="Mark enrolled student as dropped out (Manager/Admin)",
)
async def drop_student(
    request: Request,
    profile_id: int,
    data: schemas.DropStudentRequest,
    current_user: models.User = CasbinAuth,  # F10 fix 2026-05-16 (same pattern as reject_admission)
    db: AsyncSession = Depends(database.get_db),
):
    """
    Mark an enrolled student as dropped out - Manager/Admin action.

    Side-channel: profile status stays "enrolled", is_dropped=True.
    Lead syncs to sts12 (Ngưng theo học) via milestone consultation.

    **Validation:**
    - Profile must be in "enrolled" status
    - Must not already be dropped
    - Reason is mandatory (10+ chars)
    - Optimistic locking via version check

    RBAC enforced via CasbinAuth dep (runs before Pydantic body parse,
    so officer/accountant get 403 without schema disclosure).
    """
    try:
        result, callback = await admission_service.mark_student_dropped(
            db=db,
            profile_id=profile_id,
            actor=current_user,
            data=data.model_dump(),
        )

        await db.commit()
        await db.refresh(result)

        # Bundle (APPLICATION_STATUS_CHANGED + LEAD_STATUS_CHANGED) and
        # commission callback (literal sts11 → sts12) are composed inside
        # the service per Path C / Arch-3.
        if callback:
            await callback()

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
