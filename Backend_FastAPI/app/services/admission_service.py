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

    # Step 6: Auto-generate documents_checklist
    mandatory_docs = applied_rules.get("mandatory_docs", [])
    
    # Also collect mandatory docs from criteria (if any)
    for criterion in criteria:
        required_docs = criterion.get("required_documents", [])
        for doc in required_docs:
            doc_code = doc.get("code") if isinstance(doc, dict) else doc
            if doc_code and doc_code not in mandatory_docs:
                mandatory_docs.append(doc_code)
    
    documents_checklist = _generate_documents_checklist(mandatory_docs)

    # Step 7: Create AdmissionProfile
    new_profile = models.AdmissionProfile(
        lead_id=lead_id,
        status="draft",
        applied_rules=applied_rules,  # Snapshot (immutable) with criteria
        family_info=[],
        academic_history=[],
        admission_scores=None,
        documents_checklist=documents_checklist,
        # Pre-fill from Lead
        full_name=lead.full_name,
        phone=lead.phone,
        email=lead.email,
    )

    db.add(new_profile)
    await db.flush()  # Get ID without committing (router commits)

    # ✅ SPRINT 6: Reload with relationships for response
    new_profile = await admission_repo.reload_profile_with_lead(new_profile.id)

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

    if "admission_scores" in data and data["admission_scores"] is not None:
        profile.admission_scores = data["admission_scores"]

    if "documents_checklist" in data and data["documents_checklist"] is not None:
        profile.documents_checklist = data["documents_checklist"]

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
    applied_rules = profile.applied_rules or {}
    mandatory_docs = applied_rules.get("mandatory_docs", [])
    
    # ========================================
    # Phase 6: Dynamic Admission Scoring Validation
    # ========================================
    
    # Get criteria from applied_rules (new structure)
    criteria = applied_rules.get("criteria", [])
    min_gpa = applied_rules.get("min_gpa")  # Legacy fallback
    
    # Get admission scores from profile
    admission_scores = profile.admission_scores or {}
    selected_criterion_id = admission_scores.get("selected_criterion_id")
    
    if not criteria and min_gpa is not None:
        # Legacy validation: GPA-only (backward compatibility)
        gpa = admission_scores.get("gpa")
        if gpa is None:
            errors.append("GPA chưa được nhập")
        elif gpa < min_gpa:
            errors.append(f"GPA ({gpa}) không đạt yêu cầu tối thiểu ({min_gpa})")
    
    elif criteria:
        # New validation: Dynamic admission method
        if not selected_criterion_id:
            errors.append("Chưa chọn phương thức xét tuyển")
        else:
            # Find selected criterion
            selected_criterion = next(
                (c for c in criteria if c.get("id") == selected_criterion_id),
                None
            )
            
            if not selected_criterion:
                errors.append(f"Phương thức xét tuyển không hợp lệ: {selected_criterion_id}")
            else:
                method_name = selected_criterion.get("method_name", "")
                min_score = selected_criterion.get("min_score", 0)
                subject_groups = selected_criterion.get("subject_groups", [])
                
                # Determine validation type based on method name
                is_gpa_method = (
                    "học bạ" in method_name.lower() or 
                    "gpa" in method_name.lower() or
                    "điểm trung bình" in method_name.lower()
                )
                
                if is_gpa_method:
                    # GPA-based validation
                    gpa = admission_scores.get("gpa")
                    if gpa is None:
                        errors.append("GPA chưa được nhập")
                    elif min_score and gpa < min_score:
                        errors.append(
                            f"GPA ({gpa}) không đạt điểm chuẩn ({min_score}) "
                            f"của phương thức '{method_name}'"
                        )
                else:
                    # Exam-based validation (subject scores)
                    selected_group = admission_scores.get("selected_group")
                    subject_scores = admission_scores.get("subject_scores", {})
                    
                    if subject_groups and not selected_group:
                        errors.append("Chưa chọn tổ hợp môn xét tuyển")
                    elif selected_group and selected_group not in subject_groups:
                        errors.append(
                            f"Tổ hợp môn '{selected_group}' không thuộc danh sách cho phép "
                            f"({', '.join(subject_groups)})"
                        )
                    
                    # Calculate total score from subject_scores
                    if subject_scores:
                        total = sum(
                            v for v in subject_scores.values() 
                            if isinstance(v, (int, float))
                        )
                        if min_score and total < min_score:
                            errors.append(
                                f"Tổng điểm ({total:.1f}) không đạt điểm chuẩn ({min_score}) "
                                f"của phương thức '{method_name}'"
                            )
                    else:
                        errors.append("Chưa nhập điểm các môn xét tuyển")
    else:
        # No validation criteria defined
        errors.append("Không có tiêu chí xét tuyển được định nghĩa")

    # Validation 2: Check mandatory documents
    if not profile.documents_checklist:
        if mandatory_docs:
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
        # ✅ SPRINT 6: Use Repository for validation
        from app.repositories import AdmissionRepository
        admission_repo = AdmissionRepository(db)
        
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
    3. Verify doc_code exists in checklist
    4. Save file to disk (uploads/admissions/{id}/{doc_code}_{filename})
    5. Update documents_checklist status='uploaded' and file_path
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    
    Returns:
        Tuple of (updated_doc_item, post_commit_callback)
    
    Security:
    - Path Traversal: filename sanitization (inherent in modern frameworks but good practice)
    - File Type: Should be validated at Router level generally, but here we accept generic
    """
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

    # Find document item in checklist
    checklist = profile.documents_checklist or []
    doc_item = next((d for d in checklist if d["code"] == doc_code), None)
    
    if not doc_item:
        raise BadRequest(f"Document code '{doc_code}' not found in checklist")

    # Prepare file path with security measures
    import os
    import shutil
    import uuid
    
    upload_dir = f"uploads/admissions/{profile_id}"
    os.makedirs(upload_dir, exist_ok=True)
    
    # SECURITY: Delete old file if exists (prevent orphan files)
    old_file_path = doc_item.get("file_path")
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

    # Update checklist
    # IMPORTANT: SQLAlchemy doesn't detect in-place mutations of JSONB columns.
    # We must create new dict objects AND use flag_modified() to ensure persistence.
    from sqlalchemy.orm.attributes import flag_modified
    
    new_checklist = []
    uploaded_at = datetime.now().isoformat()
    for item in checklist:
        if item["code"] == doc_code:
            # Create a NEW dict with updated values (not mutate in place)
            new_item = {
                **item,
                "status": "uploaded",
                "file_path": file_path,
                "uploaded_at": uploaded_at,
            }
            new_checklist.append(new_item)
        else:
            # Copy other items to create new references
            new_checklist.append(dict(item))
    
    profile.documents_checklist = new_checklist
    profile.updated_at = datetime.now(timezone.utc)
    
    # Explicitly mark the JSONB column as modified
    flag_modified(profile, "documents_checklist")
    
    await db.flush()
    
    # Prepare response data (matches DocumentUploadResponse schema)
    response_data = {
        "code": doc_code,
        "label": doc_item.get("label", doc_code),
        "is_mandatory": doc_item.get("is_mandatory", True),
        "status": "uploaded",
        "file_path": file_path,
        "uploaded_at": uploaded_at,
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


# ==============================================================================
# DELETE PROFILE
# ==============================================================================

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
