# flake8: noqa: F401
# app/schemas/__init__.py

# Giúp import dễ dàng hơn bằng cách "export" các schema quan trọng ra ngoài

# Schemas từ config.py
from .config import AssignmentConfig, ScoringConfig, SkillRule, SkillRuleCreate

# Schemas từ lead.py
from .lead import (
    AssignLead,
    Consultation,
    ConsultationCreate,
    Lead,
    LeadAction,
    LeadImportError,      # <-- Đảm bảo cái này cũng được export
    LeadImportResult,
    LeadCreate,
    LeadInsights,
    LeadsPage,
    LeadUpdate,
    TimelineItem,
    AssignmentLog,
    BulkAssignLeadsSchema # <-- THÊM DÒNG NÀY
)

# Schemas từ organization.py
from .organization import (
    Major,
    MajorCreate,
    MajorUpdate,
    OrganizationUnit,
    OrganizationUnitCreate,
    OrganizationUnitUpdate,
    OrganizationUnitShallow # Đảm bảo export cả Shallow
)

# Schemas từ pipeline.py
from .pipeline import (
    ConsultationStatus,
    ConsultationStatusCreate,
    ConsultationStatusUpdate,
    FullPipeline,
    PipelineStage,
    PipelineStageCreate,
    PipelineStageUpdate,
)

# Schemas từ user.py
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
    UserCreate,
    UsersPage,
    UserUpdate,
)

# Schemas từ permissions.py (Nếu có, như trong file testing.md)
from .permissions import PolicyCreate, RoleAssignment