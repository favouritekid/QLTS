# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base

# Config models
from .config import LeadScoringConfig, OfficerAssignmentConfig, SkillRequirementRule

# Lead management models
from .lead import Application, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory

# Notification models
from .notification import Notification
from .notification_preference import NotificationPreference

# Organization models (includes temporal models)
from .organization import Major, OrganizationUnit
from .major_academic_info import MajorAcademicInfo  # NEW: Year-versioned academic data

# Pipeline models
from .pipeline import ConsultationStatus, PipelineStage

# User models (includes temporal models)
from .user import User
from .user_unit_assignment import UserUnitAssignment  # NEW: Assignment history
from .user_activity import UserActivityLog
from .user_session import UserSession

# Import tất cả các model để chúng được đăng ký với Base
# và để chúng có thể được truy cập qua package 'models' (vd: models.User)

__all__ = [
    "Base",
    # Config
    "LeadScoringConfig",
    "OfficerAssignmentConfig",
    "SkillRequirementRule",
    # Lead
    "Application",
    "AssignmentLog",
    "Consultation",
    "CRMInteraction",
    "Lead",
    "LeadStatusHistory",
    # Notification
    "Notification",
    "NotificationPreference",
    # Organization
    "Major",
    "MajorAcademicInfo",  # NEW
    "OrganizationUnit",
    # Pipeline
    "ConsultationStatus",
    "PipelineStage",
    # User
    "User",
    "UserUnitAssignment",  # NEW
    "UserActivityLog",
    "UserSession",
]
