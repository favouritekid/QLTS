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
from sqlalchemy.orm.attributes import flag_modified

from .. import models
from ..schemas.admission import DEFAULT_UPLOAD_CONFIG
from ..core.constants import UserRole
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    PermissionDeniedError,
    ConflictError,
)
from ..utils.masking import mask_citizen_id

log = structlog.get_logger(__name__)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _resolve_idor_filters(current_user: models.User) -> tuple[Optional[int], Optional[int]]:
    """
    Resolve IDOR filter parameters based on user role.

    Returns (unit_id, assigned_officer_id) for repository queries.
    - Admin: (None, None) — see all
    - Manager: (unit_id, None) — see unit
    - Officer: (unit_id, officer_id) — see only assigned
    """
    if current_user.role == UserRole.ADMIN:
        return None, None
    elif current_user.role == UserRole.MANAGER:
        return current_user.unit_id, None
    elif current_user.role == UserRole.OFFICER:
        return current_user.unit_id, current_user.id
    else:
        raise PermissionDeniedError(f"Unexpected role '{current_user.role}' for admission access")


def _check_idor_access(
    profile: models.AdmissionProfile,
    current_user: models.User,
) -> None:
    """
    3-tier IDOR Protection for admission profiles.

    Rules:
    - Admin: Full access to all profiles
    - Manager: Access profiles where lead.unit_id == user.unit_id
    - Officer: Access profiles where lead.assigned_officer_id == user.id AND lead.unit_id == user.unit_id

    Raises:
        ResourceNotFoundError: Returns 404 to prevent resource enumeration
    """
    if current_user.role == UserRole.ADMIN:
        return

    if not profile.lead:
        log.error(
            "Data integrity: profile without lead",
            profile_id=profile.id,
        )
        raise ResourceNotFoundError(f"Admission profile {profile.id} not found")

    if current_user.role == UserRole.MANAGER:
        if profile.lead.unit_id == current_user.unit_id:
            return
    elif current_user.role == UserRole.OFFICER:
        if (profile.lead.assigned_officer_id == current_user.id
                and profile.lead.unit_id == current_user.unit_id):
            return

    log.warning(
        "IDOR attempt: User tried to access profile without permission",
        user_id=current_user.id,
        user_role=current_user.role,
        user_unit_id=current_user.unit_id,
        profile_id=profile.id,
        profile_unit_id=profile.lead.unit_id if profile.lead else None,
        profile_officer_id=profile.lead.assigned_officer_id if profile.lead else None,
    )
    raise ResourceNotFoundError(f"Admission profile {profile.id} not found")


async def check_enrollment_fee_eligibility(
    db: AsyncSession,
    profile_id: int,
) -> None:
    """
    Fee Gate: Verify tuition fee is paid/waived before enrollment.

    Per FINANCE_MODULE_DESIGN.md Section 5.3 (Gate 2):
    - Enrollment MUST be blocked if tuition fee not cleared
    - Fee is "cleared" if status == 'paid' OR status == 'waived'
    - This check is ONLY enforced when ENABLE_FEE_VERIFICATION=True

    Args:
        db: Database session
        profile_id: AdmissionProfile ID

    Raises:
        BadRequest: If tuition fee not paid/waived

    Note:
        - Feature flag check should be done by caller
        - This function ONLY checks tuition fee, not application fee
          (application fee is Gate 1, enforced in approve_profile)
    """
    from app.config import settings
    from app.repositories.fee_repository import FeeRepository
    from app.models.finance.fee import FeeTypeEnum, FeeStatusEnum

    fee_repo = FeeRepository(db)

    # Get tuition fee for this profile
    fees = await fee_repo.get_by_profile_id(
        profile_id=profile_id,
        fee_type=FeeTypeEnum.tuition.value
    )

    if not fees:
        # No tuition fee record found - this could mean:
        # 1. Fee hasn't been calculated yet
        # 2. Fee module is not enabled for this profile
        # For now, we block enrollment if no fee record exists
        log.warning(
            "Fee gate check failed: No tuition fee record found",
            profile_id=profile_id,
        )
        raise BadRequest(
            "Cannot enroll: Tuition fee has not been calculated. "
            "Please calculate the fee before proceeding with enrollment."
        )

    # Check the most recent tuition fee (should only be one per year)
    fee = fees[0]

    # Fee must be paid or waived to proceed
    if fee.status not in (FeeStatusEnum.paid.value, FeeStatusEnum.waived.value):
        remaining = fee.remaining_amount
        log.warning(
            "Fee gate check failed: Tuition fee not cleared",
            profile_id=profile_id,
            fee_id=fee.id,
            fee_status=fee.status,
            remaining_amount=str(remaining),
        )
        raise BadRequest(
            f"Cannot enroll: Tuition fee not cleared. "
            f"Current status: {fee.status}, Remaining: {remaining:,.0f} VND. "
            "Please complete payment or apply for fee waiver before enrollment."
        )

    log.info(
        "Fee gate check passed: Tuition fee cleared",
        profile_id=profile_id,
        fee_id=fee.id,
        fee_status=fee.status,
    )


def _validate_scores(
    profile: models.AdmissionProfile,
    applied_rules: dict,
) -> tuple[bool, list[str], list[str]]:
    """
    Validate score requirements based on applied rules.
    Returns: (has_gpa_error, validation_errors_list, gpa_errors_list)
    """
    min_gpa = float(applied_rules.get("min_gpa") or 0)
    req_count_val = applied_rules.get("required_subject_count")
    required_count = int(req_count_val) if req_count_val is not None else 3
    
    # Get current score count from relational data
    scores_map = {s.subject.code: float(s.score) for s in profile.subject_scores} if profile.subject_scores else {}
    current_count = len(scores_map)
    
    method_type = applied_rules.get("method_type", "subject_based")
    current_gpa = profile.average_score or 0
    min_score = float(applied_rules.get("min_score") or 0)
    current_total = profile.total_score or 0

    validation_errors = []
    gpa_errors = []
    gpa_error = False

    if method_type == "gpa_only":
        # GPA-Only: Check average_score only
        if min_gpa > 0 and current_gpa < min_gpa:
            error_msg = f"GPA không đạt: {current_gpa:.2f} < {min_gpa}"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True

    elif method_type == "combined":
        # Combined: Check BOTH total_score AND average_score
        # First: Check subject count
        if current_count < required_count:
            error_msg = f"Chưa nhập đủ đầu điểm ({current_count}/{required_count})"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True
        else:
            # Check total_score
            if min_score > 0 and current_total < min_score:
                error_msg = f"Tổng điểm thấp hơn điểm chuẩn: {current_total:.2f} < {min_score}"
                validation_errors.append(error_msg)
                gpa_errors.append(error_msg)
                gpa_error = True
            # Check GPA (even if total passed)
            if min_gpa > 0 and current_gpa < min_gpa:
                error_msg = f"GPA không đạt: {current_gpa:.2f} < {min_gpa}"
                validation_errors.append(error_msg)
                gpa_errors.append(error_msg)
                gpa_error = True

    else:
        # subject_based, hoc_ba, tot_nghiep, etc.: Check total_score only
        if current_count < required_count:
            error_msg = f"Chưa nhập đủ đầu điểm ({current_count}/{required_count})"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True
        elif min_score > 0 and current_total < min_score:
            error_msg = f"Tổng điểm thấp hơn điểm chuẩn: {current_total:.2f} < {min_score}"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True
            
    return gpa_error, validation_errors, gpa_errors


def _validate_documents(
    profile: models.AdmissionProfile,
    documents: list | None,
    applied_rules: dict,
) -> tuple[list[str], list[str], set[str], list[str]]:
    """
    Validate document requirements.
    Returns: (doc_errors_list, validation_errors_list, uploaded_doc_codes_set, upload_required_docs_list)
    """
    upload_required_docs = applied_rules.get("upload_required_docs", applied_rules.get("mandatory_docs", []))
    doc_errors = []
    validation_errors = []
    uploaded_doc_codes = set()
    
    if documents is not None:
        # Verified/paper_submitted documents are ALWAYS valid
        # Only check file_path for "uploaded" status
        uploaded_doc_codes = {
            doc.document_type.code for doc in documents
            if doc.status in ["verified", "paper_submitted"] or (doc.file_path and doc.status == "uploaded")
        }
        
        # Log document validation details (preserved from original code)
        log.debug(
            "Document validation check",
            profile_id=profile.id,
            upload_required_docs=upload_required_docs,
            uploaded_doc_codes=list(uploaded_doc_codes),
            total_documents=len(documents),
        )
        
        for doc_code in upload_required_docs:
            if doc_code not in uploaded_doc_codes:
                doc_errors.append(doc_code)
                validation_errors.append(f"Thiếu tài liệu bắt buộc: {doc_code}")
                
    return doc_errors, validation_errors, uploaded_doc_codes, upload_required_docs


def _validate_personal_info(
    profile: models.AdmissionProfile,
) -> tuple[list[str], list[str]]:
    """
    Validate mandatory personal fields.
    Returns: (missing_fields_list, validation_errors_list)
    """
    missing_personal = []
    validation_errors = []
    
    field_map = {
        "full_name": "Họ tên",
        "dob": "Ngày sinh",
        "gender": "Giới tính",
        "citizen_id": "Số CCCD/CMND",
        "nationality": "Quốc tịch",
        "ethnicity": "Dân tộc",
        "phone": "Số điện thoại",
        "place_of_birth": "Nơi sinh"
    }
    
    for field, label in field_map.items():
        if not getattr(profile, field, None):
            missing_personal.append(label)
            validation_errors.append(f"Thiếu thông tin cá nhân: {label}")
            
    return missing_personal, validation_errors


def _compute_completion_percent(
    profile: models.AdmissionProfile,
    documents: list = None,
) -> int:
    """
    Compute completion_percent for a profile from step status weights.

    Pure helper — no current_user needed. Runs validation helpers internally
    but does NOT set any transient fields on the profile except completion_percent.

    Args:
        profile: AdmissionProfile with subject_scores and lead loaded
        documents: Optional list of ProfileDocument

    Returns:
        Completion percentage (0-100)
    """
    applied_rules = profile.applied_rules or {}
    gpa_error, _, _ = _validate_scores(profile, applied_rules)
    doc_errors, _, _, _ = _validate_documents(profile, documents, applied_rules)
    missing_personal, _ = _validate_personal_info(profile)

    # Eligibility (simplified — mirrors _compute_frontend_fields logic)
    has_any_validation_error = gpa_error or len(doc_errors) > 0 or len(missing_personal) > 0
    is_ineligible = has_any_validation_error and profile.status not in ("approved", "enrolled")

    cccd_error = not profile.citizen_id
    personal_required = ["full_name", "phone", "citizen_id"]
    personal_optional = ["email", "dob", "gender", "nationality", "ethnicity"]
    personal_required_filled = all(getattr(profile, f, None) for f in personal_required)
    personal_optional_filled = all(getattr(profile, f, None) for f in personal_optional)
    has_family = profile.family_info and len(profile.family_info) > 0
    has_academic = profile.academic_history and len(profile.academic_history) > 0
    has_any_scores = bool(profile.subject_scores) if hasattr(profile, "subject_scores") else False

    docs_format_confirmed = True
    if documents is not None:
        for doc in documents:
            if doc.status == "uploaded" and doc.file_path:
                docs_format_confirmed = False
                break

    step_status = {
        1: "error" if (cccd_error or not personal_required_filled) else ("success" if personal_optional_filled else "warning"),
        2: "success" if has_family else "warning",
        3: "success" if has_academic else "warning",
        4: "error" if gpa_error else ("success" if has_any_scores else "warning"),
        5: "error" if len(doc_errors) > 0 else ("warning" if not docs_format_confirmed else "success"),
        6: "success",
        7: "locked" if is_ineligible else "success",
    }

    step_weights = {1: 14, 2: 14, 3: 14, 4: 15, 5: 15, 6: 14, 7: 14}
    completion = 0
    for step_num, weight in step_weights.items():
        state = step_status.get(step_num, "locked")
        if state == "success":
            completion += weight
        elif state == "warning":
            completion += int(weight * 0.5)
    return min(100, completion)


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
        current_user: Current authenticated user (for role-based permissions). None for debug.
        documents: Optional list of ProfileDocument (to avoid re-fetching)
    """
    status = profile.status
    user_role = current_user.role                                   
    is_admin = user_role == UserRole.ADMIN                          
    is_manager = user_role == UserRole.MANAGER                      
    is_officer = user_role == UserRole.OFFICER


    # Check if user owns this profile (for applicant self-actions)
    is_owner = (profile.lead
                and profile.lead.assigned_officer_id is not None
                and profile.lead.assigned_officer_id == current_user.id)

    # =========================================================================
    # 1. PERMISSIONS (computed from role + status + Casbin-like rules)
    # =========================================================================
    _is_dropped = getattr(profile, "is_dropped", False)
    permissions = {
        "edit": status in ["draft", "rejected", "revision_requested"] and (is_owner or is_manager or is_admin),
        "save": status in ["draft", "rejected", "revision_requested"] and (is_owner or is_manager or is_admin),
        "submit": status == "draft" and (is_owner or is_manager or is_admin),
        "approve": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        "reject": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        "request_revision": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        "resubmit": status in ["rejected", "revision_requested"] and (is_owner or is_manager or is_admin),
        "enroll": status in ["confirmed", "overridden"] and (is_owner or is_manager or is_admin),
        "drop": status == "enrolled" and not _is_dropped and (is_manager or is_admin),
        "claim": (status in ["submitted", "resubmitted"] and (is_manager or is_admin)
                  and not profile.assigned_reviewer_id),
        "unclaim": (bool(profile.assigned_reviewer_id)
                    and (profile.assigned_reviewer_id == current_user.id or is_admin)),
        "delete": status == "draft" and is_admin,
        "view": True,
    }
    profile.permissions = permissions
    
    # =========================================================================
    # 2. AVAILABLE ACTIONS (list of action names that are currently allowed)
    # =========================================================================
    profile.available_actions = [action for action, allowed in permissions.items() if allowed]

    # Denormalized display names (avoid N+1 in frontend)
    # ⚠️ Use __dict__.get() instead of hasattr/getattr to avoid triggering
    # SQLAlchemy lazy-load from a sync function (raises MissingGreenlet in async session).
    # Callers MUST eager-load these relationships via selectinload() before reaching here.
    _reviewer = profile.__dict__.get("assigned_reviewer")
    profile.assigned_reviewer_name = _reviewer.full_name if _reviewer else None

    _lead = profile.__dict__.get("lead")
    _officer = _lead.__dict__.get("assigned_officer") if _lead else None
    profile.assigned_officer_name = _officer.full_name if _officer else None

    # =========================================================================
    # 3. ELIGIBILITY STATUS & VALIDATION ERRORS
    # =========================================================================
    applied_rules = profile.applied_rules or {}
    
    # Set snapshot_score if available (computed by _calculate_and_update_totals)
    if not hasattr(profile, 'snapshot_score') or profile.snapshot_score is None:
        profile.snapshot_score = None
    
    # --- Execute Validation Helpers ---
    gpa_error, score_ve, gpa_errors = _validate_scores(profile, applied_rules)
    doc_errors, doc_ve, uploaded_doc_codes, upload_required_docs = _validate_documents(profile, documents, applied_rules)
    missing_personal, personal_ve = _validate_personal_info(profile)
    
    # Aggregate validation errors
    validation_errors = score_ve + doc_ve + personal_ve
    
    # Track CCCD error for backward compatibility with step_status logic
    cccd_error = not profile.citizen_id
    
    # Determine eligibility status
    if len(validation_errors) == 0:
        profile.eligibility_status = "eligible"
    elif status in ["approved", "enrolled"]:
        profile.eligibility_status = "eligible"
    else:
        profile.eligibility_status = "ineligible"
    
    # Ticket #2: Compute is_qualified
    profile.is_qualified = not gpa_error
    if status in ["approved", "enrolled"]:
        profile.is_qualified = True
    
    profile.validation_errors = validation_errors

    # =========================================================================
    # 4. VALIDATION SUMMARY (Grouped Errors for UX)
    # =========================================================================
    # Calculate GPA label for summary
    min_gpa = float(applied_rules.get("min_gpa") or 0)
    current_gpa = profile.average_score or 0
    personal_error_count = len(missing_personal)
    
    profile.validation_summary = {
        "gpa": {
            "has_error": len(gpa_errors) > 0,
            "label": f"GPA: {current_gpa:.1f}/{min_gpa}" if min_gpa > 0 else "GPA: N/A",
            "count": len(gpa_errors)
        },
        "documents": {
            "has_error": len(doc_errors) > 0,
            "label": f"Tài liệu: {len(uploaded_doc_codes)}/{len(upload_required_docs)}",
            "count": len(doc_errors)
        },
        "personal": {
            "has_error": personal_error_count > 0,
            "label": f"Thiếu {personal_error_count} thông tin cá nhân" if personal_error_count > 0 else "Thông tin cá nhân: OK",
            "count": personal_error_count
        }
    }

    # =========================================================================
    # 4.1 GROUPED VALIDATION ERRORS (Enhanced UX - Categorized Display)
    # =========================================================================
    profile.grouped_validation_errors = {
        "personal_info": {
            "category": "Thông tin cá nhân",
            "errors": personal_ve, # Use the computed list from helper
            "count": len(personal_ve)
        },
        "documents": {
            "category": "Tài liệu",
            "errors": [f"Thiếu tài liệu bắt buộc: {doc_code}" for doc_code in doc_errors],
            "count": len(doc_errors)
        },
        "scores": {
            "category": "Điểm số",
            "errors": gpa_errors,
            "count": len(gpa_errors)
        }
    }

    # =========================================================================
    # 4.2 SCORE SNAPSHOT STATUS (Thin Client Compliance - Ticket #5)
    # Backend computes pass/fail for each subject and total score
    # Frontend ONLY renders, never calculates
    # =========================================================================
    min_subject_score = float(applied_rules.get("min_subject_score") or 0)
    min_score = float(applied_rules.get("min_score") or 0)
    total_score = profile.total_score
    subject_scores = {s.subject.code: float(s.score) for s in profile.subject_scores} if profile.subject_scores else {}

    # Compute subject pass/fail statuses
    subject_statuses = {}
    for code, score in subject_scores.items():
        if score is not None:
            # Pass if score >= min_subject_score (0 threshold means always pass)
            subject_statuses[code] = "passing" if score >= min_subject_score else "failing"
        else:
            subject_statuses[code] = None  # No score yet

    # Compute total score status
    total_status = None
    if total_score is not None:
        # Pass if total >= min_score (0 threshold means always pass)
        total_status = "passing" if total_score >= min_score else "failing"

    profile.score_snapshot_status = {
        "total_status": total_status,
        "subject_statuses": subject_statuses,
        "min_subject_score": min_subject_score,
        "min_score": min_score,
    }
    
    # =========================================================================
    # 5. STEP STATUS (Architecture Compliant - Backend computes, FE renders)
    # =========================================================================
    # Required personal fields for step 1 check
    personal_required = ["full_name", "phone", "citizen_id"]
    personal_optional = ["email", "dob", "gender", "nationality", "ethnicity"]
    personal_required_filled = all(getattr(profile, f, None) for f in personal_required)
    personal_optional_filled = all(getattr(profile, f, None) for f in personal_optional)
    
    # Family
    has_family = profile.family_info and len(profile.family_info) > 0
    
    # Academic
    has_academic = profile.academic_history and len(profile.academic_history) > 0
    
    has_any_scores = bool(profile.subject_scores) if hasattr(profile, 'subject_scores') else False

    # ✅ FIX: Documents format confirmation check
    # Check if all uploaded documents have been verified by manager or confirmed as paper submitted
    docs_format_confirmed = True
    if documents is not None:
        for doc in documents:
            # If document is uploaded but not yet verified/paper_submitted, format not confirmed
            if doc.status == "uploaded" and doc.file_path:
                docs_format_confirmed = False
                break

    step_status = {
        # Step 1: Personal Info
        1: "error" if (cccd_error or not personal_required_filled) else ("success" if personal_optional_filled else "warning"),
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
    # 6. COMPLETION PERCENT (delegates to shared pure helper)
    # =========================================================================
    profile.completion_percent = _compute_completion_percent(profile, documents)
    
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
                    "submission_format_confirmed": doc.status == "verified",
                    "label_from_db": doc.document_type.name,
                }
    
    # Build documents_checklist
    documents_checklist = []
    for i, doc_code in enumerate(all_mandatory_docs):
        config = doc_configs.get(doc_code, {})
        uploaded_doc = doc_by_code.get(doc_code, {})
        
        documents_checklist.append({
            "code": doc_code,
            "label": config.get("label") or uploaded_doc.get("label_from_db") or doc_code,
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

    # ✅ Ticket #3.1: Document Status Summary (Backend Computed)
    # Calculate stats for Thin Client compliance
    if documents is not None:
         mandatory_docs = [doc for doc in documents if doc.document_type and doc.document_type.code in upload_required_docs]
         
         # Count based on status
         submitted_count = len([d for d in mandatory_docs if d.status in ["uploaded", "verified", "paper_submitted"]])
         verified_count = len([d for d in mandatory_docs if d.status == "verified"])
         mandatory_count = len(upload_required_docs)
         missing_count = len(doc_errors) # Already computed via validation helper
         
         profile.document_stats = {
             "submitted_count": submitted_count,
             "verified_count": verified_count, 
             "mandatory_count": mandatory_count,
             "missing_count": missing_count
         }

    # =========================================================================
    # 8. EXECUTIVE SUMMARY (Dashboard Overview)
    # =========================================================================
    # Provides high-level status summary for dashboard display
    # Frontend uses this to show overall progress and next actions

    # Count steps by status
    step_counts = {"success": 0, "warning": 0, "error": 0, "locked": 0}
    for step_state in step_status.values():
        step_counts[step_state] = step_counts.get(step_state, 0) + 1

    # Determine overall status
    has_errors = step_counts["error"] > 0
    has_warnings = step_counts["warning"] > 0
    has_locked = step_counts["locked"] > 0

    if has_errors or has_locked:
        overall_status = "incomplete"  # Blocking issues exist
    elif has_warnings:
        overall_status = "warning"  # Optional fields missing
    else:
        overall_status = "ready"  # All steps complete

    # Identify critical blockers (errors that prevent submission)
    critical_blockers = []
    if personal_error_count > 0:
        critical_blockers.append(f"Thiếu {personal_error_count} thông tin cá nhân bắt buộc")
    if len(doc_errors) > 0:
        critical_blockers.append(f"Thiếu {len(doc_errors)} tài liệu bắt buộc")
    if gpa_error:
        critical_blockers.append("Điểm số chưa đạt yêu cầu")

    # Identify warnings (non-blocking issues)
    warning_messages = []
    if not has_family:
        warning_messages.append("Chưa điền thông tin gia đình")
    if not has_academic:
        warning_messages.append("Chưa điền lịch sử học tập")
    if not docs_format_confirmed:
        warning_messages.append("Một số tài liệu chưa được xác nhận định dạng")

    # Suggest next action
    if step_status[1] == "error":
        next_action = "Hoàn thiện thông tin cá nhân bắt buộc"
    elif step_status[4] == "error":
        next_action = "Nhập điểm số đạt yêu cầu"
    elif step_status[5] == "error":
        next_action = "Tải lên tài liệu bắt buộc"
    elif has_warnings:
        next_action = "Hoàn thiện thông tin còn thiếu (không bắt buộc)"
    elif profile.eligibility_status == "eligible" and status == "draft":
        next_action = "Kiểm tra và nộp hồ sơ"
    else:
        next_action = "Hồ sơ đã hoàn tất"

    # Can submit only if eligible and in draft status
    can_submit = profile.eligibility_status == "eligible" and status == "draft"

    profile.executive_summary = {
        "overall_status": overall_status,
        "completion_percent": profile.completion_percent,
        "step_summary": step_counts,
        "critical_blockers": critical_blockers,
        "warnings": warning_messages,
        "next_action": next_action,
        "can_submit": can_submit,
    }

    # =========================================================================
    # 9. SENSITIVE DATA MASKING (Security & Privacy Compliance)
    # =========================================================================
    # Mask CCCD for display purposes - show only last 4 digits
    # Full citizen_id is still available for form editing
    profile.citizen_id_masked = mask_citizen_id(profile.citizen_id)


async def _populate_response_fields(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    current_user: Optional[models.User],
    *,
    documents: Optional[List[models.ProfileDocument]] = None,
) -> None:
    """Populate transient computed fields on a profile for API response serialization.

    Call this AFTER ``await db.flush()`` and BEFORE returning from any mutation
    function whose return value is serialized via ``AdmissionProfileResponse``.
    Without this call, computed fields (``permissions``, ``available_actions``,
    ``eligibility_status``, ``step_status``, ``completion_percent``,
    ``validation_errors``, ``assigned_officer_name``, ``assigned_reviewer_name``)
    silently fall back to schema defaults — making mutation responses diverge
    from subsequent ``GET`` responses.

    Args:
        db: AsyncSession used to (optionally) load fresh documents.
        profile: AdmissionProfile mutated in-place by ``_compute_frontend_fields``.
        current_user: Acting user. May be ``None`` for system callbacks (e.g. a
            future payment gateway hitting ``record_application_fee_payment``
            without a user context). When ``None`` the helper is a no-op:
            computed fields stay at schema defaults, which is acceptable for
            non-user-facing flows because there is no UI rendering that needs
            ``permissions``.
        documents: Optional pre-loaded list of ``ProfileDocument``. If ``None``
            the helper fetches them via ``AdmissionRepository.get_all_documents``.
            Pass when documents are already loaded (e.g. after
            ``reload_profile_with_lead``) to avoid a redundant query.

    Requires ``profile.lead`` (with nested ``lead.assigned_officer``) and
    ``profile.assigned_reviewer`` to already be eager-loaded by the caller —
    use the nested ``selectinload`` pattern from ``update_profile`` or the
    ``get_admission_for_manager`` / ``get_admission_for_user`` dependencies.
    Missing eager-loads will silently produce ``null`` denormalized name fields
    rather than crash, because ``_compute_frontend_fields`` uses
    ``profile.__dict__.get(...)``.
    """
    if current_user is None:
        # System callback path: no role/permissions to compute. Skip silently.
        return

    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Populate transient score fields (average_score, total_score, snapshot_score,
    # admission_scores). _compute_frontend_fields → _validate_scores reads these
    # via direct attribute access and would AttributeError on a freshly DB-loaded
    # profile. Mirror update_profile's pattern: fetch fresh scores then compute.
    fresh_scores = await admission_repo.get_profile_scores(profile.id)
    _calculate_and_update_totals(profile, scores=fresh_scores)

    if documents is None:
        documents = await admission_repo.get_all_documents(profile.id)

    _compute_frontend_fields(profile, current_user, documents)


async def _create_admission_milestone_consultation(
    db: AsyncSession,
    lead: models.Lead,
    event: str,
    actor: Optional[models.User] = None,
    profile_id: Optional[int] = None,
    student_code: Optional[str] = None,
    reason: Optional[str] = None,
    fallback_officer_id: Optional[int] = None,
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
            admission_event=event,
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
            admission_event=event,
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
    # Resolution order: actor > lead.assigned_officer > fallback_officer_id
    officer_id = (
        actor.id if actor
        else lead.assigned_officer_id
        or fallback_officer_id
    )
    if officer_id is None:
        log.error(
            "Cannot create milestone consultation: no officer resolvable",
            lead_id=lead.id,
            admission_event=event,
        )
        raise BusinessRuleViolation(
            "Hồ sơ chưa sẵn sàng để xử lý: không xác định được cán bộ phụ trách. "
            "Vui lòng liên hệ nhà trường."
        )
    system_consultation = models.Consultation(
        lead_id=lead.id,
        officer_id=officer_id,
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
        admission_event=event,
        stage_id=projection.pipeline_stage_id,
        stage_name=projection.stage_name,
        status_id=projection.consultation_status_id,
        status_name=projection.consultation_name,
        profile_id=profile_id,
        actor_id=actor.id if actor else None,
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
        ResourceNotFoundError: User doesn't have access to this lead (IDOR protection)
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

    # Step 2: IDOR Check (3-tier)
    if current_user.role != UserRole.ADMIN:
        if lead.unit_id != current_user.unit_id:
            log.warning(
                "IDOR attempt: User tried to create profile for lead in different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                lead_id=lead_id,
                lead_unit_id=lead.unit_id,
            )
            raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")

        # C1: Officer-level IDOR — block creating profile for lead assigned to another officer
        if current_user.role == UserRole.OFFICER:
            if lead.assigned_officer_id and lead.assigned_officer_id != current_user.id:
                log.warning(
                    "IDOR attempt: Officer tried to create profile for lead assigned to another officer",
                    user_id=current_user.id,
                    lead_id=lead_id,
                    assigned_officer_id=lead.assigned_officer_id,
                )
                raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")
            # Auto-assign officer if NULL and same unit
            if lead.assigned_officer_id is None:
                lead.assigned_officer_id = current_user.id

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
        # "rejected",      # REMOVED: Allow re-engagement with rejected leads
        # "unqualified",   # REMOVED: Allow re-engagement with unqualified leads
        "converted",       # Already enrolled (shouldn't happen, but defensive)
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
            f"Lead must be in active pipeline (new, assigned, contacted, qualified) or be re-engaged."
        )

    # Note: If lead is rejected/unqualified, proceeding here effectively re-opens them via admission process.


    # =========================================================================
    # ✅ EDGE CASE #9 FIX: Validate Consultation Completeness
    # Enforces workflow: Lead → Consultation (with status) → Admission
    # Uses ACTUAL consultation data, not just cached fields on Lead
    # =========================================================================

    # Step 4a: Get latest consultation (actual DB query for accuracy)
    latest_consultation = await admission_repo.get_latest_consultation_for_lead(lead_id)

    if not latest_consultation:
        log.warning(
            "Attempt to create admission profile for lead without consultations",
            lead_id=lead_id,
            consultation_count=lead.consultation_count,
            user_id=current_user.id,
        )
        raise BusinessRuleViolation(
            "Chưa thể tạo hồ sơ xét tuyển: Lead chưa có lịch sử tư vấn. "
            "Vui lòng thêm ít nhất 1 lần tư vấn trước khi tạo hồ sơ."
        )

    # Step 4b: Validate consultation has a status assigned
    if not latest_consultation.consultation_status_id:
        log.warning(
            "Attempt to create admission profile with incomplete consultation",
            lead_id=lead_id,
            consultation_id=latest_consultation.id,
            has_status=False,
            user_id=current_user.id,
        )
        raise BusinessRuleViolation(
            "Chưa thể tạo hồ sơ xét tuyển: Lần tư vấn gần nhất chưa cập nhật kết quả. "
            "Vui lòng chọn trạng thái tư vấn (VD: 'Có nhu cầu', 'Đồng ý tư vấn') trước khi tạo hồ sơ."
        )

    # Step 4c: Validate consultation status is not a "universal" activity-only status
    # Universal statuses (e.g., "Không nghe máy", "Nhắn tin không phản hồi") are
    # activity markers, not pipeline progression indicators
    if latest_consultation.consultation_status and latest_consultation.consultation_status.is_universal:
        status_name = latest_consultation.consultation_status.name
        log.warning(
            "Attempt to create admission profile with universal/activity-only status",
            lead_id=lead_id,
            consultation_id=latest_consultation.id,
            status_id=latest_consultation.consultation_status_id,
            status_name=status_name,
            user_id=current_user.id,
        )
        raise BusinessRuleViolation(
            f"Chưa thể tạo hồ sơ xét tuyển: Trạng thái hiện tại '{status_name}' chỉ là ghi nhận hoạt động, "
            "chưa phải kết quả tư vấn. Vui lòng cập nhật trạng thái phản ánh kết quả tư vấn thực tế "
            "(VD: 'Có nhu cầu tìm hiểu', 'Đồng ý tư vấn', 'Từ chối tư vấn')."
        )

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

    # ✅ FIX Finding 1.2: Check if Admission Method is Active
    # We need to access the admission_method relation from the path
    # Assuming path.admission_method is eager loaded in repository or exists
    # If not loaded, we rely on the repository ensuring it returns valid paths,
    # but explicit check is safer.
    # Since get_path_by_offering_and_method likely joins admission_method, we check here.
    if admission_path.admission_method and not admission_path.admission_method.is_active:
         log.warning(
            "Attempt to create profile with inactive admission method",
            method_id=admission_method_id,
            is_active=admission_path.admission_method.is_active
        )
         raise BadRequest(
            f"Phương thức tuyển sinh '{admission_path.admission_method.name}' đang tạm dừng hoặc không hoạt động."
        )

    # ✅ FIX Finding 1.2 (Strict): Validate Academic Year consistency (Lead Match Logic)
    # Ensure the profile created belongs to the same academic year as the Lead's recruitment cycle
    # Lead -> Offering -> AcademicInfo (from lead.offering_id)
    # Profile -> Path -> AcademicInfo
    # In this function, we derived path FROM lead's offering academic_info, so by definition they match.
    # However, if Lead has an explicit 'academic_year' field (denormalized), we shout compare.
    # Currently Lead model doesn't show 'academic_year', it links to Offering.
    # So the check `academic_info.id == lead.offering.current_academic_info_id` is implicit in Step 6 logic.
    
    # We add a guard to ensure we are not creating a profile for a PAST year if the lead is new
    # But since we use get_academic_info_history(published_only=False), we might pick an old one?
    # Step 6 logic: `info.is_published` -> likely the current active one.
    
    # Let's enforce that the selected academic_info is indeed the CURRENT one for the offering
    # unless specific override logic exists.
    if not academic_info.is_published:
         # Warn if creating profile for unpublished/draft academic year
         log.warning("Creating profile for unpublished academic year", academic_info_id=academic_info.id)
    else:
        # Check if year is closed? (Assuming 'is_active' or similar flag exists, or relying on published)
        pass

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
                "label": doc.document_type_name,
            }
            for doc in resolved_docs
        },
        # Ticket #4: Upload Configuration
        "upload_config": DEFAULT_UPLOAD_CONFIG,

        # =========================================================================
        # GROUP 6: Application Fee Configuration
        # =========================================================================
        "application_fee": float(admission_path.application_fee) if admission_path.application_fee else 0,
        "requires_application_fee": admission_path.requires_application_fee,
        "fee_status": "exempt" if not admission_path.requires_application_fee else "pending",
        # fee_status values: "exempt" (miễn phí), "pending" (chờ thanh toán), "paid" (đã thanh toán)

        # =========================================================================
        # GROUP 7: Metadata
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
    
    # Step 14b: Lookup offering_admission_config for this path
    offering_config_id = None
    if admission_path.criteria_id:
        from sqlalchemy import select as sa_select
        oac_result = await db.execute(
            sa_select(models.OfferingAdmissionConfig.id).where(
                models.OfferingAdmissionConfig.academic_info_id == academic_info.id,
                models.OfferingAdmissionConfig.criteria_id == admission_path.criteria_id,
                models.OfferingAdmissionConfig.is_active == True,
            )
        )
        oac_row = oac_result.scalars().first()
        if oac_row:
            offering_config_id = oac_row

    # Step 15: Create AdmissionProfile
    new_profile = models.AdmissionProfile(
        lead_id=lead_id,
        academic_year=academic_year,
        status="draft",
        applied_rules=applied_rules,  # Snapshot from relational data
        family_info=[],
        academic_history=[],
        offering_admission_config_id=offering_config_id,
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

    # Audit trail: log profile creation
    from ..services import audit_service
    await audit_service.log_created(
        db, "AdmissionProfile", new_profile.id,
        actor_user_id=current_user.id,
        new_values={"lead_id": lead_id, "status": "draft", "academic_year": new_profile.academic_year},
        source="api",
    )

    # Step 16: Initialize ProfileDocument records
    await admission_repo.initialize_documents_for_profile(
        profile_id=new_profile.id,
        document_type_codes=mandatory_docs
    )

    # Step 17: Reload with relationships for response
    new_profile = await admission_repo.reload_profile_with_lead(new_profile.id)

    # Populate transient computed fields so the create response matches GET.
    # Without this, permissions={}, available_actions=[], validation_errors=[],
    # and assigned_officer_name=None leak to the client, breaking any frontend
    # that trusts the create response without re-fetching (MEDIUM #2 followup —
    # commit 1528bc89 fixed the 10 state-changing mutations but missed create).
    # reload_profile_with_lead already eager-loads documents + lead.assigned_officer
    # + assigned_reviewer + student + subject_scores, so pass the loaded documents
    # to avoid a redundant get_all_documents() query inside the helper. The helper
    # also calls _calculate_and_update_totals() internally, so we don't need a
    # separate call here.
    await _populate_response_fields(
        db, new_profile, current_user, documents=new_profile.documents
    )

    # ✅ SYNC: Update lead consultation status to match admission status
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=new_profile,
        changed_by_user_id=current_user.id,
        reason="Admission profile created",
    )

    log.info(
        "Admission profile created (relational flow)",
        profile_id=new_profile.id,
        lead_id=lead_id,
        user_id=current_user.id,
        snapshot_source="relational",
        admission_path_id=admission_path.id,
        mandatory_docs_count=len(mandatory_docs),
    )

    # ✅ PIPELINE SYNC: Create system consultation for admission milestone
    if new_profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=new_profile.lead,
            event="profile_created",
            actor=current_user,
            profile_id=new_profile.id,
        )

    return new_profile



async def get_profiles(
    db: AsyncSession,
    skip: int,
    limit: int,
    current_user: models.User = None,
    unit_id: Optional[int] = None,
    search: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> Tuple[List[models.AdmissionProfile], int]:
    """
    Get filtered list of admission profiles with total count.

    Security:
    - IDOR: Automatically filters by unit_id for non-admin users.
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # IDOR: 3-tier filtering (Admin=all, Manager=unit, Officer=assigned+unit)
    unit_filter, officer_filter = _resolve_idor_filters(current_user) if current_user else (unit_id, None)

    # Get profiles using repository with count
    profiles, total_count = await admission_repo.get_filtered_with_count(
        skip=skip,
        limit=min(limit, 100),
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
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

    # Hydrate computed fields (same as detail API) using eager-loaded relations
    for profile in profiles:
        _calculate_and_update_totals(profile)
        # documents already loaded via selectinload in get_filtered_with_count
        docs = profile.documents if hasattr(profile, "documents") else None
        if current_user:
            _compute_frontend_fields(profile, current_user, docs)

    return profiles, total_count


async def get_profiles_for_export(
    db: AsyncSession,
    current_user: models.User,
    search: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> List[models.AdmissionProfile]:
    """
    Get profiles for CSV export — no page cap, lightweight hydration.

    Only computes completion_percent (needed by CSV) via _calculate_and_update_totals.
    Skips full _compute_frontend_fields (permissions, actions, step_status, etc.).
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    profiles, _ = await admission_repo.get_filtered_with_count(
        skip=0,
        limit=10_000,  # export cap
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        search=search,
        statuses=statuses,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
        sort_by="created_at",
        order="desc",
    )

    # Lightweight hydration: totals/GPA + completion_percent, no permissions/actions
    for profile in profiles:
        _calculate_and_update_totals(profile)
        docs = profile.documents if hasattr(profile, "documents") else None
        profile.completion_percent = _compute_completion_percent(profile, docs)

    return profiles


async def get_status_counts(
    db: AsyncSession,
    current_user: models.User,
    search: Optional[str] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    """Get status counts for admission profiles (all filters except status)."""
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    return await admission_repo.get_status_counts(
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        search=search,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
    )


async def get_admission_stats(
    db: AsyncSession,
    current_user: models.User,
    academic_year: Optional[int] = None,
) -> dict:
    """Get aggregate statistics for admission profiles with computed avg_completion."""
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    stats = await admission_repo.get_aggregate_stats(
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        academic_year=academic_year,
    )

    # Compute avg_completion over ALL profiles in scope (no sampling)
    total = stats.get("total_profiles", 0)
    if total > 0:
        completion_sum = 0
        fetched = 0
        batch_size = 500
        while fetched < total:
            batch, _ = await admission_repo.get_filtered_with_count(
                skip=fetched,
                limit=batch_size,
                unit_id=unit_filter,
                assigned_officer_id=officer_filter,
                academic_year=academic_year,
            )
            if not batch:
                break
            for p in batch:
                _calculate_and_update_totals(p)
                docs = p.documents if hasattr(p, "documents") else None
                completion_sum += _compute_completion_percent(p, docs)
            fetched += len(batch)
        stats["avg_completion"] = round(completion_sum / fetched, 1) if fetched > 0 else 0.0

    return stats


async def get_academic_years(
    db: AsyncSession,
    current_user: models.User,
) -> List[int]:
    """Get distinct academic years for the current user's scope."""
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    return await admission_repo.get_distinct_academic_years(
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
    )


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
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
    """
    # ✅ SPRINT 6: Use Repository for profile retrieval
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    
    profile = await admission_repo.get_profile_by_id_with_lead(profile_id)

    if not profile:
        log.warning("Admission profile not found", profile_id=profile_id)
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check
    _check_idor_access(profile, current_user)

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
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
        BadRequest: Status is not 'draft'
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    # Prevent Race Condition (Lost Update) by locking the row
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            # Eager load lead for IDOR check + nested assigned_officer for _compute_frontend_fields
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            # Eager load assigned_reviewer for _compute_frontend_fields
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, current_user)

    # Initialize Repo
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # State Locking: Only draft, rejected, or revision_requested profiles can be updated
    if profile.status not in ["draft", "rejected", "revision_requested"]:
        log.warning(
            "Attempted to update locked profile",
            profile_id=profile_id,
            current_status=profile.status,
            user_id=current_user.id,
        )
        raise BadRequest(
            f"Cannot update profile with status '{profile.status}'. "
            "Only draft, rejected, or revision_requested profiles can be updated."
        )
    
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
        flag_modified(profile, "family_info")

    if "academic_history" in data and data["academic_history"] is not None:
        profile.academic_history = data["academic_history"]
        flag_modified(profile, "academic_history")

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
        
        # Handle GPA for gpa_only methods — persist to Lead.gpa
        if "gpa" in scores_data and scores_data["gpa"] is not None:
            gpa_value = float(scores_data["gpa"])
            if profile.lead:
                profile.lead.gpa = gpa_value


    # Update timestamp and increment version
    profile.updated_at = datetime.now(timezone.utc)
    profile.version += 1

    # ✅ FIX #2.2: Handle Integrity Errors (Duplicate Citizen ID)
    from sqlalchemy.exc import IntegrityError
    try:
        await db.flush()  # Router commits
    except IntegrityError as e:
        # Rollback is optional here as router handles transaction, but good for clarity
        # await db.rollback() 
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        
        log.error(
            "Update failed due to integrity error",
            profile_id=profile.id,
            error=error_msg
        )

        if "citizen_id" in error_msg.lower():
            raise ConflictError(f"CCCD {profile.citizen_id} đã tồn tại trong hệ thống")
        elif "unique constraint" in error_msg.lower():
            raise ConflictError("Dữ liệu trùng lặp (CCCD hoặc thông tin đã tồn tại)")
        else:
            raise ConflictError(f"Vi phạm ràng buộc dữ liệu: {error_msg}")
    
    # ✅ Fix: Fetch fresh scores but do NOT assign to profile.subject_scores (avoid SA error)
    fresh_scores = await admission_repo.get_profile_scores(profile.id)

    # Calculate totals for response using fresh data
    _calculate_and_update_totals(profile, scores=fresh_scores)

    # ✅ Fix: Re-compute validation errors/status with new scores + fresh documents.
    # Must pass documents, otherwise _validate_documents() short-circuits (returns no doc errors)
    # and documents_checklist is rebuilt with all statuses = "missing", causing the response to
    # claim validation_errors=[] and eligibility="eligible" even when mandatory docs are missing
    # (or, conversely, showing "missing" for docs that are actually uploaded). See MEDIUM #1 in
    # the post-BUG-001 residual risks audit.
    documents = await admission_repo.get_all_documents(profile.id)
    _compute_frontend_fields(profile, current_user, documents)

    # Audit trail: log profile update with field-level changes
    from ..services import audit_service
    updated_fields = {k: v for k, v in data.items() if k not in ("version",)}
    await audit_service.log_changes(
        db, "AdmissionProfile", profile.id, "updated",
        changes={"updated_fields": list(updated_fields.keys()), "updated_by": current_user.id},
        actor_user_id=current_user.id,
        source="api",
    )

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

    applied_rules = profile.applied_rules or {}
    method_type = applied_rules.get("method_type", "subject_based")

    # GPA-only methods: use Lead.gpa directly, no subject scores needed
    if method_type == "gpa_only":
        gpa_value = float(profile.lead.gpa) if (profile.lead and profile.lead.gpa) else 0.0
        profile.total_score = gpa_value
        profile.average_score = gpa_value
        scores_map = {s.subject.code: float(s.score) for s in target_scores} if target_scores else {}
        profile.admission_scores = {
            "subject_scores": scores_map,
            "total_score": gpa_value,
            "average_score": gpa_value,
            "gpa": gpa_value,
            "snapshot_score": None,
        }
        profile.snapshot_score = None
        return

    # STRICT RULE: Check required subject count
    required_count = applied_rules.get("required_subject_count") or 3

    current_count = len(target_scores) if target_scores else 0

    if current_count < required_count:
        # Incomplete scores -> Treat as 0.0 (Invalid)
        profile.total_score = 0.0
        profile.average_score = 0.0
        
        # Build map of partial scores for display, but totals are 0
        scores_map = {s.subject.code: float(s.score) for s in target_scores} if target_scores else {}

        # Transient field for response serialization (not a DB column)
        profile.admission_scores = {
            "subject_scores": scores_map,
            "total_score": 0.0,
            "average_score": 0.0,
            "gpa": 0.0,
            "snapshot_score": None
        }
        profile.snapshot_score = None
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
    # Safe extraction of method code
    method_data = applied_rules.get("admission_method")
    if isinstance(method_data, dict):
        method_code = method_data.get("code", "SNAPSHOT")
    else:
        # Fallback if stored as string literal or None
        method_code = str(method_data) if method_data else "SNAPSHOT"

    snapshot_criteria = models.AdmissionCriteria(
        code=method_code,
        min_gpa=float(applied_rules.get("min_gpa") or 0),
        min_score=float(applied_rules.get("min_score") or 0),
        min_subject_score=float(applied_rules.get("min_subject_score") or 0),
        required_subject_count=applied_rules.get("required_subject_count"),
        subject_selection_mode=applied_rules.get("subject_selection_mode", "fixed"),
        scoring_method=applied_rules.get("scoring_method", "sum"),
    )
    
    # 2. Prepare allowed subjects
    allowed_subjects = applied_rules.get("allowed_subject_codes", [])
    # Removed legacy fallback - allowed_subjects must be populated in validation phase

    # 3. Calculate using robust engine
    score_result = AdmissionScoringService.calculate_score(
        criteria=snapshot_criteria,
        subject_scores=target_scores_map,
        allowed_subjects=allowed_subjects,
    )
    
    # Update transient fields
    # Note: AdmissionScoreResult uses final_score (not total_score/average_score)
    final_score_value = float(score_result.final_score) if score_result.final_score is not None else 0.0
    profile.total_score = final_score_value
    
    # Compute average from selected scores
    # Note: AdmissionScoreResult uses `subject_scores` (not `selected_scores`)
    selected_scores_list = list(score_result.subject_scores.values()) if score_result.subject_scores else []
    if selected_scores_list:
        profile.average_score = sum(float(s) for s in selected_scores_list) / len(selected_scores_list)
    else:
        profile.average_score = 0.0

    # Transient fields for response serialization (not DB columns)
    snapshot_score = {
        "selected_subjects": score_result.selected_subjects,
        "selected_scores": {k: float(v) for k, v in score_result.subject_scores.items()},
        "status": score_result.status.value,
        "failure_reasons": score_result.failure_reasons
    }
    profile.admission_scores = {
        "subject_scores": {k: float(v) for k, v in target_scores_map.items()},
        "total_score": profile.total_score,
        "average_score": profile.average_score,
        "gpa": profile.average_score,
        "snapshot_score": snapshot_score
    }
    profile.snapshot_score = snapshot_score


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
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
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
    _check_idor_access(profile, current_user)

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

    method_type = applied_rules.get("method_type", "subject_based")

    if method_type == "gpa_only":
        # =====================================================================
        # GPA-Only Branch: validate using Lead.gpa, no subject scores required
        # =====================================================================
        gpa_value = float(profile.lead.gpa) if (profile.lead and profile.lead.gpa) else None
        min_gpa = float(applied_rules.get("min_gpa") or 0)

        if gpa_value is None:
            errors.append("Chưa nhập GPA. Vui lòng nhập điểm trung bình trước khi nộp hồ sơ.")
        elif min_gpa > 0 and gpa_value < min_gpa:
            errors.append(
                f"Điểm xét tuyển không đạt: GPA không đạt: {gpa_value:.2f} < {min_gpa}"
            )
            log.warning(
                "GPA-only scoring validation failed",
                profile_id=profile.id,
                gpa=gpa_value,
                min_gpa=min_gpa,
            )
        else:
            log.info(
                "GPA-only scoring validation passed",
                profile_id=profile.id,
                gpa=gpa_value,
                min_gpa=min_gpa,
            )
    else:
        # =====================================================================
        # Subject-Based / Combined Branch (existing logic)
        # =====================================================================

        # Use AdmissionScoringService for robust validation (Best N, Min Score, etc.)
        from .admission_scoring_service import AdmissionScoringService, ProfileStatus, SubjectSelectionMode, ScoringMethod
        from app.models.admission_config import AdmissionCriteria

        # 1. Reconstruct Criteria from Snapshot (applied_rules)
        # ✅ FIX: Safe extraction of admission_method (can be string or dict in legacy data)
        method_data = applied_rules.get("admission_method")
        if isinstance(method_data, dict):
            method_code = method_data.get("code", "SNAPSHOT")
        else:
            method_code = str(method_data) if method_data else "SNAPSHOT"

        snapshot_criteria = models.AdmissionCriteria(
            code=method_code,
            min_gpa=float(applied_rules.get("min_gpa", 0)) if applied_rules.get("min_gpa") else None,
            min_score=float(applied_rules.get("min_score", 0)) if applied_rules.get("min_score") else None,
            min_subject_score=float(applied_rules.get("min_subject_score", 0)) if applied_rules.get("min_subject_score") else None,
            required_subject_count=applied_rules.get("required_subject_count"),
            subject_selection_mode=applied_rules.get("subject_selection_mode", "fixed"),
            scoring_method=applied_rules.get("scoring_method", "sum"),
        )

        # 2. Get Scores
        scores = await admission_repo.get_profile_scores(profile.id)
        subject_scores_map = {s.subject.code: Decimal(str(s.score)) for s in scores}

        # 3. Resolve Allowed Subjects
        allowed_subjects = applied_rules.get("allowed_subject_codes")

        if not allowed_subjects:
            log.warning(
                "Profile has incomplete snapshot - missing allowed_subject_codes. "
                "Using fallback to all scored subjects (legacy compatibility). "
                "This profile should be recreated for deterministic scoring.",
                profile_id=profile.id,
                lead_id=profile.lead_id,
                snapshot_source=applied_rules.get("snapshot_source"),
            )
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
            for reason in score_result.failure_reasons:
                errors.append(f"Điểm xét tuyển không đạt: {reason}")

            log.warning(
                "Scoring validation failed",
                profile_id=profile.id,
                reasons=score_result.failure_reasons,
                disqualification_codes=score_result.disqualification_codes
            )
        else:
            official_gpa = float(score_result.final_score) if score_result.final_score else 0.0
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

    # Validation 4: Check Family Info (Fix Finding 1.7)
    if not profile.family_info:
        errors.append("Chưa nhập thông tin gia đình (Family Info is empty)")

    # Validation 5: Check Academic History (Fix Finding 1.7)
    if not profile.academic_history:
        errors.append("Chưa nhập quá trình học tập (Academic History is empty)")

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
        # ✅ CRITICAL FIX #1.3: Validate transition DRAFT -> SUBMITTED
        from .admission_state_machine import validate_transition
        try:
            validate_transition(profile.status, "submitted")
        except ValueError as e:
            raise BadRequest(str(e))
        
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

        # Audit trail: log submission
        from ..services import audit_service
        await audit_service.log_status_change(
            db, "AdmissionProfile", profile.id,
            old_status="draft", new_status=profile.status,
            actor_user_id=current_user.id,
            source="api",
        )

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
    actual_submission_format: Optional[str] = None,
) -> models.AdmissionProfile:
    """
    Upload a document for an admission profile.

    Workflow:
    1. Verify access (IDOR)
    2. Verify profile status (draft/rejected)
    3. Verify doc_code exists in ProfileDocument
    4. Save file to disk (uploads/admissions/{id}/{doc_code}_{filename})
    5. Update ProfileDocument status='uploaded', file_path, and actual_submission_format
    6. Re-compute validation_summary with updated documents

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit().

    Args:
        actual_submission_format: Type of document submitted (original | certified_copy | photo)
            User must declare what type of physical document they scanned/uploaded.

    Returns:
        AdmissionProfile with updated validation_summary

    Security:
    - Path Traversal: filename sanitization (inherent in modern frameworks but good practice)
    - File Type: Should be validated at Router level generally, but here we accept generic
    """
    # Initialize repository
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    profile = await get_profile(db, profile_id, current_user)

    # State Locking
    if profile.status not in ["draft", "rejected", "revision_requested"]:
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
        uploaded_at=uploaded_at_dt.isoformat(),
        actual_submission_format=actual_submission_format
    )

    profile.updated_at = uploaded_at_dt

    await db.flush()

    # ✅ Re-compute validation_summary with updated documents
    from app.repositories import AdmissionRepository
    admission_repo_refresh = AdmissionRepository(db)
    documents = await admission_repo_refresh.get_all_documents(profile_id)
    _compute_frontend_fields(profile, current_user, documents)

    # ✅ AUDIT LOG: Track document upload
    from .document_audit_service import log_document_upload
    await log_document_upload(
        db=db,
        profile_document_id=doc_record.id,
        actor_user_id=current_user.id,
        old_status=doc_record.status if doc_record.status != "uploaded" else "missing",
        new_file_path=file_path,
        original_filename=file.filename or "unknown",
        file_size_bytes=file_size,
        content_type=file.content_type,
        old_file_path=old_file_path,
        declared_format=actual_submission_format,
    )

    log.info(
        "Document uploaded with audit log",
        profile_id=profile_id,
        doc_code=doc_code,
        file_path=file_path,
        user_id=current_user.id
    )

    return profile


async def confirm_document_format(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    format_type: str,
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Confirm physical format of a document and mark as verified.

    This performs the full verification workflow:
    1. Updates verified_format (original | certified_copy | photo)
    2. Sets status to 'verified'
    3. Records verification timestamp and officer
    4. Re-computes validation_summary with updated document status

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        format_type: original | certified_copy | photo
        current_user: Officer performing verification

    Returns:
        AdmissionProfile with updated validation_summary

    Raises:
        ResourceNotFoundError: Document not found
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # 1. Access Check
    profile = await get_profile(db, profile_id, current_user)

    # 2. Verify Document Format (full verification)
    doc = await admission_repo.confirm_document_format(
        profile_id=profile_id,
        document_type_code=doc_code,
        verified_format=format_type,
        officer_id=current_user.id,
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found")

    await db.flush()

    # 3. Re-compute validation_summary with updated documents
    documents = await admission_repo.get_all_documents(profile_id)
    _compute_frontend_fields(profile, current_user, documents)

    # ✅ AUDIT LOG: Track document verification
    from .document_audit_service import log_document_verification
    await log_document_verification(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status="uploaded",
        verified_format=format_type,
    )

    log.info(
        "Document verified with audit log",
        profile_id=profile_id,
        doc_code=doc_code,
        verified_format=format_type,
        officer_id=current_user.id,
        officer_email=current_user.email,
    )

    return profile


async def mark_paper_submitted(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    current_user: models.User,
    actual_submission_format: Optional[str] = None,
) -> models.AdmissionProfile:
    """
    Mark a document as paper submitted (officer confirms receipt).

    For documents where requires_upload=false.
    Only officers/managers/admins can mark paper submitted.

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        current_user: Current authenticated user (must be officer+)
        actual_submission_format: Type of document submitted (original | certified_copy | photo)

    Returns:
        AdmissionProfile with updated validation_summary

    Raises:
        ResourceNotFoundError: Document not found
        BadRequest: Document requires upload (not paper submission)
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile for access check
    profile = await get_profile(db, profile_id, current_user)

    # Status guard: only allow document operations in editable states
    if profile.status not in ["draft", "submitted", "rejected", "resubmitted"]:
        raise BadRequest(
            f"Cannot modify documents when profile status is '{profile.status}'"
        )

    # Get document to capture old status
    doc_before = await admission_repo.get_document_by_type(profile_id, doc_code)
    old_status = doc_before.status if doc_before else "missing"

    # Mark paper submitted
    doc = await admission_repo.mark_paper_submitted(
        profile_id=profile_id,
        document_type_code=doc_code,
        officer_id=current_user.id,
        actual_submission_format=actual_submission_format,
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found in profile documents")

    await db.flush()

    # ✅ AUDIT LOG: Track paper submission
    from .document_audit_service import log_paper_submission
    await log_paper_submission(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status=old_status,
        declared_format=actual_submission_format,
    )

    # ✅ Re-compute validation_summary with updated documents
    documents = await admission_repo.get_all_documents(profile_id)
    _compute_frontend_fields(profile, current_user, documents)

    log.info(
        "Document paper submitted confirmed with audit log",
        profile_id=profile_id,
        doc_code=doc_code,
        officer_id=current_user.id,
    )

    return profile


async def reject_document(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    reason: str,
    current_user: models.User,
) -> tuple[Dict[str, Any], Any]:
    """
    Reject a document with reason.
    
    User will need to re-upload or resubmit.
    Only officers/managers/admins can reject documents.
    
    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        reason: Rejection reason (required)
        current_user: Current authenticated user (must be officer+)
        
    Returns:
        Tuple of (updated_doc_item, post_commit_callback)
        
    Raises:
        ResourceNotFoundError: Document not found
        BadRequest: Reason not provided
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    
    if not reason or not reason.strip():
        raise BadRequest("Rejection reason is required")
    
    # Get profile for access check
    profile = await get_profile(db, profile_id, current_user)

    # Status guard: cannot reject documents for enrolled profiles
    if profile.status == "enrolled":
        raise BadRequest("Cannot reject documents for enrolled profile")

    # Get document to capture old status
    doc_before = await admission_repo.get_document_by_type(profile_id, doc_code)
    old_status = doc_before.status if doc_before else "unknown"

    # Reject document
    doc = await admission_repo.reject_document(
        profile_id=profile_id,
        document_type_code=doc_code,
        officer_id=current_user.id,
        reason=reason.strip(),
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found in profile documents")

    await db.flush()

    # ✅ AUDIT LOG: Track document rejection
    from .document_audit_service import log_document_rejection
    await log_document_rejection(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status=old_status,
        reason=reason.strip(),
    )

    response_data = {
        "code": doc_code,
        "status": "rejected",
        "rejection_reason": reason.strip(),
        "rejected_at": doc.rejected_at.isoformat() if doc.rejected_at else None,
        "rejected_by_id": current_user.id,
    }

    async def _post_commit():
        log.info(
            "Document rejected with audit log",
            profile_id=profile_id,
            doc_code=doc_code,
            reason=reason,
            officer_id=current_user.id,
        )

    return response_data, _post_commit


async def reset_document(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Reset a document to 'missing' status (undo submission).

    Use case: User accidentally clicked "Đã nộp" or uploaded wrong file.
    Allows simple undo without complex audit trail.

    Permissions:
    - Officer: Can reset documents for profiles in draft/rejected status
    - Manager/Admin: Can reset any document except for enrolled profiles

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        current_user: Current authenticated user

    Returns:
        AdmissionProfile with updated validation_summary

    Raises:
        ResourceNotFoundError: Document not found
        BadRequest: Cannot reset (e.g., profile is enrolled)
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile for access check
    profile = await get_profile(db, profile_id, current_user)

    # State Locking: Cannot reset documents for enrolled profiles
    if profile.status == "enrolled":
        raise BadRequest("Cannot reset documents for enrolled profiles")

    # Get document to capture old status and file path before reset
    doc_before = await admission_repo.get_document_by_type(profile_id, doc_code)
    old_status = doc_before.status if doc_before else "unknown"
    old_file_path = doc_before.file_path if doc_before else None

    # Reset document
    doc = await admission_repo.reset_document(
        profile_id=profile_id,
        document_type_code=doc_code,
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found in profile documents")

    # ✅ AUDIT LOG: Track document reset
    from .document_audit_service import log_document_reset
    await log_document_reset(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status=old_status,
        old_file_path=old_file_path,
        reason="User requested reset",
    )

    # Delete physical file if exists
    if old_file_path:
        import os
        if os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                log.info("Document file deleted during reset", file_path=old_file_path)
            except OSError as e:
                log.warning("Failed to delete document file", error=str(e), file_path=old_file_path)

    await db.flush()

    # Re-compute validation_summary with updated documents
    documents = await admission_repo.get_all_documents(profile_id)
    _compute_frontend_fields(profile, current_user, documents)

    log.info(
        "Document reset to missing",
        profile_id=profile_id,
        doc_code=doc_code,
        user_id=current_user.id,
    )

    return profile


async def enroll_student(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Dict[str, Any]:
    """
    Enroll student (create Student + StudentDocument records).

    ACID Transaction Flow:
    1. Get and validate profile (status must be 'confirmed' or 'overridden')
    2. Fee Gate: Verify tuition fee is paid/waived (if ENABLE_FEE_VERIFICATION=True)
    3. BEGIN SAVEPOINT (via begin_nested)
    4. Generate unique student_code (SV + YYYY + 4-digit random, retry on conflict)
    5. Create Student record
    6. Create StudentDocument records (from ProfileDocument table)
    7. Update AdmissionProfile.status = 'enrolled'
    8. Update Lead.status = 'converted'
    9. COMMIT SAVEPOINT (auto if no errors)

    On IntegrityError:
    - Savepoint auto-rollback
    - Return 409 Conflict with error message

    Security:
    - IDOR: Check lead.unit_id == user.unit_id
    - State Check: Only confirmed/overridden profiles can be enrolled
    - Fee Gate: Tuition fee must be paid/waived (when ENABLE_FEE_VERIFICATION=True)

    Fee Gate (Phase 6):
    Per FINANCE_MODULE_DESIGN.md Section 5.3 - Gate 2:
    - When ENABLE_FEE_VERIFICATION=True, enrollment is blocked if tuition fee not cleared
    - Fee is "cleared" if status == 'paid' OR status == 'waived'
    - Default: ENABLE_FEE_VERIFICATION=False (backward compatible)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        current_user: Current authenticated user

    Returns:
        Dict with student_id, student_code, enrollment_date

    Raises:
        ResourceNotFoundError: Profile not found
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
        BadRequest: Status is not 'confirmed', or tuition fee not cleared
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
    _check_idor_access(profile, current_user)

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
    # ✅ CRITICAL FIX #1.1: Enforce State Machine (APPROVED -> CONFIRMED -> ENROLLED)
    # Prevents skipping confirmation step
    from .admission_state_machine import validate_transition
    
    try:
        validate_transition(profile.status, "enrolled")
    except ValueError as e:
        log.warning(
            "Invalid state transition for enrollment",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    if profile.status not in ("confirmed", "overridden"):
         # Double check (redundant with validate_transition but keeps specific error message clear)
         # Actually validate_transition handles this, but we keep this block if we want custom message
         # However, for strict compliance, let's rely on validate_transition or re-raise cleaner error
         pass # validate_transition already checked this

    # ✅ FEE GATE (Phase 6): Verify tuition fee is paid/waived before enrollment
    # Per FINANCE_MODULE_DESIGN.md Section 5.3 - Gate 2 (Tuition Fee Gate)
    # Only enforced when ENABLE_FEE_VERIFICATION feature flag is True
    from app.config import settings
    if settings.ENABLE_FEE_VERIFICATION:
        await check_enrollment_fee_eligibility(db, profile_id)
        log.info(
            "Fee gate passed for enrollment",
            profile_id=profile_id,
            user_id=current_user.id,
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
            _old_status_for_enroll = profile.status
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

            # Audit trail: log enrollment
            from ..services import audit_service
            await audit_service.log_status_change(
                db, "AdmissionProfile", profile.id,
                old_status=_old_status_for_enroll, new_status="enrolled",
                actor_user_id=current_user.id,
                source="api",
            )

            # ✅ SYNC: Update lead consultation status to match admission status (enrolled → sts11)
            from .lead_admission_sync import sync_lead_from_admission
            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=current_user.id,
                reason="Student enrolled successfully",
            )
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
# DELETE PROFILE (implemented at line ~2691)
# ==============================================================================

# ==============================================================================
# STATE MACHINE TRANSITIONS (Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
# ==============================================================================

async def approve_profile(
    db: AsyncSession,
    profile_id: int,
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
        profile_id: AdmissionProfile ID
        approver: User performing approval
        data: ApproveRequest data (notes)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, approver)
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

    # ✅ APPLICATION FEE CHECK
    # Per PHASE_WORKFLOW.md: Profile can only be approved if fee is paid or exempt
    applied_rules = profile.applied_rules or {}
    requires_fee = applied_rules.get("requires_application_fee", False)
    fee_status = applied_rules.get("fee_status", "exempt")

    if requires_fee and fee_status == "pending":
        log.warning(
            "Attempt to approve profile with unpaid application fee",
            profile_id=profile.id,
            fee_status=fee_status,
            approver_id=approver.id,
        )
        raise BadRequest(
            "Không thể duyệt hồ sơ: Lệ phí xét tuyển chưa được thanh toán. "
            "Vui lòng xác nhận thanh toán lệ phí trước khi duyệt hồ sơ."
        )

    # STATE CHANGE
    _old_status_for_audit = profile.status
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

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, approver)

    # Audit trail: log approval
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status=_old_status_for_audit, new_status="approved",
        actor_user_id=approver.id,
        reason=data.get("notes"),
        source="api",
    )

    # ✅ SYNC: Update lead consultation status to match admission status (approved → sts09)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=approver.id,
        reason="Admission profile approved",
    )

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
    profile_id: int,
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
        profile_id: AdmissionProfile ID
        rejector: User performing rejection
        data: RejectRequest data (reason - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, rejector)
    
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
    _old_status_for_audit = profile.status
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

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, rejector)

    # Audit trail: log rejection
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status=_old_status_for_audit, new_status="rejected",
        actor_user_id=rejector.id,
        reason=data["reason"],
        source="api",
    )

    # ✅ SYNC: Update lead consultation status to match admission status (rejected → sts16)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=rejector.id,
        reason=f"Admission profile rejected: {data['reason'][:50]}",
    )

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


async def request_revision(
    db: AsyncSession,
    profile_id: int,
    reviewer: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Request revision of admission profile (Manager/Admin action).

    Transition: SUBMITTED/RESUBMITTED -> REVISION_REQUESTED
    Uses dedicated columns (revision_requested_at/by/reason) separate from rejection.

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        reviewer: User requesting revision
        data: RevisionRequest data (reason - required, version - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    _check_idor_access(profile, reviewer)

    from .admission_state_machine import validate_transition

    try:
        validate_transition(profile.status, "revision_requested")
    except ValueError as e:
        log.warning(
            "Invalid state transition for revision request",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    if not data.get("reason"):
        raise BadRequest("Revision reason is required (min 10 characters)")

    if data["version"] != profile.version:
        log.warning(
            "Optimistic locking conflict: Version mismatch in revision request",
            profile_id=profile.id,
            expected_version=data["version"],
            actual_version=profile.version,
            user_id=reviewer.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    _old_status_for_audit = profile.status
    profile.status = "revision_requested"
    profile.revision_requested_at = datetime.now(timezone.utc)
    profile.revision_requested_by_id = reviewer.id
    profile.revision_reason = data["reason"]
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    # PIPELINE SYNC: Create system consultation for revision milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_revision_requested",
            actor=reviewer,
            profile_id=profile.id,
            reason=data["reason"],
        )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, reviewer)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status=_old_status_for_audit, new_status="revision_requested",
        actor_user_id=reviewer.id,
        reason=data["reason"],
        source="api",
    )

    # SYNC: Update lead consultation status (revision_requested -> sts17)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=reviewer.id,
        reason=f"Admission profile revision requested: {data['reason'][:50]}",
    )

    log.info(
        "Admission profile revision requested",
        profile_id=profile.id,
        reviewer_id=reviewer.id,
        reason_length=len(data["reason"]),
    )

    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Profile revision requested notification",
            profile_id=profile.id,
        )

    return profile, post_commit


# ==============================================================================
# APPLICATION FEE MANAGEMENT
# ==============================================================================

async def record_application_fee_payment(
    db: AsyncSession,
    profile_id: int,
    payment_data: Dict[str, Any],
    recorded_by: Optional[models.User] = None,
) -> tuple[models.AdmissionProfile, Any]:
    """
    Record application fee payment for an admission profile.

    This function is called when:
    1. Payment gateway callback confirms payment
    2. Manual payment confirmation by admin

    Flow:
    - Profile must be in "draft" or "submitted" status
    - Updates applied_rules.fee_status to "paid"
    - Syncs lead to sts13 (Đã hoàn lệ phí xét tuyển)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        payment_data: Payment information (transaction_id, amount, paid_at, etc.)
        recorded_by: User who recorded the payment (optional for system callbacks)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        ResourceNotFoundError: Profile not found
        BadRequest: Profile doesn't require fee or already paid
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # Check profile status — only allow fee payment for draft/submitted profiles
    if profile.status not in ("draft", "submitted"):
        raise BadRequest(
            f"Cannot record fee payment for profile in '{profile.status}' status. "
            "Only draft or submitted profiles accept fee payments."
        )

    # Check fee requirement
    applied_rules = profile.applied_rules or {}
    requires_fee = applied_rules.get("requires_application_fee", False)
    current_fee_status = applied_rules.get("fee_status", "exempt")

    if not requires_fee:
        raise BadRequest(
            "This admission profile does not require application fee payment"
        )

    if current_fee_status == "paid":
        log.info(
            "Application fee already paid (idempotent)",
            profile_id=profile_id,
        )
        # Return without error for idempotency
        async def noop():
            pass
        return profile, noop

    # Update fee_status in applied_rules
    applied_rules["fee_status"] = "paid"
    applied_rules["fee_paid_at"] = datetime.now(timezone.utc).isoformat()
    applied_rules["fee_payment_data"] = payment_data
    profile.applied_rules = {**applied_rules}  # New dict to trigger JSONB change detection
    flag_modified(profile, "applied_rules")
    profile.updated_at = datetime.now(timezone.utc)

    # ✅ SYNC: Update lead to sts13 (Đã hoàn lệ phí xét tuyển)
    from .lead_admission_sync import sync_lead_fee_paid
    await sync_lead_fee_paid(
        db=db,
        profile=profile,
        changed_by_user_id=recorded_by.id if recorded_by else None,
        reason="Application fee payment confirmed",
    )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    # Helper handles recorded_by=None silently (system callback path).
    await _populate_response_fields(db, profile, recorded_by)

    log.info(
        "Application fee payment recorded",
        profile_id=profile_id,
        lead_id=profile.lead_id,
        amount=payment_data.get("amount"),
        transaction_id=payment_data.get("transaction_id"),
        recorded_by=recorded_by.id if recorded_by else "system",
    )

    async def post_commit():
        log.info(
            "Post-commit: Fee payment notification",
            profile_id=profile_id,
        )

    return profile, post_commit


async def check_application_fee_status(
    db: AsyncSession,
    profile_id: int,
) -> Dict[str, Any]:
    """
    Check application fee status for a profile.

    Returns:
        Dict with fee status information
    """
    from app.repositories import AdmissionRepository
    repo = AdmissionRepository(db)

    profile = await repo.get_by_id(profile_id)
    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    applied_rules = profile.applied_rules or {}

    return {
        "profile_id": profile_id,
        "requires_fee": applied_rules.get("requires_application_fee", False),
        "fee_amount": applied_rules.get("application_fee", 0),
        "fee_status": applied_rules.get("fee_status", "exempt"),
        "fee_paid_at": applied_rules.get("fee_paid_at"),
        "can_approve": (
            applied_rules.get("fee_status") in ("paid", "exempt")
        ),
    }


async def resubmit_profile(
    db: AsyncSession,
    profile_id: int,
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
        profile_id: AdmissionProfile ID
        officer: User performing resubmit
        data: ResubmitRequest data (notes)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, officer)
    
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
    _old_status_for_audit = profile.status
    profile.status = "resubmitted"
    profile.resubmitted_at = datetime.now(timezone.utc)
    profile.resubmitted_by_id = officer.id
    profile.resubmit_notes = data.get("notes")
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    # Clear reviewer assignment on resubmit (manager can re-claim)
    old_reviewer = profile.assigned_reviewer_id
    if old_reviewer:
        from ..services import audit_service as _audit_svc
        await _audit_svc.log_changes(
            db, "AdmissionProfile", profile.id, "reviewer_cleared",
            changes={
                "assigned_reviewer_id": {"old": old_reviewer, "new": None},
                "assigned_at": {"old": str(profile.assigned_at) if profile.assigned_at else None, "new": None},
            },
            actor_user_id=officer.id,
            source="api",
        )
    profile.assigned_reviewer_id = None
    profile.assigned_at = None

    # ✅ PIPELINE SYNC: Create system consultation for resubmission milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_resubmitted",
            actor=officer,
            profile_id=profile.id,
        )

    # ✅ SYNC: Update lead consultation status to match admission status (resubmitted → sts07)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=officer.id,
        reason=f"Profile resubmitted: {data.get('notes', 'No notes')[:50]}",
    )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, officer)

    # Audit trail: log resubmission
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status=_old_status_for_audit, new_status="resubmitted",
        actor_user_id=officer.id,
        source="api",
    )

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

    # Invalidate stale magic-link tokens (profile leaving approved state)
    from app.repositories import AdmissionRepository
    await AdmissionRepository(db).invalidate_existing_tokens(profile.id)

    # ✅ PIPELINE SYNC: Create system consultation for confirmation milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_confirmed",
            actor=applicant,
            profile_id=profile.id,
        )

    # ✅ SYNC: Update lead consultation status to match admission status (confirmed → sts09)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=applicant.id,
        reason="Applicant confirmed enrollment intent",
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

    # Invalidate stale magic-link tokens (profile leaving approved state)
    from app.repositories import AdmissionRepository
    await AdmissionRepository(db).invalidate_existing_tokens(profile.id)

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

    # ✅ SYNC: Update lead consultation status to match admission status (overridden → sts09)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=admin.id,
        reason=f"Admin override: {data['reason'][:50]}",
    )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, admin)

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


async def claim_review(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    reviewer: models.User,
    expected_version: Optional[int] = None
):
    """
    Manager claims a profile for review (Assignment Workflow).

    Business Rules:
    1. Status MUST be 'submitted' (cannot claim draft/approved) # ADMISSION_RULE_008
    2. Profile must NOT be already claimed by someone else
    3. Version check (optimistic locking)
    """
    if profile.status not in ['submitted', 'resubmitted']:
        raise BusinessRuleViolation(
            f"Cannot claim profile in status '{profile.status}'. Only submitted/resubmitted profiles can be claimed."
        )

    # 3. Version Check (CRITICAL FIX: Prevent Race Condition)
    if expected_version is not None and profile.version != expected_version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {expected_version}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    if profile.assigned_reviewer_id:
        if profile.assigned_reviewer_id == reviewer.id:
            # Idempotent success (already claimed by self).
            # Still populate transient computed fields so the response matches
            # what a fresh GET would return — router holds the same `profile`
            # reference via the dependency.
            await _populate_response_fields(db, profile, reviewer)
            return

        # Already claimed by someone else
        raise BusinessRuleViolation(
            "Profile is already claimed by another reviewer"
        )

    # STATE CHANGE
    profile.assigned_reviewer_id = reviewer.id
    profile.assigned_at = datetime.now(timezone.utc)
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, reviewer)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_changes(
        db, "AdmissionProfile", profile.id, "claimed",
        changes={
            "assigned_reviewer_id": {"old": None, "new": reviewer.id},
            "assigned_at": {"old": None, "new": str(profile.assigned_at)},
        },
        actor_user_id=reviewer.id,
        source="api",
    )

    log.info(
        "Profile claimed for review",
        profile_id=profile.id,
        reviewer_id=reviewer.id,
    )


async def unclaim_review(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    current_user: models.User,
    expected_version: Optional[int] = None,
):
    """
    Unclaim a profile from review (Manager self-unclaim or Admin override).

    Business Rules:
    1. Profile must have an assigned reviewer
    2. Only assigned reviewer can unclaim (Admin can unclaim anyone)
    3. Version check (optimistic locking)
    """
    from app.utils.exceptions import BusinessRuleViolation

    if expected_version is not None and profile.version != expected_version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {expected_version}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    if profile.assigned_reviewer_id is None:
        raise BusinessRuleViolation("No reviewer to unclaim")

    if current_user.role != UserRole.ADMIN:
        if profile.assigned_reviewer_id != current_user.id:
            raise BusinessRuleViolation("Only assigned reviewer or Admin can unclaim")

    old_reviewer = profile.assigned_reviewer_id
    old_at = profile.assigned_at

    profile.assigned_reviewer_id = None
    profile.assigned_at = None
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, current_user)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_changes(
        db, "AdmissionProfile", profile.id, "unclaimed",
        changes={
            "assigned_reviewer_id": {"old": old_reviewer, "new": None},
            "assigned_at": {"old": str(old_at) if old_at else None, "new": None},
        },
        actor_user_id=current_user.id,
        source="api",
    )

    log.info(
        "Profile unclaimed from review",
        profile_id=profile.id,
        unclaimed_by=current_user.id,
        previous_reviewer=old_reviewer,
    )


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

    # Populate transient computed fields so the mutation response matches GET.
    # reload_profile_with_lead already eager-loads documents, so reuse them.
    await _populate_response_fields(db, profile, admin, documents=profile.documents)

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

    Behavior:
    - Does NOT revert Lead status (Lead already showed interest)
    - Creates a consultation record noting the deletion
    - Maintains full audit trail in timeline

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
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
        BadRequest: Status is not 'draft'
    """
    from app.repositories import AdmissionRepository

    admission_repo = AdmissionRepository(db)

    # Get profile with lead (for IDOR check)
    profile = await admission_repo.get_profile_by_id_with_lead(profile_id)

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check
    _check_idor_access(profile, current_user)

    # State check: Only draft profiles can be deleted
    if profile.status != "draft":
        raise BadRequest(
            f"Cannot delete profile with status '{profile.status}'. "
            "Only draft profiles can be deleted."
        )

    lead = profile.lead
    lead_id = profile.lead_id

    # ==========================================================================
    # CREATE CONSULTATION RECORD: Log the deletion event (no status revert)
    # ==========================================================================
    # Following the Golden Rule: Every admission event must have a consultation record
    # Lead status stays the same (they already showed interest by creating profile)
    
    system_consultation = models.Consultation(
        lead_id=lead_id,
        officer_id=current_user.id,
        consultation_status_id=lead.consultation_status_id,  # Keep current status
        consultation_date=datetime.now(timezone.utc),
        method="system",
        notes=f"[HỆ THỐNG] Hồ sơ xét tuyển đã bị xóa - Profile #{profile_id}",
        duration_minutes=0,
    )
    db.add(system_consultation)
    
    # Update lead timestamp
    lead.updated_at = datetime.now(timezone.utc)

    log.info(
        "Profile deletion consultation record created",
        lead_id=lead_id,
        profile_id=profile_id,
        consultation_status_id=lead.consultation_status_id,
        actor_id=current_user.id,
    )

    # Audit trail: log deletion
    from ..services import audit_service
    await audit_service.log_deleted(
        db, "AdmissionProfile", profile.id,
        actor_user_id=current_user.id,
        old_values={"lead_id": profile.lead_id, "status": profile.status},
        source="api",
    )

    # Delete the profile
    await db.delete(profile)
    await db.flush()

    log.info(
        "Admission profile deleted",
        profile_id=profile_id,
        lead_id=lead_id,
        user_id=current_user.id,
    )

    return True


# ==============================================================================
# WITHDRAWAL
# ==============================================================================


async def withdraw_profile(
    db: AsyncSession,
    profile_id: int,
    actor: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Withdraw admission profile.

    Allowed from: DRAFT, SUBMITTED, REJECTED, RESUBMITTED
    Target: WITHDRAWN (final state)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        actor: User performing withdrawal
        data: WithdrawRequest data (reason - required, version - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    _check_idor_access(profile, actor)

    from .admission_state_machine import validate_transition

    try:
        validate_transition(profile.status, "withdrawn")
    except ValueError as e:
        log.warning(
            "Invalid state transition for withdraw",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    if not data.get("reason"):
        raise BadRequest("Withdrawal reason is required")

    if data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    _old_status_for_audit = profile.status
    profile.status = "withdrawn"
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    # PIPELINE SYNC: Create system consultation for withdrawal milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_withdrawn",
            actor=actor,
            profile_id=profile.id,
            reason=data["reason"],
        )

    await db.flush()

    # Audit trail
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status=_old_status_for_audit, new_status="withdrawn",
        actor_user_id=actor.id,
        reason=data["reason"],
        source="api",
    )

    # SYNC: Update lead consultation status (withdrawn → sts08)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=actor.id,
        reason=f"Admission profile withdrawn: {data['reason'][:50]}",
    )

    log.info(
        "Admission profile withdrawn",
        profile_id=profile.id,
        actor_id=actor.id,
        old_status=_old_status_for_audit,
    )

    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Profile withdrawn notification",
            profile_id=profile.id,
        )

    return profile, post_commit


async def mark_student_dropped(
    db: AsyncSession,
    profile_id: int,
    actor: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Mark an enrolled student as dropped out (Manager/Admin action).

    Side-channel: status stays "enrolled", sets is_dropped=True.
    Milestone consultation handles lead sync to sts12.

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        actor: User marking the drop
        data: DropStudentRequest data (reason - required, version - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Profile not enrolled or already dropped
        ConflictError: Version mismatch
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    _check_idor_access(profile, actor)

    # Guard: Must be enrolled
    if profile.status != "enrolled":
        raise BadRequest(
            f"Cannot mark as dropped: profile is in '{profile.status}' status. "
            "Only enrolled students can be marked as dropped."
        )

    # Guard: Already dropped
    if profile.is_dropped:
        raise BadRequest("Student is already marked as dropped out.")

    if not data.get("reason"):
        raise BadRequest("Drop reason is required (min 10 characters)")

    if data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # Side-channel: DO NOT change profile.status (stays "enrolled")
    profile.is_dropped = True
    profile.dropped_at = datetime.now(timezone.utc)
    profile.dropped_by_id = actor.id
    profile.dropped_reason = data["reason"]
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    # PIPELINE SYNC: Milestone consultation handles lead sync to sts12/stg07
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="student_dropped",
            actor=actor,
            profile_id=profile.id,
        )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, actor)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status="enrolled", new_status="enrolled (dropped)",
        actor_user_id=actor.id,
        reason=data["reason"],
        source="api",
    )

    log.info(
        "Student marked as dropped",
        profile_id=profile.id,
        actor_id=actor.id,
    )

    async def post_commit():
        """Side effects after transaction commit."""
        log.info(
            "Post-commit: Student dropped notification",
            profile_id=profile.id,
        )

    return profile, post_commit


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
    
    # Token is only valid if profile is still in approved state
    profile_not_approved = (
        token_obj.profile is not None
        and token_obj.profile.status != "approved"
    )

    return {
        "valid": not (is_expired or is_locked or is_used or profile_not_approved),
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
    # Pessimistic lock on token + profile to prevent concurrent confirms
    token_obj = await repo.get_token_for_confirm(token_value)

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
    
    # CCCD matches — validate profile state before confirming
    from .admission_state_machine import validate_transition

    if profile.status != "approved":
        log.warning(
            "Magic-link confirm rejected: profile not in approved state",
            profile_id=profile.id,
            current_status=profile.status,
            token_id=token_obj.id,
        )
        raise BadRequest(
            "Liên kết xác nhận không còn hiệu lực. "
            "Hồ sơ đã được xử lý hoặc trạng thái đã thay đổi."
        )

    try:
        validate_transition(profile.status, "confirmed")
    except ValueError as e:
        raise BadRequest(str(e))

    # STATE CHANGE — same semantics as confirm_enrollment
    profile.status = "confirmed"
    profile.confirmed_at = now
    profile.confirmed_via = "magic_link"
    profile.version += 1
    profile.updated_at = now

    # Mark token as consumed (no longer changes profile status)
    await repo.mark_token_used(token_obj)

    # PIPELINE SYNC: milestone consultation + lead sync
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_confirmed",
            actor=None,  # public flow, no authenticated actor
            profile_id=profile.id,
            fallback_officer_id=profile.approved_by_id,
        )

    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=None,
        reason="Applicant confirmed via magic link",
    )

    # Audit trail
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status="approved", new_status="confirmed",
        actor_user_id=None,
        reason="Magic-link confirmation",
        source="magic_link",
    )

    await db.flush()

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


# ==============================================================================
# BULK ACTION FUNCTIONS
# ==============================================================================

async def bulk_approve(
    db: AsyncSession,
    items: List[Dict[str, Any]],
    approver: models.User,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Bulk approve multiple admission profiles.

    Uses the same business guards as single approve_profile:
    - State machine validation
    - Optimistic locking (version check per item)
    - Application fee gate
    - Milestone consultation + lead sync
    - Audit trail

    Each item that fails is skipped individually; does NOT rollback the batch.

    Args:
        db: Database session
        items: List of dicts with profile_id and version
        approver: User performing the approval
        notes: Optional approval notes

    Returns:
        Dict with success_count, failed_count, failed_ids, errors, callbacks
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from .admission_state_machine import validate_transition
    from .lead_admission_sync import sync_lead_from_admission
    from ..services import audit_service

    if approver.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can approve profiles")

    success_count = 0
    failed_ids = []
    errors: Dict[int, str] = {}
    approved_profiles: List[models.AdmissionProfile] = []

    for item in items:
        profile_id = item["profile_id"]
        expected_version = item["version"]
        try:
            # Pessimistic lock + eager load lead
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            result = await db.execute(stmt)
            profile = result.scalar_one_or_none()

            if not profile:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # IDOR check
            _check_idor_access(profile, approver)

            # State machine validation
            try:
                validate_transition(profile.status, "approved")
            except ValueError as e:
                failed_ids.append(profile_id)
                errors[profile_id] = str(e)
                continue

            # Optimistic locking
            if expected_version != profile.version:
                failed_ids.append(profile_id)
                errors[profile_id] = (
                    f"Version mismatch: expected {expected_version}, "
                    f"actual {profile.version}. Refresh and retry."
                )
                continue

            # Application fee gate
            applied_rules = profile.applied_rules or {}
            requires_fee = applied_rules.get("requires_application_fee", False)
            fee_status = applied_rules.get("fee_status", "exempt")
            if requires_fee and fee_status == "pending":
                failed_ids.append(profile_id)
                errors[profile_id] = "Lệ phí xét tuyển chưa được thanh toán"
                continue

            # STATE CHANGE
            now = datetime.now(timezone.utc)
            _old_status = profile.status
            profile.status = "approved"
            profile.approved_at = now
            profile.approved_by_id = approver.id
            profile.approval_notes = notes
            profile.version += 1
            profile.updated_at = now

            # Milestone consultation
            if profile.lead:
                await _create_admission_milestone_consultation(
                    db=db,
                    lead=profile.lead,
                    event="profile_approved",
                    actor=approver,
                    profile_id=profile.id,
                )

            # Lead sync
            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=approver.id,
                reason="Admission profile approved (bulk)",
            )

            # Audit trail
            await audit_service.log_status_change(
                db, "AdmissionProfile", profile.id,
                old_status=_old_status, new_status="approved",
                actor_user_id=approver.id,
                source="bulk_api",
            )

            # Annotate for router notification dispatch
            profile._pre_status = _old_status  # type: ignore[attr-defined]
            approved_profiles.append(profile)
            success_count += 1

        except ResourceNotFoundError:
            failed_ids.append(profile_id)
            errors[profile_id] = "Profile not found"
        except Exception as e:
            log.error("Bulk approve failed for profile", profile_id=profile_id, error=str(e))
            failed_ids.append(profile_id)
            errors[profile_id] = str(e)

    await db.flush()

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors if errors else None,
        "message": f"Approved {success_count} of {len(items)} profiles",
        "_approved_profiles": approved_profiles,
    }


async def bulk_reject(
    db: AsyncSession,
    items: List[Dict[str, Any]],
    rejector: models.User,
    reason: str,
) -> Dict[str, Any]:
    """
    Bulk reject multiple admission profiles.

    Uses the same business guards as single reject_profile:
    - State machine validation
    - Optimistic locking (version check per item)
    - Milestone consultation + lead sync
    - Audit trail

    Each item that fails is skipped individually; does NOT rollback the batch.

    Args:
        db: Database session
        items: List of dicts with profile_id and version
        rejector: User performing the rejection
        reason: Rejection reason (required)

    Returns:
        Dict with success_count, failed_count, failed_ids, errors, _rejected_profiles
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from .admission_state_machine import validate_transition
    from .lead_admission_sync import sync_lead_from_admission
    from ..services import audit_service

    if rejector.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can reject profiles")

    success_count = 0
    failed_ids = []
    errors: Dict[int, str] = {}
    rejected_profiles: List[models.AdmissionProfile] = []

    for item in items:
        profile_id = item["profile_id"]
        expected_version = item["version"]
        try:
            # Pessimistic lock + eager load lead
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            result = await db.execute(stmt)
            profile = result.scalar_one_or_none()

            if not profile:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # IDOR check
            _check_idor_access(profile, rejector)

            # State machine validation
            try:
                validate_transition(profile.status, "rejected")
            except ValueError as e:
                failed_ids.append(profile_id)
                errors[profile_id] = str(e)
                continue

            # Optimistic locking
            if expected_version != profile.version:
                failed_ids.append(profile_id)
                errors[profile_id] = (
                    f"Version mismatch: expected {expected_version}, "
                    f"actual {profile.version}. Refresh and retry."
                )
                continue

            # STATE CHANGE
            now = datetime.now(timezone.utc)
            _old_status = profile.status
            profile.status = "rejected"
            profile.rejected_at = now
            profile.rejected_by_id = rejector.id
            profile.rejection_reason = reason
            profile.version += 1
            profile.updated_at = now

            # Milestone consultation
            if profile.lead:
                await _create_admission_milestone_consultation(
                    db=db,
                    lead=profile.lead,
                    event="profile_rejected",
                    actor=rejector,
                    profile_id=profile.id,
                    reason=reason,
                )

            # Lead sync
            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=rejector.id,
                reason=f"Admission profile rejected (bulk): {reason[:50]}",
            )

            # Audit trail
            await audit_service.log_status_change(
                db, "AdmissionProfile", profile.id,
                old_status=_old_status, new_status="rejected",
                actor_user_id=rejector.id,
                reason=reason,
                source="bulk_api",
            )

            # Annotate for router notification dispatch
            profile._pre_status = _old_status  # type: ignore[attr-defined]
            rejected_profiles.append(profile)
            success_count += 1

        except ResourceNotFoundError:
            failed_ids.append(profile_id)
            errors[profile_id] = "Profile not found"
        except Exception as e:
            log.error("Bulk reject failed for profile", profile_id=profile_id, error=str(e))
            failed_ids.append(profile_id)
            errors[profile_id] = str(e)

    await db.flush()

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors if errors else None,
        "message": f"Rejected {success_count} of {len(items)} profiles",
        "_rejected_profiles": rejected_profiles,
    }


async def bulk_assign(
    db: AsyncSession,
    profile_ids: List[int],
    officer_id: int,
    assigner: models.User,
) -> Dict[str, Any]:
    """
    Bulk assign profiles to an officer (updates lead.assigned_officer_id).

    Security:
    - Manager/Admin can assign within their unit
    - IDOR: Verifies each profile is accessible to user

    Args:
        db: Database session
        profile_ids: List of profile IDs to assign
        officer_id: ID of the officer to assign to
        assigner: User performing the assignment

    Returns:
        Dict with success_count, failed_count, failed_ids, errors, message
    """
    from app.repositories import AdmissionRepository

    if assigner.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can assign profiles")

    # Verify officer exists
    officer = await db.get(models.User, officer_id)
    if not officer:
        raise ResourceNotFoundError("Officer not found")

    # M4: Validate officer unit matches assigner unit (Admin bypass)
    if assigner.role != UserRole.ADMIN:
        if officer.unit_id != assigner.unit_id:
            raise BadRequest("Cannot assign to officer from different unit")

    repo = AdmissionRepository(db)
    success_count = 0
    failed_ids = []
    errors: Dict[int, str] = {}

    for profile_id in profile_ids:
        try:
            profile = await repo.get_profile_by_id_with_lead(profile_id)
            if not profile:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # IDOR check for non-admin (return "not found" to prevent enumeration)
            if assigner.role != UserRole.ADMIN and profile.lead.unit_id != assigner.unit_id:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # Update lead assignment
            _old_officer_id = profile.lead.assigned_officer_id
            profile.lead.assigned_officer_id = officer_id
            success_count += 1

            # Audit trail
            from ..services import audit_service
            await audit_service.log_changes(
                db, "Lead", profile.lead.id, "assigned",
                changes={"assigned_officer_id": {"old": _old_officer_id, "new": officer_id}},
                actor_user_id=assigner.id,
                source="bulk_api",
            )

        except Exception as e:
            log.error("Bulk assign failed for profile", profile_id=profile_id, error=str(e))
            failed_ids.append(profile_id)
            errors[profile_id] = str(e)

    await db.flush()

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors if errors else None,
        "message": f"Assigned {success_count} of {len(profile_ids)} profiles to officer",
    }
