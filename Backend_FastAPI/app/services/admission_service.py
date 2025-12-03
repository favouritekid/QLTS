# app/services/admission_service.py
"""
Admission Service - Business logic for AdmissionProfile workflow.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks in ALL functions (lead.unit_id == user.unit_id)
- Transactions: Services use db.add()/db.flush(), Router commits via db.commit()
- Performance: selectinload/joinedload to prevent N+1 queries
- Error Handling: Raise custom exceptions (ResourceNotFoundError, BadRequest, etc.)

Workflow:
1. CREATE: Officer creates profile -> snapshot admission_rules from ProgramOffering
2. UPDATE: Officer updates profile (only when status = 'draft')
3. SUBMIT: System validates against applied_rules -> auto-approve or return errors
4. ENROLL: System creates Student + StudentDocument (ACID transaction)

Security Features:
- IDOR Protection: All functions check lead.unit_id == current_user.unit_id (unless admin)
- Snapshot Pattern: Validation uses applied_rules (never queries ProgramOffering)
- State Locking: Updates only allowed when status = 'draft'
- ACID Transactions: enroll_student uses begin_nested() savepoint
"""

import random
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import structlog
from sqlalchemy import select

from app.utils.redis_lock import acquire_redis_lock
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from .. import models
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    PermissionDeniedError,
    ConflictError,
)

log = structlog.get_logger(__name__)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _check_admin_or_unit_access(
    profile: models.AdmissionProfile,
    current_user: models.User
) -> None:
    """
    IDOR Protection: Check if user has access to this admission profile.

    Rules:
    - Admin: Full access to all profiles
    - Officer: Only access profiles where lead.unit_id == user.unit_id

    Raises:
        PermissionDeniedError: If user doesn't have access
    """
    if current_user.role == "admin":
        return  # Admin has full access

    if profile.lead.unit_id != current_user.unit_id:
        log.warning(
            "IDOR attempt: User tried to access profile from different unit",
            user_id=current_user.id,
            user_unit_id=current_user.unit_id,
            profile_id=profile.id,
            profile_unit_id=profile.lead.unit_id,
        )
        raise PermissionDeniedError(
            "You don't have permission to access this admission profile"
        )


def _generate_documents_checklist(mandatory_docs: List[str]) -> List[Dict[str, Any]]:
    """
    Generate documents_checklist from mandatory_docs list.

    Args:
        mandatory_docs: List of document codes (e.g., ["HOC_BA", "CCCD", "BANG_TN"])

    Returns:
        List of document items with status='missing'
    """
    # Document label mapping (can be moved to config later)
    doc_labels = {
        "HOC_BA": "Học bạ THPT",
        "CCCD": "Căn cước công dân",
        "BANG_TN": "Bằng tốt nghiệp THPT",
        "CMND": "Chứng minh nhân dân",
        "GIAY_KHAI_SINH": "Giấy khai sinh",
        "ANH_3X4": "Ảnh 3x4 (6 tấm)",
        "GIAY_KHAM_SUC_KHOE": "Giấy khám sức khỏe",
    }

    checklist = []
    for doc_code in mandatory_docs:
        checklist.append({
            "code": doc_code,
            "label": doc_labels.get(doc_code, doc_code),
            "status": "missing",
            "file_path": None,
            "uploaded_at": None,
        })

    return checklist


# ==============================================================================
# CRUD FUNCTIONS
# ==============================================================================

async def create_profile(
    db: AsyncSession,
    lead_id: int,
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Create new AdmissionProfile for a Lead.

    Workflow:
    1. Validate Lead exists and user has access (IDOR check)
    2. Check Lead has offering_id (required for admission_rules)
    3. Check Lead doesn't already have admission_profile
    4. Snapshot admission_rules from ProgramOffering
    5. Auto-generate documents_checklist from mandatory_docs
    6. Create AdmissionProfile with status='draft'

    Security:
    - IDOR: Lead.unit_id must equal current_user.unit_id
    - Business Rule: Lead.offering_id must not be null
    - Uniqueness: Lead can only have one admission_profile

    Args:
        db: Database session
        lead_id: Lead ID
        current_user: Current authenticated user

    Returns:
        Created AdmissionProfile

    Raises:
        ResourceNotFoundError: Lead or ProgramOffering not found
        PermissionDeniedError: User doesn't have access to this lead
        BadRequest: Lead already has profile, or offering_id is null, or no admission_rules
    """
    # Step 1: Get Lead with eager loading (prevent N+1)
    stmt = (
        select(models.Lead)
        .where(models.Lead.id == lead_id)
        .options(
            joinedload(models.Lead.offering),  # Load ProgramOffering
            selectinload(models.Lead.admission_profile),  # Check existing profile
        )
    )
    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()

    if not lead:
        log.warning("Lead not found", lead_id=lead_id, user_id=current_user.id)
        raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")

    # Step 2: IDOR Check
    if current_user.role != "admin":
        if lead.unit_id != current_user.unit_id:
            log.warning(
                "IDOR attempt: User tried to create profile for lead in different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                lead_id=lead_id,
                lead_unit_id=lead.unit_id,
            )
            raise PermissionDeniedError(
                "You don't have permission to create admission profile for this lead"
            )

    # Step 3: Check Lead has offering_id
    if not lead.offering_id:
        log.warning(
            "Lead has no offering_id (required for admission rules)",
            lead_id=lead_id,
        )
        raise BadRequest(
            "Lead must have a program offering assigned before creating admission profile"
        )

    # Step 4: Check Lead doesn't already have admission_profile
    if lead.admission_profile:
        log.warning(
            "Lead already has admission profile",
            lead_id=lead_id,
            existing_profile_id=lead.admission_profile.id,
        )
        raise BadRequest(
            f"Lead already has an admission profile (ID: {lead.admission_profile.id})"
        )

    # Step 5: Snapshot admission_rules from ProgramOffering
    if not lead.offering:
        log.error(
            "ProgramOffering not found (data integrity issue)",
            lead_id=lead_id,
            offering_id=lead.offering_id,
        )
        raise ResourceNotFoundError(
            f"Program offering {lead.offering_id} not found"
        )

    admission_rules = lead.offering.admission_rules
    if not admission_rules:
        log.warning(
            "ProgramOffering has no admission_rules configured",
            offering_id=lead.offering_id,
        )
        raise BadRequest(
            "Program offering has no admission rules configured. "
            "Please contact administrator."
        )

    # Step 6: Auto-generate documents_checklist
    mandatory_docs = admission_rules.get("mandatory_docs", [])
    documents_checklist = _generate_documents_checklist(mandatory_docs)

    # Step 7: Create AdmissionProfile
    new_profile = models.AdmissionProfile(
        lead_id=lead_id,
        status="draft",
        applied_rules=admission_rules,  # Snapshot (immutable)
        family_info=[],
        academic_history=[],
        admission_scores=None,
        documents_checklist=documents_checklist,
    )

    db.add(new_profile)
    await db.flush()  # Get ID without committing (router commits)

    # Reload with relationships for response
    stmt_reload = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == new_profile.id)
        .options(
            joinedload(models.AdmissionProfile.lead),
        )
    )
    result_reload = await db.execute(stmt_reload)
    new_profile = result_reload.scalar_one()

    log.info(
        "Admission profile created",
        profile_id=new_profile.id,
        lead_id=lead_id,
        user_id=current_user.id,
        snapshot_min_gpa=admission_rules.get("min_gpa"),
        mandatory_docs_count=len(mandatory_docs),
    )

    return new_profile


async def get_profile(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Get AdmissionProfile by ID.

    Security:
    - IDOR: Check lead.unit_id == user.unit_id (unless admin)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        current_user: Current authenticated user

    Returns:
        AdmissionProfile with relationships loaded

    Raises:
        ResourceNotFoundError: Profile not found
        PermissionDeniedError: User doesn't have access
    """
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            joinedload(models.AdmissionProfile.lead),  # Always load for IDOR check
            selectinload(models.AdmissionProfile.student),
        )
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        log.warning("Admission profile not found", profile_id=profile_id)
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check
    _check_admin_or_unit_access(profile, current_user)

    log.debug(
        "Admission profile retrieved",
        profile_id=profile_id,
        user_id=current_user.id,
        status=profile.status,
    )

    return profile


async def update_profile(
    db: AsyncSession,
    profile_id: int,
    data: Dict[str, Any],
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Update AdmissionProfile (only when status='draft').

    Security:
    - IDOR: Check lead.unit_id == user.unit_id
    - State Locking: Only allow updates when status='draft'

    Performance:
    - Uses selectinload to prevent N+1 queries

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        data: Update data (from AdmissionProfileUpdate schema)
        current_user: Current authenticated user

    Returns:
        Updated AdmissionProfile

    Raises:
        ResourceNotFoundError: Profile not found
        PermissionDeniedError: User doesn't have access
        BadRequest: Status is not 'draft'
    """
    # Get profile with IDOR check
    profile = await get_profile(db, profile_id, current_user)

    # State Locking: Only draft profiles can be updated
    if profile.status != "draft":
        log.warning(
            "Attempted to update non-draft profile",
            profile_id=profile_id,
            current_status=profile.status,
            user_id=current_user.id,
        )
        raise BadRequest(
            f"Cannot update profile with status '{profile.status}'. "
            "Only draft profiles can be updated."
        )

    # Optimistic Locking: Check version matches
    if "version" in data and data["version"] != profile.version:
        log.warning(
            "Version mismatch during update (concurrent modification)",
            profile_id=profile_id,
            expected_version=data["version"],
            current_version=profile.version,
            user_id=current_user.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # Update fields (only non-None values from schema)
    if "citizen_id" in data and data["citizen_id"] is not None:
        profile.citizen_id = data["citizen_id"]

    if "family_info" in data and data["family_info"] is not None:
        profile.family_info = [member.model_dump() for member in data["family_info"]]

    if "academic_history" in data and data["academic_history"] is not None:
        profile.academic_history = [record.model_dump() for record in data["academic_history"]]

    if "admission_scores" in data and data["admission_scores"] is not None:
        profile.admission_scores = data["admission_scores"].model_dump()

    if "documents_checklist" in data and data["documents_checklist"] is not None:
        profile.documents_checklist = [doc.model_dump() for doc in data["documents_checklist"]]

    # Update timestamp and increment version
    profile.updated_at = datetime.now(timezone.utc)
    profile.version += 1

    await db.flush()  # Router commits

    log.info(
        "Admission profile updated",
        profile_id=profile_id,
        user_id=current_user.id,
        updated_fields=list(data.keys()),
    )

    return profile


async def submit_and_evaluate(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Dict[str, Any]:
    """
    Submit AdmissionProfile for evaluation (auto-approve or return errors).

    Validation Rules (against SNAPSHOT applied_rules):
    1. admission_scores.gpa >= applied_rules.min_gpa
    2. All mandatory_docs have status='uploaded' and file_path not null
    3. citizen_id is unique across admission_profile and student tables
    4. JSON structures are valid (already validated by Pydantic)

    Security:
    - IDOR: Check lead.unit_id == user.unit_id
    - Snapshot: Use applied_rules ONLY (never query ProgramOffering)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        current_user: Current authenticated user

    Returns:
        Dict with:
        - status: "approved" or "rejected"
        - message: Success message (if approved)
        - errors: List of error messages (if rejected)

    Raises:
        ResourceNotFoundError: Profile not found
        PermissionDeniedError: User doesn't have access
        BadRequest: Status is not 'draft'
    """
    # Get profile with IDOR check
    profile = await get_profile(db, profile_id, current_user)

    # Must be in draft status
    if profile.status != "draft":
        raise BadRequest(
            f"Cannot submit profile with status '{profile.status}'. "
            "Only draft profiles can be submitted."
        )

    errors: List[str] = []

    # Get applied_rules (snapshot)
    applied_rules = profile.applied_rules
    min_gpa = applied_rules.get("min_gpa")
    mandatory_docs = applied_rules.get("mandatory_docs", [])

    # Validation 1: Check GPA
    if not profile.admission_scores:
        errors.append("Điểm thi chưa được nhập (admission_scores is null)")
    else:
        gpa = profile.admission_scores.get("gpa")
        if gpa is None:
            errors.append("GPA chưa được nhập")
        elif min_gpa is not None and gpa < min_gpa:
            errors.append(
                f"GPA ({gpa}) không đạt yêu cầu tối thiểu ({min_gpa})"
            )

    # Validation 2: Check mandatory documents
    if not profile.documents_checklist:
        errors.append("Danh sách tài liệu trống (documents_checklist is empty)")
    else:
        uploaded_docs = {
            doc["code"]: doc
            for doc in profile.documents_checklist
            if doc.get("status") == "uploaded" and doc.get("file_path")
        }

        for doc_code in mandatory_docs:
            if doc_code not in uploaded_docs:
                # Find document label from checklist
                doc_item = next(
                    (d for d in profile.documents_checklist if d["code"] == doc_code),
                    None
                )
                label = doc_item["label"] if doc_item else doc_code
                errors.append(f"Thiếu tài liệu bắt buộc: {label} ({doc_code})")

    # Validation 3: Check citizen_id uniqueness
    if not profile.citizen_id:
        errors.append("Số CCCD/CMND chưa được nhập (citizen_id is null)")
    else:
        # Check in admission_profile table (other profiles)
        stmt_profile = select(models.AdmissionProfile).where(
            models.AdmissionProfile.citizen_id == profile.citizen_id,
            models.AdmissionProfile.id != profile.id,  # Exclude current profile
        )
        result_profile = await db.execute(stmt_profile)
        duplicate_profile = result_profile.scalar_one_or_none()

        if duplicate_profile:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi hồ sơ khác "
                f"(ID: {duplicate_profile.id})"
            )

        # Check in student table (already enrolled students)
        # Note: Student table doesn't have citizen_id directly, but we can check
        # via admission_profile_id relationship
        stmt_student = (
            select(models.Student)
            .join(models.AdmissionProfile)
            .where(models.AdmissionProfile.citizen_id == profile.citizen_id)
        )
        result_student = await db.execute(stmt_student)
        existing_student = result_student.scalar_one_or_none()

        if existing_student:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi học viên "
                f"(Mã SV: {existing_student.student_code})"
            )

    # Decision: Approve or Reject
    if errors:
        # Reject
        profile.status = "rejected"
        profile.version += 1  # Increment version on status change
        await db.flush()

        log.warning(
            "Admission profile rejected",
            profile_id=profile_id,
            user_id=current_user.id,
            errors_count=len(errors),
            errors=errors,
        )

        return {
            "status": "rejected",
            "message": None,
            "errors": errors,
        }
    else:
        # Approve
        profile.status = "approved"
        profile.version += 1  # Increment version on status change
        await db.flush()

        log.info(
            "Admission profile approved",
            profile_id=profile_id,
            user_id=current_user.id,
            citizen_id=profile.citizen_id,
            gpa=profile.admission_scores.get("gpa") if profile.admission_scores else None,
        )

        return {
            "status": "approved",
            "message": "Hồ sơ đã được duyệt tự động. Bạn có thể tiến hành nhập học.",
            "errors": None,
        }


async def enroll_student(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Dict[str, Any]:
    """
    Enroll student (create Student + StudentDocument records).

    ACID Transaction Flow:
    1. Get and validate profile (status must be 'approved')
    2. BEGIN SAVEPOINT (via begin_nested)
    3. Generate unique student_code (SV + YYYY + 4-digit random, retry on conflict)
    4. Create Student record
    5. Create StudentDocument records (from documents_checklist)
    6. Update AdmissionProfile.status = 'enrolled'
    7. Update Lead.status = 'converted'
    8. COMMIT SAVEPOINT (auto if no errors)

    On IntegrityError:
    - Savepoint auto-rollback
    - Return 409 Conflict with error message

    Security:
    - IDOR: Check lead.unit_id == user.unit_id
    - State Check: Only approved profiles can be enrolled

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        current_user: Current authenticated user

    Returns:
        Dict with student_id, student_code, enrollment_date

    Raises:
        ResourceNotFoundError: Profile not found
        PermissionDeniedError: User doesn't have access
        BadRequest: Status is not 'approved'
        ConflictError: Unique constraint violation (student_code, citizen_id)
    """
    # Get profile with IDOR check
    profile = await get_profile(db, profile_id, current_user)

    # Must be in approved status
    if profile.status != "approved":
        raise BadRequest(
            f"Cannot enroll student with profile status '{profile.status}'. "
            "Only approved profiles can be enrolled."
        )

    # ACID Transaction with Savepoint
    try:
        async with db.begin_nested():  # Savepoint (not full transaction)
            # Step 1: Generate unique student_code with distributed lock
            year = datetime.now(timezone.utc).year
            student_code = None

            # Redis distributed lock to prevent concurrent generation collisions
            async with acquire_redis_lock(
                key=f"student_code_gen:{year}",
                timeout=10,
                max_retries=50
            ) as lock_acquired:
                if not lock_acquired:
                    log.error(
                        "Failed to acquire lock for student_code generation",
                        profile_id=profile_id,
                        year=year
                    )
                    raise ConflictError(
                        "Too many concurrent enrollment requests. Please try again in a few seconds."
                    )

                for attempt in range(10):  # Retry up to 10 times
                    random_digits = random.randint(0, 9999)
                    candidate_code = f"SV{year}{random_digits:04d}"

                    # Check uniqueness
                    stmt_check = select(models.Student).where(
                        models.Student.student_code == candidate_code
                    )
                    existing = (await db.execute(stmt_check)).scalar_one_or_none()

                    if not existing:
                        student_code = candidate_code
                        break

                if not student_code:
                    log.error(
                        "Failed to generate unique student_code after 10 attempts",
                        profile_id=profile_id,
                    )
                    raise BadRequest(
                        "Cannot generate unique student code. Please try again."
                    )

            # Step 2: Create Student
            student = models.Student(
                admission_profile_id=profile.id,
                student_code=student_code,
                enrollment_date=datetime.now(timezone.utc),
            )
            db.add(student)
            await db.flush()  # Get student.id

            # Step 3: Create StudentDocument records
            for doc_item in profile.documents_checklist:
                if doc_item.get("status") == "uploaded" and doc_item.get("file_path"):
                    # Parse uploaded_at safely (prevent ValueError on invalid ISO format)
                    uploaded_at = datetime.now(timezone.utc)
                    if doc_item.get("uploaded_at"):
                        try:
                            uploaded_at = datetime.fromisoformat(doc_item["uploaded_at"])
                        except (ValueError, TypeError):
                            # Invalid format, use current time
                            log.warning(
                                "Invalid uploaded_at format, using current time",
                                doc_code=doc_item.get("code"),
                                uploaded_at_value=doc_item.get("uploaded_at"),
                            )
                            uploaded_at = datetime.now(timezone.utc)

                    doc = models.StudentDocument(
                        student_id=student.id,
                        doc_type=doc_item["code"],
                        file_path=doc_item["file_path"],
                        is_verified=False,  # Default: pending verification
                        uploaded_at=uploaded_at,
                    )
                    db.add(doc)

            # Step 4: Update AdmissionProfile status
            profile.status = "enrolled"
            profile.updated_at = datetime.now(timezone.utc)
            profile.version += 1  # Increment version on enrollment

            # Step 5: Update Lead status
            profile.lead.status = "converted"
            profile.lead.updated_at = datetime.now(timezone.utc)

            await db.flush()
            # Savepoint auto-commits here if no errors

        log.info(
            "Student enrolled successfully",
            student_id=student.id,
            student_code=student.student_code,
            profile_id=profile_id,
            lead_id=profile.lead_id,
            user_id=current_user.id,
        )

        return {
            "student_id": student.id,
            "student_code": student.student_code,
            "enrollment_date": student.enrollment_date,
        }

    except IntegrityError as e:
        # Savepoint auto-rollback
        error_msg = str(e.orig)

        log.error(
            "Enrollment failed due to integrity error",
            profile_id=profile_id,
            error=error_msg,
        )

        # Parse error message
        if "student_code" in error_msg.lower():
            raise ConflictError(
                f"Student code {student_code} already exists"
            )
        elif "citizen_id" in error_msg.lower():
            raise ConflictError(
                f"Citizen ID {profile.citizen_id} is already enrolled"
            )
        else:
            raise ConflictError(
                "Enrollment failed due to data conflict. Please try again."
            )
