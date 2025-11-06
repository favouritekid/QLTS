# app/schemas/__init__.py
# flake8: noqa: F401

# Giúp import dễ dàng hơn bằng cách "export" tất cả các schema
# ra cấp cao nhất của package 'schemas' (vd: schemas.UserCreate)

# --- Từ config.py ---
from .config import (
    AssignmentConfig,
    ScoringConfig,
    SkillRule,
    SkillRuleBase,
    SkillRuleCreate,
)

# --- Từ lead.py ---
from .lead import (
    AssignLead,
    AssignmentLog,
    BulkAssignLeadsSchema,
    Consultation,
    ConsultationBase,
    ConsultationCreate,
    Lead,
    LeadAction,
    LeadBase,
    LeadCreate,
    LeadImportError,
    LeadImportResult,
    LeadInsights,
    LeadsPage,
    LeadUpdate,
    TimelineItem,
)

# --- Từ organization.py ---
from .organization import (
    Major,
    MajorBase,
    MajorCreate,
    MajorUpdate,
    OrganizationUnit,
    OrganizationUnitCreate,
    OrganizationUnitShallow,
    OrganizationUnitUpdate,
)

# --- Từ permissions.py ---
from .permissions import Policy, PolicyCreate, RoleAssignment

# --- Từ pipeline.py ---
from .pipeline import (
    ConsultationStatus,
    ConsultationStatusBase,
    ConsultationStatusCreate,
    ConsultationStatusUpdate,
    FullPipeline,
    PipelineStage,
    PipelineStageBase,
    PipelineStageCreate,
    PipelineStageUpdate,
)

# --- Từ user.py ---
from .user import (
    AdminSetPasswordSchema,
    AdminUserCreate,
    BulkActionSchema,
    ChangePasswordSchema,
    ForgotPasswordSchema,
    LoginSchema,
    RefreshTokenRequest,
    ResetPasswordSchema,
    Token,
    TokenData,
    User,
    UserBase,
    UserCreate,
    UserInDB,
    UsersPage,
    UserUpdate,
)

# --- Từ user_session.py ---
from .user_session import (
    UserSessionBase,
    UserSessionCreate,
    UserSessionListResponse,
    UserSessionResponse,
    UserSessionUpdate,
    RevokeAllSessionsRequest 
)