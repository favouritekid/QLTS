# app/services/admission_state_machine.py
"""
Admission State Machine - Single source of truth for status transitions.

Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 1.4:
- Enum-based state definitions
- ALLOWED_TRANSITIONS map as validation source
- Helper functions for validation

Architecture Compliance (Section 0.4.1):
- ALL updates to admission_profile.status MUST go through Service Layer
- Direct database updates are FORBIDDEN except via controlled migrations
- This module provides validation helpers for service methods

State Diagram:
    DRAFT → SUBMITTED → APPROVED → CONFIRMED → ENROLLED
                     ↘ REJECTED → RESUBMITTED ↗
              APPROVED ↘ OVERRIDDEN ↗ → ENROLLED
"""

from enum import Enum
from typing import Set, Dict


class AdmissionStatus(str, Enum):
    """
    Admission status enum.

    State Lifecycle:
    1. DRAFT: Initial state (officer creates profile)
    2. SUBMITTED: Applicant submits for review
    3. APPROVED: Manager approves application
    4. REJECTED: Manager rejects (can resubmit)
    5. RESUBMITTED: Officer resubmits after fixing issues
    6. CONFIRMED: Applicant confirms enrollment intent
    7. OVERRIDDEN: Admin overrides normal flow (audit required)
    8. ENROLLED: Final state (student record created)
    """
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESUBMITTED = "resubmitted"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"
    ENROLLED = "enrolled"  # FINAL STATE


# Single source of truth for transitions
ALLOWED_TRANSITIONS: Dict[AdmissionStatus, Set[AdmissionStatus]] = {
    AdmissionStatus.DRAFT: {AdmissionStatus.SUBMITTED},
    AdmissionStatus.SUBMITTED: {AdmissionStatus.APPROVED, AdmissionStatus.REJECTED},
    AdmissionStatus.REJECTED: {AdmissionStatus.RESUBMITTED},
    AdmissionStatus.RESUBMITTED: {AdmissionStatus.APPROVED, AdmissionStatus.REJECTED},
    AdmissionStatus.APPROVED: {AdmissionStatus.CONFIRMED, AdmissionStatus.OVERRIDDEN},
    AdmissionStatus.OVERRIDDEN: {AdmissionStatus.ENROLLED},
    AdmissionStatus.CONFIRMED: {AdmissionStatus.ENROLLED},
    AdmissionStatus.ENROLLED: set(),  # Final state - no transitions
}


def can_transition(current: str, target: str) -> bool:
    """
    Check if transition is valid according to state machine.

    Args:
        current: Current status (string value)
        target: Target status (string value)

    Returns:
        True if transition is allowed, False otherwise

    Example:
        >>> can_transition("draft", "submitted")
        True
        >>> can_transition("draft", "enrolled")
        False
        >>> can_transition("enrolled", "approved")
        False  # ENROLLED is final
    """
    try:
        current_status = AdmissionStatus(current)
        target_status = AdmissionStatus(target)
        return target_status in ALLOWED_TRANSITIONS.get(current_status, set())
    except ValueError:
        # Invalid status string
        return False


def get_allowed_transitions(current: str) -> Set[str]:
    """
    Get all valid next states for current status.

    Args:
        current: Current status (string value)

    Returns:
        Set of allowed target status strings

    Example:
        >>> get_allowed_transitions("approved")
        {'confirmed', 'overridden'}
        >>> get_allowed_transitions("enrolled")
        set()  # No transitions from final state
        >>> get_allowed_transitions("invalid")
        set()  # Invalid status returns empty set
    """
    try:
        current_status = AdmissionStatus(current)
        return {s.value for s in ALLOWED_TRANSITIONS.get(current_status, set())}
    except ValueError:
        return set()


def is_final_state(status: str) -> bool:
    """
    Check if status is a final state (no further transitions).

    Args:
        status: Status string to check

    Returns:
        True if status is final (ENROLLED), False otherwise

    Example:
        >>> is_final_state("enrolled")
        True
        >>> is_final_state("approved")
        False
    """
    try:
        status_enum = AdmissionStatus(status)
        return len(ALLOWED_TRANSITIONS.get(status_enum, set())) == 0
    except ValueError:
        return False


def validate_transition(current: str, target: str) -> None:
    """
    Validate state transition and raise exception if invalid.

    This is a convenience function for service layer to validate
    transitions and get a clear error message.

    Args:
        current: Current status
        target: Target status

    Raises:
        ValueError: If transition is invalid (with clear error message)

    Example:
        >>> validate_transition("draft", "submitted")
        # No exception - valid transition

        >>> validate_transition("draft", "enrolled")
        ValueError: Invalid transition: draft → enrolled. Allowed: submitted
    """
    if not can_transition(current, target):
        allowed = get_allowed_transitions(current)
        allowed_str = ", ".join(sorted(allowed)) if allowed else "none (final state)"
        raise ValueError(
            f"Invalid transition: {current} → {target}. "
            f"Allowed transitions from {current}: {allowed_str}"
        )


# Export all public symbols
__all__ = [
    "AdmissionStatus",
    "ALLOWED_TRANSITIONS",
    "can_transition",
    "get_allowed_transitions",
    "is_final_state",
    "validate_transition",
]
