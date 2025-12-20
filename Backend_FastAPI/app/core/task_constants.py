# app/core/task_constants.py
"""
Constants for Celery task results and reasons.
Eliminates magic strings across task modules.
"""


class AssignmentResult:
    """Status values for lead assignment tasks."""
    ASSIGNED = "assigned"
    SKIPPED = "skipped"
    FAILED = "failed"


class AssignmentFailureReason:
    """Reason codes when assignment fails or is skipped."""
    NO_OFFICERS = "no_officers_available"
    AT_CAPACITY = "all_officers_at_capacity"
    LEAD_NOT_FOUND = "lead_not_found"
    LEAD_DELETED = "lead_deleted"
    ALREADY_ASSIGNED = "already_assigned"


class AssignmentSkipReason:
    """Reason codes when assignment is skipped (not an error)."""
    LEAD_NOT_FOUND = "lead_not_found"
    LEAD_DELETED = "lead_deleted"
    ALREADY_ASSIGNED = "already_assigned"
