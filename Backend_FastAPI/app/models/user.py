# app/models/user.py
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

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
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    # NEW: Pointer to current assignment (source of truth)
    current_assignment_id = Column(
        Integer,
        ForeignKey("user_unit_assignment.id", ondelete="SET NULL"),
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

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    # LƯU Ý QUAN TRỌNG:
    # Các phương thức set_password, check_password, get_reset_password_token
    # đã được gỡ bỏ khỏi model.
    # Logic này sẽ được chuyển đến lớp Services (ví dụ: user_service)
    # để tuân thủ nguyên tắc Single Responsibility: Model chỉ định nghĩa dữ liệu.
