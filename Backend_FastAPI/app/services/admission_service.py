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
from ..core.constants import UserRole
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
    if current_user.role == UserRole.ADMIN:
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
    5. Initialize ProfileDocument records from mandatory_docs
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
    # ✅ SPRINT 6: Use Repository for lead lookup
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    
    # Step 1: Get Lead with eager loading (prevent N+1)
    lead = await admission_repo.get_lead_with_offering(lead_id)

    if not lead:
        log.warning("Lead not found", lead_id=lead_id, user_id=current_user.id)
        raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")

    # Step 2: IDOR Check
    if current_user.role != UserRole.ADMIN:
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

    admission_rules = lead.offering.admission_rules or {}
    if not admission_rules:
        log.warning(
            "ProgramOffering has no admission_rules configured",
            offering_id=lead.offering_id,
        )
        # Don't raise error - we can still create profile with empty rules
        # This allows for profiles to be created before rules are fully configured
        admission_rules = {}
    
    # Step 5.1: Phase 6 - Include admission_criteria from OfferingAcademicInfo
    # OfferingAcademicInfo contains year-specific criteria (Level 3)
    # ⚠️ Use repository method to avoid MissingGreenlet (lazy loading in async)
    criteria = []
    from app.repositories import OrganizationRepository
    org_repo = OrganizationRepository(db)
    academic_info_list = await org_repo.get_academic_info_history(
        lead.offering_id, 
        published_only=False
    )
    
    if academic_info_list:
        # Get the first published, or fallback to most recent
        academic_info = next(
            (info for info in academic_info_list if info.is_published),
            academic_info_list[0] if academic_info_list else None
        )
        if academic_info and academic_info.admission_criteria:
            criteria = academic_info.admission_criteria
            log.info(
                "Snapshotting admission_criteria from OfferingAcademicInfo",
                offering_id=lead.offering_id,
                academic_year=academic_info.academic_year,
                criteria_count=len(criteria),
            )
    
    # Merge criteria into applied_rules for backward compatibility + new features
    applied_rules = {
        **admission_rules,
        "criteria": criteria,  # New: dynamic admission methods
    }

    # Step 6: Collect mandatory document codes
    mandatory_docs = applied_rules.get("mandatory_docs", [])

    # Also collect mandatory docs from criteria (if any)
    for criterion in criteria:
        required_docs = criterion.get("required_documents", [])
        for doc in required_docs:
            doc_code = doc.get("code") if isinstance(doc, dict) else doc
            if doc_code and doc_code not in mandatory_docs:
                mandatory_docs.append(doc_code)

    # Step 7: Create AdmissionProfile
    new_profile = models.AdmissionProfile(
        lead_id=lead_id,
        status="draft",
        applied_rules=applied_rules,  # Snapshot (immutable) with criteria
        family_info=[],
        academic_history=[],
        # Pre-fill from Lead
        full_name=lead.full_name,
        phone=lead.phone,
        email=lead.email,
    )

    db.add(new_profile)
    await db.flush()  # Get ID without committing (router commits)

    # Step 8: Initialize ProfileDocument records (replaces JSONB checklist)
    await admission_repo.initialize_documents_for_profile(
        profile_id=new_profile.id,
        document_type_codes=mandatory_docs
    )

    # ✅ SPRINT 6: Reload with relationships for response
    new_profile = await admission_repo.reload_profile_with_lead(new_profile.id)

    # Calculate totals for response
    _calculate_and_update_totals(new_profile)

    log.info(
        "Admission profile created",
        profile_id=new_profile.id,
        lead_id=lead_id,
        user_id=current_user.id,
        snapshot_min_gpa=applied_rules.get("min_gpa"),
        criteria_count=len(criteria),
        mandatory_docs_count=len(mandatory_docs),
    )

    return new_profile



async def get_profiles(
    db: AsyncSession,
    skip: int,
    limit: int,
    status_filter: Optional[str],
    current_user: models.User,
) -> List[models.AdmissionProfile]:
    """
    Get filtered list of admission profiles.

    Security:
    - IDOR: Automatically filters by unit_id for non-admin users.

    Args:
        db: Database session
        skip: Pagination offset
        limit: Page size
        status_filter: Optional status filter
        current_user: Current authenticated user

    Returns:
        List of AdmissionProfile
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Build filters
    filters = {}
    if status_filter:
        filters["status"] = status_filter

    # IDOR: Pass unit_id to repository for non-admin users (DB-level filter)
    unit_filter = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    # Get profiles using repository
    profiles = await admission_repo.get_filtered(
        skip=skip,
        limit=min(limit, 100),
        unit_id=unit_filter,
        **filters
    )

    return profiles


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
    # ✅ SPRINT 6: Use Repository for profile retrieval
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    
    profile = await admission_repo.get_profile_by_id_with_lead(profile_id)

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

    # Calculate totals for response
    _calculate_and_update_totals(profile)

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

    # Initialize Repo
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # State Locking: Only draft or rejected profiles can be updated
    if profile.status not in ["draft", "rejected"]:
        log.warning(
            "Attempted to update locked profile",
            profile_id=profile_id,
            current_status=profile.status,
            user_id=current_user.id,
        )
        raise BadRequest(
            f"Cannot update profile with status '{profile.status}'. "
            "Only draft or rejected profiles can be updated."
        )
    
    # If profile is rejected, reset to draft on update
    if profile.status == "rejected":
        profile.status = "draft"

    # Optimistic Locking: Check version matches
    if data.get("version") is not None and data["version"] != profile.version:
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
    # Update fields (only non-None values from schema)
    if "citizen_id" in data and data["citizen_id"] is not None:
        profile.citizen_id = data["citizen_id"]

    # ✅ Sync with Lead: Full Name
    if "full_name" in data and data["full_name"] is not None:
        profile.full_name = data["full_name"]
        if profile.lead and data["full_name"].strip():
            profile.lead.full_name = data["full_name"]

    # ✅ Sync with Lead: Phone
    if "phone" in data and data["phone"] is not None:
        profile.phone = data["phone"]
        if profile.lead and data["phone"].strip():
            profile.lead.phone = data["phone"]

    # ✅ Sync with Lead: Email
    if "email" in data and data["email"] is not None:
        profile.email = data["email"]
        if profile.lead:
            profile.lead.email = data["email"]
    
    # Other fields
    if "dob" in data and data["dob"] is not None:
        profile.dob = data["dob"]
    
    if "gender" in data and data["gender"] is not None:
        profile.gender = data["gender"]
        
    if "permanent_province" in data: profile.permanent_province = data["permanent_province"]
    if "permanent_district" in data: profile.permanent_district = data["permanent_district"]
    if "permanent_ward" in data: profile.permanent_ward = data["permanent_ward"]
    if "place_of_birth" in data: profile.place_of_birth = data["place_of_birth"]
    if "native_place" in data: profile.native_place = data["native_place"]
    if "social_insurance_number" in data: profile.social_insurance_number = data["social_insurance_number"]
    if "nationality" in data: profile.nationality = data["nationality"]
    if "ethnicity" in data: profile.ethnicity = data["ethnicity"]
    if "religion" in data: profile.religion = data["religion"]
    if "disability_type" in data: profile.disability_type = data["disability_type"]
    
    # Political date fields
    if "union_entry_date" in data: profile.union_entry_date = data["union_entry_date"]
    if "party_entry_date" in data: profile.party_entry_date = data["party_entry_date"]
    if "party_official_entry_date" in data: profile.party_official_entry_date = data["party_official_entry_date"]

    if "family_info" in data and data["family_info"] is not None:
        profile.family_info = data["family_info"]

    if "academic_history" in data and data["academic_history"] is not None:
        profile.academic_history = data["academic_history"]

    # ✅ Phase 6: Update Admission Scores
    if "admission_scores" in data and data["admission_scores"] is not None:
        # Extract subject scores map from Pydantic model dict
        # data["admission_scores"] is a dict (from model_dump)
        scores_data = data["admission_scores"]
        
        # Handle subject_scores
        if "subject_scores" in scores_data and scores_data["subject_scores"]:
            subject_scores = scores_data["subject_scores"]
            await admission_repo.update_profile_scores(profile.id, subject_scores)
            
            # Update snapshot rules/criteria if needed? 
            # No, scores are data, rules are config.
        
        # Handle simple GPA (for hoc_ba w/o subjects) - Stored in JSONB 'applied_rules' or separate?
        # Current requirement focuses on ProfileSubjectScore for Dynamic Scoring
        # We can store raw GPA in applied_rules override or user data if needed, 
        # but for now let's focus on Subject Scores.


    # Update timestamp and increment version
    profile.updated_at = datetime.now(timezone.utc)
    profile.version += 1

    await db.flush()  # Router commits
    
    # ✅ Fix: Fetch fresh scores but do NOT assign to profile.subject_scores (avoid SA error)
    fresh_scores = await admission_repo.get_profile_scores(profile.id)
    
    # Calculate totals for response using fresh data
    _calculate_and_update_totals(profile, scores=fresh_scores)

    log.info(
        "Admission profile updated",
        profile_id=profile_id,
        user_id=current_user.id,
        updated_fields=list(data.keys()),
    )

    return profile


def _calculate_and_update_totals(profile: models.AdmissionProfile, scores: list = None) -> None:
    """
    Calculate total_score and average_score from subject_scores.
    
    Args:
        profile: AdmissionProfile object
        scores: Optional explicit list of ProfileSubjectScore (overrides profile.subject_scores)
    
    Note: These fields are transient (not in DB) but required by Schema.
    """
    # Use provided scores OR fallback to profile relationship
    # If scores arg is provided managed explicitly, use it.
    # Otherwise check if profile.subject_scores is loaded and populated.
    
    target_scores = scores if scores is not None else profile.subject_scores
    
    if not target_scores:
        profile.total_score = 0.0
        profile.average_score = 0.0
        profile.admission_scores = {"subject_scores": {}, "total_score": 0.0, "average_score": 0.0}
        return

    # Calculate
    total = sum(float(s.score) for s in target_scores)
    count = len(target_scores)
    avg = total / count if count > 0 else 0.0
    
    # Update transient fields
    profile.total_score = round(total, 2)
    profile.average_score = round(avg, 2)
    
    # Update admission_scores schema field
    scores_map = {s.subject.code: float(s.score) for s in target_scores}
    profile.admission_scores = {
        "subject_scores": scores_map,
        "total_score": profile.total_score,
        "average_score": profile.average_score,
        "gpa": profile.average_score # For backward compatibility
    }


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
    
    # Initialize repository for document/citizen_id checks
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Must be in draft status
    if profile.status != "draft":
        raise BadRequest(
            f"Cannot submit profile with status '{profile.status}'. "
            "Only draft profiles can be submitted."
        )

    errors: List[str] = []

    # Get applied_rules (snapshot)
    applied_rules = profile.applied_rules or {}
    mandatory_docs = applied_rules.get("mandatory_docs", [])
    
    # ========================================
    # Phase 6: Dynamic Admission Scoring Validation
    # ========================================
    # ========================================
    # Phase 6: Dynamic Admission Scoring Validation
    # ========================================
    
    # 1. Get Scores from ProfileSubjectScore table
    scores = await admission_repo.get_profile_scores(profile.id)
    
    # 2. Calculate GPA & Validate
    min_gpa = float(applied_rules.get("min_gpa", 0))
    
    if min_gpa > 0:
        if not scores:
            errors.append("Chưa nhập điểm môn học nào (yêu cầu xét tuyển)")
        else:
            # Simple average calculation for Phase 1
            # TODO (Phase 2): Implement weighted average based on admission_method criteria
            total_score = sum(float(s.score) for s in scores)
            gpa = total_score / len(scores)
            
            if gpa < min_gpa:
                errors.append(f"Điểm trung bình (GPA) không đạt: {gpa:.2f} < {min_gpa}")
            else:
                log.info(
                    "GPA validation passed",
                    profile_id=profile.id,
                    gpa=gpa,
                    min_gpa=min_gpa,
                    calculated_at=datetime.now(timezone.utc).isoformat()
                )

    # Validation 2: Check mandatory documents (using relational ProfileDocument)
    uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
    uploaded_doc_codes = {doc.document_type.code for doc in uploaded_docs}

    for doc_code in mandatory_docs:
        if doc_code not in uploaded_doc_codes:
            # Find document for label
            doc = await admission_repo.get_document_by_type(profile.id, doc_code)
            label = doc.document_type.name if doc else doc_code
            errors.append(f"Thiếu tài liệu bắt buộc: {label} ({doc_code})")

    # Validation 3: Check citizen_id uniqueness
    if not profile.citizen_id:
        errors.append("Số CCCD/CMND chưa được nhập (citizen_id is null)")
    else:
        # Check in admission_profile table (other profiles)
        duplicate_profile = await admission_repo.check_citizen_id_exists(
            profile.citizen_id, exclude_profile_id=profile.id
        )

        if duplicate_profile:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi hồ sơ khác "
                f"(ID: {duplicate_profile.id})"
            )

        # Check in student table (already enrolled students)
        existing_student = await admission_repo.check_citizen_id_enrolled(profile.citizen_id)

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

        # TODO (Phase 2): Log GPA from ProfileSubjectScore table
        log.info(
            "Admission profile approved",
            profile_id=profile_id,
            user_id=current_user.id,
            citizen_id=profile.citizen_id,
        )

        return {
            "status": "approved",
            "message": "Hồ sơ đã được duyệt tự động. Bạn có thể tiến hành nhập học.",
            "errors": None,
        }


async def upload_document(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    file: Any,  # UploadFile
    current_user: models.User,
) -> tuple[Dict[str, Any], Any]:
    """
    Upload a document for an admission profile.

    Workflow:
    1. Verify access (IDOR)
    2. Verify profile status (draft/rejected)
    3. Verify doc_code exists in ProfileDocument
    4. Save file to disk (uploads/admissions/{id}/{doc_code}_{filename})
    5. Update ProfileDocument status='uploaded' and file_path
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    
    Returns:
        Tuple of (updated_doc_item, post_commit_callback)
    
    Security:
    - Path Traversal: filename sanitization (inherent in modern frameworks but good practice)
    - File Type: Should be validated at Router level generally, but here we accept generic
    """
    # Initialize repository
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    profile = await get_profile(db, profile_id, current_user)

    # State Locking
    if profile.status not in ["draft", "rejected"]:
        raise BadRequest(f"Cannot upload documents for profile with status '{profile.status}'")

    # File validation constants
    ALLOWED_CONTENT_TYPES = ["application/pdf", "image/jpeg", "image/png"]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    # Validate file type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise BadRequest(
            f"Invalid file type '{file.content_type}'. "
            "Allowed: PDF, JPG, PNG"
        )
    
    # Validate file size (read file to check size)
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to beginning
    
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        raise BadRequest(
            f"File too large ({size_mb:.1f}MB). Maximum allowed: 10MB"
        )

    # Find document in ProfileDocument table (replaces JSONB checklist)
    doc_record = await admission_repo.get_document_by_type(profile_id, doc_code)

    if not doc_record:
        raise BadRequest(f"Document code '{doc_code}' not found in profile documents")

    # Prepare file path with security measures
    import os
    import shutil
    import uuid

    upload_dir = f"uploads/admissions/{profile_id}"
    os.makedirs(upload_dir, exist_ok=True)

    # SECURITY: Delete old file if exists (prevent orphan files)
    old_file_path = doc_record.file_path
    if old_file_path and os.path.exists(old_file_path):
        try:
            os.remove(old_file_path)
            log.info("Old document file deleted", old_path=old_file_path)
        except OSError as e:
            log.warning("Failed to delete old file", path=old_file_path, error=str(e))

    # SECURITY: Generate UUID-based filename (prevents path traversal & leaks)
    original_filename = file.filename or "document"
    file_extension = os.path.splitext(original_filename)[1].lower()
    # Whitelist extensions
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
    if file_extension not in allowed_extensions:
        file_extension = ".bin"  # Fallback for unknown types

    unique_filename = f"{doc_code}_{uuid.uuid4().hex[:12]}{file_extension}"
    file_path = f"{upload_dir}/{unique_filename}"

    # Save file
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error("File upload failed", error=str(e), profile_id=profile_id)
        raise BadRequest("Failed to save file")

    # Update ProfileDocument record (replaces JSONB flag_modified workaround)
    uploaded_at_dt = datetime.now(timezone.utc)
    await admission_repo.update_document_status(
        profile_id=profile_id,
        document_type_code=doc_code,
        status="uploaded",
        file_path=file_path,
        uploaded_at=uploaded_at_dt.isoformat()
    )

    profile.updated_at = uploaded_at_dt

    await db.flush()

    # Prepare response data (matches DocumentUploadResponse schema)
    response_data = {
        "code": doc_code,
        "label": doc_record.document_type.name,
        "is_mandatory": True,  # All documents in ProfileDocument are mandatory
        "status": "uploaded",
        "file_path": file_path,
        "uploaded_at": uploaded_at_dt.isoformat(),
    }
    
    # Post-commit callback for logging/side effects
    async def _post_commit():
        log.info(
            "Document uploaded", 
            profile_id=profile_id, 
            doc_code=doc_code, 
            file_path=file_path,
            user_id=current_user.id
        )
    
    return response_data, _post_commit


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
    5. Create StudentDocument records (from ProfileDocument table)
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
    # Initialize repository
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile with IDOR check
    profile = await get_profile(db, profile_id, current_user)

    # Must be in approved or confirmed status
    # 'confirmed' = Lead confirmed via magic link, ready to enroll
    if profile.status not in ("approved", "confirmed", "overridden"):
        raise BadRequest(
            f"Cannot enroll student with profile status '{profile.status}'. "
            "Only approved, confirmed, or overridden profiles can be enrolled."
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

                    # ✅ SPRINT 6: Use Repository for uniqueness check
                    from app.repositories import AdmissionRepository
                    admission_repo_inner = AdmissionRepository(db)
                    
                    if not await admission_repo_inner.check_student_code_exists(candidate_code):
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
            # Step 3b: Copy ProfileDocument records to StudentDocument (relational approach)
            uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
            for profile_doc in uploaded_docs:
                # Use uploaded_at from ProfileDocument or fallback to now
                uploaded_at = profile_doc.uploaded_at or datetime.now(timezone.utc)

                doc = models.StudentDocument(
                    student_id=student.id,
                    doc_type=profile_doc.document_type.code,
                    file_path=profile_doc.file_path,
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


# ==============================================================================
# DELETE PROFILE
# ==============================================================================

# ==============================================================================
# STATE MACHINE TRANSITIONS (Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
# ==============================================================================

async def approve_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    approver: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Approve admission profile (Manager/Admin action).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → APPROVED
    - State validation via admission_state_machine module
    - Version checking for optimistic locking
    - Returns (result, post_commit_callback) pattern

    Architecture Compliance:
    - No HTTPException (use Domain Exceptions)
    - No Request/Response imports
    - Return callback for side effects
    - Router calls db.commit()

    Args:
        db: Database session
        profile: AdmissionProfile (from IDOR dependency)
        approver: User performing approval
        data: ApproveRequest data (notes)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    from .admission_state_machine import validate_transition

    # STATE VALIDATION (Business Rule)
    try:
        validate_transition(profile.status, "approved")
    except ValueError as e:
        log.warning(
            "Invalid state transition for approve",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # VERSION CHECK (Optimistic Locking)
    # Only check if version is explicitly provided (not None)
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE CHANGE
    profile.status = "approved"
    profile.approved_at = datetime.now(timezone.utc)
    profile.approved_by_id = approver.id
    profile.approval_notes = data.get("notes")
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()  # Flush, don't commit! Router commits.

    log.info(
        "Admission profile approved",
        profile_id=profile.id,
        approver_id=approver.id,
        previous_status=profile.status,
        citizen_id=profile.citizen_id,
    )

    # PREPARE POST-COMMIT CALLBACK
    async def post_commit():
        """Side effects after transaction commit (notifications, etc.)."""
        # TODO: Send notification to applicant
        log.info(
            "Post-commit: Profile approved notification",
            profile_id=profile.id,
        )

    return profile, post_commit


async def reject_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    rejector: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Reject admission profile (Manager/Admin action).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → REJECTED
    - Reason is MANDATORY (validated in schema, min 10 chars)
    - State validation via admission_state_machine module
    - Returns (result, post_commit_callback) pattern

    Args:
        db: Database session
        profile: AdmissionProfile (from IDOR dependency)
        rejector: User performing rejection
        data: RejectRequest data (reason - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from .admission_state_machine import validate_transition

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "rejected")
    except ValueError as e:
        log.warning(
            "Invalid state transition for reject",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # BUSINESS RULE: Reason is mandatory (already validated by schema)
    if not data.get("reason"):
        raise BadRequest("Rejection reason is required (min 10 characters)")

    # VERSION CHECK
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE CHANGE
    profile.status = "rejected"
    profile.rejected_at = datetime.now(timezone.utc)
    profile.rejected_by_id = rejector.id
    profile.rejection_reason = data["reason"]
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    log.info(
        "Admission profile rejected",
        profile_id=profile.id,
        rejector_id=rejector.id,
        reason_length=len(data["reason"]),
    )

    # POST-COMMIT CALLBACK
    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Profile rejected notification",
            profile_id=profile.id,
        )

    return profile, post_commit


async def resubmit_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    officer: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Resubmit rejected profile (Officer action).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2:
    - Transition: REJECTED → RESUBMITTED
    - Officer fixes issues and resubmits for Manager review
    - Optional notes about what was fixed

    Args:
        db: Database session
        profile: AdmissionProfile (from IDOR dependency)
        officer: User performing resubmit
        data: ResubmitRequest data (notes)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    from .admission_state_machine import validate_transition

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "resubmitted")
    except ValueError as e:
        log.warning(
            "Invalid state transition for resubmit",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # VERSION CHECK
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE CHANGE
    profile.status = "resubmitted"
    profile.resubmitted_at = datetime.now(timezone.utc)
    profile.resubmitted_by_id = officer.id
    profile.resubmit_notes = data.get("notes")
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    log.info(
        "Admission profile resubmitted",
        profile_id=profile.id,
        officer_id=officer.id,
    )

    # POST-COMMIT CALLBACK
    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Profile resubmitted notification",
            profile_id=profile.id,
        )

    return profile, post_commit


async def confirm_enrollment(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    applicant: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Confirm enrollment intent (Applicant/User SELF action).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.3:
    - Transition: APPROVED → CONFIRMED
    - SELF check enforced by get_admission_for_owner dependency
    - Applicant confirms they want to enroll

    Args:
        db: Database session
        profile: AdmissionProfile (from IDOR dependency with SELF check)
        applicant: User performing confirmation (must be profile owner)
        data: ConfirmRequest data (empty)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    from .admission_state_machine import validate_transition

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "confirmed")
    except ValueError as e:
        log.warning(
            "Invalid state transition for confirm",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # VERSION CHECK
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE CHANGE
    profile.status = "confirmed"
    profile.confirmed_at = datetime.now(timezone.utc)
    profile.confirmed_by_id = applicant.id
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    log.info(
        "Admission profile confirmed by applicant",
        profile_id=profile.id,
        applicant_id=applicant.id,
    )

    # POST-COMMIT CALLBACK
    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Enrollment confirmed notification",
            profile_id=profile.id,
        )

    return profile, post_commit


async def override_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    admin: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Override normal flow (Admin only, with audit).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: APPROVED → OVERRIDDEN
    - Admin only (enforced by router)
    - Reason MANDATORY (min 10 chars, for audit)
    - Full audit logging required

    Args:
        db: Database session
        profile: AdmissionProfile
        admin: Admin user performing override
        data: OverrideRequest data (reason, bypass_rules)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from .admission_state_machine import validate_transition

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "overridden")
    except ValueError as e:
        log.warning(
            "Invalid state transition for override",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # BUSINESS RULE: Reason is mandatory (already validated by schema)
    if not data.get("reason"):
        raise BadRequest("Override reason is required (min 10 characters)")

    # VERSION CHECK
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE CHANGE
    profile.status = "overridden"
    profile.overridden_at = datetime.now(timezone.utc)
    profile.overridden_by_id = admin.id
    profile.override_reason = data["reason"]
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    # AUDIT LOG (per AUTHORIZATION_DECISIONS.md Decision 11)
    # TODO: Implement proper audit log table
    log.warning(
        "AUDIT: Admin override action",
        profile_id=profile.id,
        admin_id=admin.id,
        admin_email=admin.email,
        reason=data["reason"],
        bypass_rules=data.get("bypass_rules", []),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # POST-COMMIT CALLBACK
    async def post_commit():
        """Side effects after transaction commit."""
        # TODO: Send audit alert to compliance team
        log.info(
            "Post-commit: Override audit notification sent",
            profile_id=profile.id,
        )

    return profile, post_commit


async def finalize_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    admin: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Finalize enrollment (Admin only, creates Student record).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: OVERRIDDEN/CONFIRMED → ENROLLED
    - Admin only (enforced by router)
    - Triggers student record creation (delegates to enroll_student)

    Args:
        db: Database session
        profile: AdmissionProfile
        admin: Admin user performing finalization
        data: FinalizeRequest data (empty)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch or enrollment conflict
    """
    from .admission_state_machine import validate_transition

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "enrolled")
    except ValueError as e:
        log.warning(
            "Invalid state transition for finalize",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # VERSION CHECK
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # DELEGATE TO EXISTING ENROLL_STUDENT FUNCTION
    # This function already handles:
    # - Student code generation with Redis lock
    # - Student record creation
    # - StudentDocument creation
    # - Lead status update
    # - ACID transaction with savepoint
    enrollment_result = await enroll_student(db, profile.id, admin)

    log.info(
        "Admission profile finalized (enrolled)",
        profile_id=profile.id,
        admin_id=admin.id,
        student_code=enrollment_result["student_code"],
    )

    # Reload profile to get updated status
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    profile = await admission_repo.reload_profile_with_lead(profile.id)

    # POST-COMMIT CALLBACK
    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Enrollment finalized notification",
            profile_id=profile.id,
            student_code=enrollment_result["student_code"],
        )

    return profile, post_commit


async def delete_profile(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> bool:
    """
    Delete AdmissionProfile (only when status='draft').

    Security:
    - IDOR: Check lead.unit_id == user.unit_id (unless admin)
    - State Locking: Only draft profiles can be deleted

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() after this function returns.

    Args:
        db: AsyncSession for database operations
        profile_id: AdmissionProfile ID to delete
        current_user: Current authenticated user

    Returns:
        True if deleted successfully

    Raises:
        ResourceNotFoundError: Profile not found
        PermissionDeniedError: User doesn't have access
        BadRequest: Status is not 'draft'
    """
    from app.repositories import AdmissionRepository

    admission_repo = AdmissionRepository(db)

    # Get profile with lead (for IDOR check)
    profile = await admission_repo.get_profile_by_id_with_lead(profile_id)

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check
    _check_admin_or_unit_access(profile, current_user)

    # State check: Only draft profiles can be deleted
    if profile.status != "draft":
        raise BadRequest(
            f"Cannot delete profile with status '{profile.status}'. "
            "Only draft profiles can be deleted."
        )

    # Delete the profile
    await db.delete(profile)
    await db.flush()

    log.info(
        "Admission profile deleted",
        profile_id=profile_id,
        user_id=current_user.id,
    )

    return True


# ==============================================================================
# CONFIRMATION TOKEN FUNCTIONS (Magic Link)
# ==============================================================================


async def generate_confirmation_token(
    db: AsyncSession,
    profile: models.AdmissionProfile,
) -> tuple[models.AdmissionConfirmationToken, callable]:
    """
    Generate magic link confirmation token for approved profile.
    
    Called by: approve_profile() or send_confirmation endpoint.
    
    Args:
        db: Database session
        profile: Approved AdmissionProfile
        
    Returns:
        Tuple of (token_object, email_callback)
        
    Raises:
        BadRequest: Profile status is not 'approved'
    """
    import secrets
    from datetime import timedelta, datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository
    
    # Validate profile status
    if profile.status != "approved":
        raise BadRequest(
            f"Cannot generate confirmation token for profile with status '{profile.status}'. "
            "Only approved profiles can receive confirmation links."
        )
    
    # Generate secure token
    token_value = secrets.token_urlsafe(32)  # 256-bit entropy
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS
    )
    
    # Create token via repository
    repo = AdmissionRepository(db)
    token_obj = await repo.create_confirmation_token(
        profile_id=profile.id,
        token=token_value,
        expires_at=expires_at,
    )
    
    log.info(
        "Confirmation token generated",
        profile_id=profile.id,
        token_id=token_obj.id,
        expires_at=expires_at.isoformat(),
    )
    
    # Post-commit callback for sending email
    async def _send_email_callback():
        # This will be implemented when email service is ready
        # For now, just log
        log.info(
            "POST-COMMIT: Would send confirmation email",
            profile_id=profile.id,
            lead_email=profile.lead.email if profile.lead else None,
            token_id=token_obj.id,
        )
    
    return token_obj, _send_email_callback


async def get_token_info(
    db: AsyncSession,
    token_value: str,
) -> dict:
    """
    Get token info for frontend to display confirmation form.
    
    Called by: GET /confirm/{token}
    
    Args:
        db: Database session
        token_value: Token string from URL
        
    Returns:
        Dict with token status info for ConfirmTokenInfoResponse
        
    Raises:
        ResourceNotFoundError: Token not found
    """
    from datetime import datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository
    
    repo = AdmissionRepository(db)
    token_obj = await repo.get_token_by_value(token_value)
    
    if not token_obj:
        raise ResourceNotFoundError("Invalid or expired confirmation link")
    
    now = datetime.now(timezone.utc)
    is_expired = token_obj.expires_at < now
    is_locked = token_obj.locked_at is not None
    is_used = token_obj.confirmed_at is not None
    attempts_remaining = max(0, settings.ADMISSION_CONFIRM_MAX_ATTEMPTS - token_obj.attempt_count)
    
    # Get lead name from profile
    profile_name = "Học viên"
    if token_obj.profile and token_obj.profile.lead:
        profile_name = token_obj.profile.lead.full_name or profile_name
    
    return {
        "valid": not (is_expired or is_locked or is_used),
        "expired": is_expired,
        "locked": is_locked,
        "already_used": is_used,
        "attempts_remaining": attempts_remaining,
        "profile_name": profile_name,
        "expires_at": token_obj.expires_at,
    }


async def verify_and_confirm(
    db: AsyncSession,
    token_value: str,
    last_digits: str,
) -> tuple[models.AdmissionProfile, callable]:
    """
    Verify CCCD and confirm admission via token.
    
    Called by: POST /confirm/{token}
    
    Steps:
    1. Validate token (exists, not expired, not used, not locked)
    2. Verify last 4 digits of citizen_id
    3. If match: confirm profile, mark token used
    4. If mismatch: increment attempts, lock if exceeded
    
    Args:
        db: Database session
        token_value: Token string from URL
        last_digits: Last 4 digits of CCCD from user input
        
    Returns:
        Tuple of (updated_profile, notification_callback)
        
    Raises:
        ResourceNotFoundError: Token not found
        BadRequest: Token expired/used/locked or CCCD mismatch
    """
    from datetime import datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository
    
    repo = AdmissionRepository(db)
    token_obj = await repo.get_token_by_value(token_value)
    
    if not token_obj:
        raise ResourceNotFoundError("Invalid or expired confirmation link")
    
    now = datetime.now(timezone.utc)
    
    # Check token status
    if token_obj.confirmed_at is not None:
        raise BadRequest("This confirmation link has already been used")
    
    if token_obj.locked_at is not None:
        raise BadRequest(
            "This confirmation link has been locked due to too many failed attempts. "
            "Please contact support for assistance."
        )
    
    if token_obj.expires_at < now:
        raise BadRequest("This confirmation link has expired. Please request a new link.")
    
    # Get profile and verify CCCD
    profile = token_obj.profile
    if not profile or not profile.citizen_id:
        raise BadRequest("Profile data is incomplete. Please contact support.")
    
    # Verify last 4 digits
    expected_digits = profile.citizen_id[-settings.ADMISSION_CONFIRM_CCCD_DIGITS:]
    
    if last_digits != expected_digits:
        # Increment attempts
        await repo.increment_token_attempts(token_obj, settings.ADMISSION_CONFIRM_MAX_ATTEMPTS)
        
        attempts_remaining = max(0, settings.ADMISSION_CONFIRM_MAX_ATTEMPTS - token_obj.attempt_count)
        
        if token_obj.locked_at is not None:
            log.warning(
                "Confirmation token locked after max attempts",
                token_id=token_obj.id,
                profile_id=profile.id,
            )
            raise BadRequest(
                "Too many failed attempts. This confirmation link has been locked. "
                "Please contact support for assistance."
            )
        
        log.warning(
            "CCCD verification failed",
            token_id=token_obj.id,
            profile_id=profile.id,
            attempts_remaining=attempts_remaining,
        )
        raise BadRequest(
            f"Incorrect CCCD digits. {attempts_remaining} attempts remaining."
        )
    
    # CCCD matches - confirm the profile!
    await repo.mark_token_confirmed(token_obj, confirmed_via="magic_link")
    
    log.info(
        "Admission confirmed via magic link",
        profile_id=profile.id,
        token_id=token_obj.id,
        confirmed_at=now.isoformat(),
    )
    
    # Post-commit callback for notifications
    async def _notification_callback():
        log.info(
            "POST-COMMIT: Would send confirmation success notification",
            profile_id=profile.id,
            lead_id=profile.lead_id,
        )
    
    return profile, _notification_callback
