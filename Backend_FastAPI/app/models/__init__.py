# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base

# Config models
from .config import (
    ConfigDegreeLevel,
    ConfigDocumentType,
    ConfigOfferingType,
    KpiConfig,
    KpiMonthlySnapshot,
    KpiTarget,
    LeadScoringConfig,
    OfficerAssignmentConfig,
    SkillRequirementRule,
)

# Lead management models
from .lead import Application, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory

# Admission models (NEW: Replacement for Application)
from .admission import AdmissionProfile
from .student import Student, StudentDocument

# Notification models
from .notification import Notification, NotificationAction, NotificationRule, NotificationTemplate
from .notification_preference import NotificationPreference

# Organization models (includes temporal models)
# OLD: from .organization import Major  # REMOVED after 3-tier migration
from .organization import OfferingDistributionConfig, OrganizationUnit

# Organization (NEW 3-tier)
from .major_program import MajorProgram  # Level 1
from .program_offering import ProgramOffering  # Level 2
from .offering_academic_info import OfferingAcademicInfo  # Level 3

# Tuition Discount Policy
from .tuition_discount_policy import TuitionDiscountPolicy, DiscountTypeEnum

# OLD: Legacy models (REMOVED after migration k6l7m8n9o0p1)
# from .major_academic_info import MajorAcademicInfo  # Table dropped, references Major model

# Pipeline models
from .pipeline import AllowedTransition, ConsultationStatus, OutcomeTypeEnum, PipelineStage

# User models (includes temporal models)
from .user import User
from .user_unit_assignment import UserUnitAssignment  # NEW: Assignment history
from .user_activity import UserActivityLog
from .user_session import UserSession
from .login_history import LoginHistory  # Security: Login audit trail

# Import tất cả các model để chúng được đăng ký với Base
# và để chúng có thể được truy cập qua package 'models' (vd: models.User)

__all__ = [
    "Base",
    # Config
    "ConfigDegreeLevel",
    "ConfigDocumentType",
    "ConfigOfferingType",
    "KpiConfig",
    "KpiMonthlySnapshot",
    "KpiTarget",
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
    # Admission (NEW)
    "AdmissionProfile",
    "Student",
    "StudentDocument",
    # Notification
    "Notification",
    "NotificationRule",
    "NotificationTemplate",
    "NotificationPreference",
    # Organization (Legacy)
    # "Major",  # REMOVED after 3-tier migration k6l7m8n9o0p1
    # "MajorAcademicInfo",  # REMOVED after 3-tier migration k6l7m8n9o0p1
    "OrganizationUnit",
    "OfferingDistributionConfig",
    # Organization (NEW 3-tier)
    "MajorProgram",
    "ProgramOffering",
    "OfferingAcademicInfo",
    # Tuition Discount Policy
    "TuitionDiscountPolicy",
    "DiscountTypeEnum",
    # Pipeline
    "AllowedTransition",
    "ConsultationStatus",
    "OutcomeTypeEnum",
    "PipelineStage",
    # User
    "User",
    "UserUnitAssignment",
    "UserActivityLog",
    "UserSession",
    "LoginHistory",
]
