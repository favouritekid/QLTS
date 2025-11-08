# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base
from .config import LeadScoringConfig, OfficerAssignmentConfig, SkillRequirementRule
from .lead import Application, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory
from .notification import Notification
from .notification_preference import NotificationPreference
from .organization import Major, OrganizationUnit
from .pipeline import ConsultationStatus, PipelineStage
from .user import User
from .user_activity import UserActivityLog
from .user_session import UserSession

# Import tất cả các model để chúng được đăng ký với Base
# và để chúng có thể được truy cập qua package 'models' (vd: models.User)
