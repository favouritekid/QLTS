# app/services/lead_service.py
from datetime import (
    datetime, timezone  # ✅ SỬA LỖI: Thêm dấu cách (E231) và xóa cách thừa cuối dòng (W291)
)
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import case, func, or_, select  # ✅ SỬA LỖI: Thêm 'desc' vào import và xóa comment
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from .. import models, schemas
from ..config import settings
from ..utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from ..services import pipeline_service, distribution_service, audit_service
from ..core.status_mapping import sync_lead_status_from_consultation
from ..core.constants import UserRole
from .status_helper import StatusHelper, AssignmentStatus
from ..repositories import LeadRepository  # ✅ PHASE 2: Repository Pattern
from ..repositories.collaborator_repository import CollaboratorRepository
from .lead_profile_sync import sync_profile_from_lead, detect_changed_personal_fields, SYNCABLE_FIELDS
from ..utils.csv_helpers import sanitize_csv_cell
from ..core.events import SystemEvents
from .notification_dispatcher import dispatch

log = structlog.get_logger(__name__)


def _handle_lead_integrity_error(exc: IntegrityError) -> None:
    """Convert DB IntegrityError from lead unique indexes into DuplicateResourceError."""
    detail = str(exc.orig) if exc.orig else str(exc)
    if "uq_lead_email_unit_active" in detail:
        raise DuplicateResourceError(
            detail="Email này đã tồn tại trong đơn vị. (DB constraint)"
        ) from exc
    if "uq_lead_phone_active" in detail:
        raise DuplicateResourceError(
            detail="Số điện thoại này đã được sử dụng bởi lead khác. (DB constraint)"
        ) from exc
    # Re-raise unknown integrity errors
    raise


# =========================================================================
# ALLOWED FIELDS FOR LEAD UPDATE (Defense in Depth)
# =========================================================================
# Explicit whitelist of fields that can be updated via API.
# Even if Pydantic schema allows a field, service layer double-checks.
# Fields NOT in this list will be blocked and logged as potential attack.
# =========================================================================
ALLOWED_LEAD_UPDATE_FIELDS: frozenset = frozenset({
    # Personal/Contact info
    "full_name",
    "phone",
    "phone2",
    "email",
    # CRM info
    "source",
    "education_level",
    "gpa",
    "location",
    # Officer assessment (CRM operational)
    "officer_rating",
    "officer_summary",
    # Fit score input fields (manual assessment)
    "birth_year",
    "location_proximity",
    "occupation_relevance",
    "academic_performance",
})

# Fields handled separately with special logic (not blocked, but not direct setattr)
SPECIAL_HANDLED_FIELDS: frozenset = frozenset({
    "consultation_status_id",  # Blocked - must use consultation flow
    "pipeline_stage_id",       # Blocked - must use consultation flow
    "offering_id",             # Handled separately for auto-reassign
    "unit_id",                 # Handled separately for reassignment
    "version",                 # Optimistic locking - not stored directly
    "referrer_id",             # Handled separately with CTV validation
})


# =========================================================================
# TERMINAL STATUS GUARD
# =========================================================================
# Phase "enrolled" + is_final = HARD BLOCK (Lead đã hoàn tất quy trình)
# Other phases + is_final = SOFT BLOCK (cho phép ghi nhận, không update status)
# =========================================================================

class TerminalGuardResult:
    """Result of terminal status check."""
    __slots__ = ("is_terminal", "hard_block", "reason", "current_status")

    def __init__(
        self,
        is_terminal: bool = False,
        hard_block: bool = False,
        reason: str = "",
        current_status: Optional["models.ConsultationStatus"] = None
    ):
        self.is_terminal = is_terminal
        self.hard_block = hard_block
        self.reason = reason
        self.current_status = current_status


async def check_terminal_status_guard(
    db: AsyncSession,
    lead: "models.Lead",
) -> TerminalGuardResult:
    """
    Check if lead is in a terminal state that blocks or limits further updates.

    Terminal Status Guard Logic:
    - If current status has is_final=True AND phase="enrolled" → HARD BLOCK
      (Lead đã nhập học/bảo lưu - quy trình hoàn tất)
    - If current status has is_final=True AND phase!="enrolled" → SOFT BLOCK
      (Lead đã từ chối/rút hồ sơ - cho phép ghi nhận nhưng không update status)
    - Otherwise → ALLOW (không có guard)

    Args:
        db: Database session
        lead: Lead object (must be loaded from DB)

    Returns:
        TerminalGuardResult with:
        - is_terminal: True if current status is terminal
        - hard_block: True if should completely block consultation creation
        - reason: Human-readable explanation
        - current_status: The ConsultationStatus object (if loaded)
    """
    if not lead.consultation_status_id:
        # Lead chưa có status → cho phép
        return TerminalGuardResult(is_terminal=False)

    # Lấy current status với is_final và phase
    current_status = await db.get(models.ConsultationStatus, lead.consultation_status_id)
    if not current_status:
        log.warning(
            "Terminal guard: current_status not found",
            lead_id=lead.id,
            consultation_status_id=lead.consultation_status_id
        )
        return TerminalGuardResult(is_terminal=False)

    # Check terminal state
    if not current_status.is_final:
        return TerminalGuardResult(is_terminal=False, current_status=current_status)

    # Terminal state detected
    if current_status.phase == "enrolled":
        # HARD BLOCK: Lead đã nhập học/bảo lưu
        return TerminalGuardResult(
            is_terminal=True,
            hard_block=True,
            reason=f"Lead đang ở trạng thái '{current_status.name}' (phase={current_status.phase}, is_final=True). "
                   f"Không thể thêm consultation mới cho lead đã hoàn tất quy trình nhập học.",
            current_status=current_status
        )
    else:
        # SOFT BLOCK: Lead terminal nhưng không phải enrolled (từ chối, rút hồ sơ, etc.)
        return TerminalGuardResult(
            is_terminal=True,
            hard_block=False,
            reason=f"Lead đang ở trạng thái terminal '{current_status.name}' (phase={current_status.phase}, is_final=True). "
                   f"Cho phép ghi nhận consultation nhưng không cập nhật lead status.",
            current_status=current_status
        )


async def update_lead_next_activity(
    db: AsyncSession,
    lead_id: int
) -> None:
    """
    Cập nhật lead.next_activity_at = scheduled_at sớm nhất chưa gửi reminder.

    Logic:
    - Tìm MIN(scheduled_at) trong consultations WHERE:
      - lead_id = lead_id
      - reminder_sent = False
      - scheduled_at >= NOW (chỉ tương lai, không lấy quá khứ)
      - scheduled_at IS NOT NULL
    - Set lead.next_activity_at = giá trị tìm được (hoặc NULL nếu không có)

    Args:
        db: Database session
        lead_id: Lead ID cần update
    """
    # ✅ REFACTORED: Use LeadRepository
    repo = LeadRepository(db)
    await repo.update_next_activity(lead_id)
    # Logging handled inside repository or implicit
    return


def calculate_fit_score(
    lead_birth_year: Optional[int],
    lead_education_level: Optional[str],
    lead_location_proximity: int,
    lead_occupation_relevance: int,
    lead_source: Optional[str],
    lead_academic_performance: int,
    scoring_rules: Optional[dict],
) -> int:
    """
    Calculate Fit Score (0-40 points) for lead qualification.
    
    Scoring breakdown (40 total):
    - Age: 0/4/8 based on target age range
    - Education: 0/4/8 based on required education
    - Location: 0/2/5 (Officer self-assessment)
    - Occupation: 0/2/5 (Officer self-assessment)
    - Hot Level: 0/4/8 (per-offering config)
    - Source: 1-3 (fixed mapping)
    - Academic Performance: 0/1/2/3 (Officer assessment)
    
    Args:
        lead_birth_year: Lead's birth year (e.g., 2000)
        lead_education_level: Lead's education level
        lead_location_proximity: 0=Far, 1=Nearby, 2=Close
        lead_occupation_relevance: 0=Unrelated, 1=Indirect, 2=Direct
        lead_source: Lead source (referral, website, etc.)
        lead_academic_performance: 0=Weak, 1=Average, 2=Good, 3=Excellent
        scoring_rules: ProgramOffering.scoring_rules JSON
        
    Returns:
        int: Fit Score (0-40)
    """
    from datetime import datetime
    
    score = 0
    current_year = datetime.now().year
    
    # Default scoring rules if not provided
    if not scoring_rules:
        scoring_rules = {}
    
    # 1. Age Score (0/4/8 points)
    if lead_birth_year:
        age = current_year - lead_birth_year
        target_min = scoring_rules.get("target_age_min", 18)
        target_max = scoring_rules.get("target_age_max", 60)
        
        if target_min <= age <= target_max:
            score += 8  # Exact match
        elif abs(age - target_min) <= 3 or abs(age - target_max) <= 3:
            score += 4   # Close match (within 3 years)
        # else: 0 points
    
    # 2. Education Score (0/4/8 points)
    if lead_education_level:
        required_edu = scoring_rules.get("required_education")
        if required_edu:
            EDUCATION_ORDER = ["high_school", "diploma", "bachelor", "master", "phd"]
            lead_edu_idx = EDUCATION_ORDER.index(lead_education_level.lower()) if lead_education_level.lower() in EDUCATION_ORDER else -1
            req_edu_idx = EDUCATION_ORDER.index(required_edu.lower()) if required_edu.lower() in EDUCATION_ORDER else -1
            
            if lead_edu_idx >= 0 and req_edu_idx >= 0:
                if lead_edu_idx == req_edu_idx:
                    score += 8  # Exact match
                elif lead_edu_idx > req_edu_idx:
                    score += 4   # Higher than required
                # else: 0 points (lower than required)
    
    # 3. Location Score (0/2/5 points) - Officer self-assessment
    LOCATION_SCORES = {0: 0, 1: 2, 2: 5}
    score += LOCATION_SCORES.get(lead_location_proximity, 0)
    
    # 4. Occupation Score (0/2/5 points) - Officer self-assessment
    OCCUPATION_SCORES = {0: 0, 1: 2, 2: 5}
    score += OCCUPATION_SCORES.get(lead_occupation_relevance, 0)
    
    # 5. Hot Level Score (0/4/8 points)
    hot_level = scoring_rules.get("hot_level", 0)
    HOT_LEVEL_SCORES = {0: 0, 1: 4, 2: 8}
    score += HOT_LEVEL_SCORES.get(hot_level, 0)
    
    # 6. Source Score (1-3 points) - Fixed mapping
    SOURCE_SCORES = {
        "referral": 3, "event": 3,
        "website": 2, "social_media": 2, "walk_in": 2,
        "phone": 1, "email": 1, "other": 1
    }
    if lead_source:
        score += SOURCE_SCORES.get(lead_source.lower(), 1)
    
    # 7. Academic Performance Score (0-3 points)
    score += min(lead_academic_performance, 3)
    
    # Cap at 40
    return min(score, 40)

async def calculate_lead_score(
    db: AsyncSession,
    lead_education_level: Optional[str] = None,
    lead_gpa: Optional[float] = None,
    lead_source: Optional[str] = None,
    lead_location: Optional[str] = None,
    unit_id: Optional[int] = None,
    # Behavioral metrics
    consultation_count: int = 0,
    has_application: bool = False,
    days_since_last_activity: int = 0,
) -> int:
    """
    Calculate lead score based on configurable rules from LeadScoringConfig.

    Args:
        db: Database session
        lead_education_level: Education level of lead (high_school, bachelor, master, phd)
        lead_gpa: GPA of lead (0.0-10.0)
        lead_source: Source of lead (website, referral, social_media, etc.)
        lead_location: Location of lead
        unit_id: Organization unit ID (for unit-specific scoring config)
        consultation_count: Number of consultations
        has_application: Whether lead has submitted application
        days_since_last_activity: Days since last activity (for decay)

    Returns:
        int: Calculated lead score (0-100)
    """
    try:
        # Default scoring weights (used if no config found)
        default_education_scores = {
            "high_school": 20,
            "bachelor": 40,
            "master": 60,
            "phd": 80,
        }
        default_source_scores = {
            "referral": 30,
            "website": 20,
            "social_media": 15,
            "walk_in": 10,
            "email": 15,
            "phone": 15,
            "event": 25,
            "other": 5,
        }
        default_gpa_multiplier = 4  # 10.0 GPA × 4 = 40 points (0-10 scale)
        default_location_bonus = 20
        
        # Behavioral defaults
        default_consultation_score = 5  # Points per consultation
        default_max_consultation_score = 25
        default_application_score = 30
        default_stale_penalty = 10
        MAX_STALE_PENALTY = 50  # Hard cap — prevents config from wiping full score
        stale_threshold_days = 7

        score = 0

        # ✅ SPRINT 5: Use Repository for scoring config
        from app.repositories import LeadRepository
        lead_repo = LeadRepository(db)
        
        # Try to load scoring config from database
        scoring_config = None
        if unit_id:
            scoring_config = await lead_repo.get_scoring_config_by_unit(unit_id)

        # Extract config params or use defaults
        if scoring_config and scoring_config.params:
            params = scoring_config.params
            education_scores = params.get("education_scores", default_education_scores)
            source_scores = params.get("source_scores", default_source_scores)
            gpa_multiplier = params.get("gpa_multiplier", default_gpa_multiplier)
            priority_locations = params.get("priority_locations", [])
            location_bonus = params.get("location_bonus", default_location_bonus)
            
            # Behavioral config
            consultation_score_weight = params.get("consultation_score", default_consultation_score)
            max_consultation_score = params.get("max_consultation_score", default_max_consultation_score)
            application_score = params.get("application_score", default_application_score)
            stale_penalty = params.get("stale_penalty", default_stale_penalty)
        else:
            education_scores = default_education_scores
            source_scores = default_source_scores
            gpa_multiplier = default_gpa_multiplier
            priority_locations = []
            location_bonus = default_location_bonus

            consultation_score_weight = default_consultation_score
            max_consultation_score = default_max_consultation_score
            application_score = default_application_score
            stale_penalty = default_stale_penalty

        # Sanitize stale_penalty: must be a finite non-negative number within [0, MAX]
        try:
            import math
            stale_penalty = float(stale_penalty)
            if not math.isfinite(stale_penalty):
                log.warning(
                    "stale_penalty is non-finite, falling back to default",
                    raw_value=stale_penalty,
                    fallback=default_stale_penalty,
                    unit_id=unit_id,
                )
                stale_penalty = default_stale_penalty
            elif stale_penalty < 0:
                log.warning(
                    "stale_penalty is negative, falling back to default",
                    raw_value=stale_penalty,
                    fallback=default_stale_penalty,
                    unit_id=unit_id,
                )
                stale_penalty = default_stale_penalty
            elif stale_penalty > MAX_STALE_PENALTY:
                log.warning(
                    "stale_penalty exceeds MAX_STALE_PENALTY, clamping",
                    raw_value=stale_penalty,
                    clamped_to=MAX_STALE_PENALTY,
                    unit_id=unit_id,
                )
                stale_penalty = MAX_STALE_PENALTY
        except (TypeError, ValueError):
            log.warning(
                "stale_penalty has invalid type, falling back to default",
                raw_value=repr(stale_penalty),
                fallback=default_stale_penalty,
                unit_id=unit_id,
            )
            stale_penalty = default_stale_penalty

        # --- Demographic Scoring ---
        
        # Calculate education score
        if lead_education_level:
            score += education_scores.get(lead_education_level.lower(), 0)

        # Calculate GPA score (0-10 scale)
        if lead_gpa is not None and lead_gpa > 0:
            gpa_score = min(int(lead_gpa * gpa_multiplier), 40)  # Cap at 40 points
            score += gpa_score

        # Calculate source score
        if lead_source:
            score += source_scores.get(lead_source.lower(), 0)

        # Calculate location bonus
        if lead_location and priority_locations:
            if lead_location.lower() in [loc.lower() for loc in priority_locations]:
                score += location_bonus

        # --- Behavioral Scoring (Auto) ---
        
        # Consultation score
        if consultation_count > 0:
            cons_score = min(consultation_count * consultation_score_weight, max_consultation_score)
            score += cons_score
            
        # Application score
        if has_application:
            score += application_score
            
        # Stale penalty
        if days_since_last_activity > stale_threshold_days:
            score -= stale_penalty

        # Cap score at 0-100
        final_score = max(0, min(score, 100))

        log.debug(
            "Lead score calculated",
            education=lead_education_level,
            gpa=lead_gpa,
            cons_count=consultation_count,
            has_app=has_application,
            stale_days=days_since_last_activity,
            base_score=score,
            final_score=final_score,
        )

        return final_score

    except Exception as e:
        log.error(
            "Error calculating lead score, returning default 0",
            error=str(e),
            exc_info=True,
        )
        return 0


async def _log_lead_state_change(
    db: AsyncSession,
    lead: models.Lead,
    old_state: dict,
    new_state: dict,
    changed_by: Optional[models.User] = None,
    reason: str = "State updated",
    loss_reason_code: Optional[str] = None,
):
    """
    Hàm helper tập trung để ghi lại bất kỳ thay đổi trạng thái nào của Lead.
    """
    # Chỉ ghi log nếu thực sự có thay đổi
    if old_state == new_state:
        log.debug(
            "No state change detected, skipping history log.",
            lead_id=getattr(lead, "id", None),
        )  # Thêm getattr phòng trường hợp lead chưa có ID
        return

    # Flush để lấy ID nếu chưa có (ví dụ khi tạo mới)
    if lead.id is None:
        try:
            await db.flush([lead])  # Flush chỉ đối tượng lead
            # Kiểm tra lại ID sau khi flush
            if lead.id is None:
                log.error(
                    "Failed to obtain Lead ID after flush, cannot log history.",
                    lead_email=lead.email,
                )
                # Có thể raise lỗi ở đây nếu việc log history là bắt buộc
                return  # Hoặc bỏ qua việc log nếu ID không lấy được
        except Exception as e:
            # Nếu flush bị lỗi (ví dụ: lỗi FK khác), ta log và raise ngay
            log.error(
                "Failed to flush Lead object before logging history",
                lead_email=lead.email,
                error=str(e),
            )
            raise  # Ném lỗi ban đầu (ví dụ: IntegrityError) lên để service xử lý

    history_entry = models.LeadStatusHistory(
        lead_id=lead.id,  # Giờ chắc chắn có ID
        changed_by_user_id=changed_by.id if changed_by else None,
        reason=reason,
        old_status=old_state.get("status"),
        old_consultation_status_id=old_state.get("consultation_status_id"),
        old_pipeline_stage_id=old_state.get("pipeline_stage_id"),
        old_assigned_officer_id=old_state.get("assigned_officer_id"),
        new_status=new_state.get("status"),
        new_consultation_status_id=new_state.get("consultation_status_id"),
        new_pipeline_stage_id=new_state.get("pipeline_stage_id"),
        new_assigned_officer_id=new_state.get("assigned_officer_id"),
        # Loss Reason - for final negative status transitions
        loss_reason_code=loss_reason_code,
    )
    db.add(history_entry)
    log.info(
        "Lead state change history logged",
        lead_id=lead.id,
        reason=reason,
        loss_reason_code=loss_reason_code,
        old=old_state,
        new=new_state,
    )


def _get_current_lead_state(lead: models.Lead) -> dict:
    """Helper để chụp nhanh trạng thái hiện tại của Lead."""
    return {
        "status": lead.status,
        "assignment_status": getattr(lead, "assignment_status", "pending"),
        "consultation_status_id": lead.consultation_status_id,
        "pipeline_stage_id": lead.pipeline_stage_id,
        "assigned_officer_id": lead.assigned_officer_id,
    }


def _get_lead_audit_state(lead: models.Lead) -> dict:
    """
    Helper to capture comprehensive Lead state for audit logging.

    Captures all user-editable fields that should be tracked in audit logs.
    """
    return {
        "full_name": lead.full_name,
        "phone": lead.phone,
        "phone2": lead.phone2,
        "email": lead.email,
        "source": lead.source,
        "education_level": lead.education_level,
        "gpa": lead.gpa,
        "location": lead.location,
        "officer_summary": lead.officer_summary,
        "unit_id": lead.unit_id,
        "offering_id": lead.offering_id,
        "status": lead.status,
        "consultation_status_id": lead.consultation_status_id,
        "pipeline_stage_id": lead.pipeline_stage_id,
        "assigned_officer_id": lead.assigned_officer_id,
    }


async def get_lead_by_id(db: AsyncSession, lead_id: int, include_deleted: bool = False) -> models.Lead:
    """
    Lấy chi tiết Lead bằng ID (Detail View).
    
    ✅ REFACTORED: Now uses LeadRepository for data access.
    Includes full eager loading for Timeline and Insights.

    Args:
        db: Database session
        lead_id: Lead ID to fetch
        include_deleted: If True, include soft-deleted leads (default: False)
        
    Returns:
        Lead with all relationships loaded
        
    Raises:
        ResourceNotFoundError: If lead not found
    """
    repo = LeadRepository(db)
    lead = await repo.get_by_id_full(lead_id, include_deleted=include_deleted)
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_lead_by_id_shallow(db: AsyncSession, lead_id: int, include_deleted: bool = False) -> models.Lead:
    """
    Lấy chi tiết Lead (Shallow View - Nhanh).
    
    ✅ REFACTORED: Now uses LeadRepository for data access.
    Only loads minimal 1-1 relationships for quick operations.

    Args:
        db: Database session
        lead_id: Lead ID to fetch
        include_deleted: If True, include soft-deleted leads (default: False)
        
    Returns:
        Lead with basic relationships loaded
        
    Raises:
        ResourceNotFoundError: If lead not found
    """
    repo = LeadRepository(db)
    lead = await repo.get_by_id_shallow(lead_id, include_deleted=include_deleted)
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_leads(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    status: Optional[str] = None,
    assigned_officer_id: Optional[str] = None,  # Now comma-separated string for multi-select
    unit_id: Optional[int] = None,
    offering_id: Optional[str] = None,  # Now comma-separated string for multi-select
    source: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc",
    # === PIPELINE STAGE FILTER ===
    pipeline_stage_id: Optional[str] = None,  # Already string, now comma-separated for multi
    # === DATE RANGE FILTER ===
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    date_field: str = "created_at",
    # === SCORE RANGE FILTER ===
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    # === VALIDITY STATUS FILTER ===
    validity_status: Optional[str] = None,
    # === SELECTIVE EXPORT ===
    lead_ids: Optional[List[int]] = None,
) -> Tuple[int, List[models.Lead]]:
    """
    Lấy danh sách Leads (List View).

    ✅ PHASE 2 - WEEK 2: Refactored to use LeadRepository
    ✅ Multi-select filters: status, source, offering_id, pipeline_stage_id, assigned_officer_id now accept comma-separated values
    """
    from app.repositories import LeadRepository

    repo = LeadRepository(db)
    return await repo.get_filtered(
        skip=skip,
        limit=limit,
        status=status,
        assigned_officer_id=assigned_officer_id,
        unit_id=unit_id,
        offering_id=offering_id,
        source=source,
        search=search,
        sort_by=sort_by,
        order=order,
        # === PIPELINE STAGE FILTER ===
        pipeline_stage_id=pipeline_stage_id,
        # === DATE RANGE FILTER ===
        date_from=date_from,
        date_to=date_to,
        date_field=date_field,
        # === SCORE RANGE FILTER ===
        score_min=score_min,
        score_max=score_max,
        # === VALIDITY STATUS FILTER ===
        validity_status=validity_status,
        # === SELECTIVE EXPORT ===
        lead_ids=lead_ids,
    )



async def create_lead(
    db: AsyncSession,
    lead_in: schemas.LeadCreate,
    created_by: models.User = None
) -> Tuple[models.Lead, Callable]:
    """
    Tạo Lead mới với role-based logic.

    Role-based behavior:
    - Admin: Can set any unit_id, can assign to any officer or use auto-assignment
    - Manager: Can assign to officers in their unit or use auto-assignment
    - Officer: Auto-assigned to themselves, unit forced to their unit

    Args:
        db: Database session
        lead_in: Lead creation data
        created_by: User creating the lead (determines role-based behavior)

    Returns:
        Created Lead model

    Raises:
        DuplicateResourceError: If lead with same email/phone exists in unit
        PermissionDeniedError: If user tries to assign to officer outside their scope
    """
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task
    from datetime import datetime, timezone

    try:
        # === ROLE-BASED PREPROCESSING ===
        create_data = lead_in.model_dump()
        direct_assignment_officer_id = None  # Will be set if direct assignment is needed
        skip_auto_assignment = False
        unit_already_distributed = False  # Flag to skip second distribution call
        validated_collaborator = None  # Saved after referrer validation for smart routing

        if created_by:
            user_role = created_by.role

            if user_role == UserRole.OFFICER:
                # Officer: Force unit to their unit, auto-assign to themselves
                create_data["unit_id"] = created_by.unit_id
                direct_assignment_officer_id = created_by.id
                skip_auto_assignment = True
                log.info(
                    "Officer creating lead - will be assigned to themselves",
                    officer_id=created_by.id,
                    unit_id=created_by.unit_id
                )

            elif user_role == UserRole.MANAGER:
                # Manager: Always use their unit
                create_data["unit_id"] = created_by.unit_id
                # Can choose officer in their unit or use auto-assignment
                if create_data.get("assigned_officer_id"):
                    # Validate officer belongs to manager's unit
                    officer = await db.get(models.User, create_data["assigned_officer_id"])
                    if not officer or officer.unit_id != created_by.unit_id:
                        raise PermissionDeniedError(
                            detail="Manager can only assign leads to officers in their unit"
                        )
                    if officer.role != UserRole.OFFICER:
                        raise PermissionDeniedError(
                            detail="Can only assign leads to users with 'officer' role"
                        )
                    if officer.status != "active":
                        raise PermissionDeniedError(
                            detail=f"Cannot assign to inactive officer (status: {officer.status})"
                        )
                    direct_assignment_officer_id = create_data["assigned_officer_id"]
                    skip_auto_assignment = True
                    log.info(
                        "Manager directly assigning lead to officer",
                        manager_id=created_by.id,
                        officer_id=direct_assignment_officer_id
                    )
                # If no officer specified, use auto-assignment (Celery)

            elif user_role == UserRole.ADMIN:
                # Admin: unit_id can be auto-determined from offering distribution
                # If offering_id is provided, try to get unit from distribution config FIRST
                if create_data.get("offering_id") and not create_data.get("unit_id"):
                    # Try to get target unit from distribution config
                    target_unit_id = await distribution_service.get_target_unit_for_offering(
                        db,
                        offering_id=create_data["offering_id"],
                        fallback_unit_id=None  # No fallback - we want to know if config exists
                    )
                    if target_unit_id:
                        create_data["unit_id"] = target_unit_id
                        unit_already_distributed = True  # Skip second distribution call
                        log.info(
                            "Admin: unit auto-determined from offering distribution",
                            offering_id=create_data["offering_id"],
                            unit_id=target_unit_id
                        )
                    else:
                        raise BadRequest(
                            detail="Cannot determine unit: No distribution config for this offering. Please select a unit manually."
                        )

                # If still no unit_id after trying offering distribution, error
                if not create_data.get("unit_id"):
                    raise BadRequest(
                        detail="unit_id is required when no offering_id is provided"
                    )

                # Admin: Full control - can assign to any officer or use auto
                if create_data.get("assigned_officer_id"):
                    # Validate officer exists and has correct role
                    officer = await db.get(models.User, create_data["assigned_officer_id"])
                    if not officer:
                        raise ResourceNotFoundError(
                            detail=f"Officer with id {create_data['assigned_officer_id']} not found"
                        )
                    if officer.role != UserRole.OFFICER:
                        raise PermissionDeniedError(
                            detail="Can only assign leads to users with 'officer' role"
                        )
                    # ✅ FIX: Check officer is active (consistent with assign_lead_manually)
                    if officer.status != "active":
                        raise PermissionDeniedError(
                            detail=f"Cannot assign to inactive officer (status: {officer.status})"
                        )
                    direct_assignment_officer_id = create_data["assigned_officer_id"]
                    skip_auto_assignment = True
                    log.info(
                        "Admin directly assigning lead to officer",
                        admin_id=created_by.id,
                        officer_id=direct_assignment_officer_id
                    )
                # If no officer specified, use auto-assignment (Celery)

        # Remove assigned_officer_id from create_data (it's not a Lead model field for creation)
        create_data.pop("assigned_officer_id", None)

        # === REFERRER (CTV) VALIDATION ===
        referrer_id = create_data.pop("referrer_id", None)
        if referrer_id is not None:
            collab_repo = CollaboratorRepository(db)
            collaborator = await collab_repo.get_by_id(referrer_id)
            if not collaborator or collaborator.status != "active":
                raise ResourceNotFoundError("CTV giới thiệu không tồn tại hoặc chưa kích hoạt")

            # IDOR: Officer can only use their own managed CTVs
            if user_role == UserRole.OFFICER:
                if collaborator.managed_by_officer_id != created_by.id:
                    raise ResourceNotFoundError("CTV giới thiệu không tồn tại hoặc chưa kích hoạt")
            elif user_role == UserRole.MANAGER:
                if collaborator.unit_id != created_by.unit_id:
                    raise ResourceNotFoundError("CTV giới thiệu không tồn tại hoặc chưa kích hoạt")
            # Admin: no restriction

            create_data["referrer_id"] = referrer_id
            create_data["source"] = "referral"
            validated_collaborator = collaborator  # Save for smart routing later

        # === DUPLICATE CHECK ===
        # Phone: Check globally across ALL units (phone must be unique system-wide)
        # Email: Check within same unit only (email can exist in different units)
        
        # ✅ REFACTORED: Use LeadRepository for phone check
        repo = LeadRepository(db)
        
        # Determine check values
        check_phone = lead_in.phone
        check_phone2 = lead_in.phone2
        
        # Check for conflict
        existing_phone_lead = await repo.check_phone_conflict(check_phone, check_phone2)
        
        if existing_phone_lead:
            # Helper to get officer name
            officer_name = "Chưa phân công"
            if existing_phone_lead.assigned_officer:
                officer_name = existing_phone_lead.assigned_officer.full_name or "N/A"
            
            # Helper to get unit name (need to load if not loaded)
            unit_name = "N/A"
            if existing_phone_lead.unit_id:
                # Optimized: Repo should load unit or we fallback
                # For now assume repo loaded it or we lazy load
                if existing_phone_lead.unit:
                     unit_name = existing_phone_lead.unit.name
                else:
                     # Fallback minimal query if absolutely needed (avoid if possible)
                     unit_temp = await db.get(models.OrganizationUnit, existing_phone_lead.unit_id)
                     if unit_temp: unit_name = unit_temp.name
            
            lead_name = existing_phone_lead.full_name or "N/A"
            lead_phone = existing_phone_lead.phone or "N/A"
            
            raise DuplicateResourceError(
                detail=f"Số điện thoại này đã tồn tại. Lead: {lead_name} (SĐT: {lead_phone}) - Đơn vị: {unit_name} - Quản lý bởi: {officer_name}"
            )

        # NOTE: Email check moved AFTER distribution/routing below (P0 fix)

        # === NEW FEATURE: Shared Offering Distribution ===
        # If Lead has offering_id, determine target unit via distribution config
        # This overrides the unit_id provided by user (if any offering-based routing exists)
        # SKIP distribution if officer/manager is creating lead (they keep lead in their unit)
        # SKIP if unit was already determined via distribution in role preprocessing
        if create_data.get("offering_id") and not skip_auto_assignment and not unit_already_distributed:
            original_unit_id = create_data.get("unit_id")
            target_unit_id = await distribution_service.get_target_unit_for_offering(
                db,
                offering_id=create_data["offering_id"],
                fallback_unit_id=original_unit_id  # Use provided unit as fallback
            )

            # Override unit_id with distribution result
            if target_unit_id != original_unit_id:
                log.info(
                    "Lead unit routed via Offering Distribution",
                    offering_id=create_data["offering_id"],
                    original_unit_id=original_unit_id,
                    routed_unit_id=target_unit_id,
                    routing_rule="WeightedRoundRobin"
                )
                create_data["unit_id"] = target_unit_id

        # === SMART AUTO-ASSIGN: Route referral leads to CTV's managing officer ===
        # When admin/manager creates referral lead WITHOUT specifying officer,
        # prioritize the CTV's managing officer if they're in the target unit.
        # This preserves the CTV-Officer relationship and improves conversion rates.
        if validated_collaborator and not skip_auto_assignment:
            ctv_officer_id = validated_collaborator.managed_by_officer_id
            if ctv_officer_id:
                ctv_officer = await db.get(models.User, ctv_officer_id)
                if (
                    ctv_officer
                    and ctv_officer.status == "active"
                    and ctv_officer.role == UserRole.OFFICER
                    and ctv_officer.unit_id == create_data.get("unit_id")
                ):
                    direct_assignment_officer_id = ctv_officer.id
                    skip_auto_assignment = True
                    log.info(
                        "Smart auto-assign: routing referral lead to CTV's managing officer",
                        referrer_id=validated_collaborator.id,
                        officer_id=ctv_officer.id,
                        unit_id=create_data.get("unit_id"),
                    )
                else:
                    log.info(
                        "Smart auto-assign: CTV's officer not eligible for target unit, fallback to round-robin",
                        referrer_id=validated_collaborator.id,
                        ctv_officer_id=ctv_officer_id,
                        target_unit_id=create_data.get("unit_id"),
                        officer_status=ctv_officer.status if ctv_officer else "not_found",
                        officer_unit_id=ctv_officer.unit_id if ctv_officer else None,
                    )

        # ✅ P0 FIX: Email check AFTER distribution/routing determines final unit_id
        # Previously checked before distribution, so conflicts in target unit were missed
        if lead_in.email:
            existing_email_lead = await repo.check_email_conflict(
                email=lead_in.email,
                unit_id=create_data["unit_id"]
            )
            if existing_email_lead:
                officer_name = "Chưa phân công"
                if existing_email_lead.assigned_officer:
                    officer_name = existing_email_lead.assigned_officer.full_name or "N/A"
                lead_name = existing_email_lead.full_name or "N/A"
                lead_phone = existing_email_lead.phone or "N/A"
                raise DuplicateResourceError(
                    detail=f"Email này đã tồn tại trong đơn vị. Lead: {lead_name} (SĐT: {lead_phone}) - Quản lý bởi: {officer_name}"
                )

        # Calculate lead score before creating the lead
        calculated_score = await calculate_lead_score(
            db,
            lead_education_level=create_data.get("education_level"),
            lead_gpa=create_data.get("gpa"),
            lead_source=create_data.get("source"),
            lead_location=create_data.get("location"),
            unit_id=create_data.get("unit_id"),
        )

        # Set the calculated score
        create_data["lead_score"] = calculated_score
        db_lead = models.Lead(**create_data)

        # Lấy trạng thái ban đầu từ DB (database-driven, không hardcode ID)
        initial_status = await StatusHelper.get_initial_status(db)

        # Trạng thái "trước khi tạo"
        old_state = _get_current_lead_state(models.Lead())  # Trạng thái rỗng

        # Gán trạng thái ban đầu cho Lead mới
        if initial_status:
            await StatusHelper.sync_lead_status(db_lead, initial_status)
        else:
            # Ghi log cảnh báo nếu không tìm thấy status mặc định
            log.warning(
                "Initial consultation status not found during lead creation."
            )
            # Gán giá trị mặc định an toàn
            db_lead.status = "new"
            db_lead.consultation_status_id = None
            db_lead.pipeline_stage_id = None

        # Set initial assignment status
        StatusHelper.set_assignment_status(db_lead, AssignmentStatus.PENDING)

        # Trạng thái "sau khi gán"
        new_state = _get_current_lead_state(db_lead)

        # Thêm Lead vào session (chưa commit)
        db.add(db_lead)

        # Ghi log lịch sử thay đổi (cần flush để lấy lead.id)
        await _log_lead_state_change(
            db,
            db_lead,
            old_state,
            new_state,
            changed_by=None,  # Không có user nào thay đổi khi tạo
            reason="Lead created",
        )

        # === DIRECT ASSIGNMENT (if specified) ===
        # If direct assignment is needed, set it before commit
        if direct_assignment_officer_id:
            db_lead.assigned_officer_id = direct_assignment_officer_id
            db_lead.assigned_at = datetime.now(timezone.utc)
            # Update assignment_status to "assigned" (workflow status)
            StatusHelper.set_assignment_status(db_lead, AssignmentStatus.ASSIGNED)
            log.info(
                "Lead directly assigned to officer",
                lead_id=db_lead.id,
                officer_id=direct_assignment_officer_id,
                assignment_type="direct",
                assignment_status=db_lead.assignment_status
            )

        # === ✅ CRITICAL: Load relationships BEFORE flush to avoid greenlet errors ===
        # Must load offering while we're still in transaction context
        # Store relationship references immediately to avoid triggering lazy loads
        offering_name = ""
        if db_lead.offering_id:
            await db.refresh(db_lead, ["offering"])
            offering_obj = db_lead.offering  # Store reference immediately

            if offering_obj is not None:
                # Check if offering has program_id before attempting to load
                if hasattr(offering_obj, 'program_id') and offering_obj.program_id:
                    await db.refresh(offering_obj, ["program"])
                    program_obj = offering_obj.program  # Store reference

                    if program_obj is not None:
                        offering_name = f"{program_obj.name} - {offering_obj.offering_type}"
                    else:
                        offering_name = offering_obj.offering_type
                else:
                    offering_name = offering_obj.offering_type

        # ✅ TRANSACTION FIX: Flush instead of commit
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            _handle_lead_integrity_error(exc)
        await db.refresh(db_lead)

        # ✅ PR3: Register phone identities (DB-level uniqueness safety net)
        try:
            await repo.register_phone_identities(
                lead_id=db_lead.id,
                phone=db_lead.phone,
                phone2=db_lead.phone2,
            )
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            _handle_lead_integrity_error(exc)

        # ✅ AUDIT LOG: Log lead creation
        await audit_service.log_created(
            db,
            entity_type="Lead",
            entity_id=db_lead.id,
            actor_user_id=created_by.id if created_by else None,
            new_values={
                "full_name": db_lead.full_name,
                "phone": db_lead.phone,
                "email": db_lead.email,
                "unit_id": db_lead.unit_id,
                "offering_id": db_lead.offering_id,
                "source": db_lead.source,
                "status": db_lead.status,
            },
            source="api",
        )

        # ✅ Dispatch LEAD_CREATED notification in savepoint
        _lead_created_cb = None
        try:
            async with db.begin_nested():
                _, _lead_created_cb = await dispatch(
                    db=db,
                    event=SystemEvents.LEAD_CREATED,
                    payload={
                        "lead_id": db_lead.id,
                        "unit_id": db_lead.unit_id,
                        "lead_name": db_lead.full_name or "Unknown",
                        "source": db_lead.source or "Unknown",
                        "actor_id": created_by.id if created_by else 0,
                        "actor_name": created_by.full_name or created_by.username if created_by else "System",
                    },
                    dedupe_key=f"lead_created:{db_lead.id}",
                )
        except Exception as e:
            log.warning("Dispatch failed, business data preserved", lead_id=db_lead.id, error=str(e))

        # ✅ Dispatch LEAD_ASSIGNED notification in savepoint (if direct assignment)
        _lead_assigned_cb = None
        if skip_auto_assignment and direct_assignment_officer_id:
            try:
                async with db.begin_nested():
                    _, _lead_assigned_cb = await dispatch(
                        db=db,
                        event=SystemEvents.LEAD_ASSIGNED,
                        payload={
                            "lead_id": db_lead.id,
                            "officer_id": direct_assignment_officer_id,
                            "actor_id": created_by.id if created_by else 0,
                            "actor_name": created_by.full_name or created_by.username if created_by else "System",
                            "lead_name": db_lead.full_name or "Unknown",
                            "lead_phone": db_lead.phone or "",
                            "offering_name": offering_name
                        },
                        dedupe_key=f"lead_assigned:{db_lead.id}:{direct_assignment_officer_id}",
                    )
            except Exception as e:
                log.warning("Dispatch failed, business data preserved", lead_id=db_lead.id, error=str(e))

        # ✅ Create post-commit callback with all post-commit actions
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "New lead created successfully", lead_id=db_lead.id, email=db_lead.email
            )
            if _lead_created_cb:
                await _lead_created_cb()
            if skip_auto_assignment:
                if direct_assignment_officer_id and _lead_assigned_cb:
                    await _lead_assigned_cb()
                    log.info(
                        "Direct assignment notification dispatched",
                        lead_id=db_lead.id,
                        officer_id=direct_assignment_officer_id
                    )
            else:
                # Dispatch Celery task for auto-assignment
                try:
                    process_automatic_lead_assignment_task.delay(db_lead.id)
                    log.info("Auto-assignment task dispatched successfully", lead_id=db_lead.id)
                except Exception as e:
                    log.error(
                        "Failed to dispatch Celery auto-assignment task",
                        lead_id=db_lead.id,
                        error=str(e),
                        exc_info=True,
                    )

        # Get fully loaded lead object for return
        lead = await get_lead_by_id(db, db_lead.id)
        return lead, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to create lead",
            lead_email=lead_in.email,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_lead(
    db: AsyncSession, lead_id: int, lead_in: schemas.LeadUpdate, updated_by: models.User
) -> Tuple[models.Lead, Callable]:
    """
    Cập nhật Lead một cách an toàn, ghi log lịch sử.
    """
    async with db.begin_nested():  # Sử dụng transaction lồng nhau
        try:
            # ✅ REFACTORED: Use LeadRepository for locking
            repo = LeadRepository(db)
            db_lead = await repo.get_by_id_for_update(lead_id)

            if not db_lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")

            # ✅ FIX: Implement proper permission check (was just pass before)
            # Admin/Manager can update any lead, Officer can only update their assigned leads
            if updated_by.role not in (UserRole.ADMIN, UserRole.MANAGER):
                if db_lead.assigned_officer_id != updated_by.id:
                    raise PermissionDeniedError(
                        detail="You are not assigned to this lead."
                    )

            # ✅ OPTIMISTIC LOCKING: Check version if provided
            if lead_in.version is not None:
                if db_lead.version != lead_in.version:
                    log.warning(
                        "Optimistic lock conflict detected",
                        lead_id=lead_id,
                        expected_version=lead_in.version,
                        current_version=db_lead.version,
                        updated_by=updated_by.id
                    )
                    raise ConflictError(
                        detail=f"Lead đã được cập nhật bởi người khác. "
                               f"Vui lòng tải lại và thử lại. "
                               f"(Version: {lead_in.version} → {db_lead.version})"
                    )

            # Lưu trạng thái cũ trước khi thay đổi
            old_state = _get_current_lead_state(db_lead)

            # ✅ AUDIT LOG: Capture comprehensive state for audit logging
            old_audit_state = _get_lead_audit_state(db_lead)

            # ✅ BIDIRECTIONAL SYNC: Capture old personal info for Lead → Profile sync
            old_personal_info = {
                "full_name": db_lead.full_name,
                "phone": db_lead.phone,
                "email": db_lead.email,
            }

            # Lấy dữ liệu cập nhật từ schema Pydantic
            update_data = lead_in.model_dump(exclude_unset=True)

            # =========================================================================
            # ✅ IDENTITY FIELD LOCK: Block updates to identity fields when profile locked
            # Identity fields (full_name, phone, email) cannot be changed when Lead has
            # an AdmissionProfile in approved/rejected/enrolled state.
            # =========================================================================
            from .lead_profile_sync import check_lead_identity_update_allowed

            fields_being_updated = list(update_data.keys())
            allowed, block_reason, blocked_profile_id = await check_lead_identity_update_allowed(
                db=db,
                lead_id=lead_id,
                fields_to_update=fields_being_updated,
            )

            if not allowed:
                raise BusinessRuleViolation(detail=block_reason)

            # Kiểm tra trùng lặp email nếu email được cập nhật (case-insensitive)
            # Kiểm tra trùng lặp email nếu email được cập nhật (case-insensitive)
            if "email" in update_data and update_data["email"] and (
                not db_lead.email or update_data["email"].lower() != db_lead.email.lower()
            ):
                # ✅ REFACTORED: Use LeadRepository
                new_email = update_data["email"]
                dup_lead = await repo.check_email_conflict(
                    email=new_email, 
                    unit_id=db_lead.unit_id,
                    exclude_id=lead_id
                )
                
                if dup_lead:
                    officer_name = (
                        dup_lead.assigned_officer.full_name 
                        if dup_lead.assigned_officer 
                        else "Chưa phân công"
                    )
                    raise DuplicateResourceError(
                        detail=f"Email này đã được sử dụng. Lead: {dup_lead.full_name} (SĐT: {dup_lead.phone}) - Đang được quản lý bởi: {officer_name}"
                    )

            # Kiểm tra trùng lặp phone/phone2 nếu được cập nhật
            phone_changed = "phone" in update_data and update_data["phone"] != db_lead.phone
            phone2_changed = "phone2" in update_data and update_data["phone2"] != db_lead.phone2

            if phone_changed or phone2_changed:
                # Determine the new phone values to check
                new_phone = update_data.get("phone", db_lead.phone)
                new_phone2 = update_data.get("phone2", db_lead.phone2)

                # ✅ REFACTORED: Use Repository for global check (fixes unit-scope bug)
                repo = LeadRepository(db)
                dup_lead = await repo.check_phone_conflict(
                    phone=new_phone,
                    phone2=new_phone2,
                    exclude_id=lead_id
                )

                if dup_lead:
                    # Load unit for better error message (since it might be in another unit)
                    if dup_lead.unit_id:
                         await db.refresh(dup_lead, ["unit"])

                    officer_name = (
                        dup_lead.assigned_officer.full_name
                        if dup_lead.assigned_officer
                        else "Chưa phân công"
                    )
                    unit_name = dup_lead.unit.name if dup_lead.unit else "N/A"

                    raise DuplicateResourceError(
                        detail=f"Số điện thoại này đã được sử dụng. Lead: {dup_lead.full_name} (SĐT: {dup_lead.phone}) - Đơn vị: {unit_name} - Quản lý bởi: {officer_name}"
                    )

            # === NEW FEATURE: Auto-Reassign on Offering Change ===
            # Track offering_id change before applying updates
            old_offering_id = db_lead.offering_id
            offering_changed = "offering_id" in update_data and update_data["offering_id"] != old_offering_id

            # =========================================================================
            # ✅ EDGE CASE FIX: Block offering change when AdmissionProfile exists
            # AdmissionProfile contains snapshotted applied_rules from the offering's
            # admission path. Changing offering would make the rules invalid.
            # =========================================================================
            if offering_changed:
                from app.repositories import AdmissionRepository
                admission_repo = AdmissionRepository(db)
                existing_profile = await admission_repo.get_profile_by_lead_id(lead_id)

                if existing_profile:
                    log.warning(
                        "Blocked offering change: Lead has admission profile",
                        lead_id=lead_id,
                        old_offering_id=old_offering_id,
                        new_offering_id=update_data["offering_id"],
                        profile_id=existing_profile.id,
                        profile_status=existing_profile.status,
                        user_id=updated_by.id,
                    )
                    raise BusinessRuleViolation(
                        f"Không thể đổi ngành khi Lead đã có hồ sơ xét tuyển (#{existing_profile.id}, "
                        f"trạng thái: {existing_profile.status}). "
                        "Hồ sơ xét tuyển chứa quy định tuyển sinh của ngành cũ. "
                        "Vui lòng hủy hồ sơ xét tuyển trước khi đổi ngành."
                    )

            # Check if scoring-related fields are being updated
            scoring_fields = ["education_level", "gpa", "source", "location"]
            should_recalculate_score = any(field in update_data for field in scoring_fields)

            # =========================================================================
            # ✅ DEFENSE IN DEPTH: Whitelist validation for allowed fields
            # Even if Pydantic schema allows a field, we double-check here.
            # This prevents accidental exposure of internal fields like lead_score.
            # =========================================================================
            for key, value in update_data.items():
                if key in ALLOWED_LEAD_UPDATE_FIELDS:
                    # ✅ Field is in whitelist - safe to update
                    setattr(db_lead, key, value)
                elif key in SPECIAL_HANDLED_FIELDS:
                    # Field has special handling logic (processed below or already checked)
                    pass
                else:
                    # ⚠️ Field not in whitelist - potential security issue
                    log.warning(
                        "Blocked attempt to update non-whitelisted field",
                        field=key,
                        lead_id=lead_id,
                        user_id=updated_by.id,
                        user_role=updated_by.role,
                        hint="If this field should be updatable, add it to ALLOWED_LEAD_UPDATE_FIELDS",
                    )

            # Recalculate lead score if relevant fields changed
            if should_recalculate_score:
                recalculated_score = await calculate_lead_score(
                    db,
                    lead_education_level=db_lead.education_level,
                    lead_gpa=db_lead.gpa,
                    lead_source=db_lead.source,
                    lead_location=db_lead.location,
                    unit_id=db_lead.unit_id,
                )
                db_lead.lead_score = recalculated_score
                log.info(
                    "Lead score recalculated on update",
                    lead_id=lead_id,
                    old_score=db_lead.lead_score if not should_recalculate_score else "N/A",
                    new_score=recalculated_score,
                )

            # ✅ CRITICAL FIX: GOLDEN RULE ENFORCEMENT
            # Block direct status updates. Status must ONLY change via Consultation.
            if "consultation_status_id" in update_data or "pipeline_stage_id" in update_data:
                raise BadRequest(
                    detail="Không được phép cập nhật trạng thái trực tiếp. "
                           "Vui lòng sử dụng tính năng 'Thêm Tương Tác' (Consultation) để ghi nhận kết quả và thay đổi trạng thái."
                )

            # === REFERRER (CTV) VALIDATION on update ===
            if "referrer_id" in update_data:
                new_referrer_id = update_data["referrer_id"]
                if new_referrer_id is not None:
                    collab_repo = CollaboratorRepository(db)
                    collaborator = await collab_repo.get_by_id(new_referrer_id)
                    if not collaborator or collaborator.status != "active":
                        raise ResourceNotFoundError("CTV giới thiệu không tồn tại hoặc chưa kích hoạt")

                    user_role = updated_by.role
                    if user_role == UserRole.OFFICER:
                        if collaborator.managed_by_officer_id != updated_by.id:
                            raise ResourceNotFoundError("CTV giới thiệu không tồn tại hoặc chưa kích hoạt")
                    elif user_role == UserRole.MANAGER:
                        if collaborator.unit_id != updated_by.unit_id:
                            raise ResourceNotFoundError("CTV giới thiệu không tồn tại hoặc chưa kích hoạt")

                db_lead.referrer_id = new_referrer_id
                if new_referrer_id is not None:
                    db_lead.source = "referral"

            # === NEW FEATURE: Auto-Reassign when Offering Changes ===
            # If offering_id changed, re-route Lead to new Unit and reset assignment
            reassignment_triggered = False
            if offering_changed:
                new_offering_id = update_data["offering_id"]

                log.info(
                    "Offering changed on Lead update - checking for unit change",
                    lead_id=lead_id,
                    old_offering_id=old_offering_id,
                    new_offering_id=new_offering_id,
                    current_unit_id=db_lead.unit_id
                )

                # Apply offering_id update
                db_lead.offering_id = new_offering_id

                # Determine new target unit via distribution
                if new_offering_id:
                    new_target_unit_id = await distribution_service.get_target_unit_for_offering(
                        db,
                        offering_id=new_offering_id,
                        fallback_unit_id=db_lead.unit_id  # Current unit as fallback
                    )
                else:
                    # Offering removed - keep current unit
                    new_target_unit_id = db_lead.unit_id

                # Check if unit actually changed (territory conflict)
                if new_target_unit_id != db_lead.unit_id:
                    old_unit_id = db_lead.unit_id
                    old_officer_id = db_lead.assigned_officer_id

                    log.warning(
                        "Offering change causes Unit change - Auto-reassigning Lead",
                        lead_id=lead_id,
                        old_offering_id=old_offering_id,
                        new_offering_id=new_offering_id,
                        old_unit_id=old_unit_id,
                        new_unit_id=new_target_unit_id,
                        old_officer_id=old_officer_id,
                        reason="territorial_conflict"
                    )

                    # === ATOMIC REASSIGNMENT TRANSACTION ===
                    # 1. Update unit_id
                    db_lead.unit_id = new_target_unit_id

                    # 2. Reset assignment fields
                    db_lead.assigned_officer_id = None
                    db_lead.assigned_at = None

                    # 3. Set assignment_status to pending (waiting for new assignment)
                    StatusHelper.set_assignment_status(db_lead, AssignmentStatus.PENDING)

                    # 4. Create system AssignmentLog
                    reassignment_log = models.AssignmentLog(
                        lead_id=lead_id,
                        officer_id=updated_by.id,  # Log who triggered the change
                        method="system_auto_reassign",
                        reason=f"Offering changed from #{old_offering_id} to #{new_offering_id}. "
                               f"Unit changed from #{old_unit_id} to #{new_target_unit_id}. "
                               f"Previous officer: {old_officer_id}",
                        timestamp=datetime.now(timezone.utc)
                    )
                    db.add(reassignment_log)

                    reassignment_triggered = True

                    # ✅ P0 FIX: Re-check email uniqueness in NEW unit
                    # Offering change → unit change → email might conflict in target unit
                    if db_lead.email:
                        email_conflict = await repo.check_email_conflict(
                            email=db_lead.email,
                            unit_id=new_target_unit_id,
                            exclude_id=lead_id
                        )
                        if email_conflict:
                            raise DuplicateResourceError(
                                detail=f"Không thể chuyển đơn vị: Email '{db_lead.email}' đã tồn tại trong đơn vị đích. "
                                       f"Lead: {email_conflict.full_name} (SĐT: {email_conflict.phone})"
                            )

                    log.info(
                        "Lead auto-reassignment completed",
                        lead_id=lead_id,
                        new_unit_id=new_target_unit_id,
                        old_officer_id=old_officer_id,
                        assignment_status=db_lead.assignment_status
                    )

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(db_lead)

            # ✅ OPTIMISTIC LOCKING: Increment version
            db_lead.version = (db_lead.version or 1) + 1

            # ✅ PR3: Update phone identities when phone/phone2 changed
            if phone_changed or phone2_changed:
                await repo.update_phone_identities(
                    lead_id=lead_id,
                    phone=db_lead.phone,
                    phone2=db_lead.phone2,
                )

            # Thêm đối tượng vào session (đánh dấu là dirty)
            db.add(db_lead)

            # Ghi log lịch sử nếu có thay đổi
            await _log_lead_state_change(
                db,
                db_lead,
                old_state,
                new_state,
                changed_by=updated_by,
                reason=f"Lead details updated by {updated_by.role}",
            )

            # ✅ LEAD INSIGHTS UPGRADE: Update cached metrics
            # Especially important when lead_score changes (affects is_hot_lead)
            from app.services import lead_cache_service
            await lead_cache_service.update_lead_cache(db, lead_id, db_lead)

            # ✅ BIDIRECTIONAL SYNC: Sync personal info from Lead → AdmissionProfile
            # Only syncs to profiles in editable states (draft, submitted)
            new_personal_info = {
                "full_name": db_lead.full_name,
                "phone": db_lead.phone,
                "email": db_lead.email,
            }
            changed_personal_fields = detect_changed_personal_fields(
                old_personal_info, new_personal_info
            )
            if changed_personal_fields:
                synced, synced_profile_ids = await sync_profile_from_lead(
                    db=db,
                    lead=db_lead,
                    changed_fields=changed_personal_fields,
                    changed_by_user_id=updated_by.id,
                )
                if synced:
                    log.info(
                        "Personal info synced from Lead to AdmissionProfiles",
                        lead_id=lead_id,
                        changed_fields=changed_personal_fields,
                        synced_profile_ids=synced_profile_ids,
                    )

            # ✅ AUDIT LOG: Log lead update with changes (comprehensive field tracking)
            # Detect what fields were changed using full audit state
            audit_changes = audit_service.detect_changes(
                old_audit_state,
                _get_lead_audit_state(db_lead),
                exclude_fields=["_sa_instance_state", "updated_at", "created_at"]
            )
            if audit_changes:
                await audit_service.log_changes(
                    db,
                    entity_type="Lead",
                    entity_id=lead_id,
                    action="updated",
                    changes=audit_changes,
                    actor_user_id=updated_by.id,
                    source="api",
                )

            log.info("Lead updated successfully within transaction", lead_id=lead_id)
            # Transaction sẽ commit khi ra khỏi `async with db.begin_nested()`

        except IntegrityError as exc:
            # ✅ PR3: Convert phone identity IntegrityError to DuplicateResourceError
            _handle_lead_integrity_error(exc)
        except Exception as e:
            # Rollback tự động xảy ra khi có lỗi trong `async with`
            # Phân biệt giữa lỗi business logic và lỗi hệ thống
            if isinstance(e, (DuplicateResourceError, ResourceNotFoundError, PermissionDeniedError, ConflictError)):
                # Business logic exceptions - không cần traceback
                log.warning(
                    "Lead update rejected due to business rule",
                    lead_id=lead_id,
                    error=str(e),
                )
            else:
                # Unexpected system errors - cần traceback để debug
                log.error(
                    "Failed to update lead, rolling back nested transaction",
                    lead_id=lead_id,
                    error=str(e),
                    exc_info=True,
                )
            raise e  # Ném lại lỗi để router xử lý

        # === POST-COMMIT ACTIONS (Only if transaction succeeded) ===
        _reassign_cb = None

        if reassignment_triggered:
            # Dispatch notification for lead reassignment in savepoint (safe for post-commit callback)
            try:
                async with db.begin_nested():
                    _, _reassign_cb = await dispatch(
                        db=db,
                        event=SystemEvents.LEAD_REASSIGNED,
                        payload={
                            "lead_id": lead_id,
                            "old_officer_id": old_officer_id,  # type: ignore
                            "new_officer_id": None,  # Will be assigned by auto-assignment
                            "old_unit_id": old_unit_id,  # type: ignore
                            "new_unit_id": new_target_unit_id,  # type: ignore
                            "actor_id": updated_by.id,
                            "actor_name": updated_by.full_name or updated_by.username,
                            "reason": f"Offering changed from #{old_offering_id} to #{new_offering_id}",  # type: ignore
                            "user_ids": [old_officer_id] if old_officer_id else [],  # Notify old officer
                        },
                        dedupe_key=f"lead_reassigned:{lead_id}",
                    )
            except Exception as e:
                log.error(
                    "Failed to dispatch lead reassignment notification",
                    lead_id=lead_id,
                    error=str(e),
                    exc_info=True
                )
                # Don't fail the request - notifications are non-critical

        async def _post_commit():
            """Execute after router commits the transaction."""
            if _reassign_cb:
                try:
                    await _reassign_cb()
                except Exception:
                    log.error("Failed to execute reassignment notification callback", lead_id=lead_id, exc_info=True)

            if reassignment_triggered:
                try:
                    from ..celery_utils import process_automatic_lead_assignment_task
                    process_automatic_lead_assignment_task.delay(lead_id)
                    log.info("Auto-assignment task dispatched after offering change", lead_id=lead_id)
                except Exception:
                    log.error("Failed to dispatch auto-assignment task after offering change", lead_id=lead_id, exc_info=True)

        # Trả về lead đã được tải đầy đủ (bao gồm relations)
        lead = await get_lead_by_id(db, lead_id)
        return lead, _post_commit


async def add_consultation(
    db: AsyncSession, lead_id: int, officer_id: int, data: schemas.ConsultationCreate
) -> tuple[models.Consultation, bool, str | None]:
    """
    Thêm consultation mới, cập nhật trạng thái Lead và ghi log lịch sử.

    CONCURRENCY SAFE: Uses SELECT ... FOR UPDATE to prevent race conditions
    when multiple requests try to update the same lead's pipeline_stage.

    Returns:
        tuple: (consultation, status_updated, terminal_guard_reason)
        - consultation: The created Consultation object
        - status_updated: Whether the lead status was actually updated
        - terminal_guard_reason: Reason status was not updated (soft-terminal guard), or None
    """
    async with db.begin_nested():
        try:
            # ✅ REFACTORED: Use LeadRepository for locking
            repo = LeadRepository(db)
            lead = await repo.get_by_id_for_update(lead_id)

            if not lead:
                raise ResourceNotFoundError(f"Lead with id {lead_id} not found")
            
            # ✅ FIX: Check if lead is deleted
            if lead.deleted_at is not None:
                raise BadRequest(detail="Cannot add consultation to a deleted lead.")
            
            # Note: Relations are not eagerly loaded here. If accessed, explicit refresh needed.
            
            # Lấy Officer
            officer = await db.get(models.User, officer_id)
            if not officer:
                raise ResourceNotFoundError(f"Officer with id {officer_id} not found.")

            # ✅ FIX: Kiểm tra quyền - Admin và Manager có thể thêm consultation cho bất kỳ lead trong scope
            # Officer phải được gán cho Lead này
            if officer.role not in (UserRole.ADMIN, UserRole.MANAGER):
                if lead.assigned_officer_id != officer_id:
                    raise PermissionDeniedError(detail="You are not assigned to this lead.")

            # Lấy ConsultationStatus mới từ DB
            new_status = await db.get(models.ConsultationStatus, data.status_id)
            if not new_status:
                raise ResourceNotFoundError(
                    detail=f"Consultation status with id {data.status_id} not found."
                )

            # ✅ TERMINAL STATUS GUARD (Issue #3 fix)
            # Check if lead is in terminal state BEFORE any workflow validation
            terminal_guard = await check_terminal_status_guard(db, lead)
            if terminal_guard.hard_block:
                # HARD BLOCK: Lead đã nhập học - không cho tạo consultation
                log.warning(
                    "Terminal guard HARD BLOCK: cannot add consultation to enrolled lead",
                    lead_id=lead_id,
                    current_status_id=lead.consultation_status_id,
                    current_status_name=terminal_guard.current_status.name if terminal_guard.current_status else None,
                    attempted_status=new_status.id,
                    officer_id=officer_id,
                )
                raise BusinessRuleViolation(
                    detail=terminal_guard.reason
                )

            # SOFT BLOCK flag - sẽ sử dụng ở bước update lead status
            skip_status_update = terminal_guard.is_terminal

            # ✅ NEW: Validate workflow transition (following update_lead pattern)
            # Chỉ validate nếu lead đã có status và status thực sự thay đổi
            current_status_id = lead.consultation_status_id
            if current_status_id and current_status_id != data.status_id:
                # ✅ PHASE-BASED WORKFLOW: Validate phase before transition
                from app.services.phase_manager import (
                    derive_phase_from_admission,
                    is_status_allowed_for_phase,
                    UNIVERSAL_STATUSES,
                )
                from app.repositories import AdmissionRepository
                
                # Get admission profile to derive phase
                admission_repo = AdmissionRepository(db)
                admission_profile = await admission_repo.get_profile_by_lead_id(lead_id)
                current_phase = derive_phase_from_admission(admission_profile)
                
                # Check if new status is allowed in current phase
                # Note: officer.role is UserRole enum (StrEnum works with both string and enum comparisons)
                if not is_status_allowed_for_phase(current_phase, data.status_id, officer.role):
                    # Check if it's a universal status (always allowed)
                    if data.status_id not in UNIVERSAL_STATUSES:
                        raise BadRequest(
                            detail=f"Status '{new_status.name}' không hợp lệ trong phase '{current_phase.value}'. "
                                   f"Lead hiện đang ở giai đoạn {current_phase.value.upper()}."
                        )
                
                is_valid = await pipeline_service.validate_status_transition(
                    db, 
                    from_status_id=current_status_id, 
                    to_status_id=data.status_id
                )
                
                if not is_valid:
                    # ✅ SECURITY: Admin can bypass allowed_transitions rules ONLY
                    # Phase guard (is_status_allowed_for_phase) has ALREADY been checked above
                    # Admin bypass does NOT skip phase validation - only transition rules
                    if officer.role != UserRole.ADMIN:
                        raise BadRequest(
                            detail=f"Không thể chuyển trạng thái từ '{current_status_id}' sang '{data.status_id}'. "
                                   f"Quy trình không cho phép (Allowed Transitions). "
                                   f"Liên hệ Admin nếu cần bypass."
                        )
                    else:
                        # ✅ AUDIT: Double-check phase guard is respected even for admin
                        # This is redundant (already checked at line 1257) but adds defense-in-depth
                        if not is_status_allowed_for_phase(current_phase, data.status_id, "admin"):
                            if data.status_id not in UNIVERSAL_STATUSES:
                                log.error(
                                    "SECURITY: Admin attempted phase-violating transition (blocked)",
                                    admin_id=officer.id,
                                    lead_id=lead_id,
                                    current_phase=current_phase.value,
                                    target_status=data.status_id,
                                )
                                raise BadRequest(
                                    detail=f"Không thể bypass: Status '{new_status.name}' không thuộc phase '{current_phase.value}'. "
                                           f"Admin bypass chỉ bỏ qua transition rules, không bỏ qua phase guards."
                                )

                        # Log admin bypass for audit trail
                        log.warning(
                            "Admin bypassed transition rule in add_consultation",
                            admin_id=officer.id,
                            admin_username=officer.username,
                            lead_id=lead_id,
                            from_status=current_status_id,
                            to_status=data.status_id,
                            to_status_name=new_status.name,
                            current_phase=current_phase.value,
                            is_universal=new_status.is_universal,
                            reason="Admin override - no explicit transition rule exists but phase guard passed",
                        )


            # Lưu trạng thái Lead cũ
            old_state = _get_current_lead_state(lead)

            # ✅ LOSS REASON VALIDATION: Require loss_reason_code for final negative status
            # Validate BEFORE mutating lead/consultation state
            if new_status.is_final and new_status.outcome_type == "negative":
                if not data.loss_reason_code:
                    raise BadRequest(
                        detail="Vui lòng chọn lý do không tiếp tục (loss_reason_code) khi chuyển sang trạng thái cuối cùng."
                    )

            # ✅ TERMINAL STATUS GUARD (Issue #3) - Using check result from earlier
            # skip_status_update flag was set by check_terminal_status_guard() above
            if skip_status_update:
                log.warning(
                    "Terminal guard SOFT BLOCK: skipping lead status update for terminal lead",
                    lead_id=lead_id,
                    current_status_id=lead.consultation_status_id,
                    current_status_phase=terminal_guard.current_status.phase if terminal_guard.current_status else None,
                    attempted_status=new_status.id,
                    attempted_status_name=new_status.name,
                    officer_id=officer_id,
                    reason=terminal_guard.reason,
                )
                # Still create consultation record for history, but don't update lead status
                # Continue to consultation creation below without status update
            # ✅ Chỉ cập nhật pipeline nếu status.updates_pipeline = True
            elif new_status.updates_pipeline:
                # Cập nhật trạng thái Lead theo status mới của consultation
                lead.consultation_status_id = new_status.id
                lead.pipeline_stage_id = new_status.stage_id
                # ✅ Sync lead.status từ consultation_status (Hybrid Approach)
                sync_lead_status_from_consultation(lead, new_status)

                log.info(
                    "Updating lead pipeline",
                    lead_id=lead_id,
                    old_status=old_state.get("consultation_status_id"),
                    new_status=new_status.id,
                    status_name=new_status.name
                )
            else:
                # Universal status - chỉ ghi nhận consultation, không thay đổi pipeline
                log.info(
                    "Universal status - không update pipeline",
                    lead_id=lead_id,
                    status_id=new_status.id,
                    status_name=new_status.name,
                    is_universal=new_status.is_universal
                )

            # Chuẩn bị dữ liệu để tạo Consultation
            # Exclude fields that don't belong to Consultation model:
            # - status_id: mapped to consultation_status_id
            # - consultation_date: handled separately with fallback to NOW
            # - loss_reason_code/loss_reason_note: belong to LeadStatusHistory, not Consultation
            create_consult_data = data.model_dump(exclude={"status_id", "consultation_date", "loss_reason_code", "loss_reason_note"})
            # (Đã xóa .strip() vì Pydantic xử lý)

            # Handle consultation_date: use provided value or default to NOW
            consultation_date = data.consultation_date or datetime.now(timezone.utc)

            # Tạo đối tượng Consultation mới
            new_consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=officer_id,
                consultation_status_id=new_status.id,  # Gán status ID cho consultation
                consultation_date=consultation_date,
                **create_consult_data,
            )

            # Thêm các đối tượng vào session
            db.add(new_consultation)
            # ✅ P0 FIX: Always increment version when consultation is created
            # (previously only bumped when updates_pipeline=True)
            lead.version = (lead.version or 1) + 1
            db.add(lead)

            # Lấy trạng thái Lead mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead (chỉ khi có thay đổi thực sự)
            if new_status.updates_pipeline and old_state != new_state:
                await _log_lead_state_change(
                    db,
                    lead,
                    old_state,
                    new_state,
                    changed_by=officer,
                    reason=data.loss_reason_note or f"Consultation added: {data.method}",
                    loss_reason_code=data.loss_reason_code if (new_status.is_final and new_status.outcome_type == "negative") else None,
                )

            # Không cần commit ở đây, `async with` sẽ xử lý

            # Flush để lấy ID cho consultation mới (cần cho refresh)
            await db.flush([new_consultation])

            # ✅ LEAD INSIGHTS UPGRADE: Update cached metrics
            # Runs sync within transaction for consistency
            from app.services import lead_cache_service
            await lead_cache_service.update_lead_cache(db, lead_id, lead)

            # ✅ AUDIT LOG: Log consultation creation
            await audit_service.log_created(
                db,
                entity_type="Consultation",
                entity_id=new_consultation.id,
                actor_user_id=officer_id,
                new_values={
                    "lead_id": lead_id,
                    "consultation_status_id": new_status.id,
                    "consultation_status_name": new_status.name,
                    "method": data.method,
                    "consultation_date": consultation_date.isoformat() if consultation_date else None,
                },
                source="api",
            )

            # ✅ ARCHITECTURE FIX: Use Repository instead of direct query
            # Service must not query Model directly (Rule E: Repository Pattern)
            repo = LeadRepository(db)
            new_consultation = await repo.get_consultation_with_status_stage(new_consultation.id)

            # ✅ Quick Disposition: Cập nhật next_activity_at dựa trên tất cả consultations
            # NOTE: update_lead_cache already updates next_activity_at
            if data.scheduled_at:
                log.info(
                    "Consultation scheduled_at set",
                    lead_id=lead_id,
                    consultation_scheduled_at=data.scheduled_at.isoformat() if data.scheduled_at else None,
                )

            log.info(
                "New consultation added for lead",
                lead_id=lead_id,
                consultation_id=new_consultation.id,
                officer_id=officer_id,
            )
            # Return consultation + terminal guard diagnostics
            # status_updated = actual lead-state mutation (compare before/after)
            status_updated = old_state != new_state
            terminal_reason = terminal_guard.reason if skip_status_update else None
            return new_consultation, status_updated, terminal_reason

        except Exception as e:
            # Rollback tự động
            log.error(
                "Failed to add consultation",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e


async def assign_lead_manually(
    db: AsyncSession, lead_id: int, officer_id: int, assigner: models.User
) -> Tuple[models.Lead, Callable]:
    """
    Gán lead thủ công cho một officer, cập nhật trạng thái và ghi logs.

    ✅ REFACTORED: Now uses notification_dispatcher instead of direct socket calls.
    This ensures notifications are persisted to database AND sent via Socket.IO/Email.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead và Officer
            lead = await get_lead_by_id(db, lead_id)
            
            # ✅ FIX: Explicit deleted check (get_lead_by_id may not always exclude)
            if lead.deleted_at is not None:
                raise BadRequest(detail="Cannot assign a deleted lead.")
            
            officer = await db.get(models.User, officer_id)

            # Kiểm tra Officer hợp lệ
            if not officer:
                raise ResourceNotFoundError(
                    detail=f"User (Officer) with id {officer_id} not found."
                )
            if officer.role != UserRole.OFFICER:
                raise PermissionDeniedError(
                    detail=f"User with id {officer_id} is not an officer."
                )
            # ✅ FIX: Check officer is active
            if officer.status != "active":
                raise PermissionDeniedError(
                    detail=f"Officer with id {officer_id} is not active (status: {officer.status})."
                )

            # ✅ FIX: Manager can only assign to officers in their unit
            if assigner.role == UserRole.MANAGER:
                if officer.unit_id != assigner.unit_id:
                    raise PermissionDeniedError(
                        detail="Manager chỉ có thể phân công lead cho officer trong đơn vị của mình."
                    )

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)
            old_officer_id = lead.assigned_officer_id

            # Cập nhật Lead
            lead.assigned_officer_id = officer.id
            lead.assigned_at = datetime.now(timezone.utc)
            # Cập nhật assignment_status thành 'assigned'
            StatusHelper.set_assignment_status(lead, AssignmentStatus.ASSIGNED)

            # Cập nhật Officer
            officer.last_assigned_at = datetime.now(timezone.utc)
            db.add(officer)  # Đánh dấu officer là dirty

            # Tạo Assignment Log (distinguish initial assignment vs reassignment)
            is_reassignment = old_officer_id is not None and old_officer_id != officer_id
            log_method = "manual_reassignment" if is_reassignment else "manual"
            log_reason = (
                f"Reassigned from officer #{old_officer_id} to #{officer_id} by {assigner.role} {assigner.username}"
                if is_reassignment
                else f"Manually assigned by {assigner.role} {assigner.username}"
            )
            log_entry = models.AssignmentLog(
                lead_id=lead_id,
                officer_id=officer_id,
                method=log_method,
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),
            )
            # ✅ P0 FIX: Increment version on assignment change
            lead.version = (lead.version or 1) + 1
            db.add(lead)
            db.add(log_entry)

            # Lấy trạng thái mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db, lead, old_state, new_state, changed_by=assigner, reason=log_reason
            )

            log.info(
                "Lead assigned manually",
                lead_id=lead_id,
                officer_id=officer_id,
                assigner_id=assigner.id,
            )
            # Commit nested transaction (auto-commits on context exit)

        except Exception as e:
            # Rollback tự động
            log.error(
                "Failed to assign lead manually",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e

    # === ✅ Dispatch LEAD_ASSIGNED notification in savepoint ===
    _assign_cb = None
    try:
        # Load lead relationships for notification payload
        await db.refresh(lead, ["offering", "unit"])

        # Prepare notification payload according to LEAD_ASSIGNED schema
        notification_payload = {
            "lead_id": lead.id,
            "officer_id": officer.id,
            "actor_id": assigner.id,
            "actor_name": assigner.full_name or assigner.username,
            "lead_name": lead.full_name or "Unknown",
            "lead_phone": lead.phone or "",
            "offering_name": f"{lead.offering.program.name} - {lead.offering.offering_type}" if lead.offering and lead.offering.program else (lead.offering.offering_type if lead.offering else "N/A")
        }

        async with db.begin_nested():
            _, _assign_cb = await dispatch(
                db=db,
                event=SystemEvents.LEAD_ASSIGNED,
                payload=notification_payload,
                dedupe_key=f"lead_assigned:{lead.id}:{officer.id}",
            )
    except Exception as e:
        log.error(
            "Failed to dispatch assignment notification (lead still assigned successfully)",
            lead_id=lead.id,
            officer_id=officer.id,
            error=str(e),
            exc_info=True
        )

    async def _post_commit():
        """Execute after router commits the transaction."""
        if _assign_cb:
            await _assign_cb()
            log.info(
                "Manual assignment notification dispatched",
                lead_id=lead.id,
                officer_id=officer.id,
                assigner_id=assigner.id
            )

    # Trả về lead đã được tải đầy đủ
    result_lead = await get_lead_by_id(db, lead_id)
    return result_lead, _post_commit


async def get_lead_timeline(db: AsyncSession, lead_id: int) -> List[dict]:
    """Lấy timeline tổng hợp của Lead (consultations và assignment logs)."""

    # 1. ✅ GỌI HÀM ĐÃ TỐI ƯU HÓA EAGER LOADING (từ dòng 104)
    # Hàm này đã load sẵn:
    # - consultations.officer
    # - consultations.consultation_status
    # - assignment_logs.officer
    try:
        lead = await get_lead_by_id(db, lead_id)
    except ResourceNotFoundError:
        raise
    except Exception as e:
        log.error("Failed to get lead for timeline", lead_id=lead_id, error=str(e))
        raise

    # 2. ✅ XÓA BỎ TẤT CẢ CÁC LỆNH `db.refresh(...)`
    log.debug(
        "Lead and all relations loaded via eager loading for timeline", lead_id=lead_id
    )

    timeline_items = []

    # 3. Xử lý consultations (Dữ liệu đã có sẵn)
    # ✅ FIX: Filter out soft-deleted consultations
    if lead.consultations:
        for c in lead.consultations:
            if c.deleted_at is not None:
                continue  # Skip soft-deleted consultations
            # ❌ KHÔNG CẦN: await db.refresh(c, ["officer", "consultation_status"])
            timeline_items.append(
                schemas.TimelineItem(
                    type="consultation",
                    data=schemas.Consultation.model_validate(c),
                    timestamp=c.consultation_date,
                ).model_dump()
            )

    # 4. Xử lý assignment logs (Dữ liệu đã có sẵn)
    if lead.assignment_logs:
        for log_entry in lead.assignment_logs:
            # ❌ KHÔNG CẦN: await db.refresh(log_entry, ["officer"])
            timeline_items.append(
                schemas.TimelineItem(
                    type="assignment",
                    data=schemas.AssignmentLog.model_validate(log_entry),
                    timestamp=log_entry.timestamp,
                ).model_dump()
            )

    # Sắp xếp timeline theo timestamp giảm dần (mới nhất trước)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=True)
    return timeline_items


async def delete_consultation(
    db: AsyncSession, lead_id: int, consultation_id: int, current_user: models.User
):
    """
    Xóa một consultation và cập nhật lại trạng thái Lead.

    Permission Rules:
    - Admin: Can delete any consultation
    - Officer: Can only delete the most recent consultation (prevents breaking consultation chain)

    CONCURRENCY SAFE: Uses SELECT ... FOR UPDATE to prevent race conditions
    when multiple requests try to update the same lead's pipeline_stage.
    """
    async with db.begin_nested():
        try:
            # ✅ FIX: Row-level lock để prevent race condition
            # ✅ REFACTORED: Use LeadRepository for locking
            repo = LeadRepository(db)
            lead = await repo.get_by_id_for_update(lead_id)
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")
            
            # ✅ FIX: Check if lead is deleted
            if lead.deleted_at is not None:
                raise BadRequest(detail="Cannot modify consultations for a deleted lead.")

            # ✅ H4: TERMINAL STATUS GUARD: Block deletion for enrolled leads
            terminal_guard = await check_terminal_status_guard(db, lead)
            if terminal_guard.hard_block:
                raise BusinessRuleViolation(
                    detail=terminal_guard.reason
                )

            # Soft terminal: allow deletion but skip status revert
            skip_status_revert = terminal_guard.is_terminal

            # Lấy Consultation cần xóa với row-level lock
            # ✅ FIX: Use FOR UPDATE to prevent concurrent modification
            # ✅ FIX: Filter out already soft-deleted consultations
            consultation_result = await db.execute(
                select(models.Consultation)
                .where(
                    models.Consultation.id == consultation_id,
                    models.Consultation.deleted_at.is_(None),  # Not already deleted
                )
                .with_for_update()
            )
            consultation = consultation_result.scalar_one_or_none()
            if not consultation:
                raise ResourceNotFoundError(
                    detail=f"Consultation with id {consultation_id} not found or already deleted."
                )
            # Kiểm tra consultation thuộc đúng Lead
            if consultation.lead_id != lead_id:
                raise BadRequest(
                    detail="Consultation does not belong to the specified lead."
                )

            # Kiểm tra quyền
            if current_user.role in (UserRole.ADMIN, UserRole.MANAGER):
                # ✅ FIX: Admin và Manager có quyền xóa bất kỳ consultation nào
                pass
            elif current_user.role == UserRole.OFFICER:
                # Officer chỉ được xóa consultation mới nhất
                # Tìm consultation mới nhất của Lead này
                # Officer chỉ được xóa consultation mới nhất
                # ✅ REFACTORED: Use LeadRepository
                latest_consultation = await repo.get_latest_consultation(lead_id)

                if not latest_consultation or latest_consultation.id != consultation_id:
                    raise PermissionDeniedError(
                        detail="Officers can only delete the most recent consultation to maintain consultation chain integrity."
                    )

                # Kiểm tra officer có được gán cho Lead này không
                if lead.assigned_officer_id != current_user.id:
                    raise PermissionDeniedError(
                        detail="You are not assigned to this lead."
                    )
            else:
                # Các role khác không có quyền xóa consultation
                raise PermissionDeniedError(detail="You don't have permission to delete consultations.")

            # Lưu trạng thái cũ của Lead trước khi xóa consultation
            old_state = _get_current_lead_state(lead)

            # ✅ FIX: Soft delete thay vì hard delete
            # Giữ audit trail, có thể restore nếu xóa nhầm
            consultation.deleted_at = datetime.now(timezone.utc)
            await db.flush()  # Ensure soft delete is processed before querying remaining
            log.info(
                "Consultation soft-deleted",
                consultation_id=consultation_id,
                lead_id=lead_id,
                deleted_by=current_user.id,
                deleted_at=consultation.deleted_at.isoformat(),
            )

            # Tìm consultation gần nhất còn lại để cập nhật trạng thái Lead
            # ✅ REFACTORED: Use LeadRepository
            latest_remaining = await repo.get_latest_consultation(lead_id)

            new_status_id = None
            new_stage_id = None
            revert_status_obj = None  # ConsultationStatus object for sync

            # Nếu còn consultation khác
            if latest_remaining and latest_remaining.consultation_status_id:
                latest_status = await db.get(
                    models.ConsultationStatus, latest_remaining.consultation_status_id
                )
                if latest_status:
                    new_status_id = latest_status.id
                    new_stage_id = latest_status.stage_id
                    revert_status_obj = latest_status
                    log.info(
                        f"Reverting lead status to latest remaining consultation's status: {new_status_id}",
                        lead_id=lead_id,
                    )
                else:
                    log.warning(
                        f"Status '{latest_remaining.consultation_status_id}' not found for latest consultation {latest_remaining.id}",
                        lead_id=lead_id,
                    )
            # Nếu không còn consultation nào, revert về trạng thái ban đầu
            else:
                initial_status = await StatusHelper.get_initial_status(db)
                if initial_status:
                    new_status_id = initial_status.id
                    new_stage_id = initial_status.stage_id
                    revert_status_obj = initial_status
                    log.info(
                        "Reverting lead status to initial status",
                        lead_id=lead_id,
                        status_id=new_status_id,
                    )
                else:
                    log.warning(
                        "Initial status not found when reverting lead status.",
                        lead_id=lead_id,
                    )
                    # Gán giá trị an toàn nếu không tìm thấy status ban đầu
                    new_status_id = None
                    new_stage_id = None

            if not skip_status_revert:
                # Cập nhật trạng thái Lead
                lead.consultation_status_id = new_status_id
                lead.pipeline_stage_id = new_stage_id
                # ✅ Sync lead.status từ consultation_status (Hybrid Approach)
                if revert_status_obj:
                    sync_lead_status_from_consultation(lead, revert_status_obj)
                else:
                    # Fallback khi không tìm thấy status object
                    lead.status = "new"
            else:
                log.warning(
                    "Terminal guard SOFT BLOCK: skipping lead status revert on consultation delete",
                    lead_id=lead_id,
                    current_status_id=lead.consultation_status_id,
                )

            # ✅ Always increment version when consultation is deleted (data changed)
            lead.version = (lead.version or 1) + 1
            db.add(lead)

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead do xóa consultation
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=current_user,
                reason=f"Deleted consultation ID {consultation_id}",
            )

            # ✅ Quick Disposition: Cập nhật next_activity_at sau khi xóa consultation
            # FIX: Flush to ensure deletion is visible to query
            await db.flush()
            
            # ✅ LEAD INSIGHTS UPGRADE: Update cached metrics
            from app.services import lead_cache_service
            await lead_cache_service.update_lead_cache(db, lead_id, lead)
            log.info("Updated lead cache after deleting consultation", lead_id=lead_id, deleted_consultation_id=consultation_id)

            # ✅ AUDIT LOG: Log consultation deletion
            await audit_service.log_deleted(
                db,
                entity_type="Consultation",
                entity_id=consultation_id,
                actor_user_id=current_user.id,
                old_values={
                    "lead_id": lead_id,
                    "consultation_status_id": consultation.consultation_status_id,
                    "consultation_date": consultation.consultation_date.isoformat() if consultation.consultation_date else None,
                    "notes": consultation.notes[:200] if consultation.notes else None,
                },
                reason=f"Consultation soft-deleted by {current_user.role} {current_user.username}",
                source="api",
            )

            # Store values for use after transaction
            _lead_id = lead_id
            _consultation_id = consultation_id
            _officer_id = lead.assigned_officer_id
            _new_status_id = new_status_id

        except Exception as e:
            # Rollback tự động by begin_nested context
            log.error(
                "Failed to delete consultation",
                lead_id=lead_id,
                consultation_id=consultation_id,
                error=str(e),
                exc_info=True,
            )
            raise e

    # After successful transaction, log and emit events
    log.info(
        "Consultation deleted and lead status reverted",
        user_id=current_user.id,
        lead_id=_lead_id,
        consultation_id=_consultation_id,
        new_lead_status=_new_status_id,
    )

    # Note: Consultation deleted notification is dispatched by the router after commit.
    # The service only flushes; the router handles commit and notification dispatch.


async def restore_consultation(
    db: AsyncSession, lead_id: int, consultation_id: int, current_user: models.User
) -> models.Consultation:
    """
    Restore a soft-deleted consultation and update Lead status accordingly.

    Permission Rules:
    - Admin/Manager: Can restore any consultation
    - Officer: Can only restore if assigned to the lead

    Business Logic:
    - Clears deleted_at timestamp to restore the consultation
    - Updates lead's consultation_status_id to the restored consultation's status
      (only if restored consultation is the most recent by consultation_date)
    - Logs the change in LeadStatusHistory

    Args:
        db: Database session
        lead_id: Lead ID
        consultation_id: Consultation ID to restore
        current_user: User performing the restoration

    Returns:
        models.Consultation: The restored consultation object

    Raises:
        ResourceNotFoundError: If consultation not found or not deleted
        BusinessRuleViolation: If consultation is not deleted
        PermissionDeniedError: If user doesn't have permission
    """
    async with db.begin_nested():
        try:
            repo = LeadRepository(db)
            lead = await repo.get_by_id_for_update(lead_id)

            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Check if lead is deleted
            if lead.deleted_at is not None:
                raise BadRequest(detail="Cannot restore consultations for a deleted lead.")

            # Fetch the deleted consultation
            consultation_result = await db.execute(
                select(models.Consultation)
                .where(
                    models.Consultation.id == consultation_id,
                    models.Consultation.lead_id == lead_id,
                    models.Consultation.deleted_at.isnot(None),  # Must be deleted
                )
                .with_for_update()
            )
            consultation = consultation_result.scalar_one_or_none()

            if not consultation:
                raise ResourceNotFoundError(
                    detail=f"Deleted consultation with id {consultation_id} not found."
                )

            # Permission check
            if current_user.role in (UserRole.ADMIN, UserRole.MANAGER):
                pass  # Admin/Manager can restore any
            elif current_user.role == UserRole.OFFICER:
                if lead.assigned_officer_id != current_user.id:
                    raise PermissionDeniedError(
                        detail="You are not assigned to this lead."
                    )
            else:
                raise PermissionDeniedError(
                    detail="You don't have permission to restore consultations."
                )

            # Capture old state
            old_state = _get_current_lead_state(lead)

            # Restore the consultation
            consultation.deleted_at = None
            await db.flush()

            log.info(
                "Consultation restored",
                consultation_id=consultation_id,
                lead_id=lead_id,
                restored_by=current_user.id,
            )

            # Determine if we need to update lead status
            # Get the latest consultation (including the just-restored one)
            latest_consultation = await repo.get_latest_consultation(lead_id)

            # If restored consultation is now the latest, update lead status
            if latest_consultation and latest_consultation.id == consultation_id:
                if consultation.consultation_status_id:
                    new_status = await db.get(
                        models.ConsultationStatus, consultation.consultation_status_id
                    )
                    if new_status:
                        lead.consultation_status_id = new_status.id
                        lead.pipeline_stage_id = new_status.stage_id
                        sync_lead_status_from_consultation(lead, new_status)
                        db.add(lead)

                        log.info(
                            "Lead status updated to restored consultation's status",
                            lead_id=lead_id,
                            new_status_id=new_status.id,
                        )

            # Get new state and log change
            new_state = _get_current_lead_state(lead)
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=current_user,
                reason=f"Restored consultation ID {consultation_id}",
            )

            # Update lead cache
            from app.services import lead_cache_service
            await lead_cache_service.update_lead_cache(db, lead_id, lead)

            # ✅ AUDIT LOG: Log consultation restoration
            await audit_service.log_audit(
                db,
                entity_type="Consultation",
                entity_id=consultation_id,
                action="restored",
                actor_user_id=current_user.id,
                new_value={
                    "lead_id": lead_id,
                    "consultation_status_id": consultation.consultation_status_id,
                    "consultation_date": consultation.consultation_date.isoformat() if consultation.consultation_date else None,
                },
                reason=f"Consultation restored by {current_user.role} {current_user.username}",
                source="api",
            )

            return consultation

        except (ResourceNotFoundError, BusinessRuleViolation, PermissionDeniedError):
            raise
        except Exception as e:
            log.error(
                "Failed to restore consultation",
                lead_id=lead_id,
                consultation_id=consultation_id,
                error=str(e),
                exc_info=True,
            )
            raise e


async def update_consultation(
    db: AsyncSession,
    lead_id: int,
    consultation_id: int,
    consultation_in: schemas.ConsultationUpdate,
    current_user: models.User,
):
    """
    Cập nhật một consultation.

    Permission Rules:
    - Admin: Can update any consultation
    - Officer: Can only update the most recent consultation (prevents breaking consultation chain)

    Business Logic:
    - If status_id is changed, update lead's consultation_status_id and pipeline_stage_id
    - Log the change in LeadStatusHistory if lead status changes
    - Emit Socket.IO event for real-time updates

    CONCURRENCY SAFE: Uses SELECT ... FOR UPDATE to prevent race conditions
    when multiple requests try to update the same lead's pipeline_stage.
    """
    async with db.begin_nested():
        try:
            # ✅ REFACTORED: Use LeadRepository for locking
            repo = LeadRepository(db)
            lead = await repo.get_by_id_for_update(lead_id)
            
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")
            
            # ✅ FIX: Check if lead is deleted (consistent with delete_consultation)
            if lead.deleted_at is not None:
                raise BadRequest(detail="Cannot modify consultations for a deleted lead.")

            # Lấy Consultation cần update
            consultation = await db.get(models.Consultation, consultation_id)
            if not consultation:
                raise ResourceNotFoundError(
                    detail=f"Consultation with id {consultation_id} not found."
                )
            # ✅ H3: Block updating soft-deleted consultation
            if consultation.deleted_at is not None:
                raise ResourceNotFoundError(
                    detail=f"Consultation with id {consultation_id} not found or already deleted."
                )
            # Kiểm tra consultation thuộc đúng Lead
            if consultation.lead_id != lead_id:
                raise BadRequest(
                    detail="Consultation does not belong to the specified lead."
                )

            # ✅ FIX: Single check for latest consultation (eliminates TOCTOU vulnerability)
            # Query once and reuse the result for both permission check and status update
            # ✅ REFACTORED: Use LeadRepository
            latest_consultation = await repo.get_latest_consultation(lead_id)
            is_latest_consultation = (
                latest_consultation and latest_consultation.id == consultation_id
            )

            # Kiểm tra quyền
            if current_user.role in (UserRole.ADMIN, UserRole.MANAGER):
                # Admin và Manager có quyền update bất kỳ consultation nào
                pass
            elif current_user.role == UserRole.OFFICER:
                # === BUSINESS RULES FOR OFFICER ===
                # 1. Phải là consultation mới nhất (chain integrity)
                if not is_latest_consultation:
                    raise PermissionDeniedError(
                        detail="Officers can only update the most recent consultation to maintain consultation chain integrity."
                    )

                # 2. Phải được gán cho Lead này
                if lead.assigned_officer_id != current_user.id:
                    raise PermissionDeniedError(
                        detail="You are not assigned to this lead."
                    )

                # 3. Phải là người tạo consultation
                if consultation.officer_id != current_user.id:
                    raise PermissionDeniedError(
                        detail="Bạn chỉ có thể chỉnh sửa consultation do chính mình tạo."
                    )

                # 4. Phải trong vòng 24 giờ kể từ khi tạo
                edit_window_anchor = consultation.created_at or consultation.consultation_date
                if not edit_window_anchor:
                    raise PermissionDeniedError(
                        detail="Không thể xác định thời gian tạo consultation, liên hệ admin."
                    )
                consultation_age = datetime.now(timezone.utc) - edit_window_anchor
                if consultation_age.total_seconds() > 24 * 60 * 60:  # 24 hours in seconds
                    raise PermissionDeniedError(
                        detail="Ngoài giờ không được chỉnh sửa, hãy liên hệ admin hoặc manager để nhờ hỗ trợ."
                    )
            else:
                # Các role khác không có quyền update consultation
                raise PermissionDeniedError(
                    detail="You don't have permission to update consultations."
                )

            # Lưu trạng thái cũ của Lead trước khi update
            old_state = _get_current_lead_state(lead)
            old_consultation_status_id = consultation.consultation_status_id

            # Update các trường được cung cấp
            update_data = consultation_in.model_dump(exclude_unset=True)

            # ✅ SECURITY FIX: Validate status_id BEFORE modifying consultation
            # Prevents creating consultation with invalid/nonexistent status
            validated_status = None
            skip_status_update = False  # ✅ TERMINAL STATUS GUARD flag
            if "status_id" in update_data:
                new_status_id = update_data["status_id"]
                validated_status = await db.get(models.ConsultationStatus, new_status_id)
                if not validated_status:
                    raise ResourceNotFoundError(
                        detail=f"Consultation status '{new_status_id}' not found. Cannot update consultation."
                    )

                # ✅ TERMINAL STATUS GUARD (Issue #3 fix)
                # Check if lead is in terminal state BEFORE workflow validation
                terminal_guard = await check_terminal_status_guard(db, lead)
                if terminal_guard.hard_block:
                    # HARD BLOCK: Lead đã nhập học - không cho thay đổi consultation status
                    log.warning(
                        "Terminal guard HARD BLOCK: cannot change consultation status for enrolled lead",
                        lead_id=lead_id,
                        consultation_id=consultation_id,
                        current_status_id=lead.consultation_status_id,
                        current_status_name=terminal_guard.current_status.name if terminal_guard.current_status else None,
                        attempted_status=new_status_id,
                        user_id=current_user.id,
                    )
                    raise BusinessRuleViolation(
                        detail=terminal_guard.reason
                    )
                skip_status_update = terminal_guard.is_terminal

                # ✅ FIX: Validate workflow transition (consistent with add_consultation)
                # Only validate if status is actually changing
                if old_consultation_status_id and old_consultation_status_id != new_status_id:
                    # Phase-based workflow validation
                    from app.services.phase_manager import (
                        derive_phase_from_admission,
                        is_status_allowed_for_phase,
                        UNIVERSAL_STATUSES,
                    )
                    from app.repositories import AdmissionRepository

                    # Get admission profile to derive phase
                    admission_repo = AdmissionRepository(db)
                    admission_profile = await admission_repo.get_profile_by_lead_id(lead_id)
                    current_phase = derive_phase_from_admission(admission_profile)

                    # Check if new status is allowed in current phase
                    if not is_status_allowed_for_phase(current_phase, new_status_id, current_user.role):
                        if new_status_id not in UNIVERSAL_STATUSES:
                            raise BadRequest(
                                detail=f"Status '{validated_status.name}' không hợp lệ trong phase '{current_phase.value}'. "
                                       f"Lead hiện đang ở giai đoạn {current_phase.value.upper()}."
                            )

                    # Validate allowed transitions
                    is_valid = await pipeline_service.validate_status_transition(
                        db,
                        from_status_id=old_consultation_status_id,
                        to_status_id=new_status_id
                    )

                    if not is_valid:
                        # Admin can bypass transition rules (but not phase guards)
                        if current_user.role != UserRole.ADMIN:
                            raise BadRequest(
                                detail=f"Không thể chuyển trạng thái từ '{old_consultation_status_id}' sang '{new_status_id}'. "
                                       f"Quy trình không cho phép (Allowed Transitions). "
                                       f"Liên hệ Admin nếu cần bypass."
                            )
                        else:
                            log.warning(
                                "Admin bypassed transition rule in update_consultation",
                                admin_id=current_user.id,
                                admin_username=current_user.username,
                                lead_id=lead_id,
                                consultation_id=consultation_id,
                                from_status=old_consultation_status_id,
                                to_status=new_status_id,
                            )

                # ✅ LOSS REASON VALIDATION: Require loss_reason_code for final negative status
                if validated_status.is_final and validated_status.outcome_type == "negative":
                    loss_reason_code = update_data.get("loss_reason_code")
                    if not loss_reason_code:
                        raise BadRequest(
                            detail="Vui lòng chọn lý do không tiếp tục (loss_reason_code) khi chuyển sang trạng thái cuối cùng."
                        )

            # Fields that belong to LeadStatusHistory, not Consultation model
            NON_CONSULTATION_FIELDS = {"loss_reason_code", "loss_reason_note"}

            for field, value in update_data.items():
                if field in NON_CONSULTATION_FIELDS:
                    continue  # Skip fields not in Consultation model
                elif field == "status_id":
                    # Đặt consultation_status_id (already validated above)
                    consultation.consultation_status_id = value
                else:
                    setattr(consultation, field, value)

            db.add(consultation)

            # Nếu status_id thay đổi và đây là consultation mới nhất
            # Cập nhật trạng thái Lead (reuse is_latest_consultation from above)
            status_changed = False
            if "status_id" in update_data and update_data["status_id"] != old_consultation_status_id:
                if is_latest_consultation:
                    # ✅ TERMINAL STATUS GUARD (Issue #3) - Using check result from earlier
                    # skip_status_update flag was set by check_terminal_status_guard() above
                    if skip_status_update:
                        log.warning(
                            "Terminal guard SOFT BLOCK: skipping lead status update for terminal lead",
                            lead_id=lead_id,
                            consultation_id=consultation_id,
                            current_status_id=lead.consultation_status_id,
                            current_status_phase=terminal_guard.current_status.phase if terminal_guard.current_status else None,
                            attempted_status=update_data["status_id"],
                            user_id=current_user.id,
                            reason=terminal_guard.reason,
                        )
                        # Skip status update but continue with consultation update
                    else:
                        # Đây là consultation mới nhất, cập nhật lead status
                        # ✅ SECURITY FIX: Status already validated above, use validated_status
                        # No need for redundant db.get() - status existence is guaranteed
                        new_status = validated_status  # Reuse from validation above
                        lead.consultation_status_id = new_status.id
                        lead.pipeline_stage_id = new_status.stage_id
                        # ✅ Sync lead.status từ consultation_status (Hybrid Approach)
                        sync_lead_status_from_consultation(lead, new_status)
                        db.add(lead)
                        status_changed = True

                        log.info(
                            "Lead status updated via consultation update",
                            lead_id=lead_id,
                            consultation_id=consultation_id,
                            old_status=old_consultation_status_id,
                            new_status=new_status.id,
                        )

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead (nếu có thay đổi)
            if status_changed:
                # Get loss_reason for final negative status
                loss_reason_for_log = None
                loss_reason_note_for_log = None
                if validated_status and validated_status.is_final and validated_status.outcome_type == "negative":
                    loss_reason_for_log = update_data.get("loss_reason_code")
                    loss_reason_note_for_log = update_data.get("loss_reason_note")

                await _log_lead_state_change(
                    db,
                    lead,
                    old_state,
                    new_state,
                    changed_by=current_user,
                    reason=loss_reason_note_for_log or f"Updated consultation ID {consultation_id}",
                    loss_reason_code=loss_reason_for_log,
                )

            # Flush to get changes ready (commit handled by begin_nested context)
            await db.flush()
            
            # ✅ FIX MissingGreenlet: Re-query with eager loading for nested relationships
            # db.refresh() cannot load nested relationships like consultation_status.stage
            # ✅ ARCHITECTURE FIX: Use Repository instead of direct query
            # Service must not query Model directly (Rule E: Repository Pattern)
            repo = LeadRepository(db)
            consultation = await repo.get_consultation_with_status_stage(consultation.id)

            # ✅ LEAD INSIGHTS UPGRADE: Update cached metrics
            # Runs on ANY consultation update (status change, scheduled_at change, etc.)
            from app.services import lead_cache_service
            await lead_cache_service.update_lead_cache(db, lead_id, lead)

            # Store values for use after transaction
            _lead_id = lead_id
            _consultation_id = consultation_id
            _officer_id = lead.assigned_officer_id
            _consultation_status_id = consultation.consultation_status_id or ""
            _status_changed = status_changed

        except Exception as e:
            # Rollback tự động by begin_nested context
            log.error(
                "Failed to update consultation",
                lead_id=lead_id,
                consultation_id=consultation_id,
                error=str(e),
                exc_info=True,
            )
            raise e

    # After successful transaction, log and emit events
    log.info(
        "Consultation updated successfully",
        user_id=current_user.id,
        lead_id=_lead_id,
        consultation_id=_consultation_id,
        status_changed=_status_changed,
    )

    # Note: Consultation updated notification is dispatched by the router after commit.
    # The service only flushes; the router handles commit and notification dispatch.

    return consultation


# ============================================================================
# REASSIGN QUOTA CHECK
# ============================================================================

REASSIGN_QUOTA_LIMIT = 5  # Max reassigns per week
REASSIGN_QUOTA_PERIOD_DAYS = 7  # Reset quota every 7 days


async def check_reassign_quota(db: AsyncSession, officer_id: int) -> dict:
    """
    Check if officer has remaining reassign quota.
    
    ✅ ARCHITECTURE COMPLIANT: Uses LeadRepository for data access.
    
    Returns:
        dict: {"allowed": bool, "used": int, "limit": int, "remaining": int}
    """
    from app.repositories.lead_repository import LeadRepository
    
    # ✅ FIX: Use repository instead of direct query
    repo = LeadRepository(db)
    used_count = await repo.count_reassignments_in_period(
        officer_id=officer_id,
        days=REASSIGN_QUOTA_PERIOD_DAYS
    )
    
    remaining = max(0, REASSIGN_QUOTA_LIMIT - used_count)
    
    log.debug(
        "Checked reassign quota",
        officer_id=officer_id,
        used=used_count,
        limit=REASSIGN_QUOTA_LIMIT,
        remaining=remaining,
    )
    
    return {
        "allowed": used_count < REASSIGN_QUOTA_LIMIT,
        "used": used_count,
        "limit": REASSIGN_QUOTA_LIMIT,
        "remaining": remaining,
    }


async def process_officer_action(
    db: AsyncSession, lead_id: int, officer: models.User, action: str, reason: str
) -> models.Lead:
    """
    Xử lý hành động (reject/reassign) của Officer trên Lead, ghi logs và dispatch task.
    """
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task

    # ✅ FIX: Capture values early to avoid lazy loading issues
    officer_id = officer.id
    is_admin_or_manager = officer.role in (UserRole.ADMIN, UserRole.MANAGER)
    
    # ✅ QUOTA CHECK: Only apply to Officers, not Admin/Manager
    if action == "reassign" and not is_admin_or_manager:
        quota = await check_reassign_quota(db, officer_id)
        if not quota["allowed"]:
            raise BadRequest(
                detail=f"Bạn đã hết lượt phân công lại trong tuần này ({quota['used']}/{quota['limit']}). Vui lòng liên hệ quản lý."
            )
        log.info(
            "Officer reassign quota check passed",
            officer_id=officer_id,
            remaining=quota["remaining"],
        )
    
    trigger_reassignment = False  # Biến cờ để dispatch task sau commit
    try:
        async with db.begin_nested():
            # ✅ ARCHITECTURE COMPLIANT: Use LeadRepository instead of direct query
            from app.repositories.lead_repository import LeadRepository
            repo = LeadRepository(db)
            lead = await repo.get_by_id_for_update(lead_id)
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")
            
            # ✅ FIX: Check if lead is deleted
            if lead.deleted_at is not None:
                raise BadRequest(detail="Cannot process action on a deleted lead.")

            # ✅ FIX: Admin/Manager can reassign ANY lead, Officers can only reassign their own
            if not is_admin_or_manager and lead.assigned_officer_id != officer_id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            log_method = ""  # Method cho AssignmentLog
            # (Đã xóa .strip() vì Pydantic xử lý)
            log_reason = reason if reason else "No reason provided by officer"

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)
            new_state = old_state.copy()  # Tạo bản sao để sửa đổi

            if action == "reassign":
                new_state["assigned_officer_id"] = None
                # Giữ nguyên consult/stage và status (không đổi consultation workflow)
                new_state["consultation_status_id"] = lead.consultation_status_id
                new_state["pipeline_stage_id"] = lead.pipeline_stage_id
                new_state["status"] = lead.status  # Keep status synced from consultation
                # ✅ FIX: Must set BOTH the FK column AND the relationship
                lead.assigned_officer_id = None  # FK column
                lead.assigned_at = None
                lead.assigned_officer = None  # Relationship
                
                # ✅ BLACKLIST: Only add to blacklist for OFFICER self-reassign (not Admin manual reassign)
                if not is_admin_or_manager:
                    # ✅ FIX: Create NEW list to ensure SQLAlchemy detects JSON mutation
                    rejected_list = list(lead.rejected_by_officer_ids or [])
                    if officer_id not in rejected_list:
                        rejected_list.append(officer_id)
                        lead.rejected_by_officer_ids = rejected_list
                        # ✅ FIX: Explicitly flag as modified for JSON field mutation tracking
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(lead, "rejected_by_officer_ids")
                        log.info(
                            "Added officer to lead blacklist",
                            lead_id=lead_id,
                            officer_id=officer_id,
                            blacklist=rejected_list,
                        )
                
                # Update assignment_status to reassign_pending
                StatusHelper.set_assignment_status(lead, AssignmentStatus.REASSIGN_PENDING)
                log_method = "officer_reassign"
                trigger_reassignment = True
                log.info(
                    "Officer requested lead reassignment",
                    lead_id=lead_id,
                    officer_id=officer.id,
                    assignment_status=lead.assignment_status,
                )

            elif action == "reject":
                # Get rejected status from database (database-driven)
                rejected_status = await StatusHelper.get_rejected_status(db)
                log_method = "officer_reject"

                if rejected_status:
                    # Sync lead status from consultation_status
                    await StatusHelper.sync_lead_status(lead, rejected_status)
                    new_state["status"] = lead.status
                    new_state["consultation_status_id"] = rejected_status.id
                    new_state["pipeline_stage_id"] = rejected_status.stage_id
                    log.info(
                        "Setting consultation status to rejected",
                        lead_id=lead_id,
                        status_id=rejected_status.id,
                        legacy_status=rejected_status.legacy_status,
                    )
                else:
                    log.warning(
                        "Rejected consultation status not found in database.",
                        lead_id=lead_id,
                    )
                    # Fallback: set status directly
                    new_state["status"] = "rejected"
                    new_state["consultation_status_id"] = None
                    new_state["pipeline_stage_id"] = None

                log.info(
                    "Officer rejected lead", lead_id=lead_id, officer_id=officer.id
                )

            else:
                # Hành động không hợp lệ
                raise BadRequest(
                    detail=f"Invalid action: {action}. Allowed actions: 'reject', 'reassign'."
                )

            # Cập nhật các trường của Lead dựa trên new_state
            lead.status = new_state["status"]
            lead.consultation_status_id = new_state["consultation_status_id"]
            lead.pipeline_stage_id = new_state["pipeline_stage_id"]
            lead.assigned_officer_id = new_state["assigned_officer_id"]
            # assigned_at đã được xử lý trong 'reassign'

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db, lead, old_state, new_state, changed_by=officer, reason=log_reason
            )

            # Tạo AssignmentLog cho hành động này
            log_entry = models.AssignmentLog(
                lead_id=lead.id,
                officer_id=officer.id,  # Ghi lại officer thực hiện action
                method=log_method,
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),
            )
            db.add(lead)  # Đánh dấu lead là dirty
            db.add(log_entry)

            # Commit transaction bên trong
            log.info(
                f"Processed officer action '{action}' within transaction",
                lead_id=lead_id,
            )

        # ✅ FIX: Return callback to dispatch Celery AFTER db.commit() in router
        # This fixes race condition where Celery reads stale blacklist
        lead_id_for_callback = lead.id  # Capture for closure
        
        async def post_commit_callback():
            if trigger_reassignment:
                try:
                    process_automatic_lead_assignment_task.delay(lead_id_for_callback)
                    log.info("Re-assignment task dispatched for lead", lead_id=lead_id_for_callback)
                except Exception as e:
                    log.error(
                        "Failed to dispatch Celery re-assignment task after officer action",
                        lead_id=lead_id_for_callback,
                        error=str(e),
                        exc_info=True,
                    )

        # Trả về lead đã được tải đầy đủ + callback
        result = await get_lead_by_id(db, lead_id)
        return result, post_commit_callback

    except (
        PermissionDeniedError,
        BadRequest,
        ResourceNotFoundError,
    ) as e:  # Thêm ResourceNotFoundError
        # Rollback nếu lỗi validation hoặc không tìm thấy
        await db.rollback()
        log.warning(
            "Officer action failed validation or resource not found",
            lead_id=lead_id,
            officer_id=officer_id,  # ✅ FIX: Use captured variable
            action=action,
            detail=getattr(e, "detail", str(e)),
        )
        raise e
    except Exception as e:
        # Rollback cho các lỗi không mong muốn khác
        await db.rollback()
        log.error(
            "Failed to process officer action",
            lead_id=lead_id,
            officer_id=officer_id,  # ✅ FIX: Use captured variable
            action=action,
            error=str(e),
            exc_info=True,
        )
        raise e


async def revert_last_status(
    db: AsyncSession,
    lead_id: int,
    admin_user: models.User,
    reason: Optional[str] = None,  # Cho phép reason là None
) -> models.Lead:
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của Lead về trạng thái trước đó.
    """
    # ✅ FIX: Check admin role at service layer
    if admin_user.role != UserRole.ADMIN:
        raise PermissionDeniedError(
            detail="Only admin can revert lead status."
        )
    
    # (Pydantic/Form() nên xử lý .strip(), nhưng giữ ở đây để an toàn nếu gọi nội bộ)
    final_reason = reason.strip() if reason else "Admin reverted last status change"
    try:
        async with db.begin_nested():
            # ✅ SPRINT 5: Import Repository FIRST before usage
            from app.repositories import LeadRepository
            
            # Lấy Lead (không cần eager load quá nhiều)
            # ✅ REFACTORED: Use LeadRepository for locking
            repo = LeadRepository(db)
            lead = await repo.get_by_id_for_update(lead_id)
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Tìm bản ghi lịch sử gần nhất
            last_history_entry = await repo.get_last_status_history_entry(lead_id)

            if not last_history_entry:
                raise BadRequest(
                    detail="No status history found for this lead to revert."
                )

            # Trạng thái "đích" để hoàn tác về chính là trạng thái "cũ" trong bản ghi history
            if (
                last_history_entry.old_status is None
                and last_history_entry.old_consultation_status_id is None
                and last_history_entry.old_pipeline_stage_id is None
                and last_history_entry.old_assigned_officer_id is None
            ):
                raise BadRequest(
                    detail="Cannot revert to the initial state (before any status change recorded)."
                )

            # Lấy trạng thái hiện tại của Lead
            current_state = _get_current_lead_state(lead)

            # Xây dựng trạng thái cần hoàn tác về
            revert_to_state = {
                "status": last_history_entry.old_status,
                "consultation_status_id": last_history_entry.old_consultation_status_id,
                "pipeline_stage_id": last_history_entry.old_pipeline_stage_id,
                "assigned_officer_id": last_history_entry.old_assigned_officer_id,
            }

            # Kiểm tra xem có cần hoàn tác không
            if current_state == revert_to_state:
                log.info(
                    "Lead state is already the same as the previous recorded state, no revert needed.",
                    lead_id=lead_id,
                )
                # Trả về lead hiện tại nếu không có gì thay đổi
                return await get_lead_by_id(
                    db, lead_id
                )  # Vẫn gọi get_lead_by_id để đảm bảo eager loading

            log.info(
                "Admin reverting lead state",
                lead_id=lead_id,
                admin_id=admin_user.id,
                from_state=current_state,
                to_state=revert_to_state,
                reason=final_reason,
            )

            # Ghi log lịch sử cho hành động hoàn tác này
            await _log_lead_state_change(
                db,
                lead,
                old_state=current_state,  # Trạng thái cũ là trạng thái hiện tại
                new_state=revert_to_state,  # Trạng thái mới là trạng thái cần revert về
                changed_by=admin_user,
                reason=final_reason,
            )

            # Cập nhật các trường của Lead về trạng thái cũ
            lead.status = revert_to_state["status"]
            lead.consultation_status_id = revert_to_state["consultation_status_id"]
            lead.pipeline_stage_id = revert_to_state["pipeline_stage_id"]
            lead.assigned_officer_id = revert_to_state["assigned_officer_id"]

            # Cập nhật assigned_at nếu officer được khôi phục từ trạng thái không có officer
            if (
                revert_to_state["assigned_officer_id"] is not None
                and current_state["assigned_officer_id"] is None
            ):
                lead.assigned_at = datetime.now(timezone.utc)
            elif revert_to_state["assigned_officer_id"] is None:
                lead.assigned_at = (
                    None  # Xóa assigned_at nếu revert về trạng thái không gán
                )

            db.add(lead)  # Đánh dấu lead là dirty

            # Commit transaction
            log.info("Revert lead status completed within transaction", lead_id=lead_id)

    except (BadRequest, ResourceNotFoundError) as e:
        await db.rollback()
        log.warning(
            "Failed to revert lead status due to validation error",
            lead_id=lead_id,
            detail=getattr(e, "detail", str(e)),
        )
        raise e
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to revert lead status",
            lead_id=lead_id,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        raise e

    # Trả về lead đã được tải đầy đủ sau khi commit thành công
    return await get_lead_by_id(db, lead_id)


# =============================================================================
# PHASE 1 - Task 1.8: LEAD IMPORT (EXTRACTED FROM ROUTER)
# =============================================================================

async def import_leads_from_file_content(
    file_content: bytes,
    filename: str,
    db: AsyncSession,
    default_unit_id: Optional[int] = None,  # Force all leads to this unit
    auto_assign_officer_id: Optional[int] = None,  # Auto-assign to this officer
) -> Tuple[schemas.LeadImportResult, Callable]:
    """
    Import leads from CSV or Excel file content.

    This function extracts business logic from the router layer, making it
    protocol-independent and reusable across different contexts (HTTP, CLI, Celery).

    Business Rules:
    - Supports CSV (.csv) and Excel (.xlsx) files
    - Required columns: full_name, email, phone, source, unit_id
    - Optional columns: offering_id
    - Email must be unique (checks both DB and current file)
    - Leads are created with default initial status
    - Batch insertion with error collection (doesn't fail fast)
    - Transaction rollback on bulk insert failure

    Args:
        file_content: File content as bytes (CSV or Excel)
        filename: Original filename (used to determine file type)
        db: Database session (injected via DI)

    Returns:
        LeadImportResult containing:
        - total_rows_processed: Number of rows processed
        - successful_imports: Number of leads created
        - failed_imports: Number of rows with errors
        - created_lead_ids: List of created lead IDs
        - errors: List of LeadImportError objects

    Raises:
        ValueError: If file format is invalid or file is empty

    Example:
        >>> with open("leads.csv", "rb") as f:
        ...     content = f.read()
        >>> result = await import_leads_from_file_content(
        ...     file_content=content,
        ...     filename="leads.csv",
        ...     db=session
        ... )
        >>> print(f"Created {result.successful_imports} leads")
    """
    import io
    import pandas as pd
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # ✅ FIX Bug #3: Validate auto_assign_officer_id if provided
    if auto_assign_officer_id:
        officer = await db.get(models.User, auto_assign_officer_id)
        if not officer:
            raise ResourceNotFoundError(f"Officer with id {auto_assign_officer_id} not found")
        if officer.role != UserRole.OFFICER:
            raise PermissionDeniedError(f"User {auto_assign_officer_id} is not an officer")
        if officer.status != "active":
            raise BadRequest(f"Officer {auto_assign_officer_id} is not active")

    # --- 0. Validate file size ---
    MAX_IMPORT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    if len(file_content) > MAX_IMPORT_FILE_SIZE:
        raise ValueError(
            f"File quá lớn ({len(file_content) / (1024*1024):.1f} MB). "
            f"Giới hạn tối đa {MAX_IMPORT_FILE_SIZE // (1024*1024)} MB."
        )

    # --- 1. Validate file extension ---
    file_extension = ""
    if filename:
        file_extension = filename.rsplit(".", 1)[-1].lower()

    if file_extension not in ["csv", "xlsx"]:
        log.warning(
            "Import failed: Invalid file extension",
            filename=filename,
            ext=file_extension,
        )
        raise ValueError(
            "Invalid file format. Only .csv and .xlsx files are supported."
        )

    # --- 2. Read file content into DataFrame ---
    try:
        if not file_content:
            raise ValueError("Empty file uploaded.")

        if file_extension == "csv":
            df = pd.read_csv(io.BytesIO(file_content))
        else:  # xlsx
            df = pd.read_excel(io.BytesIO(file_content), engine="openpyxl")

        log.info(f"Successfully read {len(df)} rows from {file_extension} file.")

        # --- 2b. Validate row count ---
        MAX_IMPORT_ROWS = 10000
        if len(df) > MAX_IMPORT_ROWS:
            raise ValueError(
                f"File chứa {len(df)} dòng, vượt quá giới hạn {MAX_IMPORT_ROWS} dòng/lần import."
            )

    except ValueError as e:
        raise e  # Re-raise validation errors
    except Exception as e:
        log.error(
            "Failed to read or parse file content",
            filename=filename,
            error=str(e),
            exc_info=True,
        )
        raise ValueError(
            f"Could not read or parse the file. Ensure it is a valid {file_extension} file. Error: {e}"
        )

    # --- 3. Validate columns and process data ---
    required_columns = {"full_name", "email", "phone", "source", "unit_id"}

    # Normalize column names (lowercase, strip, replace spaces)
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")

    # Check required columns
    missing_cols = required_columns - set(df.columns)
    if missing_cols:
        log.warning(
            "Import failed: Missing required columns", missing=list(missing_cols)
        )
        raise ValueError(
            f"File is missing required columns: {', '.join(missing_cols)}"
        )

    leads_to_insert = []
    errors: List[schemas.LeadImportError] = []
    processed_row_count = 0

    # Get default initial status (database-driven)
    initial_status_obj = await StatusHelper.get_initial_status(db)
    if not initial_status_obj:
        log.error(
            "FATAL: Initial consultation status not found in DB. Cannot import leads."
        )
        raise ValueError(
            "System configuration error: Initial lead status not found."
        )

    initial_status_id = initial_status_obj.id
    initial_stage_id = initial_status_obj.stage_id
    initial_legacy_status = initial_status_obj.legacy_status or "new"

    # ✅ REFACTORED: Use LeadRepository for batch email check (unit-scoped)
    repo = LeadRepository(db)

    all_emails_in_file = set()
    if 'email' in df.columns:
        # Extract emails, lowercased
        raw_emails = df['email'].dropna().astype(str).tolist()
        all_emails_in_file = {e.strip().lower() for e in raw_emails if e.strip()}

    # ✅ P0 FIX: Check email conflicts within target unit (not globally)
    existing_emails_in_db = await repo.check_batch_email_conflict(
        list(all_emails_in_file), unit_id=default_unit_id
    )
    emails_in_current_file = set()

    # ✅ FIX: Batch check for existing phones (phone + phone2)
    from app.utils.phone_helpers import normalize_vietnam_phone
    repo = LeadRepository(db)
    all_phones_in_file = set()
    if 'phone' in df.columns:
        raw_phones = df['phone'].dropna().astype(str).tolist()
        for p in raw_phones:
            cleaned = p.strip()
            # Handle Excel float artifact: "901234567.0" → "901234567"
            # Don't split on "." — that breaks dotted phones like "0901.234.567"
            if cleaned.endswith(".0"):
                cleaned = cleaned[:-2]
            norm = normalize_vietnam_phone(cleaned) if cleaned else None
            if norm:
                all_phones_in_file.add(norm)
    if 'phone2' in df.columns:
        raw_phones2 = df['phone2'].dropna().astype(str).tolist()
        for p in raw_phones2:
            cleaned = p.strip()
            if cleaned.endswith(".0"):
                cleaned = cleaned[:-2]
            norm = normalize_vietnam_phone(cleaned) if cleaned else None
            if norm:
                all_phones_in_file.add(norm)

    existing_phones_in_db = await repo.check_batch_phone_conflict(list(all_phones_in_file))
    phones_in_current_file = set()  # Tracks normalized phones seen so far in this file

    # --- 4. Process each row ---
    for index, row in df.iterrows():
        processed_row_count += 1
        row_number = index + 2  # Excel row number (header is row 1)
        row_data = row.to_dict()
        cleaned_data = {}
        validation_errors_for_row = []

        # Type conversion for required fields
        try:
            cleaned_data["full_name"] = sanitize_csv_cell(str(row_data.get("full_name", "")).strip())
            cleaned_data["email"] = str(row_data.get("email", "")).strip()

            # Special handling for 'phone': convert to string, strip Excel float ".0"
            phone_val = row_data.get("phone")
            if pd.notna(phone_val):
                phone_str = str(phone_val).strip()
                # Handle Excel float artifact: "901234567.0" → "901234567"
                # Don't split on "." — that breaks dotted phones like "0901.234.567"
                if phone_str.endswith(".0"):
                    phone_str = phone_str[:-2]
                cleaned_data["phone"] = phone_str
            else:
                cleaned_data["phone"] = ""

            # ✅ Phase 2 cleanup: Extract phone2 if present in file
            phone2_val = row_data.get("phone2")
            if pd.notna(phone2_val):
                phone2_str = str(phone2_val).strip()
                if phone2_str.endswith(".0"):
                    phone2_str = phone2_str[:-2]
                cleaned_data["phone2"] = phone2_str if phone2_str else None
            else:
                cleaned_data["phone2"] = None

            cleaned_data["source"] = sanitize_csv_cell(str(row_data.get("source", "")).strip())

            # ✅ Extract optional fields for Scoring
            cleaned_data["education_level"] = sanitize_csv_cell(str(row_data.get("education_level", "")).strip()) or None
            
            gpa_val = row_data.get("gpa")
            if pd.notna(gpa_val):
                 try:
                     cleaned_data["gpa"] = float(gpa_val)
                 except (ValueError, TypeError):
                     # Log but don't fail row just for GPA
                     cleaned_data["gpa"] = None
            else:
                cleaned_data["gpa"] = None
                
            cleaned_data["location"] = sanitize_csv_cell(str(row_data.get("location", "")).strip()) or None


            # Convert 'unit_id' to int (or use default if provided)
            if default_unit_id:
                # Override with default unit (for officer import)
                cleaned_data["unit_id"] = default_unit_id
            else:
                unit_id_val = row_data.get("unit_id")
                if pd.notna(unit_id_val):
                    cleaned_data["unit_id"] = int(float(unit_id_val))
                else:
                    cleaned_data["unit_id"] = None

        except (ValueError, TypeError, Exception) as e:
            validation_errors_for_row.append(f"Type conversion error: {e}")

        # Type conversion for optional 'offering_id'
        offering_id_val = row_data.get("offering_id")
        if pd.notna(offering_id_val):
            try:
                cleaned_data["offering_id"] = int(float(offering_id_val))
            except (ValueError, TypeError):
                validation_errors_for_row.append(
                    "Invalid format for 'offering_id', expected a number."
                )
        else:
            cleaned_data["offering_id"] = None

        # Validate with Pydantic
        try:
            # If there are type conversion errors, raise them
            if validation_errors_for_row:
                raise ValueError(", ".join(validation_errors_for_row))

            lead_in = schemas.LeadCreate(**cleaned_data)

            # Check email duplication (case-insensitive)
            email_lower = lead_in.email.lower() if lead_in.email else None
            if email_lower and (
                email_lower in existing_emails_in_db
                or email_lower in emails_in_current_file
            ):
                raise ValueError(
                    f"Email '{lead_in.email}' đã tồn tại trong cơ sở dữ liệu hoặc file này."
                )

            if email_lower:
                emails_in_current_file.add(email_lower)

            # ✅ Phone Validation (phone + phone2, normalized cross-slot)
            phone_raw = cleaned_data.get("phone")
            phone_norm = normalize_vietnam_phone(phone_raw) if phone_raw else None
            phone2_raw = cleaned_data.get("phone2")
            phone2_norm = normalize_vietnam_phone(phone2_raw) if phone2_raw else None

            if phone_norm:
                if phone_norm in existing_phones_in_db or phone_norm in phones_in_current_file:
                    raise ValueError(f"SĐT '{phone_raw}' đã tồn tại trong hệ thống hoặc file này.")
            if phone2_norm:
                if phone2_norm in existing_phones_in_db or phone2_norm in phones_in_current_file:
                    raise ValueError(f"SĐT phụ '{phone2_raw}' đã tồn tại trong hệ thống hoặc file này.")
                if phone2_norm == phone_norm:
                    raise ValueError(f"SĐT phụ '{phone2_raw}' trùng với SĐT chính.")

            # Register normalized phones for cross-row dedup
            if phone_norm:
                phones_in_current_file.add(phone_norm)
            if phone2_norm:
                phones_in_current_file.add(phone2_norm)

            # ✅ Calculate Lead Score
            score = await calculate_lead_score(
                db,
                lead_education_level=cleaned_data.get("education_level"),
                lead_gpa=cleaned_data.get("gpa"),
                lead_source=cleaned_data.get("source"),
                lead_location=cleaned_data.get("location"),
                unit_id=cleaned_data.get("unit_id"),
            )

            # Prepare dict for bulk insert
            lead_dict = lead_in.model_dump()
            lead_dict["lead_score"] = score
            lead_dict["status"] = initial_legacy_status  # Use legacy_status from DB
            lead_dict["consultation_status_id"] = initial_status_id
            lead_dict["pipeline_stage_id"] = initial_stage_id

            # Auto-assign to officer if specified
            if auto_assign_officer_id:
                lead_dict["assigned_officer_id"] = auto_assign_officer_id
                lead_dict["assigned_at"] = datetime.now(timezone.utc)
                lead_dict["assignment_status"] = AssignmentStatus.ASSIGNED
            else:
                lead_dict["assigned_officer_id"] = None
                lead_dict["assigned_at"] = None
                lead_dict["assignment_status"] = AssignmentStatus.PENDING

            leads_to_insert.append(lead_dict)

        except (ValueError, TypeError) as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Data validation failed: {e}",
                    row_data=row_data,
                )
            )
        except Exception as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Unexpected error processing row: {e}",
                    row_data=row_data,
                )
            )

    # --- 5. Bulk insert ---
    created_lead_ids: List[int] = []
    batch_size = 100  # Commit every 100 leads

    if leads_to_insert:
        try:
            for i in range(0, len(leads_to_insert), batch_size):
                batch = leads_to_insert[i : i + batch_size]
                
                if not batch:
                    continue

                try:
                    async with db.begin_nested():  # Start nested transaction
                        # Insert batch and get IDs
                        batch_ids = await repo.bulk_insert_leads(batch)
                        created_lead_ids.extend(batch_ids)

                        # ✅ PR3: Register phone identities for each lead in batch
                        for lead_dict, lead_id in zip(batch, batch_ids):
                            await repo.register_phone_identities(
                                lead_id=lead_id,
                                phone=lead_dict.get("phone"),
                                phone2=lead_dict.get("phone2"),
                            )
                except IntegrityError as exc:
                    detail = str(exc.orig) if exc.orig else str(exc)
                    log.warning("Batch insert IntegrityError", batch_offset=i, detail=detail)
                    errors.append(
                        schemas.LeadImportError(
                            row_number=-1,
                            error_message=f"Batch {i // batch_size + 1} bị trùng dữ liệu (email/phone): {detail[:200]}",
                            row_data={},
                        )
                    )
                    continue

                log.info(
                    f"Committed batch {i // batch_size + 1}, {len(batch_ids)} leads inserted."
                )

            # ✅ TRANSACTION FIX: Flush instead of commit
            await db.flush()

        except Exception as e:
            # ✅ Router will handle rollback
            log.error(
                "Bulk lead insertion failed during batch",
                error=str(e),
                exc_info=True,
            )
            # Record error
            errors.append(
                schemas.LeadImportError(
                    row_number=-1,
                    error_message=f"Database bulk insert error (batch failed): {e}",
                    row_data={},
                )
            )
            created_lead_ids = []  # Reset IDs due to rollback

    # --- 6. Build result ---
    result = schemas.LeadImportResult(
        total_rows_processed=processed_row_count,
        successful_imports=len(created_lead_ids),
        failed_imports=len(errors),
        created_lead_ids=created_lead_ids,
        errors=errors,
    )

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        result_summary = result.model_dump(exclude={"errors"})
        if errors:
            log.warning("Lead import process finished with errors", result=result_summary)
        else:
            log.info("Lead import process finished successfully", result=result_summary)

    return result, _post_commit


# =============================================================================
# BULK OPERATIONS
# =============================================================================

async def bulk_assign_leads(
    db: AsyncSession,
    lead_ids: List[int],
    officer_id: int,
    assigner: models.User
) -> dict:
    """
    Bulk assign multiple leads to a single officer (Admin/Manager only).

    Args:
        db: Database session
        lead_ids: List of Lead IDs to assign
        officer_id: Target officer ID
        assigner: User performing the assignment

    Returns:
        dict: {
            "total": int,
            "successful": int,
            "failed": int,
            "assigned_lead_ids": List[int],
            "errors": List[dict]
        }

    Business Rules:
    - All leads must exist and not be deleted
    - Officer must be active and have role="officer"
    - Creates AssignmentLog for each successful assignment
    - Logs state change in LeadStatusHistory
    - Continues on errors (doesn't fail fast)
    """
    # ✅ FIX Bug #1: Validate assigner role (Admin/Manager only)
    if assigner.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Admin or Manager can bulk assign leads")

    # Validate officer
    officer = await db.get(models.User, officer_id)
    if not officer:
        raise ResourceNotFoundError(f"Officer with id {officer_id} not found")
    if officer.role != UserRole.OFFICER:
        raise PermissionDeniedError(f"User {officer_id} is not an officer")
    if officer.status != "active":
        raise BadRequest(f"Officer {officer_id} is not active")
    # ✅ FIX Bug #2: Check availability_status
    if officer.availability_status != "available":
        raise BadRequest(f"Officer {officer_id} is not available for assignment")

    # ✅ FIX: Manager can only bulk assign to officers in their unit
    if assigner.role == UserRole.MANAGER:
        if officer.unit_id != assigner.unit_id:
            raise PermissionDeniedError(
                "Manager chỉ có thể phân công lead cho officer trong đơn vị của mình."
            )

    assigned_lead_ids = []
    errors = []

    for lead_id in lead_ids:
        try:
            # Assign lead using existing service function
            lead, _cb = await assign_lead_manually(db, lead_id, officer_id, assigner)
            assigned_lead_ids.append(lead.id)

        except (ResourceNotFoundError, PermissionDeniedError, BadRequest) as e:
            errors.append({
                "lead_id": lead_id,
                "error": str(e)
            })
            log.warning(
                "Bulk assign: Failed to assign lead",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e)
            )
        except Exception as e:
            errors.append({
                "lead_id": lead_id,
                "error": f"Unexpected error: {str(e)}"
            })
            log.error(
                "Bulk assign: Unexpected error",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True
            )

    log.info(
        "Bulk assign completed",
        total=len(lead_ids),
        successful=len(assigned_lead_ids),
        failed=len(errors),
        officer_id=officer_id,
        assigner_id=assigner.id
    )

    return {
        "total": len(lead_ids),
        "successful": len(assigned_lead_ids),
        "failed": len(errors),
        "assigned_lead_ids": assigned_lead_ids,
        "errors": errors
    }


async def bulk_update_pipeline_stage(
    db: AsyncSession,
    lead_ids: List[int],
    pipeline_stage_id: str,
    updated_by: models.User
) -> dict:
    """
    Bulk update pipeline_stage_id for multiple leads (Admin only).

    ✅ PHASE 8: Replaces db.get() in router with Repository pattern.
    ✅ PR4: Returns skip diagnostics for leads that were not updated.

    Args:
        db: Database session
        lead_ids: List of Lead IDs to update
        pipeline_stage_id: New pipeline stage ID
        updated_by: User performing the update

    Returns:
        dict: {
            "message": str,
            "updated_count": int,
            "skipped": [{"lead_id": int, "reason": str}, ...]
        }

    Business Rules:
    - Only Admin can perform bulk updates
    - Skips deleted leads and leads already at target stage
    - Returns detailed skip reasons per lead
    """
    # Admin-only check
    if updated_by.role != UserRole.ADMIN:
        raise PermissionDeniedError("Only Admin can bulk update pipeline stage")

    repo = LeadRepository(db)
    skipped: list[dict] = []

    # Pre-fetch leads to determine which should be skipped
    from sqlalchemy import select
    stmt = select(models.Lead).where(models.Lead.id.in_(lead_ids))
    result = await db.execute(stmt)
    found_leads = {lead.id: lead for lead in result.scalars().all()}

    # Identify skipped leads
    updatable_ids: list[int] = []
    for lid in lead_ids:
        lead = found_leads.get(lid)
        if lead is None:
            skipped.append({"lead_id": lid, "reason": "Lead không tồn tại"})
        elif lead.deleted_at is not None:
            skipped.append({"lead_id": lid, "reason": "Lead đã bị xóa"})
        elif lead.pipeline_stage_id == pipeline_stage_id:
            skipped.append({"lead_id": lid, "reason": "Lead đã ở giai đoạn này"})
        else:
            updatable_ids.append(lid)

    # Update only qualifying leads
    updated_count = 0
    if updatable_ids:
        updated_count = await repo.bulk_update_pipeline_stage(updatable_ids, pipeline_stage_id)

    log.info(
        "Bulk pipeline stage update completed",
        total_requested=len(lead_ids),
        updated_count=updated_count,
        skipped_count=len(skipped),
        pipeline_stage_id=pipeline_stage_id,
        updated_by_id=updated_by.id
    )

    return {
        "message": f"Updated {updated_count} leads",
        "updated_count": updated_count,
        "skipped": skipped,
    }


# =============================================================================
# DELETE LEAD (SOFT DELETE)
# =============================================================================

async def delete_lead(
    db: AsyncSession,
    lead_id: int,
    deleted_by: models.User
) -> models.Lead:
    """
    Soft delete a Lead (Admin only).

    Business Rules:
    - Sets deleted_at timestamp instead of physically deleting
    - Preserves all historical data (consultations, applications, logs)
    - Deleted leads are filtered out from normal queries
    - Only Admin can delete leads
    - Cannot delete already-deleted leads

    Args:
        db: Database session
        lead_id: Lead ID to delete
        deleted_by: User performing the deletion (for audit trail)

    Returns:
        models.Lead: The soft-deleted lead object

    Raises:
        ResourceNotFoundError: If lead not found or already deleted
        PermissionDeniedError: If user doesn't have permission (checked in router)

    Example:
        >>> lead = await delete_lead(db, lead_id=123, deleted_by=admin_user)
        >>> print(lead.deleted_at)  # 2025-11-18 02:30:00+00:00
    """
    # ✅ FIX: Enforce admin-only at service layer
    if deleted_by.role != UserRole.ADMIN:
        raise PermissionDeniedError(
            detail="Only admin can delete leads."
        )
    
    try:
        async with db.begin_nested():
            # Fetch lead with admission_profile relationship
            lead = await get_lead_by_id_shallow(db, lead_id, include_deleted=False)

            # Check if lead is already deleted (double-check)
            if lead.deleted_at is not None:
                raise ResourceNotFoundError(
                    detail=f"Lead with id {lead_id} is already deleted"
                )

            # ✅ FIX: Prevent deletion of leads with admission profiles
            # Check if lead has an admission profile (indicates enrollment process started)
            admission_profile_check = await db.execute(
                select(models.AdmissionProfile.id)
                .where(models.AdmissionProfile.lead_id == lead_id)
                .limit(1)
            )
            has_admission_profile = admission_profile_check.scalar_one_or_none() is not None

            if has_admission_profile:
                raise BusinessRuleViolation(
                    detail="Không thể xóa lead đã có hồ sơ xét tuyển. "
                           "Vui lòng hủy hồ sơ xét tuyển trước khi xóa lead."
                )

            # Capture old state for history logging
            old_state = _get_current_lead_state(lead)

            # Get current timestamp for atomic soft-delete
            deleted_timestamp = datetime.now(timezone.utc)

            # ✅ FIX: Soft-delete all related consultations atomically
            from sqlalchemy import update
            consultation_update_result = await db.execute(
                update(models.Consultation)
                .where(models.Consultation.lead_id == lead_id)
                .where(models.Consultation.deleted_at.is_(None))
                .values(deleted_at=deleted_timestamp)
            )
            consultations_deleted = consultation_update_result.rowcount

            # Set deleted_at timestamp (soft delete)
            lead.deleted_at = deleted_timestamp

            # ✅ PR3: Soft-delete phone identity rows (release phone numbers)
            repo = LeadRepository(db)
            await repo.unregister_phone_identities(lead_id)

            # Optionally update status to indicate deletion
            lead.status = "deleted"

            # Mark as modified
            db.add(lead)

            # Get new state
            new_state = _get_current_lead_state(lead)

            # Log state change in history
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=deleted_by,
                reason=f"Lead soft-deleted by {deleted_by.role} {deleted_by.username}"
            )

            # ✅ AUDIT LOG: Log lead deletion
            await audit_service.log_deleted(
                db,
                entity_type="Lead",
                entity_id=lead_id,
                actor_user_id=deleted_by.id,
                old_values={
                    "full_name": lead.full_name,
                    "phone": lead.phone,
                    "email": lead.email,
                    "unit_id": lead.unit_id,
                    "consultations_deleted": consultations_deleted,
                },
                reason=f"Lead soft-deleted by {deleted_by.role} {deleted_by.username}",
                source="api",
            )

            log.info(
                "Lead soft-deleted successfully",
                lead_id=lead_id,
                consultations_deleted=consultations_deleted,
                deleted_by_user_id=deleted_by.id,
                deleted_by_username=deleted_by.username
            )

            return lead

    except (ResourceNotFoundError, BusinessRuleViolation):
        raise
    except Exception as e:
        # begin_nested() handles savepoint rollback automatically
        log.error(
            "Failed to delete lead",
            lead_id=lead_id,
            deleted_by_user_id=deleted_by.id,
            error=str(e),
            exc_info=True
        )
        raise e


# =============================================================================
# RESTORE LEAD (UNDELETE)
# =============================================================================

async def restore_lead(
    db: AsyncSession,
    lead_id: int,
    restored_by: models.User
) -> models.Lead:
    """
    Restore a soft-deleted Lead and its related consultations (Admin only).

    Business Rules:
    - Clears deleted_at timestamp to restore the lead
    - Also restores all consultations that were deleted at the same time
    - Only Admin can restore leads
    - Cannot restore leads that are not deleted

    Args:
        db: Database session
        lead_id: Lead ID to restore
        restored_by: User performing the restoration (for audit trail)

    Returns:
        models.Lead: The restored lead object

    Raises:
        ResourceNotFoundError: If lead not found
        BusinessRuleViolation: If lead is not deleted
        PermissionDeniedError: If user doesn't have permission

    Example:
        >>> lead = await restore_lead(db, lead_id=123, restored_by=admin_user)
        >>> print(lead.deleted_at)  # None
    """
    # Enforce admin-only at service layer
    if restored_by.role != UserRole.ADMIN:
        raise PermissionDeniedError(
            detail="Only admin can restore leads."
        )

    try:
        async with db.begin_nested():
            # Fetch lead including deleted ones
            lead = await get_lead_by_id_shallow(db, lead_id, include_deleted=True)

            # Check if lead is actually deleted
            if lead.deleted_at is None:
                raise BusinessRuleViolation(
                    detail=f"Lead with id {lead_id} is not deleted"
                )

            # ✅ FIX: Check phone/email conflicts before restoring
            # Prevents restoring a lead whose phone/email is now used by another active lead
            repo = LeadRepository(db)

            # Check phone conflict (global check)
            if lead.phone or lead.phone2:
                phone_conflict = await repo.check_phone_conflict(
                    phone=lead.phone,
                    phone2=lead.phone2,
                    exclude_id=lead_id  # Exclude the lead being restored
                )
                if phone_conflict:
                    raise BusinessRuleViolation(
                        detail=f"Không thể khôi phục lead: Số điện thoại đã được sử dụng bởi lead khác "
                               f"({phone_conflict.full_name} - {phone_conflict.phone})"
                    )

            # Check email conflict (unit-scoped check)
            if lead.email and lead.unit_id:
                email_conflict = await repo.check_email_conflict(
                    email=lead.email,
                    unit_id=lead.unit_id,
                    exclude_id=lead_id
                )
                if email_conflict:
                    raise BusinessRuleViolation(
                        detail=f"Không thể khôi phục lead: Email đã được sử dụng bởi lead khác "
                               f"({email_conflict.full_name} - {email_conflict.email})"
                    )

            # Capture old state for history logging
            old_state = _get_current_lead_state(lead)

            # Get the deleted_at timestamp to find related consultations
            lead_deleted_at = lead.deleted_at

            # Restore all related consultations that were deleted at the same time
            # (within 2 seconds tolerance to account for slight timing differences)
            from sqlalchemy import update
            consultation_update_result = await db.execute(
                update(models.Consultation)
                .where(models.Consultation.lead_id == lead_id)
                .where(models.Consultation.deleted_at.isnot(None))
                .where(
                    func.abs(
                        func.extract('epoch', models.Consultation.deleted_at) -
                        func.extract('epoch', lead_deleted_at)
                    ) < 2  # Within 2 seconds
                )
                .values(deleted_at=None)
            )
            consultations_restored = consultation_update_result.rowcount

            # Flush to ensure restored consultations are visible to subsequent queries
            await db.flush()

            # Clear deleted_at to restore the lead
            lead.deleted_at = None

            # ✅ PR3: Restore phone identity rows (re-enforce uniqueness)
            # IntegrityError will be caught by the outer except block
            await repo.restore_phone_identities(lead_id)

            # ✅ H5: Restore status from latest non-deleted consultation (no hardcode "new")
            latest_consultation = await repo.get_latest_consultation(lead_id)
            if latest_consultation and latest_consultation.consultation_status_id:
                latest_status = await db.get(
                    models.ConsultationStatus, latest_consultation.consultation_status_id
                )
                if latest_status:
                    lead.consultation_status_id = latest_status.id
                    lead.pipeline_stage_id = latest_status.stage_id
                    sync_lead_status_from_consultation(lead, latest_status)
                else:
                    initial_status = await StatusHelper.get_initial_status(db)
                    if initial_status:
                        lead.consultation_status_id = initial_status.id
                        lead.pipeline_stage_id = initial_status.stage_id
                        sync_lead_status_from_consultation(lead, initial_status)
                    else:
                        lead.status = "new"
            else:
                initial_status = await StatusHelper.get_initial_status(db)
                if initial_status:
                    lead.consultation_status_id = initial_status.id
                    lead.pipeline_stage_id = initial_status.stage_id
                    sync_lead_status_from_consultation(lead, initial_status)
                else:
                    lead.status = "new"

            # Mark as modified
            db.add(lead)

            # Get new state
            new_state = _get_current_lead_state(lead)

            # Log state change in history
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=restored_by,
                reason=f"Lead restored by {restored_by.role} {restored_by.username}"
            )

            # ✅ AUDIT LOG: Log lead restoration
            await audit_service.log_audit(
                db,
                entity_type="Lead",
                entity_id=lead_id,
                action="restored",
                actor_user_id=restored_by.id,
                new_value={
                    "full_name": lead.full_name,
                    "phone": lead.phone,
                    "email": lead.email,
                    "consultations_restored": consultations_restored,
                },
                reason=f"Lead restored by {restored_by.role} {restored_by.username}",
                source="api",
            )

            log.info(
                "Lead restored successfully",
                lead_id=lead_id,
                consultations_restored=consultations_restored,
                restored_by_user_id=restored_by.id,
                restored_by_username=restored_by.username
            )

            return lead

    except (ResourceNotFoundError, BusinessRuleViolation, DuplicateResourceError):
        raise
    except IntegrityError as exc:
        _handle_lead_integrity_error(exc)
    except Exception as e:
        # ✅ M10: Removed redundant full-session rollback; begin_nested() handles savepoint rollback automatically
        log.error(
            "Failed to restore lead",
            lead_id=lead_id,
            restored_by_user_id=restored_by.id,
            error=str(e),
            exc_info=True
        )
        raise e