# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base

# Config models
from .config import (
    ConfigDegreeLevel,
    ConfigDocumentType,
    ConfigOfferingType,
    # ConfigSubjectGroup removed — table dropped, model removed from Base metadata
    ConfigSystemCategory,
    HolidayCalendar,  # A1: KPI Planning
    KpiConfig,
    KpiMonthlySnapshot,
    KpiPlan,  # A1: KPI Planning
    KpiPlanMonth,  # A1: KPI Planning
    KpiTarget,
    LeadScoringConfig,
    OfficerAssignmentConfig,
    SkillRequirementRule,
)

# Collaborator (CTV) models
from .collaborator import Collaborator, LeadClaim

# Commission models
from .commission import CommissionPolicy, CommissionRecord

# Lead management models
from .lead import AssignmentDecisionLog, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory
from .lead_phone import LeadPhoneIdentity
from .lead_reopen_request import LeadReopenRequest

# Admission models (NEW: Replacement for Application)
from .admission import AdmissionProfile, AdmissionConfirmationToken
# phase1_10 (#184 Wave 2 PR-2A) — status transition audit trail.
from .admission_profile_status_history import AdmissionProfileStatusHistory
# phase3_01 (#184 Wave 3 PR-3A) — multi-NV choice + per-choice score.
from .admission_profile_choice import (
    AdmissionProfileChoice,
    ProfileChoiceScore,
    CHOICE_DECISIONS,
)
# phase1_07b table promoted to ORM model in Phase 3 PR-3D-B BE-2 for admin queue.
from .admission_backfill_exception import AdmissionBackfillException
from .admission_survey_feedback import AdmissionSurveyFeedback
from .student import Student, StudentDocument

# Admission Config Domain (Phase 1: Relational admission system)
from .admission_config import (
    Subject,
    SubjectGroup,
    SubjectGroupSubject,
    AdmissionMethod,
    AdmissionCriteria,
    CriteriaSubjectGroup,
    OfferingAdmissionConfig,
    DocumentGroup,
    DocumentGroupItem,
    ProfileSubjectScore,
    ProfileDocument,
    DocumentAuditLog,  # Audit trail for document operations
    AdmissionPath,  # Phase 1: Admission Configuration Console
    PathSubjectGroupConfig,  # Phase 2 v8.2 PR-2D
    PathSubjectGroupItem,  # Phase 2 v8.2 PR-2D
)

# Notification models
from .notification import Notification, NotificationAction, NotificationRule, NotificationTemplate
from .notification_preference import NotificationPreference
from .notification_delivery import NotificationDelivery
from .notification_consent import NotificationConsent
from .notification_consent_history import NotificationConsentHistory
from .notification_outbox import NotificationOutbox
from .notification_quota import NotificationQuota

# phase1_13 (#184 Wave 1 PR-1D) — runtime config key/value store.
# Closes B4 P0 blocker. Admin-only mutation via SystemConfigService.
from .system_config import SystemConfig
from .zalo_token_store import ZaloTokenStore
from .staff_zalo_bot_link import StaffZaloBotLink

# Organization models (includes temporal models)
# OLD: from .organization import Major  # REMOVED after 3-tier migration
from .organization import OfferingDistributionConfig, OrganizationUnit

# Organization (NEW 3-tier)
from .major_program import MajorProgram  # Level 1
from .program_offering import ProgramOffering  # Level 2
from .offering_academic_info import OfferingAcademicInfo  # Level 3
from .offering_admission_round import OfferingAdmissionRound  # Phase 2 v8.2 PR-2A v2 — year-level
from .offering_semester_tuition import OfferingSemesterTuition  # PR 1 (ADR-002)

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
from .trusted_device import TrustedDevice  # Security: Trusted devices for login
from .entity_audit_log import EntityAuditLog  # Generic audit trail for any entity

# Administrative Geography (Temporal Versioning)
from .administrative_node import AdministrativeNode, AdministrativeLevel

# Q9 #07 PR1 — Priority bonus configs + VN locality dictionaries (phase1_08b)
from .priority_config import PriorityAreaConfig, PriorityObjectConfig
from .vn_locality import VnCommuneAreaMap
# Q9 #07 PR5 v1.3 (phase1_09) — VN school 3-table family + SCD
# Replaces VnHighSchool (PR1 single-table placeholder, dropped phase1_09)
from .vn_school import VnSchool, VnSchoolNameHistory, VnSchoolKvAssignment
# Q9 #07 Phase E Foundation (q9_07_e0a) — priority bonus intervention audit log.
from .priority_audit import PriorityAuditLog

# Finance Module (Phase 0+1: Foundation)
from .finance import (
    # Enums
    FeeTypeEnum,
    FeeStatusEnum,
    InvoiceStatusEnum,
    PaymentIntentStatusEnum,
    GatewayStatusEnum,
    PaymentStatusEnum,
    TransactionTypeEnum,
    RefundStatusEnum,
    OverpaymentStatusEnum,
    ResolutionTypeEnum,
    # Models
    InstallmentPlan,
    PaymentMethod,
    AccountingPeriod,
    Fee,
    FeeAppliedDiscount,
    Invoice,
    PaymentIntent,
    Payment,
    PaymentTransaction,
    RefundRequest,
    OverpaymentRecord,
)

# SMS Marketing Module (Phase 1: schema) — 12 model. SMS_MARKETING_MODULE_DESIGN.md §4.
from .sms import (
    SmsContactGroup,
    SmsContact,
    SmsContactGroupMember,
    SmsContactImportBatch,
    SmsPrefixCarrierRule,
    SmsCampaign,
    SmsCampaignGroup,
    SmsCampaignRecipient,
    SmsCampaignExportBatch,
    SmsClickEvent,
    SmsOptOut,
    SmsMarketingConsentEvent,
)

# Import tất cả các model để chúng được đăng ký với Base
# và để chúng có thể được truy cập qua package 'models' (vd: models.User)

__all__ = [
    "Base",
    # Config
    "ConfigDegreeLevel",
    "ConfigDocumentType",
    "ConfigOfferingType",
    # "ConfigSubjectGroup",  # REMOVED — table dropped, see config.py
    "ConfigSystemCategory",
    "HolidayCalendar",  # A1: KPI Planning
    "KpiConfig",
    "KpiMonthlySnapshot",
    "KpiPlan",  # A1: KPI Planning
    "KpiPlanMonth",  # A1: KPI Planning
    "KpiTarget",
    "LeadScoringConfig",
    "OfficerAssignmentConfig",
    "SkillRequirementRule",
    # Collaborator (CTV)
    "Collaborator",
    "LeadClaim",
    # Commission
    "CommissionPolicy",
    "CommissionRecord",
    # Lead
    "AssignmentDecisionLog",  # A1: KPI Planning instrumentation
    "AssignmentLog",
    "Consultation",
    "CRMInteraction",
    "Lead",
    "LeadPhoneIdentity",
    "LeadReopenRequest",
    "LeadStatusHistory",
    # Admission (NEW)
    "AdmissionProfile",
    "AdmissionConfirmationToken",
    "AdmissionSurveyFeedback",
    "Student",
    "StudentDocument",
    "ProfileSubjectScore",
    "ProfileDocument",
    "DocumentAuditLog",  # Audit trail for document operations
    "AdmissionPath",  # Phase 1: Admission Configuration Console
    # Notification
    "Notification",
    "NotificationAction",
    "NotificationRule",
    "NotificationTemplate",
    "NotificationPreference",
    "NotificationDelivery",
    "NotificationConsent",
    "NotificationConsentHistory",
    "NotificationOutbox",
    "NotificationQuota",
    "ZaloTokenStore",
    "StaffZaloBotLink",
    # Organization (Legacy)
    # "Major",  # REMOVED after 3-tier migration k6l7m8n9o0p1
    # "MajorAcademicInfo",  # REMOVED after 3-tier migration k6l7m8n9o0p1
    "OrganizationUnit",
    "OfferingDistributionConfig",
    # Organization (NEW 3-tier)
    "MajorProgram",
    "ProgramOffering",
    "OfferingAcademicInfo",
    "OfferingAdmissionRound",
    "OfferingSemesterTuition",
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
    "TrustedDevice",
    "EntityAuditLog",
    # Administrative Geography
    "AdministrativeNode",
    "AdministrativeLevel",
    # Q9 #07 PR1 — Priority bonus configs + VN locality dictionaries
    "PriorityAreaConfig",
    "PriorityObjectConfig",
    "VnCommuneAreaMap",
    # VnHighSchool removed in phase1_09 — see VnSchool family below
    "VnSchool",
    "VnSchoolNameHistory",
    "VnSchoolKvAssignment",
    # Q9 #07 Phase E Foundation
    "PriorityAuditLog",
    # Finance Module (Phase 0+1: Foundation)
    # Enums
    "FeeTypeEnum",
    "FeeStatusEnum",
    "InvoiceStatusEnum",
    "PaymentIntentStatusEnum",
    "GatewayStatusEnum",
    "PaymentStatusEnum",
    "TransactionTypeEnum",
    "RefundStatusEnum",
    "OverpaymentStatusEnum",
    "ResolutionTypeEnum",
    # Models
    "InstallmentPlan",
    "PaymentMethod",
    "AccountingPeriod",
    "Fee",
    "FeeAppliedDiscount",
    "Invoice",
    "PaymentIntent",
    "Payment",
    "PaymentTransaction",
    "RefundRequest",
    "OverpaymentRecord",
    # SMS Marketing Module (Phase 1: schema)
    "SmsContactGroup",
    "SmsContact",
    "SmsContactGroupMember",
    "SmsContactImportBatch",
    "SmsPrefixCarrierRule",
    "SmsCampaign",
    "SmsCampaignGroup",
    "SmsCampaignRecipient",
    "SmsCampaignExportBatch",
    "SmsClickEvent",
    "SmsOptOut",
    "SmsMarketingConsentEvent",
]
