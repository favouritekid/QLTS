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

from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models, schemas
from ..core.deps import (
    CasbinAuth,  # ✅ Phase 2.2: Use standard alias
    get_admission_for_manager,
    get_admission_for_user,
    # get_admission_for_owner - DEPRECATED: Replaced by token-based confirmation
)
from ..services import admission_service
from ..services.notification_dispatcher import dispatch
from ..core.events import SystemEvents
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    PermissionDeniedError,
    ConflictError,
)

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
    response_model=list[schemas.AdmissionProfileResponse],
    summary="List admission profiles",
)
async def list_admission_profiles(
    request: Request,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List AdmissionProfiles accessible to current user.

    **Security:**
    - Admin: Can see all profiles
    - Officer: Only profiles where lead.unit_id == user.unit_id

    **Query Parameters:**
    - status: Filter by status (draft, approved, rejected, enrolled)
    - skip: Pagination offset (default: 0)
    - limit: Page size (default: 50, max: 100)

    **Returns:**
    - List of AdmissionProfiles with relationships
    """
    profiles = await admission_service.get_profiles(
        db=db,
        skip=skip,
        limit=limit,
        status_filter=status,
        current_user=current_user,
    )
    
    return profiles


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
    - 404: Lead or ProgramOffering not found
    - 403: User doesn't have access to this lead
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
        try:
            await dispatch(
                db=db,
                event=SystemEvents.APPLICATION_CREATED,  # Reuse application event
                payload={
                    "application_id": profile.id,  # Use profile.id
                    "lead_id": profile.lead_id,
                    "officer_id": current_user.id,
                    "major_program_name": None,
                    "actor_id": current_user.id,
                },
                dedupe_key=f"admission_profile_created:{profile.id}"
            )
        except Exception as e:
            log.warning(
                "Failed to dispatch admission profile created notification",
                profile_id=profile.id,
                error=str(e)
            )

        return profile

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
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
    - 404: Profile not found
    - 403: User doesn't have access to this profile
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
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
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
    - 404: Profile not found
    - 403: User doesn't have access to this profile
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
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
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
    - 404: Profile not found
    - 403: User doesn't have access
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

        # If approved, dispatch notification
        if result["status"] == "approved":
            try:
                await dispatch(
                    db=db,
                    event=SystemEvents.APPLICATION_CREATED,  # Reuse event
                    payload={
                        "application_id": profile_id,
                        "lead_id": None,  # Will be fetched by resolver
                        "officer_id": current_user.id,
                        "status": "approved",
                        "actor_id": current_user.id,
                    },
                    dedupe_key=f"admission_profile_approved:{profile_id}"
                )
            except Exception as e:
                log.warning(
                    "Failed to dispatch admission approved notification",
                    profile_id=profile_id,
                    error=str(e)
                )

        return result

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/upload",
    response_model=schemas.DocumentUploadResponse,
    summary="Upload admission document",
    status_code=status.HTTP_200_OK,
)
async def upload_document(
    request: Request,
    profile_id: int,
    doc_code: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Upload a document for an admission profile.
    
    File will be saved and the checklist item status updated to 'uploaded'.
    """
    try:
        updated_doc, post_commit = await admission_service.upload_document(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            file=file,
            current_user=current_user,
        )
        await db.commit()
        await post_commit()
        return updated_doc

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{profile_id}/documents/{doc_code}/paper-submitted",
    response_model=dict,
    summary="Mark document as paper submitted (Officer confirms receipt)",
    status_code=status.HTTP_200_OK,
)
async def mark_document_paper_submitted(
    request: Request,
    profile_id: int,
    doc_code: str,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Mark a document as paper submitted (officer confirms receipt).
    
    For documents where requires_upload=false.
    Only officers/managers/admins can mark paper submitted.
    
    **Returns:**
    - { code, status, paper_submitted_at, paper_submitted_by_id }
    """
    try:
        result, post_commit = await admission_service.mark_paper_submitted(
            db=db,
            profile_id=profile_id,
            doc_code=doc_code,
            current_user=current_user,
        )
        await db.commit()
        await post_commit()
        return result

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
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
    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
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
    1. Generate unique student_code (SV + YYYY + 4-digit random)
    2. Create Student record
    3. Create StudentDocument records (from documents_checklist)
    4. Update AdmissionProfile.status = 'enrolled'
    5. Update Lead.status = 'converted'

    **Security:**
    - IDOR: Only accessible to users in same unit
    - State Check: Only approved profiles can be enrolled
    - Rate Limiting: 10 requests/minute (prevent brute-force student_code)

    **Returns:**
    - { student_id, student_code, enrollment_date }

    **Errors:**
    - 404: Profile not found
    - 403: User doesn't have access
    - 400: Profile is not approved
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

        # Dispatch notification (non-blocking)
        try:
            await dispatch(
                db=db,
                event=SystemEvents.APPLICATION_CREATED,  # Reuse event
                payload={
                    "application_id": profile_id,
                    "student_id": result["student_id"],
                    "student_code": result["student_code"],
                    "lead_id": None,
                    "officer_id": current_user.id,
                    "status": "enrolled",
                    "actor_id": current_user.id,
                },
                dedupe_key=f"student_enrolled:{result['student_id']}"
            )
        except Exception as e:
            log.warning(
                "Failed to dispatch student enrolled notification",
                student_id=result["student_id"],
                error=str(e)
            )

        return result

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
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
    - 404: Profile not found
    - 403: User doesn't have access to this profile
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
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ==============================================================================
# STATE MACHINE ENDPOINTS (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
# ==============================================================================

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
    current_user: models.User = CasbinAuth,  # Layer 2: RBAC (Manager/Admin)
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # Layer 3: IDOR
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
    try:
        # 1. DELEGATE to Service
        result, callback = await admission_service.approve_profile(
            db=db,
            profile=profile,
            approver=current_user,
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
    "/{profile_id}/reject",
    response_model=schemas.AdmissionProfileResponse,
    summary="Reject admission profile (Manager/Admin)",
)
async def reject_admission(
    request: Request,
    profile_id: int,
    data: schemas.RejectRequest,
    current_user: models.User = CasbinAuth,  # Layer 2: RBAC (Manager/Admin)
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),  # Layer 3: IDOR
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
    - Optimistic locking via version check
    - Rejection reason required (min 10 chars, XSS sanitized)

    **Request Body:**
    - reason: Rejection reason (REQUIRED, min 10 chars, max 1000)
    - version: Optional version for optimistic locking

    **Returns:**
    - Updated AdmissionProfile with status='rejected'

    **Errors:**
    - 400: Invalid state transition, version mismatch, or invalid reason
    - 404: Profile not found (or IDOR protection)
    """
    try:
        # 1. DELEGATE to Service
        result, callback = await admission_service.reject_profile(
            db=db,
            profile=profile,
            rejector=current_user,
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
    "/{profile_id}/resubmit",
    response_model=schemas.AdmissionProfileResponse,
    summary="Resubmit admission profile after rejection (Officer)",
)
async def resubmit_admission(
    request: Request,
    profile_id: int,
    data: schemas.ResubmitRequest,
    current_user: models.User = CasbinAuth,  # Layer 2: RBAC (Officer/Admin)
    profile: models.AdmissionProfile = Depends(get_admission_for_user),  # Layer 3: IDOR
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
    - Optimistic locking via version check
    - Resubmit notes required (min 10 chars, XSS sanitized)

    **Request Body:**
    - notes: Resubmission notes explaining what was fixed (REQUIRED, min 10 chars)
    - version: Optional version for optimistic locking

    **Returns:**
    - Updated AdmissionProfile with status='resubmitted'

    **Errors:**
    - 400: Invalid state transition, version mismatch, or invalid notes
    - 404: Profile not found (or IDOR protection)
    """
    try:
        # 1. DELEGATE to Service
        result, callback = await admission_service.resubmit_profile(
            db=db,
            profile=profile,
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
async def get_confirm_token_info(
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
        )
    
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
