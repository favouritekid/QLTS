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
from ..core import deps
from ..core.deps import (
    CasbinAuth,  # ✅ Phase 2.2: Use standard alias
    get_admission_for_manager,
    get_admission_for_user,
    # get_admission_for_owner - DEPRECATED: Replaced by token-based confirmation
)
from ..services import admission_service
from ..services.notification_dispatcher import safe_dispatch
from ..core.events import SystemEvents
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    PermissionDeniedError,
    ConflictError,
)
from ..core.constants import UserRole
from ..services.commission_service import safe_check_commission_on_status_change

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admissions", tags=["Admissions"])


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

    # Validate payment_status
    if payment_status and payment_status not in ("paid", "unpaid", "partial", "no_fee"):
        raise HTTPException(status_code=400, detail="Invalid payment_status. Must be: paid, unpaid, partial, no_fee")

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

        # Dispatch notification (non-blocking)
        await safe_dispatch(
            db=db,
            event=SystemEvents.APPLICATION_CREATED,
            payload={
                "application_id": profile.id,
                "lead_id": profile.lead_id,
                "officer_id": current_user.id,
                "major_program_name": None,
                "actor_id": current_user.id,
            },
            dedupe_key=f"admission_profile_created:{profile.id}"
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
    try:
        result = await admission_service.bulk_approve(
            db=db,
            items=[item.model_dump() for item in body.items],
            approver=current_user,
            notes=body.notes,
        )

        # Extract approved profiles before commit (for post-commit dispatch)
        approved_profiles = result.pop("_approved_profiles", [])

        await db.commit()

        # POST-COMMIT: Dispatch LEAD_STATUS_CHANGED + commission for each approved profile
        for profile in approved_profiles:
            if profile.lead_id:
                await safe_dispatch(
                    db=db,
                    event=SystemEvents.LEAD_STATUS_CHANGED,
                    payload={
                        "lead_id": profile.lead_id,
                        "lead_name": f"Profile #{profile.id}",
                        "officer_id": current_user.id,
                        "old_status": "submitted",
                        "new_status": "sts09",
                        "actor_id": current_user.id,
                        "actor_name": current_user.full_name or current_user.username,
                    },
                    dedupe_key=f"lead_status_changed:{profile.lead_id}:sts09",
                )
                await safe_check_commission_on_status_change(
                    db, profile.lead_id, "submitted", "sts09", current_user.id,
                )

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
        result = await admission_service.bulk_reject(
            db=db,
            items=[item.model_dump() for item in body.items],
            rejector=current_user,
            reason=body.reason,
        )

        # Extract rejected profiles before commit (for post-commit dispatch)
        rejected_profiles = result.pop("_rejected_profiles", [])

        await db.commit()

        # POST-COMMIT: Dispatch LEAD_STATUS_CHANGED + commission for each rejected profile
        for profile in rejected_profiles:
            if profile.lead_id:
                await safe_dispatch(
                    db=db,
                    event=SystemEvents.LEAD_STATUS_CHANGED,
                    payload={
                        "lead_id": profile.lead_id,
                        "lead_name": f"Profile #{profile.id}",
                        "officer_id": current_user.id,
                        "old_status": "submitted",
                        "new_status": "sts16",
                        "actor_id": current_user.id,
                        "actor_name": current_user.full_name or current_user.username,
                    },
                    dedupe_key=f"lead_status_changed:{profile.lead_id}:sts16",
                )
                await safe_check_commission_on_status_change(
                    db, profile.lead_id, "submitted", "sts16", current_user.id,
                )

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

    # Data rows
    for profile in profiles:
        lead = profile.lead
        writer.writerow([
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
        ])

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
    Submit AdmissionProfile for auto-evaluation.

    **Validation Rules (against snapshot applied_rules):**
    1. admission_scores.gpa >= applied_rules.min_gpa
    2. All mandatory_docs have status='uploaded' and file_path not null
    3. citizen_id is unique across admission_profile and student tables

    **On Success:**
    - Profile.status = 'approved'
    - Returns: { status: "approved", message: "..." }

    **On Failure:**
    - Profile.status = 'rejected'
    - Returns: { status: "rejected", errors: ["...", "..."] }

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

        # If approved, dispatch status change notification
        # NOTE: APPLICATION_* events are legacy aliases for AdmissionProfile operations
        if result["status"] == "approved":
            await safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "old_status": "submitted",
                    "new_status": "approved",
                    "officer_id": current_user.id,
                    "actor_id": current_user.id,
                },
                dedupe_key=f"admission_profile_approved:{profile_id}"
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
        profile = await admission_service.upload_document(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            file=file,
            current_user=current_user,
            actual_submission_format=actual_submission_format,
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
        profile = await admission_service.reset_document(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
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
        result = await admission_service.enroll_student(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        # Transaction commit (Router responsibility)
        await db.commit()

        # Dispatch enrollment status change notification
        # NOTE: APPLICATION_* events are legacy aliases for AdmissionProfile operations
        await safe_dispatch(
            db=db,
            event=SystemEvents.APPLICATION_STATUS_CHANGED,
            payload={
                "application_id": profile_id,
                "old_status": "approved",
                "new_status": "enrolled",
                "student_id": result["student_id"],
                "student_code": result["student_code"],
                "officer_id": current_user.id,
                "actor_id": current_user.id,
            },
            dedupe_key=f"student_enrolled:{result['student_id']}"
        )

        # Dispatch LEAD_STATUS_CHANGED for commission trigger (Path 4)
        # Query lead_id from the profile
        profile = await db.get(models.AdmissionProfile, profile_id)
        if profile and profile.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "officer_id": current_user.id,
                    "old_status": "confirmed",
                    "new_status": "sts11",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts11",
            )

            # Commission check (Path 4 - enrollment)
            await safe_check_commission_on_status_change(
                db, profile.lead_id, "confirmed", "sts11", current_user.id,
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
        await admission_service.delete_profile(
            db=db,
            profile_id=profile_id,
            current_user=current_user,
        )

        # Transaction commit
        await db.commit()

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
    profile_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get application fee status for an admission profile.

    Returns:
    - requires_fee: Whether this profile requires application fee
    - fee_amount: Fee amount in VND
    - fee_status: "exempt" | "pending" | "paid"
    - can_approve: Whether profile can be approved (fee paid or exempt)
    """
    try:
        result = await admission_service.check_application_fee_status(
            db=db,
            profile_id=profile_id,
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

    try:
        # 1. DELEGATE to Service (Service handles Locking + IDOR)
        result, callback = await admission_service.approve_profile(
            db=db,
            profile_id=profile_id,  # Pass ID, not object
            approver=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT Side Effects
        await callback()

        # 4. Dispatch LEAD_STATUS_CHANGED for commission trigger (Path 4 - approve)
        if result.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": result.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "officer_id": current_user.id,
                    "old_status": "submitted",
                    "new_status": "sts09",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"lead_status_changed:{result.lead_id}:sts09",
            )

            # Commission check (Path 4 - approve)
            await safe_check_commission_on_status_change(
                db, result.lead_id, "submitted", "sts09", current_user.id,
            )

        # 5. RETURN Pydantic Model
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
        # 1. DELEGATE to Service (Service handles Locking + IDOR)
        result, callback = await admission_service.reject_profile(
            db=db,
            profile_id=profile_id, # Pass ID
            rejector=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT Side Effects
        await callback()

        # 4. Dispatch LEAD_STATUS_CHANGED for commission trigger (Path 4 - reject)
        if result.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": result.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "officer_id": current_user.id,
                    "old_status": "submitted",
                    "new_status": "sts16",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"lead_status_changed:{result.lead_id}:sts16",
            )

            # Commission check (Path 4 - reject)
            await safe_check_commission_on_status_change(
                db, result.lead_id, "submitted", "sts16", current_user.id,
            )

        # 5. RETURN Pydantic Model
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

        await callback()

        # Dispatch LEAD_STATUS_CHANGED for commission trigger
        if result.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": result.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "officer_id": current_user.id,
                    "old_status": "submitted",
                    "new_status": "sts17",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"lead_status_changed:{result.lead_id}:sts17",
            )

            await safe_check_commission_on_status_change(
                db, result.lead_id, "submitted", "sts17", current_user.id,
            )

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
    - From: REJECTED
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
        # 1. DELEGATE to Service
        result, callback = await admission_service.resubmit_profile(
            db=db,
            profile_id=profile_id, # Pass ID
            officer=current_user,
            data=data.model_dump(),
        )

        # 2. COMMIT Transaction
        await db.commit()
        await db.refresh(result)

        # 3. POST-COMMIT Side Effects
        await callback()

        # 4. RETURN Pydantic Model
        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ==============================================================================
# DEPRECATED: confirm_enrollment endpoint
# ==============================================================================
# 
# The old /{profile_id}/confirm endpoint has been REMOVED.
# Confirmation is now done via Magic Link + CCCD verification:
# 
# - GET /api/admissions/confirm/{token}  (public - get token info)
# - POST /api/admissions/confirm/{token} (public - verify CCCD & confirm)
# 
# See: implementation_plan.md (Magic Link + CCCD Verification)
#


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
    - version: Optional version for optimistic locking

    **Returns:**
    - Updated AdmissionProfile with status='overridden'

    **Errors:**
    - 400: Invalid state transition, version mismatch, or invalid reason
    - 404: Profile not found (or IDOR protection)
    """
    try:
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

        # 4. RETURN Pydantic Model
        return result

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
    - version: Optional version for optimistic locking

    **Returns:**
    - Updated AdmissionProfile with status='enrolled'

    **Errors:**
    - 400: Invalid state transition or version mismatch
    - 404: Profile not found (or IDOR protection)
    """
    try:
        # 1. DELEGATE to Service
        result, callback = await admission_service.finalize_profile(
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

        # 4. RETURN Pydantic Model
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
        
        # 4. RETURN Response
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
        return schemas.SendConfirmationResponse(
            message="Đường link xác nhận đã được gửi thành công!",
            token_expires_at=token_obj.expires_at,
            sent_to_email=lead.email if lead else None,
            sent_to_phone=lead.phone if lead else None,
            token_value=token_obj.token,
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

        await callback()

        # Dispatch LEAD_STATUS_CHANGED for commission trigger
        if result.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": result.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "officer_id": current_user.id,
                    "old_status": "sts11",
                    "new_status": "sts12",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"lead_status_changed:{result.lead_id}:sts12",
            )

            await safe_check_commission_on_status_change(
                db, result.lead_id, "sts11", "sts12", current_user.id,
            )

        return result

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
