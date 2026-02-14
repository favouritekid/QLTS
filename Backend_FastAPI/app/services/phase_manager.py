# app/services/phase_manager.py
"""
Phase-Based Workflow Manager

This module provides the core logic for:
- Deriving lead phase from admission profile status
- Validating status changes based on current phase
- Managing phase transition rules

Phase = Business lifecycle stage (4 phases)
Status = Detailed state within phase
Stage = Visual pipeline position (Kanban)

CRITICAL: Phase is derived from admission_profile.status, NOT from stage.
"""

from enum import Enum
from typing import Set, Optional, TYPE_CHECKING

import structlog

from ..core.constants import UserRole

if TYPE_CHECKING:
    from ..models import AdmissionProfile

log = structlog.get_logger(__name__)


class LeadPhase(str, Enum):
    """Lead lifecycle phases."""
    CONSULTATION = "consultation"  # stg01-02: Tư vấn
    ADMISSION = "admission"        # stg03-04: Xét tuyển
    FEE = "fee"                    # stg05: Học phí
    ENROLLED = "enrolled"          # stg06-07: Nhập học (Terminal)


# =============================================================================
# PHASE → STATUS MAPPING
# =============================================================================

# PRINCIPLE:
# - Phase = manages PROCESS (business lifecycle stage)
# - Stage = manages WORK (visual pipeline/kanban position)
# - Status = reflects REALITY (what actually happened)
#
# When a lead moves to ADMISSION phase, consultation statuses should NOT be used.
# User can only select statuses within current phase OR universal statuses.

PHASE_STATUSES: dict[LeadPhase, Set[str]] = {
    # CONSULTATION: Contact tracking before admission application
    LeadPhase.CONSULTATION: {"sts00", "sts02", "sts03", "sts04", "sts05", "sts06"},
    
    # ADMISSION: Application processing statuses
    LeadPhase.ADMISSION: {"sts07", "sts08", "sts09", "sts13", "sts16", "sts17"},
    
    # FEE: Payment processing statuses
    LeadPhase.FEE: {"sts10", "sts14", "sts18"},
    
    # ENROLLED: Terminal phase - enrolled or dropped
    LeadPhase.ENROLLED: {"sts11", "sts12"},
}

# Universal statuses - can be used in ANY phase, DON'T change stage
# These are for tracking contact attempts without affecting pipeline progression
# sts01: NO_ANSWER (Không nghe máy)
# sts15: NO_REPLY_MESSAGE (Nhắn tin không phản hồi)
# sts19: CANCELLED (Đã hủy lịch hẹn)
UNIVERSAL_STATUSES: Set[str] = {"sts01", "sts15", "sts19"}

# System-only statuses - cannot be selected by regular users
SYSTEM_ONLY_STATUSES: Set[str] = {"sts10", "sts11", "sts12", "sts13", "sts18"}

# Role-based statuses - only Manager/Admin can select
ROLE_BASED_STATUSES: Set[str] = {"sts09", "sts16"}

# Phase → allowed stages mapping
PHASE_STAGES: dict[LeadPhase, Set[str]] = {
    LeadPhase.CONSULTATION: {"stg01", "stg02"},
    LeadPhase.ADMISSION: {"stg03", "stg04"},
    LeadPhase.FEE: {"stg05"},
    LeadPhase.ENROLLED: {"stg06", "stg07"},
}




# =============================================================================
# PHASE DERIVATION
# =============================================================================

def derive_phase_from_admission(
    admission_profile: Optional["AdmissionProfile"]
) -> LeadPhase:
    """
    Derive lead's current phase from admission profile status.
    
    Phase derivation rules:
    - No profile → CONSULTATION
    - Profile draft/submitted/rejected/resubmitted → ADMISSION
    - Profile approved/confirmed/overridden → FEE (waiting for payment)
    - Profile enrolled → ENROLLED (terminal)
    
    Args:
        admission_profile: AdmissionProfile or None
        
    Returns:
        LeadPhase enum value
    """
    if not admission_profile:
        return LeadPhase.CONSULTATION
    
    status = admission_profile.status
    
    if status == "enrolled":
        return LeadPhase.ENROLLED
    elif status in ("approved", "confirmed", "overridden"):
        return LeadPhase.FEE
    else:
        # draft, submitted, rejected, resubmitted
        return LeadPhase.ADMISSION


def derive_phase_from_stage(stage_id: Optional[str]) -> LeadPhase:
    """
    Fallback: derive phase from stage if no admission profile.
    
    CAUTION: This should only be used for display purposes.
    Phase MUST be derived from admission_profile for business logic.
    """
    if not stage_id:
        return LeadPhase.CONSULTATION
    
    for phase, stages in PHASE_STAGES.items():
        if stage_id in stages:
            return phase
    
    return LeadPhase.CONSULTATION


# =============================================================================
# STATUS VALIDATION
# =============================================================================

def is_status_allowed_for_phase(
    phase: LeadPhase,
    status_id: str,
    user_role: str = "officer"
) -> bool:
    """
    Check if a status can be selected by user in the given phase.
    
    Args:
        phase: Current lead phase
        status_id: Target status ID
        user_role: User's role (officer, manager, admin)
        
    Returns:
        True if status is allowed
    """
    # Universal statuses are always allowed
    if status_id in UNIVERSAL_STATUSES:
        return True
    
    # System-only statuses cannot be selected manually
    if status_id in SYSTEM_ONLY_STATUSES:
        log.debug(
            "Status is system-only",
            status_id=status_id,
            user_role=user_role
        )
        return False
    
    # Role-based statuses require manager/admin
    if status_id in ROLE_BASED_STATUSES:
        if user_role not in (UserRole.MANAGER, UserRole.ADMIN):
            log.debug(
                "Status requires manager/admin role",
                status_id=status_id,
                user_role=user_role
            )
            return False
    
    # Check if status belongs to current phase
    phase_statuses = PHASE_STATUSES.get(phase, set())
    is_allowed = status_id in phase_statuses
    
    if not is_allowed:
        log.debug(
            "Status not in current phase",
            status_id=status_id,
            phase=phase.value,
            allowed_statuses=list(phase_statuses)
        )
    
    return is_allowed


def get_allowed_statuses_for_phase(
    phase: LeadPhase,
    user_role: str = "officer"
) -> Set[str]:
    """
    Get all statuses that user can select in the given phase.
    
    Args:
        phase: Current lead phase
        user_role: User's role
        
    Returns:
        Set of allowed status IDs
    """
    # Start with universal statuses
    allowed = UNIVERSAL_STATUSES.copy()
    
    # Add phase-specific statuses
    phase_statuses = PHASE_STATUSES.get(phase, set())
    
    for status_id in phase_statuses:
        # Skip system-only
        if status_id in SYSTEM_ONLY_STATUSES:
            continue
        
        # Check role-based
        if status_id in ROLE_BASED_STATUSES:
            if user_role in (UserRole.MANAGER, UserRole.ADMIN):
                allowed.add(status_id)
        else:
            allowed.add(status_id)
    
    return allowed


def get_allowed_stages_for_phase(phase: LeadPhase) -> Set[str]:
    """
    Get all stages that belong to a phase.
    """
    return PHASE_STAGES.get(phase, set())


# =============================================================================
# PHASE TRANSITION RULES
# =============================================================================

def is_terminal_phase(phase: LeadPhase) -> bool:
    """Check if phase is terminal (no further transitions allowed)."""
    return phase == LeadPhase.ENROLLED


def can_transition_to_phase(
    current_phase: LeadPhase,
    target_phase: LeadPhase
) -> bool:
    """
    Check if phase transition is allowed.
    
    Rules:
    - Can only move forward (CONSULTATION → ADMISSION → FEE → ENROLLED)
    - Cannot go backward
    - Cannot skip phases
    """
    phase_order = [
        LeadPhase.CONSULTATION,
        LeadPhase.ADMISSION,
        LeadPhase.FEE,
        LeadPhase.ENROLLED
    ]
    
    current_idx = phase_order.index(current_phase)
    target_idx = phase_order.index(target_phase)
    
    # Can only move forward by 1 step
    return target_idx == current_idx + 1
