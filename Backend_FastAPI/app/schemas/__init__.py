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
    MajorAcademicInfo,
    MajorAcademicInfoBase,
    MajorAcademicInfoCreate,
    MajorAcademicInfoUpdate,
    OrganizationUnit,
    OrganizationUnitCreate,
    OrganizationUnitShallow,
    OrganizationUnitType,
    OrganizationUnitUpdate,
    # Tree with aggregation schemas
    MajorWithStats,
    UnitAggregatedStats,
    OrganizationTreeNodeWithAggregation,
)

# --- Từ permissions.py ---
from .permissions import (
    Policy,
    PolicyCreate,
    PolicyRule,
    RoleAssignment,
    GroupingPolicyCreate,
    RoleInfo,
    RolesListResponse,
    TemplateInfo,
    TemplatesListResponse,
    PolicyBatchRequest,
    PolicyBatchResult,
    PolicyValidationRequest,
    PolicyValidationResult,
    TemplateApplicationRequest,
    PolicyStatistics,
    # Advanced permission tools schemas
    WhoCanAccessResponse,
    PermissionSimulateRequest,
    PermissionSimulateResponse,
    FeatureStatus,
    RoleFeaturesResponse,
    ToggleFeatureRequest,
    PolicySuggestionsResponse,
    PermissionExplainResponse,
)

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
    SyncUsersRequest,
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

# --- Từ user_activity.py ---
from .user_activity import (
    UserActivityLog,
    UserActivityLogBase,
    UserActivityLogCreate,
    UserActivityLogWithDetails,
    ActivityLogsPage,
    UserStatistics,
)

# --- Từ notification.py ---
from .notification import (
    Notification,
    NotificationBase,
    NotificationCreate,
    NotificationsPage,
    MarkAsReadRequest,
)

# --- Từ notification_preference.py ---
from .notification_preference import (
    NotificationPreference,
    NotificationPreferenceBase,
    NotificationPreferenceCreate,
    NotificationPreferenceUpdate,
    NotificationTypePreference,
)