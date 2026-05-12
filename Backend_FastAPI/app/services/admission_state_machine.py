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
      ↘        ↘ ↗      ↘ REJECTED → RESUBMITTED ↗
  WITHDRAWN  WITHDRAWN        ↘ WITHDRAWN
              APPROVED ↘ OVERRIDDEN ↗ → ENROLLED
"""

from enum import Enum
from typing import Set, Dict


class AdmissionStatus(str, Enum):
    """
    Admission status enum — 14 values matching phase1_11 DB CHECK constraint
    (`ck_admission_profile_status`).

    Legacy 10-state lifecycle (uses_choice_engine=false):
    1. DRAFT: Initial state (officer creates profile)
    2. SUBMITTED: Applicant submits for review
    3. APPROVED: Manager approves application (legacy single-NV path)
    4. REJECTED: Manager rejects (can resubmit)
    4b. REVISION_REQUESTED: Manager requests document revision (can resubmit)
    5. RESUBMITTED: Officer resubmits after fixing issues
    6. CONFIRMED: Applicant confirms enrollment intent
    7. OVERRIDDEN: Admin overrides normal flow (audit required)
    8. ENROLLED: Final state (student record created)
    9. WITHDRAWN: Applicant/officer withdraws application (final)

    Phase 3 multi-NV extension (uses_choice_engine=true, plan v0.7 Q-P3-02):
    10. REVIEWING: Profile under manager review (post-submit, pre-decision)
    11. RESULT_PUBLISHED: Score published before per-candidate decision (T6
        admin batch broadcast marker)
    12. ADMITTED: Choice-engine admit decision (T7, replaces APPROVED for
        multi-NV path; APPROVED kept for legacy uses_choice_engine=false)
    13. WAITLISTED: Choice-engine waitlist decision (T8, can be promoted to
        ADMITTED via T10 manual)
    """
    # Legacy 10-state single-NV lifecycle
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
    RESUBMITTED = "resubmitted"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"
    ENROLLED = "enrolled"  # FINAL STATE
    WITHDRAWN = "withdrawn"  # FINAL STATE

    # Phase 1 #11 NEW states (DB CHECK extend 14-state) — multi-NV Phase 3
    REVIEWING = "reviewing"
    RESULT_PUBLISHED = "result_published"
    ADMITTED = "admitted"
    WAITLISTED = "waitlisted"


# Single source of truth for transitions — 14-state graph mixing legacy
# single-NV edges + Phase 3 multi-NV edges. Engine writers
# (PR-3C `admission_scoring_service.evaluate_cascade`) traverse multi-NV
# edges via `transition()`; legacy callers stay on the original 10-state
# subgraph (no `uses_choice_engine` flag check at validation layer — the
# state machine itself is permissive, business-layer enforces flag via
# service guards per plan v0.7 G7 add_choice precheck pattern).
ALLOWED_TRANSITIONS: Dict[AdmissionStatus, Set[AdmissionStatus]] = {
    # Legacy 10-state lifecycle (preserved for uses_choice_engine=false)
    AdmissionStatus.DRAFT: {AdmissionStatus.SUBMITTED, AdmissionStatus.WITHDRAWN},
    AdmissionStatus.SUBMITTED: {
        # Legacy: direct decision by manager (single-NV)
        AdmissionStatus.APPROVED,
        AdmissionStatus.REJECTED,
        AdmissionStatus.REVISION_REQUESTED,
        AdmissionStatus.WITHDRAWN,
        # Phase 3 T2: submitted → reviewing (manager review window)
        AdmissionStatus.REVIEWING,
        # Phase 3 PR-3C Sub-3.5 T17: admin rollback → draft
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.REJECTED: {
        AdmissionStatus.RESUBMITTED,
        AdmissionStatus.WITHDRAWN,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.REVISION_REQUESTED: {
        AdmissionStatus.RESUBMITTED,
        AdmissionStatus.REJECTED,
        AdmissionStatus.WITHDRAWN,
        # Phase 3 T4: revision_requested → reviewing (after candidate fix)
        AdmissionStatus.REVIEWING,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.RESUBMITTED: {
        AdmissionStatus.APPROVED,
        AdmissionStatus.REJECTED,
        AdmissionStatus.REVISION_REQUESTED,
        AdmissionStatus.WITHDRAWN,
        # Phase 3: resubmitted → reviewing (uses_choice_engine path)
        AdmissionStatus.REVIEWING,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.APPROVED: {
        AdmissionStatus.CONFIRMED,
        AdmissionStatus.OVERRIDDEN,
        # Phase 3 PR-3C Sub-3.5 T17 — admin rollback approved profile
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.OVERRIDDEN: {
        AdmissionStatus.ENROLLED,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.CONFIRMED: {
        AdmissionStatus.ENROLLED,
        # Phase 3 PR-3C Sub-3.5 T17 — admin rollback confirmed (rare)
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.ENROLLED: set(),  # Final state - no transitions
    AdmissionStatus.WITHDRAWN: set(),  # Final state - no transitions

    # Phase 3 multi-NV edges (PR-3B + PR-3C Sub-3.5 T17 extension)
    AdmissionStatus.REVIEWING: {
        # T3: reviewing → revision_requested (manager requests fix)
        AdmissionStatus.REVISION_REQUESTED,
        # T6: reviewing → result_published (admin batch publish)
        AdmissionStatus.RESULT_PUBLISHED,
        # Candidate withdraws during review window
        AdmissionStatus.WITHDRAWN,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.RESULT_PUBLISHED: {
        # T7: result_published → admitted (choice-engine cascade)
        AdmissionStatus.ADMITTED,
        # T8: result_published → waitlisted (choice-engine waitlist)
        AdmissionStatus.WAITLISTED,
        # T9 (multi-NV variant): result_published → rejected
        AdmissionStatus.REJECTED,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.ADMITTED: {
        # T12 (multi-NV): admitted → confirmed (candidate accepts)
        AdmissionStatus.CONFIRMED,
        # Candidate withdraws after admit
        AdmissionStatus.WITHDRAWN,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
    AdmissionStatus.WAITLISTED: {
        # T10: waitlisted → admitted (manual admin promote)
        AdmissionStatus.ADMITTED,
        # T11: waitlisted → rejected (admin finalize reject)
        AdmissionStatus.REJECTED,
        # Candidate withdraws while waitlisted
        AdmissionStatus.WITHDRAWN,
        # Phase 3 PR-3C Sub-3.5 T17
        AdmissionStatus.DRAFT,
    },
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
    except (ValueError, TypeError, AttributeError):
        # Invalid status string, None, or non-string type
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
    except (ValueError, TypeError, AttributeError):
        return set()


def is_final_state(status: str) -> bool:
    """
    Check if status is a final state (no further transitions).

    Args:
        status: Status string to check

    Returns:
        True if status is final (ENROLLED or WITHDRAWN), False otherwise

    Example:
        >>> is_final_state("enrolled")
        True
        >>> is_final_state("approved")
        False
    """
    try:
        status_enum = AdmissionStatus(status)
        return len(ALLOWED_TRANSITIONS.get(status_enum, set())) == 0
    except (ValueError, TypeError, AttributeError):
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
