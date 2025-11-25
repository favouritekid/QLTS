# app/models/pipeline.py
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
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
    Consultation Status (Sub-status) - Detailed state within a stage.

    Examples: "First contact", "Rescheduled", "Not interested", "Enrolled"

    CRM Standards:
    - Each status belongs to one stage
    - Status has outcome_type: positive/neutral/negative
    - Final statuses (end of lifecycle) marked with is_final_status=True
    """
    __tablename__ = "consultation_status"

    id = Column(String(50), primary_key=True, comment="Unique status identifier")
    name = Column(String(255), nullable=False, comment="Display name")
    color_code = Column(String(7), nullable=False, comment="Hex color code for UI")
    stage_id = Column(
        String(50),
        ForeignKey("pipeline_stage.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent pipeline stage"
    )
    outcome_type = Column(
        Enum(OutcomeTypeEnum, name="outcome_type_enum", create_type=False),
        nullable=False,
        default=OutcomeTypeEnum.neutral,
        server_default="neutral",
        comment="Outcome classification: positive/neutral/negative"
    )
    is_final_status = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this status marks end of lead lifecycle"
    )
    # Legacy status mapping for backward compatibility with lead.status field
    # Valid values: "new", "assigned", "contacted", "qualified", "unqualified", "converted", "rejected"
    legacy_status = Column(
        String(50),
        nullable=True,
        default=None,
        comment="Maps to lead.status for backward compatibility (auto-derived if NULL)"
    )

    # Universal status support (Phase 1 - Option B architecture)
    is_universal = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True nếu status có thể dùng ở mọi pipeline stage (VD: Không nghe máy, Thuê bao)"
    )
    updates_pipeline = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="False nếu chỉ ghi nhận activity, không thay đổi pipeline progression"
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
