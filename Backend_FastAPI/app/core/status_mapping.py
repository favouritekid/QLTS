# app/core/status_mapping.py
"""
Lead Status Synchronization Layer (Hybrid Approach)

This module provides functionality to synchronize the legacy `lead.status` field
with the modern `consultation_status` workflow system.

The Hybrid Approach uses two strategies:
1. **Database-driven mapping**: If `consultation_status.legacy_status` is set,
   use it directly (allows Admin to override)
2. **Dynamic derivation**: If `legacy_status` is NULL, derive from attributes
   (stage_id, outcome_type, is_final_status)

This ensures backward compatibility while allowing the system to evolve.

Valid lead.status values:
- "new": Lead mới, chưa xử lý
- "assigned": Đã gán cho officer (system status, not derived)
- "contacted": Đã liên hệ
- "qualified": Lead tiềm năng
- "unqualified": Không phù hợp (đã từng tiến xa trong pipeline)
- "converted": Đã chuyển đổi thành công
- "rejected": Bị từ chối sớm (chưa tiến xa trong pipeline)

System statuses (not derived from consultation_status):
- "unassigned_pending": Chờ phân công
- "reassigned_pending": Chờ phân công lại
"""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from ..models import ConsultationStatus

log = structlog.get_logger(__name__)


# =============================================================================
# VALID STATUS VALUES
# =============================================================================

VALID_LEAD_STATUSES = frozenset({
    "new",
    "assigned",
    "contacted",
    "qualified",
    "unqualified",
    "converted",
    "rejected",
    # System statuses (managed by assignment_service)
    "unassigned_pending",
    "reassigned_pending",
})

# Default status when no consultation_status is set
DEFAULT_LEAD_STATUS = "new"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass(frozen=True)
class ConsultationStatusInfo:
    """
    Immutable data class containing consultation status attributes
    needed for lead.status derivation.

    Attributes:
        id: Unique status identifier (e.g., "sts00", "sts06")
        stage_id: Parent pipeline stage ID (e.g., "stg01", "stg02")
        outcome_type: Outcome classification ("positive", "neutral", "negative")
        is_final_status: Whether this status marks end of lead lifecycle
        legacy_status: Explicit mapping override (if set in DB)
    """
    id: str
    stage_id: str
    outcome_type: str  # "positive" | "neutral" | "negative"
    is_final_status: bool
    legacy_status: Optional[str] = None


# =============================================================================
# CORE DERIVATION LOGIC
# =============================================================================

def derive_lead_status(status_info: Optional[ConsultationStatusInfo]) -> str:
    """
    Derive lead.status from consultation_status attributes.

    Uses Hybrid Approach:
    1. If legacy_status is explicitly set → use it directly
    2. Otherwise → derive from stage/outcome/is_final

    Decision Tree:
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 1. Nếu không có status → "new"                                      │
    │ 2. Nếu có legacy_status override → use it                           │
    │ 3. Nếu is_final=true và outcome=negative:                           │
    │    - stg07 (Không theo học) → "unqualified"                         │
    │    - Các stage khác → "rejected"                                    │
    │ 4. Nếu stage=stg06 (Đã nhập học) → "converted"                      │
    │ 5. Nếu stage=stg01 (Chưa tư vấn) → "new"                            │
    │ 6. Nếu stage=stg02 (Đang tư vấn):                                   │
    │    - outcome=positive → "qualified"                                  │
    │    - khác → "contacted"                                              │
    │ 7. Nếu stage>=stg03 (Đã nộp hồ sơ trở đi) → "qualified"             │
    │ 8. Fallback → "new"                                                  │
    └─────────────────────────────────────────────────────────────────────┘

    Args:
        status_info: ConsultationStatusInfo object or None

    Returns:
        Derived lead status string

    Examples:
        >>> derive_lead_status(None)
        "new"

        >>> derive_lead_status(ConsultationStatusInfo(
        ...     id="sts06", stage_id="stg02", outcome_type="positive",
        ...     is_final_status=False, legacy_status="qualified"
        ... ))
        "qualified"  # Uses explicit legacy_status

        >>> derive_lead_status(ConsultationStatusInfo(
        ...     id="sts11", stage_id="stg06", outcome_type="positive",
        ...     is_final_status=True, legacy_status=None
        ... ))
        "converted"  # Derived from stg06
    """
    if status_info is None:
        return DEFAULT_LEAD_STATUS

    # Priority 1: Use explicit legacy_status if defined in DB
    if status_info.legacy_status:
        if status_info.legacy_status in VALID_LEAD_STATUSES:
            return status_info.legacy_status
        else:
            log.warning(
                "Invalid legacy_status in DB, falling back to derivation",
                status_id=status_info.id,
                invalid_legacy_status=status_info.legacy_status,
            )

    # Priority 2: Derive from attributes
    stage_id = status_info.stage_id
    outcome_type = status_info.outcome_type
    is_final = status_info.is_final_status

    # Rule 1: Final negative statuses → rejected/unqualified
    if is_final and outcome_type == "negative":
        # stg07 = Không theo học (đã từng là student, sau đó drop)
        if stage_id == "stg07":
            return "unqualified"
        # Các stage khác với negative final = rejected ngay từ đầu
        return "rejected"

    # Rule 2: Đã nhập học thành công (stage 6)
    if stage_id == "stg06":
        return "converted"

    # Rule 3: Chưa tư vấn (stage 1)
    if stage_id == "stg01":
        return "new"

    # Rule 4: Đang tư vấn (stage 2)
    if stage_id == "stg02":
        if outcome_type == "positive":
            return "qualified"
        return "contacted"

    # Rule 5: Đã nộp hồ sơ trở đi (stage 3-5) = qualified
    if stage_id in ("stg03", "stg04", "stg05"):
        return "qualified"

    # Rule 6: Stage 7 nhưng không phải negative final (edge case)
    if stage_id == "stg07":
        return "unqualified"

    # Fallback for any unknown stages
    log.warning(
        "Unknown stage_id, falling back to default status",
        status_id=status_info.id,
        stage_id=stage_id,
    )
    return DEFAULT_LEAD_STATUS


# =============================================================================
# MODEL HELPERS
# =============================================================================

def create_status_info_from_model(
    consultation_status: "ConsultationStatus"
) -> ConsultationStatusInfo:
    """
    Create ConsultationStatusInfo from SQLAlchemy model.

    Args:
        consultation_status: ConsultationStatus model instance

    Returns:
        ConsultationStatusInfo dataclass
    """
    return ConsultationStatusInfo(
        id=consultation_status.id,
        stage_id=consultation_status.stage_id,
        outcome_type=consultation_status.outcome_type.value if hasattr(
            consultation_status.outcome_type, 'value'
        ) else str(consultation_status.outcome_type),
        is_final_status=consultation_status.is_final_status,
        legacy_status=consultation_status.legacy_status,
    )


def sync_lead_status_from_consultation(
    lead,
    consultation_status: Optional["ConsultationStatus"]
) -> str:
    """
    Synchronize lead.status from consultation_status.

    This is the main entry point for services to sync lead status.
    It handles both the derivation and the assignment.

    Args:
        lead: Lead model instance (will be modified in place)
        consultation_status: ConsultationStatus model instance or None

    Returns:
        The new status value that was set

    Example:
        >>> sync_lead_status_from_consultation(lead, new_consultation_status)
        "qualified"
        >>> lead.status
        "qualified"
    """
    if consultation_status is None:
        new_status = DEFAULT_LEAD_STATUS
    else:
        status_info = create_status_info_from_model(consultation_status)
        new_status = derive_lead_status(status_info)

    old_status = lead.status
    lead.status = new_status

    if old_status != new_status:
        log.info(
            "Lead status synchronized from consultation_status",
            lead_id=lead.id,
            old_status=old_status,
            new_status=new_status,
            consultation_status_id=consultation_status.id if consultation_status else None,
        )

    return new_status


# =============================================================================
# DATABASE HELPERS
# =============================================================================

async def get_lead_status_from_db(
    db: "AsyncSession",
    consultation_status_id: Optional[str]
) -> str:
    """
    Fetch consultation_status from DB and derive lead.status.

    Use this when you only have the consultation_status_id and need
    to look up the full status object.

    Args:
        db: AsyncSession database session
        consultation_status_id: The consultation status ID to look up

    Returns:
        Derived lead status string
    """
    if consultation_status_id is None:
        return DEFAULT_LEAD_STATUS

    from sqlalchemy import select
    from ..models import ConsultationStatus

    result = await db.execute(
        select(ConsultationStatus).where(ConsultationStatus.id == consultation_status_id)
    )
    consultation_status = result.scalar_one_or_none()

    if consultation_status is None:
        log.warning(
            "ConsultationStatus not found, using default status",
            consultation_status_id=consultation_status_id,
        )
        return DEFAULT_LEAD_STATUS

    status_info = create_status_info_from_model(consultation_status)
    return derive_lead_status(status_info)


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def is_valid_lead_status(status: str) -> bool:
    """
    Check if a status value is valid for lead.status.

    Args:
        status: Status string to validate

    Returns:
        True if valid, False otherwise
    """
    return status in VALID_LEAD_STATUSES


def validate_legacy_status(legacy_status: Optional[str]) -> Optional[str]:
    """
    Validate and normalize legacy_status value.

    Args:
        legacy_status: The legacy_status to validate

    Returns:
        The validated status or None if invalid

    Raises:
        ValueError: If legacy_status is not a valid value
    """
    if legacy_status is None:
        return None

    legacy_status = legacy_status.lower().strip()

    # System statuses should not be set as legacy_status
    system_statuses = {"unassigned_pending", "reassigned_pending"}
    if legacy_status in system_statuses:
        raise ValueError(
            f"Cannot use system status '{legacy_status}' as legacy_status. "
            f"Valid values: new, assigned, contacted, qualified, unqualified, converted, rejected"
        )

    if legacy_status not in VALID_LEAD_STATUSES:
        raise ValueError(
            f"Invalid legacy_status: '{legacy_status}'. "
            f"Valid values: new, assigned, contacted, qualified, unqualified, converted, rejected"
        )

    return legacy_status
