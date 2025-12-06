# app/models/user_unit_assignment.py
"""
User Unit Assignment Model - Temporal History System

This model implements a temporal/versioned approach to tracking user assignments
to organizational units with specific roles over time.

Key Features:
- Maintains complete history of all assignments (never deleted)
- Only ONE record per user can have is_active=True at any time
- Supports querying historical assignments by date range
- Tracks who made the assignment and when

Use Cases:
- "Who was the manager of Unit X in 2024?"
- "Show all role changes for User Y"
- "When did User Z become an officer?"
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Index, text
from sqlalchemy.orm import relationship

from .base import Base


class UserUnitAssignment(Base):
    """
    Temporal record of user assignments to organizational units with roles.

    This is the SOURCE OF TRUTH for user role and unit assignments.
    The `user.role` and `user.unit_id` fields are just caches for performance.

    Workflow:
    1. Admin assigns user to unit with role → INSERT new record (is_active=True)
    2. Assignment ends → UPDATE old record (set end_date, is_active=False)
    3. User reassigned → INSERT new record + UPDATE old record

    Important Constraints:
    - Only one active assignment per user (enforced in service layer)
    - end_date must be NULL or > start_date
    - start_date cannot be in the future
    """

    __tablename__ = "user_unit_assignment"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    # Note: No explicit names needed - use_alter=True on user.current_assignment_id
    # breaks the circular dependency automatically
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # For fast user lookups
    )
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="RESTRICT"),
        nullable=False,
        index=True  # For fast unit lookups
    )
    assigned_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,  # NULL = system/migration/initial assignment
        index=True  # ✅ FIX: Added index
    )

    # Assignment Details
    role = Column(
        String(50),
        nullable=False,
        index=True  # For filtering by role
    )

    # Temporal Fields
    start_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP")  # ✅ FIXED: Use text() wrapper
    )
    end_date = Column(
        DateTime(timezone=True),
        nullable=True  # NULL = still active
    )

    # Status
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),  # ✅ FIXED: Use text() wrapper
        index=True  # Critical for fast "current assignment" queries
    )

    # Audit Fields
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP")  # ✅ FIXED: Use text() wrapper
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP")  # ✅ FIXED: Use text() wrapper
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="unit_assignments",
        foreign_keys=[user_id]
    )
    unit = relationship(
        "OrganizationUnit",
        back_populates="user_assignments"
    )
    assigned_by = relationship(
        "User",
        foreign_keys=[assigned_by_user_id]
    )

    # Composite Indexes for Common Queries
    __table_args__ = (
        # Fast lookup: "Get current assignment for user"
        Index('ix_user_assignment_active', 'user_id', 'is_active'),

        # Fast lookup: "Get all active users in unit"
        Index('ix_unit_assignment_active', 'unit_id', 'is_active'),

        # Fast lookup: "Get assignments in date range"
        Index('ix_assignment_dates', 'start_date', 'end_date'),

        # Fast lookup: "Get all managers/officers in unit"
        Index('ix_unit_role_active', 'unit_id', 'role', 'is_active'),
    )

    def __repr__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return (
            f"<UserUnitAssignment user_id={self.user_id} "
            f"unit_id={self.unit_id} role={self.role} {status}>"
        )

    @property
    def duration_days(self) -> int | None:
        """Calculate assignment duration in days."""
        if self.end_date:
            return (self.end_date - self.start_date).days
        return None

    @property
    def is_current(self) -> bool:
        """Check if this assignment is currently active."""
        return self.is_active and self.end_date is None
