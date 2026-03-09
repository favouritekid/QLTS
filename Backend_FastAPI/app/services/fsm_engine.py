"""
FSM Engine - Phase-Based Status Transition Engine (Production-Grade)

This module implements the EXACT 10 rules from the spec:
1. Status tiếp theo chỉ được sinh từ allowed_transitions dựa trên CURRENT STATUS
2. Phase chỉ đóng vai trò GUARD, không sinh danh sách status
3. required_phase trong allowed_transitions là phase của TO_STATUS
4. Cross-phase transition bị cấm tuyệt đối đối với USER / ROLE
5. Quy tắc phase guard cho user/role
6. Quy tắc cho system/event
7. Stage guard
8. System status không bao giờ cho user thao tác
9. Universal status luôn là activity
10. Activity status KHÔNG phụ thuộc transition table

PLUS 3 ADDITIONAL RULES:
- Rule #11: NULL status → only NOT_CONTACTED (sts00)
- Rule #12: Backend validation (is_transition_allowed)
- Rule #13: System transition idempotency
"""

from typing import List, Optional, Set, Tuple
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from app import models
from app.core.constants import UserRole
from app.models.pipeline import TriggerTypeEnum, SelectableModeEnum, StatusTypeEnum

log = structlog.get_logger(__name__)


# =============================================================================
# MAIN FSM FUNCTION - 7 STEPS
# =============================================================================

async def get_next_statuses_for_lead(
    db: AsyncSession,
    current_status_id: Optional[str],
    lead_phase: str,
    user_role: str = "officer"
) -> List[models.ConsultationStatus]:
    """
    Get allowed next statuses per Spec (7 STEPS + Rule #11).

    Args:
        db: Database session
        current_status_id: Current consultation status ID (None for new leads)
        lead_phase: Derived from admission_profile.status (consultation/admission/fee/enrolled)
        user_role: User's role (officer/manager/admin)

    Returns:
        List of allowed ConsultationStatus objects (empty if no valid transitions)

    Spec Steps:
        STEP 1: Get raw transitions from allowed_transitions table
        STEP 2: Apply phase guard
        STEP 3: Apply stage guard
        STEP 4: Apply trigger guard (UI filter)
        STEP 5: Append universal activities
        STEP 6: Sort by display_order
        STEP 7: Return (empty list if no valid transitions)

    Additional Rules:
        Rule #11: If current_status_id is NULL → ONLY return sts00 (NOT_CONTACTED)
    """

    # STEP 1: Get raw transitions from table
    ds_transition_raw = await _get_raw_transitions(db, current_status_id)

    # STEP 2: Phase guard
    ds_phase_safe = await _apply_phase_guard(db, ds_transition_raw, current_status_id, lead_phase)

    # STEP 3: Stage guard
    ds_stage_safe = await _apply_stage_guard(db, ds_phase_safe, current_status_id)

    # STEP 4: Trigger guard (UI filter)
    ds_ui_safe = _apply_trigger_guard(ds_stage_safe, user_role)

    # STEP 5: Append universal activities
    universal = await _get_universal_activities(db, user_role)
    combined = ds_ui_safe + universal

    # STEP 6: Sort by display_order
    combined.sort(key=lambda s: getattr(s, 'display_order', 999))

    # STEP 7: Return (empty list if no valid transitions)
    log.info(
        "FSM engine computed next statuses",
        current_status=current_status_id,
        lead_phase=lead_phase,
        user_role=user_role,
        count=len(combined)
    )

    return combined


# =============================================================================
# STEP 1: GET RAW TRANSITIONS
# =============================================================================

async def _get_raw_transitions(
    db: AsyncSession,
    from_status_id: Optional[str]
) -> List[models.ConsultationStatus]:
    """
    STEP 1: Query allowed_transitions WHERE from_status_id = X AND is_active = true

    SPEC RULE #11: If from_status_id is NULL (new lead), ONLY return NOT_CONTACTED (sts00).
    Do NOT infer from phase, stage, or allow arbitrary status selection.
    """
    if not from_status_id:
        # ✅ RULE #11: NEW LEAD → ONLY sts00 (NOT_CONTACTED)
        result = await db.execute(
            select(models.ConsultationStatus)
            .where(models.ConsultationStatus.code == "NOT_CONTACTED")
            .options(selectinload(models.ConsultationStatus.stage))
        )
        status = result.scalar_one_or_none()

        if status:
            log.info("New lead - returning NOT_CONTACTED only", status_id=status.id)
            return [status]
        else:
            log.error("NOT_CONTACTED status not found in database")
            return []

    # Query transitions for existing status
    result = await db.execute(
        select(models.ConsultationStatus)
        .join(
            models.AllowedTransition,
            models.AllowedTransition.to_status_id == models.ConsultationStatus.id
        )
        .where(
            and_(
                models.AllowedTransition.from_status_id == from_status_id,
                models.AllowedTransition.is_active == True
            )
        )
        .options(selectinload(models.ConsultationStatus.stage))
        .distinct()
    )

    statuses = list(result.scalars().all())

    log.debug(
        "Raw transitions from table",
        from_status=from_status_id,
        count=len(statuses)
    )

    return statuses


# =============================================================================
# STEP 2: PHASE GUARD
# =============================================================================

async def _apply_phase_guard(
    db: AsyncSession,
    transitions: List[models.ConsultationStatus],
    from_status_id: Optional[str],
    lead_phase: str
) -> List[models.ConsultationStatus]:
    """
    STEP 2: Phase guard

    SPEC RULES #5 & #6:
    - user/role: to_status.phase MUST == lead.phase (cross-phase forbidden)
    - system/event: allowed to cross phase if declared in table

    Note: required_phase in transition is the phase of TO_STATUS (Rule #3)
    """
    if not from_status_id:
        # New lead - skip phase guard
        return transitions

    safe = []

    for to_status in transitions:
        # Get the transition record to check trigger_type
        result = await db.execute(
            select(models.AllowedTransition)
            .where(
                and_(
                    models.AllowedTransition.from_status_id == from_status_id,
                    models.AllowedTransition.to_status_id == to_status.id,
                    models.AllowedTransition.is_active == True
                )
            )
            .limit(1)
        )
        transition = result.scalar_one_or_none()

        if not transition:
            log.warning(
                "Transition not found for status (should not happen)",
                from_status=from_status_id,
                to_status=to_status.id
            )
            continue

        trigger_type = transition.trigger_type

        # ✅ RULE #5: User/Role cannot cross phase
        if trigger_type in (TriggerTypeEnum.user, TriggerTypeEnum.role):
            if to_status.phase != lead_phase:
                log.debug(
                    "Phase guard blocked user/role cross-phase transition",
                    from_status=from_status_id,
                    to_status=to_status.id,
                    to_phase=to_status.phase,
                    lead_phase=lead_phase,
                    trigger_type=trigger_type.value
                )
                continue

        # ✅ RULE #6: System/Event can cross phase
        # ✅ RULE #3: Verify required_phase matches to_status.phase
        else:
            if transition.required_phase and transition.required_phase != to_status.phase:
                log.error(
                    "Inconsistent required_phase in transition (data error)",
                    transition_id=transition.id,
                    required_phase=transition.required_phase,
                    to_status_phase=to_status.phase
                )
                continue

        safe.append(to_status)

    log.debug(
        "Phase guard applied",
        original_count=len(transitions),
        safe_count=len(safe),
        lead_phase=lead_phase
    )

    return safe


# =============================================================================
# STEP 3: STAGE GUARD
# =============================================================================

async def _apply_stage_guard(
    db: AsyncSession,
    statuses: List[models.ConsultationStatus],
    current_status_id: Optional[str]
) -> List[models.ConsultationStatus]:
    """
    STEP 3: Stage guard

    SPEC RULE #7:
    If to_status.updates_pipeline = true:
        to_status.stage.order MUST >= current_stage.order (no backward movement)
    Non-pipeline statuses (updates_pipeline = false) are always allowed.
    """
    if not current_status_id:
        # New lead - skip stage guard
        return statuses

    # Get current status with its stage eagerly loaded
    result = await db.execute(
        select(models.ConsultationStatus)
        .where(models.ConsultationStatus.id == current_status_id)
        .options(selectinload(models.ConsultationStatus.stage))
    )
    current_status = result.scalar_one_or_none()
    if not current_status:
        log.warning("Current status not found", status_id=current_status_id)
        return statuses

    current_stage_id = current_status.stage_id

    # If current status has no stage, we cannot enforce stage ordering
    if not current_status.stage:
        log.debug(
            "Stage guard skipped - current status has no stage",
            current_status_id=current_status_id
        )
        return statuses

    current_stage_order = current_status.stage.order

    # Preload all stage orders we'll need for comparison
    to_stage_ids = {
        s.stage_id for s in statuses
        if s.updates_pipeline and s.stage_id
    }
    stage_order_map = {}
    if to_stage_ids:
        stage_result = await db.execute(
            select(models.PipelineStage)
            .where(models.PipelineStage.id.in_(to_stage_ids))
        )
        for stage in stage_result.scalars().all():
            stage_order_map[stage.id] = stage.order

    safe = []
    for to_status in statuses:
        # Non-pipeline statuses (activities, etc.) are never blocked by stage guard
        if not to_status.updates_pipeline or not to_status.stage_id:
            safe.append(to_status)
            continue

        # ✅ RULE #7: Reject backward stage movement for pipeline-updating statuses
        to_stage_order = stage_order_map.get(to_status.stage_id)
        if to_stage_order is None:
            log.warning(
                "Stage order not found for to_status stage",
                to_status_id=to_status.id,
                stage_id=to_status.stage_id
            )
            safe.append(to_status)  # Allow if we can't determine order
            continue

        if to_stage_order < current_stage_order:
            log.debug(
                "Stage guard blocked backward pipeline transition",
                current_stage_id=current_stage_id,
                current_stage_order=current_stage_order,
                to_status_id=to_status.id,
                to_stage_id=to_status.stage_id,
                to_stage_order=to_stage_order
            )
            continue

        safe.append(to_status)

    log.debug(
        "Stage guard applied",
        current_stage=current_stage_id,
        original_count=len(statuses),
        safe_count=len(safe)
    )

    return safe


# =============================================================================
# STEP 4: TRIGGER GUARD (UI FILTER)
# =============================================================================

def _apply_trigger_guard(
    statuses: List[models.ConsultationStatus],
    user_role: str
) -> List[models.ConsultationStatus]:
    """
    STEP 4: Trigger guard

    SPEC RULE #8: System status không bao giờ cho user thao tác

    UI only shows:
    - selectable_mode = 'user'
    - selectable_mode = 'role' (if user has manager/admin role)

    Hide:
    - selectable_mode = 'system'
    """
    safe = []

    for status in statuses:
        # ✅ RULE #8: Hide system-only statuses
        if status.selectable_mode == SelectableModeEnum.system:
            log.debug(
                "Trigger guard blocked system-only status",
                status_id=status.id,
                status_name=status.name
            )
            continue

        # Check role requirement
        if status.selectable_mode == SelectableModeEnum.role:
            if user_role not in (UserRole.MANAGER, UserRole.ADMIN):
                log.debug(
                    "Trigger guard blocked role-based status",
                    status_id=status.id,
                    required_role="manager/admin",
                    user_role=user_role
                )
                continue

        safe.append(status)

    log.debug(
        "Trigger guard applied",
        original_count=len(statuses),
        safe_count=len(safe),
        user_role=user_role
    )

    return safe


# =============================================================================
# STEP 5: APPEND UNIVERSAL ACTIVITIES
# =============================================================================

async def _get_universal_activities(
    db: AsyncSession,
    user_role: str
) -> List[models.ConsultationStatus]:
    """
    STEP 5: Get universal activities (is_universal = true)

    SPEC RULES #9 & #10:
    - Universal status luôn là activity
    - Không đi qua allowed_transitions
    - Không ảnh hưởng lifecycle
    """
    result = await db.execute(
        select(models.ConsultationStatus)
        .where(models.ConsultationStatus.is_universal == True)
        .options(selectinload(models.ConsultationStatus.stage))
    )

    all_universal = list(result.scalars().all())

    # Apply same role filter as trigger guard
    safe = []
    for status in all_universal:
        if status.selectable_mode == SelectableModeEnum.system:
            continue

        if status.selectable_mode == SelectableModeEnum.role:
            if user_role not in (UserRole.MANAGER, UserRole.ADMIN):
                continue

        safe.append(status)

    log.debug(
        "Universal activities appended",
        count=len(safe),
        user_role=user_role
    )

    return safe


# =============================================================================
# VALIDATION FUNCTION (RULE #12)
# =============================================================================

async def is_transition_allowed(
    db: AsyncSession,
    from_status_id: Optional[str],
    to_status_id: str,
    lead_phase: str,
    user_role: str
) -> bool:
    """
    Check if a status transition is allowed (RULE #12: Backend validation).

    This is the SINGLE SOURCE OF TRUTH for transition validation.
    Used by smart dependency to reject invalid transitions.

    Args:
        db: Database session
        from_status_id: Current status (None for new leads)
        to_status_id: Target status
        lead_phase: Current lead phase
        user_role: User's role

    Returns:
        True if transition is allowed, False otherwise
    """
    # Get allowed next statuses using full FSM logic
    allowed_statuses = await get_next_statuses_for_lead(
        db=db,
        current_status_id=from_status_id,
        lead_phase=lead_phase,
        user_role=user_role
    )

    # Check if to_status is in allowed list
    is_allowed = any(s.id == to_status_id for s in allowed_statuses)

    if not is_allowed:
        log.warning(
            "Transition validation failed",
            from_status=from_status_id,
            to_status=to_status_id,
            lead_phase=lead_phase,
            user_role=user_role
        )

    return is_allowed


# =============================================================================
# SYSTEM TRANSITION WITH IDEMPOTENCY (RULE #13)
# =============================================================================

async def execute_system_transition(
    db: AsyncSession,
    lead: models.Lead,
    to_status_id: str,
    reason: str = "system_event"
) -> bool:
    """
    Execute system transition with idempotency check (RULE #13).

    Rules:
    1. Only execute if lead.current_status_id == expected from_status
    2. Only execute if lead has NOT been in to_status before (check history)
    3. Skip if already at to_status (same-status update)

    Args:
        db: Database session
        lead: Lead object
        to_status_id: Target status ID
        reason: Reason for transition (logged)

    Returns:
        True if transition executed, False if skipped (idempotent)
    """
    from app.services.status_helper import StatusHelper

    # ✅ RULE #13.1: Skip if already at target status
    if lead.consultation_status_id == to_status_id:
        log.info(
            "System transition skipped - already at target status",
            lead_id=lead.id,
            status_id=to_status_id,
            reason="idempotent_same_status"
        )
        return False

    # ✅ RULE #13.2: Check if lead was EVER in this status before (prevent loops)
    result = await db.execute(
        select(models.LeadStatusHistory)
        .where(
            and_(
                models.LeadStatusHistory.lead_id == lead.id,
                models.LeadStatusHistory.new_consultation_status_id == to_status_id
            )
        )
        .limit(1)
    )
    previous_occurrence = result.scalar_one_or_none()

    if previous_occurrence:
        log.warning(
            "System transition skipped - lead was in this status before",
            lead_id=lead.id,
            from_status=lead.consultation_status_id,
            to_status=to_status_id,
            previous_at=previous_occurrence.changed_at,
            reason="idempotent_history_check"
        )
        return False

    # ✅ RULE #13.3: Validate transition is configured with system trigger
    result = await db.execute(
        select(models.AllowedTransition)
        .where(
            and_(
                models.AllowedTransition.from_status_id == lead.consultation_status_id,
                models.AllowedTransition.to_status_id == to_status_id,
                models.AllowedTransition.trigger_type == TriggerTypeEnum.system,
                models.AllowedTransition.is_active == True
            )
        )
    )
    transition = result.scalar_one_or_none()

    if not transition:
        log.error(
            "System transition NOT configured in allowed_transitions",
            lead_id=lead.id,
            from_status=lead.consultation_status_id,
            to_status=to_status_id,
            reason=reason
        )
        return False

    # Execute transition
    to_status = await db.get(models.ConsultationStatus, to_status_id)
    if not to_status:
        log.error("Target status not found", status_id=to_status_id)
        return False

    # ✅ Capture old state BEFORE mutation for accurate history
    old_status = lead.status
    old_consultation_status_id = lead.consultation_status_id
    old_pipeline_stage_id = lead.pipeline_stage_id

    # Update lead status using StatusHelper
    await StatusHelper.sync_lead_status(lead, to_status)

    # Create history record (using pre-mutation values for old_*)
    history = models.LeadStatusHistory(
        lead_id=lead.id,
        old_status=old_status,
        new_status=lead.status,
        old_consultation_status_id=old_consultation_status_id,
        new_consultation_status_id=to_status_id,
        old_pipeline_stage_id=old_pipeline_stage_id,
        new_pipeline_stage_id=to_status.stage_id,
        changed_by_user_id=None,  # System change
        reason=f"System transition: {reason}"
    )
    db.add(history)

    log.info(
        "System transition executed",
        lead_id=lead.id,
        from_status=transition.from_status_id,
        to_status=to_status_id,
        reason=reason
    )

    return True
