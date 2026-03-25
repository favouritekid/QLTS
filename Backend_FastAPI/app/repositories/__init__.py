# app/repositories/__init__.py
"""
✅ PHASE 2 - WEEK 1: Repository Layer

Repository pattern implementation for clean data access layer.

Export all repositories for easy import:
    from app.repositories import LeadRepository, UserRepository
"""

from app.repositories.base import BaseRepository
from app.repositories.activity_repository import ActivityRepository
from app.repositories.admission_repository import AdmissionRepository
from app.repositories.config_repository import (
    AssignmentConfigRepository,
    DegreeLevelRepository,
    DocumentTypeRepository,
    OfferingTypeRepository,
    SkillRuleRepository,
)
from app.repositories.insights_repository import InsightsRepository
from app.repositories.kpi_planning_repository import KpiPlanningRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.notification_rule_repository import NotificationRuleRepository
from app.repositories.notification_template_repository import NotificationTemplateRepository
from app.repositories.notification_preference_repository import NotificationPreferenceRepository
from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
from app.repositories.notification_consent_repository import NotificationConsentRepository
from app.repositories.officer_repository import OfficerRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.tuition_discount_repository import TuitionDiscountRepository
from app.repositories.user_repository import UserRepository
from app.repositories.login_history_repository import LoginHistoryRepository
from app.repositories.trusted_device_repository import TrustedDeviceRepository

__all__ = [
    "BaseRepository",
    "ActivityRepository",
    "AdmissionRepository",
    "AssignmentConfigRepository",
    "DegreeLevelRepository",
    "DocumentTypeRepository",
    "InsightsRepository",
    "KpiPlanningRepository",
    "KpiRepository",
    "LeadRepository",
    "NotificationRepository",
    "OfferingTypeRepository",
    "OfficerRepository",
    "OrganizationRepository",
    "PipelineRepository",
    "SessionRepository",
    "SkillRuleRepository",
    "TuitionDiscountRepository",
    "UserRepository",
    "LoginHistoryRepository",
    "TrustedDeviceRepository",
]
