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

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models, schemas
from ..config import settings
from ..core import deps
from ..core.deps import (
    CasbinAuth,  # ✅ Phase 2.2: Use standard alias
    get_admission_for_manager,
    get_admission_for_user,
    get_admission_for_user_read,
)
from ..services import admission_service
from ..services.notification_dispatcher import safe_dispatch, _rooms_for_admission, _rooms_for_lead
from ..core.events import SystemEvents
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    PermissionDeniedError,
    ConflictError,
    ValidationError,
)
from ..core.constants import UserRole
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


def get_client_ip(request: Request) -> str:
    """Helper for rate limiting key generation."""
    return request.client.host if request.client else "unknown"


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
    sort_by: str = Query("created_at", description="Sort field (created_at, updated_at, full_name, status)"),
    order: str = Query("desc", description="Sort order (asc, desc)"),
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
            admission_method_id=data.admission_method_id,  # NEW: Required for AdmissionPath lookup
            current_user=current_user,
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
            rooms=_rooms_for_admission(profile),
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
    # ADM-026 review (Major #1): per-item admin-only bypass enforcement
    # at request entry. Service-side check is defense-in-depth.
    for _item in body.items:
        deps.require_admin_for_quota_bypass(current_user, _item.bypass_quota)

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
        result = await admission_service.submit_and_evaluate(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        # Transaction commit
        await db.commit()

        # Dispatch APPLICATION_STATUS_CHANGED for the draft → submitted transition.
        # Service returns status="submitted" on success (not "approved"/"rejected").
        if result["status"] == "submitted":
            profile_row = await db.get(models.AdmissionProfile, profile_id)
            _submit_lead = None
            if profile_row and profile_row.lead_id:
                _submit_lead = await db.get(models.Lead, profile_row.lead_id)
            await safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile_row.lead_id if profile_row else None,
                    "old_status": "draft",
                    "new_status": "submitted",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"admission_profile_submitted:{profile_id}",
                rooms=_rooms_for_lead(_submit_lead),
            )

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
        )
        await db.commit()
        await db.refresh(profile)
        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR protection: return 404 to prevent resource enumeration
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except BadRequest as e:
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
                rooms=_rooms_for_lead(_deleted_lead),
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
    summary="Record application fee payment (Admin/System)",
)
async def record_fee_payment(
    request: Request,
    profile_id: int,
    transaction_id: str = Query(..., description="Payment transaction ID"),
    amount: float = Query(..., gt=0, description="Payment amount in VND"),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Record application fee payment for an admission profile.

    **Authorization:** Admin only or System callback

    **Use cases:**
    1. Manual payment confirmation by admin
    2. Payment gateway callback (via internal API)

    **Request Parameters:**
    - transaction_id: Payment transaction ID from gateway
    - amount: Payment amount in VND

    **Effects:**
    - Updates profile.applied_rules.fee_status to "paid"
    - Syncs lead to sts13 (Đã hoàn lệ phí xét tuyển)

    **Returns:**
    - Updated AdmissionProfile
    """
    # Only Admin can manually record payment
    if current_user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Only Admins can manually record fee payment")

    try:
        payment_data = {
            "transaction_id": transaction_id,
            "amount": amount,
            "paid_at": datetime.now().isoformat(),
            "recorded_by": current_user.id,
        }

        result, callback = await admission_service.record_application_fee_payment(
            db=db,
            profile_id=profile_id,
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
    current_user: models.User = Depends(deps.get_current_active_user),  # ✅ FIX: Strict Active User Check
    # profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # REMOVED: Service handles fetching with lock
    db: AsyncSession = Depends(database.get_db),
):
    """
    Approve admission profile - Manager/Admin action.

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1.3):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Manager/Admin only)
    - Layer 3: IDOR via get_admission_for_manager (unit check)
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
    - 404: Profile not found (or IDOR protection)
    """
    
    # Check Manager/Admin Role explicitly since we removed CasbinAuth/IDOR dep
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
         raise PermissionDeniedError("Only Managers or Admins can approve profiles")

    # ADM-026 review (Major #1): admin-only quota bypass enforced at request
    # entry. Service-side check in `_assert_quota_or_bypass` remains as
    # defense-in-depth.
    deps.require_admin_for_quota_bypass(current_user, data.bypass_quota)

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
    current_user: models.User = Depends(deps.get_current_active_user),  # ✅ FIX: Strict Active User Check
    # profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # REMOVED: Service handles fetching with lock
    db: AsyncSession = Depends(database.get_db),
):
    """
    Reject admission profile - Manager/Admin action.

    **Architecture Compliance** (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1.3):
    - Layer 1: Rate limiting (200 req/hour)
    - Layer 2: RBAC via CasbinAuth (Manager/Admin only)
    - Layer 3: IDOR via get_admission_for_manager (unit check)
    - Layer 4: Service layer handles business logic

    **State Transition:**
    - From: SUBMITTED or RESUBMITTED
    - To: REJECTED

    **Validation:**
    - State transition via validate_transition()
    - Reason is mandatory (10+ chars)
    - Optimistic locking via version check
    """
    
    # Check Manager/Admin Role explicitly since we removed CasbinAuth/IDOR dep
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
         raise PermissionDeniedError("Only Managers or Admins can reject profiles")

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
    current_user: models.User = Depends(deps.get_current_active_user),
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
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can request revision")

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
                rooms=_rooms_for_admission(result),
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
    # ADM-026 review (Major #1): admin-only quota bypass enforced at
    # request entry; service-side check is defense-in-depth.
    deps.require_admin_for_quota_bypass(current_user, data.bypass_quota)

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
    db: AsyncSession = Depends(database.get_db),
):
    """Get token info for frontend to display confirmation form."""
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
                rooms=_rooms_for_admission(profile),
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
    current_user: models.User = Depends(deps.get_current_active_user),
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
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can mark students as dropped")

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
