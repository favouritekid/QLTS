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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address
import structlog

from .. import database, models, schemas
from ..core import deps
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

# Dependencies
PermissionDep = Depends(deps.check_permission)

# Rate Limiter (for enroll endpoint)
limiter = Limiter(key_func=get_remote_address)


# ==============================================================================
# ENDPOINTS
# ==============================================================================

@router.post(
    "",
    response_model=schemas.AdmissionProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create admission profile for lead",
)
async def create_admission_profile(
    data: schemas.AdmissionProfileCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
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
        # Service layer handles business logic
        profile = await admission_service.create_profile(
            db=db,
            lead_id=data.lead_id,
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


@router.get(
    "/{profile_id}",
    response_model=schemas.AdmissionProfileResponse,
    summary="Get admission profile by ID",
)
async def get_admission_profile(
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
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


@router.put(
    "/{profile_id}",
    response_model=schemas.AdmissionProfileResponse,
    summary="Update admission profile (draft only)",
)
async def update_admission_profile(
    profile_id: int,
    data: schemas.AdmissionProfileUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
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


@router.post(
    "/{profile_id}/submit",
    response_model=schemas.AdmissionSubmitResponse,
    summary="Submit admission profile for evaluation",
)
async def submit_admission_profile(
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
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


@router.post(
    "/{profile_id}/enroll",
    response_model=schemas.EnrollStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll student (ACID transaction)",
)
@limiter.limit("10/minute")  # Rate limiting: 10 requests per minute
async def enroll_student(
    request: Request,  # Required for rate limiter
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
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
