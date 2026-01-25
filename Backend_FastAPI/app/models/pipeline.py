# app/models/pipeline.py
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from .base import Base


class OutcomeTypeEnum(str, enum.Enum):
    """
    Outcome classification for consultation status (CRM standard).

    - positive: Lead is moving forward in pipeline (e.g., "Agreed", "Enrolled")
    - neutral: Lead is in progress, no clear outcome yet (e.g., "Contacted", "Waiting")
    - negative: Lead rejected or failed (e.g., "Refused", "Wrong number")
    """
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class StatusTypeEnum(str, enum.Enum):
    """
    Status type classification for FSM engine.
    
    - transition: Normal workflow status, follows FSM rules
    - activity: Activity tracking status, doesn't affect workflow
    - system: System-controlled status, not user-selectable
    """
    transition = "transition"
    activity = "activity"
    system = "system"


class SelectableModeEnum(str, enum.Enum):
    """
    Who can select this status.
    
    - user: Any authenticated user (officer+)
    - role: Only manager/admin roles
    - system: Only backend system (not UI selectable)
    """
    user = "user"
    role = "role"
    system = "system"


class TriggerTypeEnum(str, enum.Enum):
    """
    What triggers a transition in FSM.
    
    - user: UI action by any user
    - role: UI action by manager/admin
    - system: Backend system action
    - event: External event (webhook, cron, etc.)
    """
    user = "user"
    role = "role"
    system = "system"
    event = "event"


class PipelineStage(Base):
    """
    Pipeline Stage (Funnel Step) - Main steps in lead conversion journey.

    Examples: "New Lead", "Contacted", "Consultation Scheduled", "Enrolled", "Lost"

    CRM Standards (Salesforce/HubSpot):
    - Stages represent major milestones in the funnel
    - Each stage can have multiple statuses
    - Final stages (Won/Lost) are marked with is_final_stage=True
    """
    __tablename__ = "pipeline_stage"

    id = Column(String(50), primary_key=True, comment="Unique stage identifier")
    name = Column(String(255), nullable=False, comment="Display name")
    order = Column(Integer, nullable=False, unique=True, comment="Position in pipeline (0-based)")
    is_final_stage = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this is a final stage (Won/Lost/Closed)"
    )

    # Relationships
    leads = relationship("Lead", back_populates="pipeline_stage")
    statuses = relationship("ConsultationStatus", back_populates="stage", cascade="all, delete-orphan")


class ConsultationStatus(Base):
    """
    Consultation Status - FSM-based status for lead lifecycle.
    
    SYSTEM SPEC v2:
    - status_type: transition/activity/system
    - selectable_mode: user/role/system
    - phase: consultation/admission/fee/enrolled/universal
    
    Activity statuses (is_universal=true) bypass FSM and are always available.
    System statuses can only be set by backend, not UI.
    """
    __tablename__ = "consultation_status"

    id = Column(String(50), primary_key=True, comment="Unique status identifier")
    
    # NEW: Machine-readable code
    code = Column(
        String(50),
        nullable=True,
        unique=True,
        comment="Machine-readable code (e.g., NOT_CONTACTED, ENROLLED)"
    )
    
    name = Column(String(255), nullable=False, comment="Display name")
    color_code = Column(String(7), nullable=False, comment="Hex color code for UI")
    
    # MODIFIED: stage_id now nullable for universal statuses
    stage_id = Column(
        String(50),
        ForeignKey("pipeline_stage.id", ondelete="CASCADE"),
        nullable=True,  # Changed from False - universal statuses have NULL stage
        comment="Parent pipeline stage (NULL for universal statuses)"
    )
    
    outcome_type = Column(
        Enum(OutcomeTypeEnum, name="outcome_type_enum", create_type=False),
        nullable=False,
        default=OutcomeTypeEnum.neutral,
        server_default="neutral",
        comment="Outcome classification: positive/neutral/negative"
    )
    
    # RENAMED: is_final_status → is_final for consistency
    is_final = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this status marks end of lead lifecycle"
    )
    
    # NEW: Status type for FSM engine
    status_type = Column(
        Enum(StatusTypeEnum, name="status_type_enum", create_type=False),
        nullable=False,
        default=StatusTypeEnum.transition,
        server_default="transition",
        comment="Status type: transition/activity/system"
    )
    
    # RENAMED: selectable_by_user → selectable_mode (now enum)
    selectable_mode = Column(
        Enum(SelectableModeEnum, name="selectable_mode_enum", create_type=False),
        nullable=False,
        default=SelectableModeEnum.user,
        server_default="user",
        comment="Who can select: user/role/system"
    )
    
    # Universal status support
    is_universal = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True for activity statuses that bypass FSM"
    )
    
    updates_pipeline = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="False if only records activity, doesn't change pipeline"
    )
    
    # RENAMED: counts_for_kpi → counts_for_funnel
    counts_for_funnel = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="True if counted in funnel analytics"
    )

    # Phase-Based Workflow
    phase = Column(
        String(20),
        nullable=False,
        default="consultation",
        server_default="consultation",
        comment="Phase: consultation/admission/fee/enrolled/universal"
    )
    
    # NEW: Description
    description = Column(
        Text,
        nullable=True,
        comment="Optional description for status"
    )

    # NEW: Display order for sorting
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Sort order for displaying statuses (lower = first)"
    )

    # DEPRECATED: Keep for backward compatibility, will remove later
    legacy_status = Column(
        String(50),
        nullable=True,
        default=None,
        comment="DEPRECATED: Maps to lead.status for backward compatibility"
    )
    
    # DEPRECATED: Keeping old column name for migration
    is_final_status = Column(
        Boolean,
        nullable=True,  # Made nullable since we're migrating to is_final
        comment="DEPRECATED: Use is_final instead"
    )
    
    selectable_by_user = Column(
        String(20),
        nullable=True,  # Made nullable since we're migrating to selectable_mode
        comment="DEPRECATED: Use selectable_mode instead"
    )
    
    counts_for_kpi = Column(
        Boolean,
        nullable=True,  # Made nullable since we're migrating to counts_for_funnel
        comment="DEPRECATED: Use counts_for_funnel instead"
    )

    # Relationships
    stage = relationship("PipelineStage", back_populates="statuses")
    leads = relationship("Lead", back_populates="consultation_status")

    # Transitions (workflow rules)
    transitions_from = relationship(
        "AllowedTransition",
        foreign_keys="AllowedTransition.from_status_id",
        back_populates="from_status",
        cascade="all, delete-orphan"
    )
    transitions_to = relationship(
        "AllowedTransition",
        foreign_keys="AllowedTransition.to_status_id",
        back_populates="to_status",
        cascade="all, delete-orphan"
    )



class AllowedTransition(Base):
    """
    Allowed Status Transitions - Workflow rules for status changes.

    Defines which status transitions are valid (e.g., "New" -> "Contacted").
    Used to prevent invalid state changes and support workflow automation.

    CRM Standards (HubSpot):
    - Prevents users from skipping required steps
    - Enables workflow automation
    - Supports pipeline integrity
    """
    __tablename__ = "allowed_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_status_id = Column(
        String(50),
        ForeignKey("consultation_status.id", ondelete="CASCADE"),
        nullable=False,
        comment="Source status ID"
    )
    to_status_id = Column(
        String(50),
        ForeignKey("consultation_status.id", ondelete="CASCADE"),
        nullable=False,
        comment="Destination status ID"
    )

    # ✅ NEW: FSM Engine fields
    trigger_type = Column(
        Enum(TriggerTypeEnum, name="trigger_type_enum", create_type=False),
        nullable=False,
        default=TriggerTypeEnum.user,
        server_default="user",
        comment="Who/what triggers this transition: user/role/system/event"
    )

    required_phase = Column(
        String(20),
        nullable=True,
        comment="Target phase (must match to_status.phase). NULL for same-phase transitions."
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether this transition is currently enabled"
    )

    description = Column(
        Text,
        nullable=True,
        comment="Human-readable description of this transition"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    from_status = relationship(
        "ConsultationStatus",
        foreign_keys=[from_status_id],
        back_populates="transitions_from"
    )
    to_status = relationship(
        "ConsultationStatus",
        foreign_keys=[to_status_id],
        back_populates="transitions_to"
    )

    __table_args__ = (
        # Ensure unique transitions - constraint defined in migration
        {"comment": "Allowed status transitions for workflow validation"},
    )
