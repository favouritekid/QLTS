# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base

# Import tất cả các model để chúng được đăng ký với Base
# và để chúng có thể được truy cập qua package 'models' (vd: models.User)

from .config import OfficerAssignmentConfig, LeadScoringConfig, SkillRequirementRule
from .lead import Lead, Consultation, Application, CRMInteraction, AssignmentLog
from .lead_history import LeadStatusHistory
from .organization import OrganizationUnit, Major
from .pipeline import PipelineStage, ConsultationStatus
from .user import User
from .user_session import UserSession