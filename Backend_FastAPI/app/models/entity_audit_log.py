# app/models/entity_audit_log.py
"""
Generic Entity Audit Log Model.

Provides field-level change tracking for any entity in the system.
This complements specialized audit logs (LeadStatusHistory, DocumentAuditLog)
by offering a generic, queryable audit trail for all models.

Design Principles:
- Single table for all entities (polymorphic via entity_type)
- JSON storage for flexible old/new value tracking
- Indexed for common query patterns (entity lookup, user lookup, date range)
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import Base


class EntityAuditLog(Base):
    """
    Generic audit log for tracking field-level changes across all entities.

    Use Cases:
    - AdmissionProfile field changes (personal info, status transitions)
    - NotificationRule configuration updates
    - AdmissionPath/AllowedTransition rule changes
    - Any model requiring compliance audit trail

    Query Patterns:
    - "Show all changes to AdmissionProfile #123"
    - "Show all changes made by User #5 today"
    - "Show all 'status' field changes in last 7 days"
    """
    __tablename__ = "entity_audit_log"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Entity identification (polymorphic)
    entity_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Model/table name (e.g., 'AdmissionProfile', 'NotificationRule')"
    )
    entity_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Primary key of the affected record"
    )

    # Action type
    action = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Action type: created, updated, deleted, status_changed, etc."
    )

    # Actor (who made the change)
    actor_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who performed the action (NULL for system actions)"
    )

    # Change details
    field_name = Column(
        String(100),
        nullable=True,
        index=True,
        comment="Specific field changed (NULL for bulk/create/delete)"
    )
    old_value = Column(
        JSONB,
        nullable=True,
        comment="Previous value(s) - JSON for complex types"
    )
    new_value = Column(
        JSONB,
        nullable=True,
        comment="New value(s) - JSON for complex types"
    )

    # Bulk changes (for updates touching multiple fields)
    changes = Column(
        JSONB,
        nullable=True,
        comment="Full changeset: {field: {old: x, new: y}, ...}"
    )

    # Context
    reason = Column(
        Text,
        nullable=True,
        comment="Human-readable reason for the change"
    )
    source = Column(
        String(50),
        nullable=True,
        comment="Change source: api, admin_panel, system, migration, etc."
    )

    # Request metadata
    ip_address = Column(
        String(45),
        nullable=True,
        comment="Client IP address (IPv4 or IPv6)"
    )
    user_agent = Column(
        String(500),
        nullable=True,
        comment="Client user agent string"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When the change occurred"
    )

    # Relationships
    actor = relationship(
        "User",
        foreign_keys=[actor_user_id],
        lazy="selectin"
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        # Query: "All changes to entity X"
        Index('ix_entity_audit_entity_lookup', 'entity_type', 'entity_id', 'created_at'),
        # Query: "All changes by user X"
        Index('ix_entity_audit_user_date', 'actor_user_id', 'created_at'),
        # Query: "All changes to field X across entities"
        Index('ix_entity_audit_field_type', 'entity_type', 'field_name', 'created_at'),
        # Query: "Recent changes by action type"
        Index('ix_entity_audit_action_date', 'action', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<EntityAuditLog(id={self.id}, entity={self.entity_type}#{self.entity_id}, "
            f"action={self.action}, field={self.field_name})>"
        )
