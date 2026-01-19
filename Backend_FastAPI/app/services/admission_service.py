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
from typing import List, Optional, Dict, Any, Tuple, Callable
from decimal import Decimal
import structlog
from sqlalchemy import or_, and_, select, func
from sqlalchemy.exc import IntegrityError

from app.utils.redis_lock import acquire_redis_lock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from .. import models
from ..schemas.admission import DEFAULT_UPLOAD_CONFIG
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


def _compute_frontend_fields(
    profile: models.AdmissionProfile,
    current_user: models.User,
    documents: list = None,
) -> None:
    """
    Phase 7: Frontend Thin Client Compliance
    
    Compute permissions, eligibility, validation_errors, available_actions, 
    and completion_percent for AdmissionProfileResponse.
    
    These are transient fields (not stored in DB) computed at response time.
    
    Args:
        profile: AdmissionProfile object
        current_user: Current authenticated user (for role-based permissions)
        documents: Optional list of ProfileDocument (to avoid re-fetching)
    """
    status = profile.status
    user_role = current_user.role
    is_admin = user_role == UserRole.ADMIN
    is_manager = user_role == UserRole.MANAGER
    is_officer = user_role in [UserRole.OFFICER, UserRole.MANAGER, UserRole.ADMIN]
    
    # Check if user owns this profile (for applicant self-actions)
    # Corrected: Lead uses assigned_officer_id, not user_id
    is_owner = profile.lead and profile.lead.assigned_officer_id == current_user.id
    
    # =========================================================================
    # 1. PERMISSIONS (computed from role + status + Casbin-like rules)
    # =========================================================================
    # ARCHITECTURE NOTE:
    # - permissions: Role-based access control (WHO can do WHAT)
    # - available_actions: State-based actions (WHAT is currently POSSIBLE)
    # 
    # FE Usage:
    # - permissions → Guard routes, show/hide menu items
    # - available_actions → Render action buttons
    #
    # Example: Admin has permission to delete, but delete is only in available_actions
    #          when status='draft'. Button should check available_actions, not permissions.
    permissions = {
        # Edit/Save: Only in draft/rejected, by owner or officer
        "edit": status in ["draft", "rejected"] and (is_owner or is_officer),
        "save": status in ["draft", "rejected"] and (is_owner or is_officer),
        
        # Submit: Only draft, by owner or officer
        "submit": status == "draft" and (is_owner or is_officer),
        
        # Approve/Reject: Only submitted/resubmitted, by manager or admin
        "approve": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        "reject": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        
        # Resubmit: Only rejected, by owner or officer
        "resubmit": status == "rejected" and (is_owner or is_officer),
        
        # Enroll: Only approved, by officer or higher
        "enroll": status == "approved" and is_officer,
        
        # Delete: Only draft, by admin
        "delete": status == "draft" and is_admin,
        
        # View: Always (if passed IDOR check)
        "view": True,
    }
    profile.permissions = permissions
    
    # =========================================================================
    # 2. AVAILABLE ACTIONS (list of action names that are currently allowed)
    # =========================================================================
    profile.available_actions = [action for action, allowed in permissions.items() if allowed]
    
    # =========================================================================
    # 3. ELIGIBILITY STATUS & VALIDATION ERRORS
    # =========================================================================
    validation_errors = []
    applied_rules = profile.applied_rules or {}
    
    # Check GPA/scores
    min_gpa = float(applied_rules.get("min_gpa") or 0)
    required_count = int(applied_rules.get("required_subject_count") or 3)
    
    # Get current score count from the just-computed admission_scores
    scores_map = profile.admission_scores.get("subject_scores", {}) if profile.admission_scores else {}
    current_count = len(scores_map)
    
    # NEW: Populate snapshot_score from admission_scores (if available)
    # This ensures frontend gets the Best N breakdown
    if profile.admission_scores and "snapshot_score" in profile.admission_scores:
        profile.snapshot_score = profile.admission_scores["snapshot_score"]
    else:
        profile.snapshot_score = None
    
    gpa_error = False
    method_type = applied_rules.get("method_type", "subject_based")
    current_gpa = profile.average_score or 0  # Define at top for validation_summary use
    
    # =======================================================================
    # SCORE VALIDATION BY METHOD TYPE
    # 
    # Method Types:
    # - gpa_only: Only check average_score >= min_gpa (typically học bạ GPA-based)
    # - subject_based: Only check total_score >= min_score (thi tổ hợp)
    # - combined: Check BOTH conditions (e.g., GPA + điểm thi)
    # - Other (hoc_ba, tot_nghiep, etc.): Treat as subject_based (total_score)
    # =======================================================================
    
    # Get thresholds from applied_rules
    min_score = float(applied_rules.get("min_score") or 0)
    current_total = profile.total_score or 0
    
    if method_type == "gpa_only":
        # GPA-Only: Check average_score only
        if min_gpa > 0 and current_gpa < min_gpa:
            validation_errors.append(f"GPA không đạt: {current_gpa:.2f} < {min_gpa}")
            gpa_error = True
            
    elif method_type == "combined":
        # Combined: Check BOTH total_score AND average_score
        # First: Check subject count
        if current_count < required_count:
            validation_errors.append(f"Chưa nhập đủ đầu điểm ({current_count}/{required_count})")
            gpa_error = True
        else:
            # Check total_score
            if min_score > 0 and current_total < min_score:
                validation_errors.append(f"Tổng điểm thấp hơn điểm chuẩn: {current_total:.2f} < {min_score}")
                gpa_error = True
            # Check GPA (even if total passed)
            if min_gpa > 0 and current_gpa < min_gpa:
                validation_errors.append(f"GPA không đạt: {current_gpa:.2f} < {min_gpa}")
                gpa_error = True
                
    else:
        # subject_based, hoc_ba, tot_nghiep, etc.: Check total_score only
        if current_count < required_count:
            validation_errors.append(f"Chưa nhập đủ đầu điểm ({current_count}/{required_count})")
            gpa_error = True
        elif min_score > 0 and current_total < min_score:
            validation_errors.append(f"Tổng điểm thấp hơn điểm chuẩn: {current_total:.2f} < {min_score}")
            gpa_error = True
    
    # Check mandatory documents that REQUIRE UPLOAD (NEW: only upload_required_docs)
    upload_required_docs = applied_rules.get("upload_required_docs", applied_rules.get("mandatory_docs", []))
    doc_errors = []
    uploaded_doc_codes = set()
    if documents is not None:
        uploaded_doc_codes = {
            doc.document_type.code for doc in documents 
            if doc.file_path and doc.status in ["uploaded", "verified"]
        }
        for doc_code in upload_required_docs:
            if doc_code not in uploaded_doc_codes:
                doc_errors.append(doc_code)
                validation_errors.append(f"Thiếu tài liệu bắt buộc: {doc_code}")
    
    # Check citizen_id
    cccd_error = not profile.citizen_id
    if cccd_error:
        validation_errors.append("Chưa nhập số CCCD/CMND")
    
    # Determine eligibility status
    # ARCHITECTURE NOTE:
    # - eligibility_status: Academic eligibility (GPA, score thresholds) - DOES NOT control UI
    # - step_status[7]: Workflow UI state (locked/success) - DOES NOT reflect academic status
    # 
    # Rule: Submit button uses available_actions, NOT eligibility_status.
    # A profile with eligibility_status='ineligible' may still be submittable for review.
    if len(validation_errors) == 0:
        profile.eligibility_status = "eligible"
    elif status in ["approved", "enrolled"]:
        # Already approved, so eligible (even if rules changed)
        profile.eligibility_status = "eligible"
    else:
        profile.eligibility_status = "ineligible"
    
    # Ticket #2: Compute is_qualified
    # IMPORTANT: is_qualified is specifically for SCORE QUALIFICATION display in Scores Tab
    # It should ONLY reflect score-based validation (not docs, CCCD, etc.)
    # 
    # - is_qualified = True if scores meet threshold (no gpa_error)
    # - eligibility_status = "eligible" if ALL validations pass (scores + docs + CCCD)
    #
    # UI uses is_qualified for "Kết quả xét tuyển" panel
    # Workflow uses eligibility_status for submission eligibility
    profile.is_qualified = not gpa_error
    
    # Override: If status is approved/enrolled, always qualified
    if status in ["approved", "enrolled"]:
        profile.is_qualified = True
    
    profile.validation_errors = validation_errors
    
    # =========================================================================
    # 4. VALIDATION SUMMARY (Grouped Errors for UX)
    # =========================================================================
    profile.validation_summary = {
        "gpa": {
            "has_error": gpa_error,
            "label": f"GPA: {current_gpa:.1f}/{min_gpa}" if min_gpa > 0 else "GPA: N/A",
            "count": 1 if gpa_error else 0
        },
        "documents": {
            "has_error": len(doc_errors) > 0,
            "label": f"Tài liệu: {len(uploaded_doc_codes)}/{len(upload_required_docs)}",
            "count": len(doc_errors)
        },
        "personal": {
            "has_error": cccd_error,
            "label": "Thiếu CCCD/CMND" if cccd_error else "CCCD: OK",
            "count": 1 if cccd_error else 0
        }
    }
    
    # =========================================================================
    # 5. STEP STATUS (Architecture Compliant - Backend computes, FE renders)
    # =========================================================================
    # Required personal fields for step 1
    personal_required = ["full_name", "phone", "citizen_id"]
    personal_optional = ["email", "dob", "gender", "nationality", "ethnicity"]
    personal_required_filled = all(getattr(profile, f, None) for f in personal_required)
    personal_optional_filled = all(getattr(profile, f, None) for f in personal_optional)
    
    # Family
    has_family = profile.family_info and len(profile.family_info) > 0
    
    # Academic
    has_academic = profile.academic_history and len(profile.academic_history) > 0
    
    # Scores
    has_any_scores = bool(profile.subject_scores) if hasattr(profile, 'subject_scores') else False
    
    # Documents: Check if all uploaded docs have format confirmed
    # TODO: Add submission_format_confirmed tracking when ProfileDocument is updated
    docs_format_confirmed = True  # Placeholder for future enhancement
    
    step_status = {
        # Step 1: Personal Info
        1: "error" if cccd_error else ("success" if personal_optional_filled else "warning"),
        # Step 2: Family
        2: "success" if has_family else "warning",
        # Step 3: Academic History
        3: "success" if has_academic else "warning",
        # Step 4: Scores
        4: "error" if gpa_error else ("success" if has_any_scores else "warning"),
        # Step 5: Documents
        5: "error" if len(doc_errors) > 0 else ("warning" if not docs_format_confirmed else "success"),
        # Step 6: Tuition (display only)
        6: "success",
        # Step 7: Finalize
        7: "locked" if profile.eligibility_status == "ineligible" else "success",
    }
    profile.step_status = step_status
    
    # =========================================================================
    # 6. COMPLETION PERCENT
    # =========================================================================
    # Simple calculation based on required fields
    required_fields = [
        "full_name", "phone", "email", "dob", "gender", "citizen_id",
        "nationality", "ethnicity", "permanent_province"
    ]
    filled_count = sum(1 for f in required_fields if getattr(profile, f, None))
    base_completion = int((filled_count / len(required_fields)) * 50)  # 50% for basic info
    
    # Add 20% for family info
    family_completion = 20 if has_family else 0
    
    # Add 20% for academic history
    academic_completion = 20 if has_academic else 0
    
    # Add 10% for documents
    doc_completion = 0
    if documents is not None and upload_required_docs:
        uploaded_count = len(uploaded_doc_codes)
        doc_completion = int((uploaded_count / max(len(upload_required_docs), 1)) * 10)
    
    profile.completion_percent = min(100, base_completion + family_completion + academic_completion + doc_completion)
    
    # =========================================================================
    # 7. DOCUMENTS CHECKLIST (for frontend display)
    # Build from applied_rules + ProfileDocument data
    # =========================================================================
    all_mandatory_docs = applied_rules.get("mandatory_docs", [])
    doc_configs = applied_rules.get("doc_configs", {})  # {code: {requires_upload, submission_format}}
    
    # Create lookup of uploaded documents by code
    doc_by_code = {}
    if documents:
        for doc in documents:
            if doc.document_type:
                doc_by_code[doc.document_type.code] = {
                    "status": doc.status,
                    "file_path": doc.file_path,
                    "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                    "rejection_reason": doc.rejection_reason,
                    # submission_format_confirmed: True if manager verified the format
                    # Defaults to True for verified status, False otherwise
                    "submission_format_confirmed": doc.status == "verified"
                }
    
    # Build documents_checklist
    documents_checklist = []
    for i, doc_code in enumerate(all_mandatory_docs):
        config = doc_configs.get(doc_code, {})
        uploaded_doc = doc_by_code.get(doc_code, {})
        
        documents_checklist.append({
            "code": doc_code,
            "label": config.get("label", doc_code),
            "is_mandatory": True,
            "requires_upload": config.get("requires_upload", True),
            "submission_format": config.get("submission_format"),
            "status": uploaded_doc.get("status", "missing"),
            "file_path": uploaded_doc.get("file_path"),
            "uploaded_at": uploaded_doc.get("uploaded_at"),
            "rejection_reason": uploaded_doc.get("rejection_reason"),
            "submission_format_confirmed": uploaded_doc.get("submission_format_confirmed", False)
        })
    
    profile.documents_checklist = documents_checklist


async def _create_admission_milestone_consultation(
    db: AsyncSession,
    lead: models.Lead,
    event: str,
    actor: models.User,
    profile_id: Optional[int] = None,
    student_code: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """
    Create system consultation record for admission milestone.

    Following the Golden Rule:
    🔒 No Admission Event may occur without:
        1. Being tied to a Consultation Status
        2. Being tied to a Pipeline Stage
        3. Creating a Consultation record (even if SYSTEM-generated)

    This function:
    1. Looks up the event projection from ADMISSION_EVENT_PROJECTIONS
    2. Creates a SYSTEM consultation record
    3. Updates lead.pipeline_stage_id and lead.consultation_status_id
    4. Syncs lead.status via sync_lead_status_from_consultation()
    5. Logs state change to lead_status_history

    Args:
        db: Database session
        lead: Lead object to update
        event: Admission event identifier (e.g., "profile_submitted")
        actor: User who triggered the event (for audit trail)
        profile_id: Optional admission profile ID (for note template)
        student_code: Optional student code (for enrollment event)
        reason: Optional reason (for rejection/override events)

    Raises:
        ValueError: If event not found in ADMISSION_EVENT_PROJECTIONS

    Note:
        - This function does NOT commit - caller must commit
        - Respects terminal state guard (won't overwrite "converted" unless allowed)
        - Creates consultation with method="system" for filtering
    """
    from ..core.admission_event_mapping import validate_projection
    from ..core.status_mapping import sync_lead_status_from_consultation
    from .lead_service import _log_lead_state_change, _get_current_lead_state

    # Get canonical projection for this event
    projection = validate_projection(event)

    # Terminal state guard: Skip if lead already converted (unless allowed)
    if projection.skip_if_converted and lead.status == "converted":
        log.warning(
            "Skipping admission milestone consultation: lead already converted",
            lead_id=lead.id,
            event=event,
            current_status="converted",
            attempted_stage=projection.pipeline_stage_id,
            attempted_status=projection.consultation_status_id,
        )
        return

    # Capture old state for history logging
    old_state = _get_current_lead_state(lead)

    # Load consultation status object for sync
    consultation_status = await db.get(models.ConsultationStatus, projection.consultation_status_id)
    if not consultation_status:
        log.error(
            "ConsultationStatus not found for admission event",
            event=event,
            consultation_status_id=projection.consultation_status_id,
        )
        raise ResourceNotFoundError(
            f"Consultation status {projection.consultation_status_id} not found. "
            f"Please check consultation_status.csv seeding."
        )

    # Build consultation note from template
    note_template = projection.system_note_template
    note = note_template.format(
        profile_id=profile_id or "N/A",
        student_code=student_code or "N/A",
        reason=reason or "N/A"
    )

    # Create SYSTEM consultation record
    system_consultation = models.Consultation(
        lead_id=lead.id,
        officer_id=actor.id,
        consultation_status_id=projection.consultation_status_id,
        consultation_date=datetime.now(timezone.utc),
        method="system",  # ✅ Special marker for auto-generated records
        notes=note,
        duration_minutes=0,  # System consultations have no duration
    )
    db.add(system_consultation)

    # Update lead pipeline (stage + status)
    lead.consultation_status_id = projection.consultation_status_id
    lead.pipeline_stage_id = projection.pipeline_stage_id

    # Sync lead.status from consultation_status (Hybrid Approach)
    sync_lead_status_from_consultation(lead, consultation_status)

    # Update lead timestamp
    lead.updated_at = datetime.now(timezone.utc)

    # Log state change to lead_status_history
    new_state = _get_current_lead_state(lead)
    await _log_lead_state_change(
        db=db,
        lead=lead,
        old_state=old_state,
        new_state=new_state,
        changed_by=actor,
        reason=f"Admission event: {event}",
    )

    log.info(
        "Admission milestone consultation created",
        lead_id=lead.id,
        event=event,
        stage_id=projection.pipeline_stage_id,
        stage_name=projection.stage_name,
        status_id=projection.consultation_status_id,
        status_name=projection.consultation_name,
        profile_id=profile_id,
        actor_id=actor.id,
    )


def _extract_allowed_subject_codes(admission_path) -> List[str]:
    """
    Extract flat list of all allowed subject codes from criteria's subject groups.

    Critical for applied_rules snapshot to ensure deterministic scoring.
    Returns sorted list of unique subject codes from ALL linked subject groups.

    Args:
        admission_path: AdmissionPath object with loaded criteria and subject_group_mappings

    Returns:
        Sorted list of subject codes (e.g., ["chemistry", "english", "math", "physics"])

    Example:
        >>> path = get_admission_path_with_relations(path_id=1)
        >>> _extract_allowed_subject_codes(path)
        ["chemistry", "english", "literature", "math", "physics"]
    """
    if not admission_path or not admission_path.criteria:
        log.warning(
            "Cannot extract subject codes: admission_path or criteria is None",
            path_id=admission_path.id if admission_path else None,
        )
        return []

    subject_codes = set()
    for mapping in admission_path.criteria.subject_group_mappings:
        if mapping.subject_group:
            for group_mapping in mapping.subject_group.subject_mappings:
                if group_mapping.subject:
                    subject_codes.add(group_mapping.subject.code)

    return sorted(list(subject_codes))


def _serialize_subject_groups(admission_path) -> List[Dict[str, Any]]:
    """
    Serialize subject groups for audit trail in applied_rules.

    Preserves the original group structure for compliance and debugging.

    Args:
        admission_path: AdmissionPath object with loaded criteria and subject_group_mappings

    Returns:
        List of subject group dictionaries with code, name, and subjects

    Example:
        >>> _serialize_subject_groups(path)
        [
            {
                "code": "A00",
                "name": "Toán - Lý - Hóa",
                "subjects": ["math", "physics", "chemistry"]
            },
            {
                "code": "D01",
                "name": "Toán - Văn - Anh",
                "subjects": ["math", "literature", "english"]
            }
        ]
    """
    if not admission_path or not admission_path.criteria:
        log.warning(
            "Cannot serialize subject groups: admission_path or criteria is None",
            path_id=admission_path.id if admission_path else None,
        )
        return []

    groups = []
    for mapping in admission_path.criteria.subject_group_mappings:
        if mapping.subject_group:
            groups.append({
                "code": mapping.subject_group.code,
                "name": mapping.subject_group.name,
                "subjects": [
                    m.subject.code 
                    for m in mapping.subject_group.subject_mappings 
                    if m.subject
                ]
            })

    return groups


# ==============================================================================
# CRUD FUNCTIONS
# ==============================================================================

async def create_profile(
    db: AsyncSession,
    lead_id: int,
    admission_method_id: int,  # NEW: Required parameter for relational lookup
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Create new AdmissionProfile for a Lead.

    REFACTORED (Phase 2): Now uses AdmissionPath (relational) instead of JSONB.

    Workflow:
    1. Validate Lead exists and user has access (IDOR check)
    2. Check Lead has offering_id
    3. Check Lead doesn't already have admission_profile
    4. Find AdmissionPath for this offering + method
    5. Resolve documents via DocumentGroup (relational override logic)
    6. Build applied_rules snapshot from relational data
    7. Create AdmissionProfile with status='draft'

    Security:
    - IDOR: Lead.unit_id must equal current_user.unit_id
    - Business Rule: AdmissionPath must exist and be active
    - Uniqueness: Lead can only have one admission_profile

    Args:
        db: Database session
        lead_id: Lead ID
        admission_method_id: Admission method ID (e.g., hoc_ba, thpt)
        current_user: Current authenticated user

    Returns:
        Created AdmissionProfile

    Raises:
        ResourceNotFoundError: Lead, ProgramOffering, or AdmissionPath not found
        PermissionDeniedError: User doesn't have access to this lead
        BadRequest: Lead already has profile, or path not active
    """
    # ✅ SPRINT 6: Use Repository for lead lookup
    from app.repositories import AdmissionRepository, OrganizationRepository
    from app.repositories.admission_path_repository import AdmissionPathRepository
    from app.services.admission_path_service import AdmissionPathService
    
    admission_repo = AdmissionRepository(db)
    org_repo = OrganizationRepository(db)
    path_repo = AdmissionPathRepository(db)
    path_service = AdmissionPathService(db)

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
            # FAKE 404 for security (inference protection)
            raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")

    # ✅ SPRINT 7 FIX: Concurrency Control
    # Prevent race conditions where multiple requests create duplicate profiles
    async with acquire_redis_lock(f"lock:create_profile:{lead_id}", timeout=5):
        # Double-check inside lock (idempotency)
        # We need to re-fetch or check relationship if session was refreshed, 
        # but since we are in same session transaction, checking the validation below is fine 
        # IF we trust the session sync. 
        # Better: Re-query specifically for existence check to be safe.
        
        existing_profile = await admission_repo.get_profile_by_lead_id(lead_id)
        if existing_profile:
             raise ConflictError(f"Lead {lead_id} already has an admission profile")

        # Step 3: Check Lead has offering_id
        if not lead.offering_id:
            log.warning(
                "Lead has no offering_id (required for admission rules)",
                lead_id=lead_id,
            )
            raise BadRequest(
                "Lead must have a program offering assigned before creating admission profile"
            )

        # Step 4: Check Lead check (Redundant with Step 2 re-check but kept for flow)
        if lead.admission_profile:
             raise ConflictError(f"Lead {lead_id} already has an admission profile")

    # ✅ AUDIT FIX: Parent-child state guard - prevent profile creation for invalid lead states
    from app.utils.exceptions import BusinessRuleViolation

    INVALID_LEAD_STATUSES_FOR_ADMISSION = frozenset({
        "rejected",      # Explicitly rejected by officer
        "unqualified",   # Failed qualification criteria
        "converted",     # Already enrolled (shouldn't happen, but defensive)
    })

    if lead.status in INVALID_LEAD_STATUSES_FOR_ADMISSION:
        log.warning(
            "Attempt to create admission profile for lead in invalid status",
            lead_id=lead_id,
            lead_status=lead.status,
            user_id=current_user.id,
        )
        raise BusinessRuleViolation(
            f"Cannot create admission profile for lead with status '{lead.status}'. "
            f"Lead must be in active pipeline (new, assigned, contacted, qualified)."
        )

    # Warn if lead status is "new" (hasn't been contacted yet)
    if lead.status == "new":
        log.warning(
            "Creating admission profile for uncontacted lead (status=new)",
            lead_id=lead_id,
            user_id=current_user.id,
        )
        # Allow but log - might be valid for self-service admission

    # Step 5: Validate offering exists
    if not lead.offering:
        log.error(
            "ProgramOffering not found (data integrity issue)",
            lead_id=lead_id,
            offering_id=lead.offering_id,
        )
        raise ResourceNotFoundError(
            f"Program offering {lead.offering_id} not found"
        )

    # Step 6: Get published OfferingAcademicInfo for this offering
    academic_info_list = await org_repo.get_academic_info_history(
        lead.offering_id, 
        published_only=False
    )
    
    academic_info = next(
        (info for info in academic_info_list if info.is_published),
        academic_info_list[0] if academic_info_list else None
    )
    
    if not academic_info:
        log.warning(
            "No academic info found for offering",
            offering_id=lead.offering_id,
        )
        raise BadRequest(
            f"No published academic info found for offering {lead.offering_id}. "
            "Please configure academic year info before creating profiles."
        )

    # Step 7: Find AdmissionPath for this offering + method (NEW: Relational)
    admission_path = await path_repo.get_path_by_offering_and_method(
        academic_info_id=academic_info.id,
        admission_method_id=admission_method_id
    )

    if not admission_path:
        log.warning(
            "No admission path configured for offering + method",
            academic_info_id=academic_info.id,
            admission_method_id=admission_method_id,
        )
        raise BadRequest(
            f"No admission path configured for this offering and method (method_id={admission_method_id}). "
            "Please configure admission paths in the Config Console before creating profiles."
        )

    if admission_path.status != "active":
        log.warning(
            "Admission path is not active",
            path_id=admission_path.id,
            path_status=admission_path.status,
        )
        raise BadRequest(
            f"Admission path is not active (status: {admission_path.status}). "
            "Only active paths can be used for profile creation."
        )

    # Step 8: Check offering_type_id for document resolution
    offering_type_id = lead.offering.offering_type_id
    if not offering_type_id:
        log.warning(
            "Program offering has no offering_type_id",
            offering_id=lead.offering_id,
        )
        raise BadRequest(
            f"Program offering {lead.offering_id} has no offering_type_id configured. "
            "Please run backfill script or configure offering type."
        )

    # Step 9: Resolve documents using DocumentGroup (relational override logic)
    resolved_docs, _ = await path_service.resolve_documents_for_path(
        path=admission_path,
        offering_type_id=offering_type_id
    )

    # Step 10: Build mandatory_docs from resolved documents
    mandatory_docs = [
        doc.document_type_code 
        for doc in resolved_docs 
        if doc.is_mandatory
    ]

    # Step 11: Load AdmissionPath with criteria (eager load)
    full_path = await path_repo.get_by_id_with_relations(admission_path.id)
    
    # Step 12: Build applied_rules from relational data (SNAPSHOT)
    # ✅ CRITICAL FIX: Complete snapshot with ALL scoring parameters
    # Per ADMISSION_PROCESSING_FLOW_ANALYSIS.md Section 6.1
    applied_rules = {
        # =========================================================================
        # GROUP 1: Basic Criteria (from AdmissionCriteria)
        # =========================================================================
        "min_gpa": float(full_path.criteria.min_gpa) if full_path and full_path.criteria and full_path.criteria.min_gpa is not None else None,
        "min_score": float(full_path.criteria.min_score) if full_path and full_path.criteria and full_path.criteria.min_score is not None else None,

        # =========================================================================
        # GROUP 2: Scoring Configuration (CRITICAL - was missing!)
        # =========================================================================
        # How to select subjects: "fixed" | "best_n" | "any_n"
        "subject_selection_mode": full_path.criteria.subject_selection_mode if full_path and full_path.criteria else "fixed",

        # How to calculate score: "sum" | "average" | "weighted"
        "scoring_method": full_path.criteria.scoring_method if full_path and full_path.criteria else "sum",

        # Number of subjects required (1, 2, 3, or None for flexible)
        "required_subject_count": full_path.criteria.required_subject_count if full_path and full_path.criteria else None,

        # Minimum score per subject (điểm liệt)
        "min_subject_score": float(full_path.criteria.min_subject_score) if full_path and full_path.criteria and full_path.criteria.min_subject_score is not None else None,

        # Maximum possible score (for display/normalization)
        "max_possible_score": float(full_path.criteria.max_possible_score) if full_path and full_path.criteria and full_path.criteria.max_possible_score is not None else None,

        # =========================================================================
        # GROUP 3: Subject Validation (CRITICAL - was missing!)
        # =========================================================================
        # Flat list of ALL allowed subject codes (for input validation)
        "allowed_subject_codes": _extract_allowed_subject_codes(full_path),

        # Original subject groups (for audit trail and fixed mode)
        "subject_groups": _serialize_subject_groups(full_path),
        
        # =========================================================================
        # GROUP 4: Method Metadata (Updated Ticket #3)
        # =========================================================================
        "admission_method": admission_path.admission_method.code if admission_path.admission_method else None,
        "admission_method_id": admission_method_id,
        # Ticket #3: Explicit method type derivation
        # If no subject groups mapped -> "gpa_only" (Hoc ba 3 years)
        # If subject groups exist -> "subject_based" (Hoc ba 3 semesters / THPT / DGNL)
        "method_type": "subject_based" if full_path.criteria and full_path.criteria.subject_group_mappings else "gpa_only",

        # =========================================================================
        # GROUP 5: Document Requirements (Updated Ticket #4)
        # =========================================================================
        "mandatory_docs": mandatory_docs,
        "doc_configs": {
            doc.document_type_code: {
                "requires_upload": doc.requires_upload,
                "submission_format": doc.submission_format,
                "is_mandatory": doc.is_mandatory,
            }
            for doc in resolved_docs
        },
        # Ticket #4: Upload Configuration
        "upload_config": DEFAULT_UPLOAD_CONFIG,

        # =========================================================================
        # GROUP 6: Metadata
        # =========================================================================
        "snapshot_source": "relational",
        "admission_path_id": admission_path.id,
        "academic_info_id": academic_info.id,
    }



    # Step 13: Validate applied_rules has content
    if not mandatory_docs and not applied_rules.get("min_gpa") and not applied_rules.get("min_score"):
        log.warning(
            "Admission path has no criteria or documents configured",
            path_id=admission_path.id,
        )
        # Allow profile creation but log warning (path might be minimal config)

    # Step 14: Determine academic_year
    academic_year = academic_info.academic_year
    
    log.info(
        "Creating profile with relational AdmissionPath",
        lead_id=lead_id,
        academic_year=academic_year,
        admission_path_id=admission_path.id,
        admission_method_id=admission_method_id,
        mandatory_docs_count=len(mandatory_docs),
    )
    
    # Step 15: Create AdmissionProfile
    new_profile = models.AdmissionProfile(
        lead_id=lead_id,
        academic_year=academic_year,
        status="draft",
        applied_rules=applied_rules,  # Snapshot from relational data
        family_info=[],
        academic_history=[],
        # Pre-fill from Lead
        full_name=lead.full_name,
        phone=lead.phone,
        email=lead.email,
    )

    db.add(new_profile)
    try:
        await db.flush()  # Get ID without committing (router commits)
    except IntegrityError as e:
        log.error("IntegrityError during profile creation (race condition)", error=str(e))
        raise ConflictError(f"Lead {lead_id} already has an admission profile (detected at DB layer)")

    # Step 16: Initialize ProfileDocument records
    await admission_repo.initialize_documents_for_profile(
        profile_id=new_profile.id,
        document_type_codes=mandatory_docs
    )

    # Step 17: Reload with relationships for response
    new_profile = await admission_repo.reload_profile_with_lead(new_profile.id)

    # Calculate totals for response
    _calculate_and_update_totals(new_profile)

    log.info(
        "Admission profile created (relational flow)",
        profile_id=new_profile.id,
        lead_id=lead_id,
        user_id=current_user.id,
        snapshot_source="relational",
        admission_path_id=admission_path.id,
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
        AdmissionProfile with relationships loaded + computed frontend fields

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
    
    # =========================================================================
    # Phase 7: Compute Frontend Thin Client Fields
    # =========================================================================
    # Fetch documents for completion calculation
    documents = await admission_repo.get_all_documents(profile_id)
    _compute_frontend_fields(profile, current_user, documents)

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
        new_citizen_id = data["citizen_id"]

        # ✅ Validate citizen_id uniqueness within same academic_year (if changed)
        if new_citizen_id != profile.citizen_id:
            # Check if new citizen_id already exists in same year
            duplicate_profile = await admission_repo.check_citizen_id_exists(
                citizen_id=new_citizen_id,
                academic_year=profile.academic_year,
                exclude_profile_id=profile.id
            )

            if duplicate_profile:
                log.warning(
                    "Cannot update citizen_id: Duplicate in same academic year",
                    profile_id=profile.id,
                    new_citizen_id=new_citizen_id,
                    academic_year=profile.academic_year,
                    duplicate_profile_id=duplicate_profile.id,
                )
                raise ConflictError(
                    f"CCCD {new_citizen_id} đã được sử dụng bởi hồ sơ khác "
                    f"trong năm {profile.academic_year} (ID: {duplicate_profile.id})"
                )

            # Check if already enrolled as student
            existing_student = await admission_repo.check_citizen_id_enrolled(new_citizen_id)
            if existing_student:
                log.warning(
                    "Cannot update citizen_id: Already enrolled as student",
                    profile_id=profile.id,
                    new_citizen_id=new_citizen_id,
                    student_code=existing_student.student_code,
                )
                raise ConflictError(
                    f"CCCD {new_citizen_id} đã được sử dụng bởi học viên "
                    f"(Mã SV: {existing_student.student_code})"
                )

        profile.citizen_id = new_citizen_id

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
            raw_scores = scores_data["subject_scores"]
            
            # Normalization (Business Logic): 
            # Ensure subject codes are lowercase and stripped of whitespace
            normalized_scores = {
                k.lower().strip(): v 
                for k, v in raw_scores.items() 
                if k and v is not None
            }
            
            await admission_repo.update_profile_scores(profile.id, normalized_scores)
            
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

    # ✅ Fix: Re-compute validation errors/status with new scores
    _compute_frontend_fields(profile, current_user)

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
    
    # STRICT RULE: Check required subject count
    applied_rules = profile.applied_rules or {}
    required_count = applied_rules.get("required_subject_count", 3)
    
    current_count = len(target_scores) if target_scores else 0
    
    if current_count < required_count:
        # Incomplete scores -> Treat as 0.0 (Invalid)
        profile.total_score = 0.0
        profile.average_score = 0.0
        
        # Build map of partial scores for display, but totals are 0
        scores_map = {s.subject.code: float(s.score) for s in target_scores} if target_scores else {}
        
        profile.admission_scores = {
            "subject_scores": scores_map,
            "average_score": 0.0,
            "gpa": 0.0
        }
        return

    # Map scores to dict for service
    from decimal import Decimal
    target_scores_map = {s.subject.code: Decimal(str(s.score)) for s in target_scores}

    # ---------------------------------------------------------
    # IMPROVED LOGIC: Use AdmissionScoringService for calculation
    # ---------------------------------------------------------
    from .admission_scoring_service import AdmissionScoringService, ProfileStatus, SubjectSelectionMode, ScoringMethod
    from app.models.admission_config import AdmissionCriteria
    
    # 1. Reconstruct Criteria from Snapshot
    applied_rules = profile.applied_rules or {}
    snapshot_criteria = models.AdmissionCriteria(
        code=applied_rules.get("admission_method", {}).get("code", "SNAPSHOT"),
        min_gpa=float(applied_rules.get("min_gpa") or 0),
        min_score=float(applied_rules.get("min_score") or 0),
        min_subject_score=float(applied_rules.get("min_subject_score") or 0),
        required_subject_count=applied_rules.get("required_subject_count"),
        subject_selection_mode=applied_rules.get("subject_selection_mode", "fixed"),
        scoring_method=applied_rules.get("scoring_method", "sum"),
    )
    
    # 2. Prepare allowed subjects
    allowed_subjects = applied_rules.get("allowed_subject_codes")
    # Soft fallback for legacy profiles (shouldn't happen for new ones)
    if not allowed_subjects: 
         allowed_subjects = list(target_scores_map.keys())

    # 3. Calculate using robust engine
    score_result = AdmissionScoringService.calculate_score(
        criteria=snapshot_criteria,
        subject_scores=target_scores_map,
        allowed_subjects=allowed_subjects,
    )
    
    # Update transient fields
    profile.total_score = float(score_result.total_score)
    profile.average_score = float(score_result.average_score)

    # Update admission_scores schema field with detailed snapshot
    profile.admission_scores = {
        "subject_scores": target_scores_map,
        "total_score": profile.total_score,
        "average_score": profile.average_score,
        "gpa": profile.average_score,
        "snapshot_score": {
            "selected_subjects": score_result.selected_subjects,
            "selected_scores": {k: float(v) for k, v in score_result.selected_scores.items()},
            "status": score_result.status.value,
            "failure_reasons": score_result.failure_reasons
        }
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
    # ✅ CRITICAL FIX #2: Add pessimistic lock to prevent race conditions
    # Scenario: 2 officers submit same profile simultaneously
    # Without lock: Both pass status check, both update to "submitted"
    # With lock: Second request waits, then fails status check
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # Use selectinload to avoid "FOR UPDATE cannot be applied to nullable side of outer join"
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))  # ✅ Eager load Lead
        .with_for_update()  # ✅ CRITICAL: Acquire row lock
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check (after lock acquired)
    _check_admin_or_unit_access(profile, current_user)

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
    # Phase 6: Dynamic Admission Scoring Validation (Refactored)
    # ========================================

    # Use AdmissionScoringService for robust validation (Best N, Min Score, etc.)
    from .admission_scoring_service import AdmissionScoringService, ProfileStatus, SubjectSelectionMode, ScoringMethod
    from app.models.admission_config import AdmissionCriteria
    
    # 1. Reconstruct Criteria from Snapshot (applied_rules)
    # Note: applied_rules is a dict snapshot. We wrap it in a pseudo-model or Dict 
    # compatible with ScoringService if possible, or construct a temporary Criteria object.
    # Since Service expects a model, we populate one.
    
    snapshot_criteria = models.AdmissionCriteria(
        code=applied_rules.get("admission_method", {}).get("code", "SNAPSHOT"),
        min_gpa=float(applied_rules.get("min_gpa", 0)) if applied_rules.get("min_gpa") else None,
        min_score=float(applied_rules.get("min_score", 0)) if applied_rules.get("min_score") else None,
        min_subject_score=float(applied_rules.get("min_subject_score", 0)) if applied_rules.get("min_subject_score") else None,
        required_subject_count=applied_rules.get("required_subject_count"),
        subject_selection_mode=applied_rules.get("subject_selection_mode", "fixed"),
        scoring_method=applied_rules.get("scoring_method", "sum"),
        # subject_group_mappings are tricky from snapshot. 
        # For Phase 1/2 we assume "fixed" mode or explicit "subject_groups" list in snapshot.
    )

    # 2. Get Scores
    scores = await admission_repo.get_profile_scores(profile.id)
    subject_scores_map = {s.subject.code: Decimal(str(s.score)) for s in scores}
    
    # 3. Resolve Allowed Subjects
    # ✅ CRITICAL FIX: Strict validation - require allowed_subject_codes in snapshot
    # This field is now mandatory (added in create_profile fix)
    allowed_subjects = applied_rules.get("allowed_subject_codes")

    if not allowed_subjects:
        # ⚠️ Legacy Profile Compatibility Check
        # If profile was created before the fix, fallback to all scored subjects
        # but log a warning for admin attention
        log.warning(
            "Profile has incomplete snapshot - missing allowed_subject_codes. "
            "Using fallback to all scored subjects (legacy compatibility). "
            "This profile should be recreated for deterministic scoring.",
            profile_id=profile.id,
            lead_id=profile.lead_id,
            snapshot_source=applied_rules.get("snapshot_source"),
        )

        # TEMPORARY FALLBACK (for legacy profiles only)
        # New profiles created after this fix will always have allowed_subject_codes
        allowed_subjects = list(subject_scores_map.keys())

        if not allowed_subjects:
            raise BadRequest(
                "Cannot evaluate profile: No subject scores found and snapshot has no subject whitelist. "
                "Please add subject scores before submitting."
            )
    
    # 4. Calculate Score using Engine
    score_result = AdmissionScoringService.calculate_score(
        criteria=snapshot_criteria,
        subject_scores=subject_scores_map,
        allowed_subjects=allowed_subjects,
    )
    
    # 5. Handle Validation Results
    if score_result.status != ProfileStatus.VALID:
        # Collect failure reasons
        for reason in score_result.failure_reasons:
            errors.append(f"Điểm xét tuyển không đạt: {reason}")
            
        log.warning(
            "Scoring validation failed",
            profile_id=profile.id,
            reasons=score_result.failure_reasons,
            disqualification_codes=score_result.disqualification_codes
        )
    else:
        # Valid! Update profile with official calculated metrics
        # (transient or persistent depending on design - here updating admission_scores JSON)
        official_gpa = float(score_result.final_score) if score_result.final_score else 0.0
        
        # Log success
        log.info(
            "Scoring validation passed",
            profile_id=profile.id,
            final_score=official_gpa,
            selected_subjects=score_result.selected_subjects
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
        # Check in admission_profile table (other profiles IN THE SAME YEAR)
        duplicate_profile = await admission_repo.check_citizen_id_exists(
            citizen_id=profile.citizen_id,
            academic_year=profile.academic_year,  # ✅ UPDATED: Filter by year
            exclude_profile_id=profile.id
        )

        if duplicate_profile:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi hồ sơ khác "
                f"trong năm {profile.academic_year} (ID: {duplicate_profile.id})"
            )

        # Check in student table (already enrolled students)
        existing_student = await admission_repo.check_citizen_id_enrolled(profile.citizen_id)

        if existing_student:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi học viên "
                f"(Mã SV: {existing_student.student_code})"
            )

    # ✅ CRITICAL FIX #1: Submit should transition to SUBMITTED, not APPROVED/REJECTED
    # Per ADMISSION_STATE_MACHINE: draft → submitted (wait for Manager approval)
    # Validation errors should NOT change status - stay in draft for user to fix
    if errors:
        # Keep in draft - user needs to fix validation errors
        await db.flush()  # No status change

        log.warning(
            "Admission profile submission failed - validation errors",
            profile_id=profile_id,
            user_id=current_user.id,
            errors_count=len(errors),
            errors=errors,
        )

        return {
            "status": "draft",  # ✅ FIX: Stay in draft, not "rejected"
            "message": None,
            "validation_errors": errors,  # ✅ FIX: Match schema field name
        }
    else:
        # ✅ FIX: Submit validation passed → Move to SUBMITTED (not APPROVED)
        profile.status = "submitted"  # ✅ CRITICAL FIX: submitted, not approved
        profile.version += 1  # Increment version on status change

        # ✅ PIPELINE SYNC: Create system consultation for admission milestone
        if profile.lead:
            await _create_admission_milestone_consultation(
                db=db,
                lead=profile.lead,
                event="profile_submitted",
                actor=current_user,
                profile_id=profile_id,
            )

        await db.flush()

        log.info(
            "Admission profile submitted successfully",
            profile_id=profile_id,
            user_id=current_user.id,
            citizen_id=profile.citizen_id,
        )

        return {
            "status": "submitted",  # ✅ FIX: submitted status
            "message": "Hồ sơ đã được nộp thành công. Chờ phê duyệt từ Manager.",
            "validation_errors": None,  # ✅ FIX: Match schema field name
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
    from sqlalchemy import select
    admission_repo = AdmissionRepository(db)

    # ✅ CRITICAL FIX #2 & #3: Acquire row lock and check state atomically
    # Scenario: Admin enrolls profile while Lead confirms via magic link
    # Without lock: Both can modify status simultaneously
    # With lock: Operations are serialized
    from sqlalchemy.orm import selectinload
    
    # Use selectinload to avoid "FOR UPDATE cannot be applied to nullable side of outer join"
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))  # ✅ Eager load Lead
        .with_for_update()  # ✅ CRITICAL: Lock row for enrollment
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check (after lock acquired)
    _check_admin_or_unit_access(profile, current_user)

    # ✅ HIGH PRIORITY FIX #7: Idempotency check - return existing student if already enrolled
    # MUST be BEFORE status check to handle idempotent requests correctly
    # Prevents duplicate student creation if endpoint is called multiple times
    # This can happen if:
    # - Client retries on network timeout
    # - Multiple admins click "Enroll" simultaneously (despite lock, status is already 'enrolled')
    # - Background job + manual action race
    if profile.status == "enrolled":
        # Profile already enrolled - return existing student (idempotent operation)
        if profile.student:
            log.info(
                "Idempotent enroll: Profile already enrolled, returning existing student",
                profile_id=profile_id,
                student_id=profile.student.id,
                student_code=profile.student.student_code,
            )
            return {
                "student_id": profile.student.id,
                "student_code": profile.student.student_code,
                "enrollment_date": profile.student.enrollment_date,
            }
        else:
            # Data inconsistency: status is 'enrolled' but no student record exists
            log.error(
                "CRITICAL: Profile status is 'enrolled' but no student record found",
                profile_id=profile_id,
                status=profile.status,
            )
            raise ConflictError(
                f"Data inconsistency: Profile {profile_id} is marked as enrolled "
                "but has no associated student record. Please contact system administrator."
            )

    # Must be in approved or confirmed status
    # 'confirmed' = Lead confirmed via magic link, ready to enroll
    if profile.status not in ("approved", "confirmed", "overridden"):
        raise BadRequest(
            f"Cannot enroll student with profile status '{profile.status}'. "
            "Only approved, confirmed, or overridden profiles can be enrolled."
        )

    # ✅ CRITICAL FIX #3: Final citizen_id duplicate check INSIDE transaction
    # Prevents race condition where 2 enrolls pass validation check but both create Student
    # Check must be AFTER acquiring lock but BEFORE creating Student record
    if not profile.citizen_id:
        raise BadRequest("Cannot enroll: Profile has no citizen_id")

    duplicate_student = await admission_repo.check_citizen_id_enrolled(profile.citizen_id)
    if duplicate_student:
        log.error(
            "CRITICAL: Citizen ID duplicate detected at enrollment time",
            profile_id=profile_id,
            citizen_id=profile.citizen_id,
            existing_student_code=duplicate_student.student_code,
            existing_student_id=duplicate_student.id,
        )
        raise ConflictError(
            f"Cannot enroll: Citizen ID {profile.citizen_id} is already enrolled "
            f"as student {duplicate_student.student_code}. "
            "This profile may have been enrolled through a different process."
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

            # Step 5: ✅ PIPELINE SYNC: Create system consultation for enrollment milestone
            await _create_admission_milestone_consultation(
                db=db,
                lead=profile.lead,
                event="profile_enrolled",
                actor=current_user,
                profile_id=profile_id,
                student_code=student_code,
            )

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

    # ✅ CRITICAL FIX #4: VERSION CHECK (Optimistic Locking) - Now REQUIRED
    # Version is now mandatory in ApproveRequest schema (no longer optional)
    # This prevents race conditions where 2 managers approve/reject simultaneously
    if data["version"] != profile.version:
        log.warning(
            "Optimistic locking conflict: Version mismatch",
            profile_id=profile.id,
            expected_version=data["version"],
            actual_version=profile.version,
            user_id=approver.id,
        )
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

    # ✅ PIPELINE SYNC: Create system consultation for approval milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_approved",
            actor=approver,
            profile_id=profile.id,
        )

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

    # ✅ CRITICAL FIX #4: VERSION CHECK - Now REQUIRED (no longer optional)
    if data["version"] != profile.version:
        log.warning(
            "Optimistic locking conflict: Version mismatch in reject",
            profile_id=profile.id,
            expected_version=data["version"],
            actual_version=profile.version,
            user_id=rejector.id,
        )
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

    # ✅ PIPELINE SYNC: Create system consultation for rejection milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_rejected",
            actor=rejector,
            profile_id=profile.id,
            reason=data["reason"],
        )

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

    # ✅ PIPELINE SYNC: Create system consultation for resubmission milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_resubmitted",
            actor=officer,
            profile_id=profile.id,
        )

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

    # ✅ PIPELINE SYNC: Create system consultation for confirmation milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_confirmed",
            actor=applicant,
            profile_id=profile.id,
        )

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

    # ✅ PIPELINE SYNC: Create system consultation for override milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_overridden",
            actor=admin,
            profile_id=profile.id,
            reason=data["reason"],
        )

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
