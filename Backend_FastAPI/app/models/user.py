# app/models/user.py
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import TSVECTOR

from .base import Base


class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), index=True, unique=True, nullable=False)
    email = Column(String(120), index=True, unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(120), nullable=True)
    avatar_url = Column(String(256), nullable=True)
    phone_number = Column(String(20), nullable=True)
    address = Column(String(256), nullable=True)
    company = Column(String(120), nullable=True)

    # ===== CACHE FIELDS (for performance) =====
    # These are denormalized from UserUnitAssignment for fast access
    role = Column(String(50), nullable=False, default="user")
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True, index=True)  # ✅ FIX: Added index

    # NEW: Pointer to current assignment (source of truth)
    # ✅ FIX: use_alter=True to resolve circular dependency with user_unit_assignment
    # This defers FK creation to ALTER TABLE (after both tables exist)
    # ✅ TEST FIX: Explicit constraint name required for proper DROP in tests
    current_assignment_id = Column(
        Integer,
        ForeignKey(
            "user_unit_assignment.id",
            name="fk_user_current_assignment",  # ✅ Explicit name for test compatibility
            ondelete="SET NULL",
            use_alter=True  # ✅ Defer constraint creation to break circular dependency
        ),
        nullable=True,
        index=True,
        comment="FK to current active UserUnitAssignment (cache sync point)"
    )

    status = Column(String(50), nullable=False, server_default="active")
    active_jti = Column(String(36), nullable=True, index=True)

    # Lead assignment fields
    skills = Column(JSON, nullable=True)
    max_capacity = Column(Integer, default=100)
    availability_status = Column(String(50), default="available")
    total_lead_score = Column(Integer, default=0, nullable=False)
    last_assigned_at = Column(DateTime(timezone=True), nullable=True)

    # ===== SEARCH OPTIMIZATION (Security Fix: Search DoS) =====
    # Full-text search vector for fast searching without leading wildcard
    # This column is populated by database trigger (see migration p1q2r3s4t5u6)
    # Performance: 2ms (index scan) vs 500ms (full table scan with ILIKE '%term%')
    search_vector = Column(
        TSVECTOR,
        nullable=True,
        comment="Full-text search vector for username, email, full_name"
    )

    # ===== RELATIONSHIPS =====

    # Organization
    unit = relationship("OrganizationUnit", back_populates="users")

    # NEW: Assignment history (source of truth)
    unit_assignments = relationship(
        "UserUnitAssignment",
        back_populates="user",
        foreign_keys="UserUnitAssignment.user_id",
        cascade="all, delete-orphan"
    )

    # NEW: Current assignment (convenience)
    current_assignment = relationship(
        "UserUnitAssignment",
        foreign_keys=[current_assignment_id],
        post_update=True  # Prevent circular FK issues
    )

    # Lead management
    leads_assigned = relationship(
        "Lead",
        back_populates="assigned_officer",
        foreign_keys="Lead.assigned_officer_id",
    )
    consultations_handled = relationship(
        "Consultation", back_populates="officer", foreign_keys="Consultation.officer_id"
    )
    applications_handled = relationship(
        "Application", back_populates="officer", foreign_keys="Application.officer_id"
    )
    assignment_logs_involved = relationship(
        "AssignmentLog",
        back_populates="officer",
        foreign_keys="AssignmentLog.officer_id",
    )

    # Session management
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )

    # ✅ TASK 6.1: Added back_populates relationships (explicit bidirectional)
    # These were previously auto-created by backref in child models

    # Notifications
    notifications = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # Notification preferences (one-to-one)
    notification_preference = relationship(
        "NotificationPreference",
        back_populates="user",
        uselist=False,  # One-to-one relationship
        cascade="all, delete-orphan"  # ✅ FIX: Delete preference when user is deleted
    )

    # Activity logs (as actor)
    activities_performed = relationship(
        "UserActivityLog",
        back_populates="actor",
        foreign_keys="UserActivityLog.actor_id"
    )

    # Activity logs (as target)
    activities_received = relationship(
        "UserActivityLog",
        back_populates="target_user",
        foreign_keys="UserActivityLog.target_user_id"
    )

    # Academic info audit trails
    created_academic_infos = relationship(
        "OfferingAcademicInfo",
        back_populates="created_by",
        foreign_keys="OfferingAcademicInfo.created_by_user_id"
    )
    updated_academic_infos = relationship(
        "OfferingAcademicInfo",
        back_populates="updated_by",
        foreign_keys="OfferingAcademicInfo.updated_by_user_id"
    )

    # Login history for security audit
    login_history = relationship(
        "LoginHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(LoginHistory.login_at)"
    )

    # Trusted devices for login security
    trusted_devices = relationship(
        "TrustedDevice",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(TrustedDevice.last_used_at)"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    # LƯU Ý QUAN TRỌNG:
    # Các phương thức set_password, check_password, get_reset_password_token
    # đã được gỡ bỏ khỏi model.
    # Logic này sẽ được chuyển đến lớp Services (ví dụ: user_service)
    # để tuân thủ nguyên tắc Single Responsibility: Model chỉ định nghĩa dữ liệu.
