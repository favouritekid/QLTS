# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base

# Config models
from .config import (
    ConfigDegreeLevel,
    ConfigOfferingType,
    LeadScoringConfig,
    OfficerAssignmentConfig,
    SkillRequirementRule,
)

# Lead management models
from .lead import Application, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory

# Notification models
from .notification import Notification
from .notification_preference import NotificationPreference

# Organization models (includes temporal models)
# OLD: from .organization import Major  # REMOVED after 3-tier migration
from .organization import OrganizationUnit

# NEW: 3-tier architecture models
from .major_program import MajorProgram  # Level 1
from .program_offering import ProgramOffering  # Level 2
from .offering_academic_info import OfferingAcademicInfo  # Level 3

# OLD: Legacy models (REMOVED after migration k6l7m8n9o0p1)
# from .major_academic_info import MajorAcademicInfo  # Table dropped, references Major model

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
    "ConfigDegreeLevel",
    "ConfigOfferingType",
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
    # Organization (Legacy)
    # "Major",  # REMOVED after 3-tier migration k6l7m8n9o0p1
    # "MajorAcademicInfo",  # REMOVED after 3-tier migration k6l7m8n9o0p1
    "OrganizationUnit",
    # Organization (NEW 3-tier)
    "MajorProgram",
    "ProgramOffering",
    "OfferingAcademicInfo",
    # Pipeline
    "ConsultationStatus",
    "PipelineStage",
    # User
    "User",
    "UserUnitAssignment",
    "UserActivityLog",
    "UserSession",
]
