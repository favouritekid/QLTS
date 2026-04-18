# app/schemas/__init__.py
# flake8: noqa: F401

# Giúp import dễ dàng hơn bằng cách "export" tất cả các schema
# ra cấp cao nhất của package 'schemas' (vd: schemas.UserCreate)

# =============================================================================
# IMPORT ORDER: Follow dependency graph to prevent circular imports
# 1. config (base, no dependencies)
# 2. organization (depends on: config)
# 3. pipeline (depends on: config, organization)
# 4. lead (depends on: organization, pipeline)
# 5. admission (depends on: lead, organization)
# =============================================================================

# --- 1. Từ config.py (Base layer) ---
from .config import (
    AssignmentConfig,
    ScoringConfig,
    SkillRule,
    SkillRuleBase,
    SkillRuleCreate,
    # System Category
    SystemCategory,
    SystemCategoryBase,
    SystemCategoryCreate,
    SystemCategoryUpdate,
)

# --- 2. Từ organization.py (Depends on: config) ---
from .organization import (
    # Legacy schemas (for backward compatibility / aliases)
    Major,
    MajorBase,
    MajorCreate,
    MajorUpdate,
    MajorAcademicInfo,
    MajorAcademicInfoBase,
    MajorAcademicInfoCreate,
    MajorAcademicInfoUpdate,
    # New 3-tier schemas
    MajorProgram,
    MajorProgramBase,
    MajorProgramCreate,
    MajorProgramUpdate,
    ProgramOffering,
    ProgramOfferingBase,
    ProgramOfferingCreate,
    ProgramOfferingUpdate,
    OfferingAcademicInfo,
    OfferingAcademicInfoBase,
    OfferingAcademicInfoCreate,
    OfferingAcademicInfoUpdate,
    # Semester Tuition (PR 2 — ADR-002)
    SemesterTuitionBase,
    SemesterTuitionCreate,
    SemesterTuitionUpdate,
    SemesterTuitionResponse,
    SemesterTuitionBulkUpsert,
    SemesterTuitionBulkUpsertItem,

    ScoringRules,  # Fit Score configuration schema
    # Organization Unit schemas
    OrganizationUnit,
    OrganizationUnitCreate,
    OrganizationUnitShallow,
    OrganizationUnitType,
    AdmissionStatus,
    OrganizationUnitUpdate,
    # Tree with aggregation schemas
    MajorWithStats,
    UnitAggregatedStats,
    OrganizationTreeNodeWithAggregation,
    # System Configuration schemas
    ConfigDegreeLevel,
    ConfigDegreeLevelBase,
    ConfigDegreeLevelCreate,
    ConfigDegreeLevelUpdate,
    ConfigOfferingType,
    ConfigOfferingTypeBase,
    ConfigOfferingTypeCreate,
    ConfigOfferingTypeUpdate,
    # Document Type schemas
    ConfigDocumentType,
    ConfigDocumentTypeBase,
    ConfigDocumentTypeCreate,
    ConfigDocumentTypeUpdate,
    # Distribution Rule schemas
    DistributionRuleBase,
    DistributionRuleCreate,
    DistributionRuleUpdate,
    DistributionRuleResponse,
    # Subject Group schemas (Phase 6: Dynamic Admission Scoring)
    SubjectGroupResponse,
)

# --- 3. Từ pipeline.py (Depends on: config, organization) ---
from .pipeline import (
    ConsultationStatus,
    ConsultationStatusBase,
    ConsultationStatusCreate,
    ConsultationStatusUpdate,
    FullPipeline,
    LossReason,
    PipelineStage,
    PipelineStageBase,
    PipelineStageCreate,
    PipelineStageUpdate,
    AllowedTransition,
    AllowedTransitionBase,
    AllowedTransitionCreate,
    AllowedTransitionUpdate,
)

# --- 4. Từ lead.py (Depends on: organization, pipeline) ---
from .lead import (
    AssignLead,
    AssignmentLog,
    BulkAssignLeadsSchema,
    BulkUpdateStageSchema,  # ✅ Option B: Bulk stage update
    BulkDeleteSchema,       # ✅ Option B: Bulk delete
    Consultation,
    ConsultationBase,
    ConsultationCreate,
    ConsultationCreateResult,
    ConsultationUpdate,
    Lead,
    LeadAction,
    LeadBase,
    LeadCreate,
    LeadDetail,
    LeadImportError,
    LeadImportResult,
    LeadInsights,
    LeadsPage,
    LeadUpdate,
    LeadStatusUpdate,  # ✅ FSM v3.0: Status update schema
    BulkStageSkippedItem,
    BulkUpdateStageResult,
    TimelineItem,
    # ✅ Phase-Based Workflow schemas
    WorkflowContext,
    WorkflowAllowedStatus,
)


# --- 5. Từ admission.py (Depends on: lead, organization) ---
from .admission import (
    # Nested schemas
    FamilyMemberSchema,
    AcademicRecordSchema,
    AdmissionScoreSchema,
    DocumentItemSchema,
    # AdmissionProfile schemas
    AdmissionProfileCreate,
    AdmissionProfileUpdate,
    AdmissionProfileResponse,
    AdmissionsPage,
    AdmissionSubmitResponse,
    EnrollStudentResponse,
    # Bulk action schemas
    BulkApproveRequest,
    BulkRejectRequest,
    BulkAssignRequest,
    BulkActionResponse,
    # Document upload
    DocumentUploadResponse,
    DocumentRejectRequest,
    DocumentSubmissionRequest,
    # Student schemas
    StudentDocumentResponse,
    StudentResponse,
    # State transition schemas (State Machine)
    ClaimRequest,
    DocumentFormatVerifyRequest,
    ApproveRequest,
    RejectRequest,
    RevisionRequest,
    ResubmitRequest,
    ConfirmRequest,
    OverrideRequest,
    WithdrawRequest,
    FinalizeRequest,
    DropStudentRequest,
    # Confirmation token schemas (Magic Link)
    ConfirmTokenVerifyRequest,
    ConfirmTokenResponse,
    ConfirmTokenInfoResponse,
    SendConfirmationResponse,
    # Aggregate schemas
    AdmissionStatusCounts,
    AdmissionStats,
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

# --- Từ user.py ---
from .user import (
    AdminSetPasswordSchema,
    AdminUserCreate,
    BulkActionSchema,
    ChangePasswordSchema,
    ForgotPasswordSchema,
    LoginSchema,
    # MFA schemas
    MfaBackupCodesRequest,
    MfaBackupCodesResponse,
    MfaDisableRequest,
    MfaEnableRequest,
    MfaSetupResponse,
    MfaStatusResponse,
    MfaVerifySchema,
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
    BulkDeleteRequest,  # ✅ TECHNICAL DEBT FIX: Bulk delete schema
    # ✅ NOTIFICATION 2.0: Notification Action schemas
    NotificationAction,
    NotificationActionCreate,
    NotificationActionUpdate,
    # ✅ PHASE 2.2: Notification Rule schemas
    NotificationRule,
    NotificationRuleBase,
    NotificationRuleCreate,
    NotificationRuleUpdate,
    NotificationRulesPage,
    NotificationRulePreview,
    NotificationRulePreviewResponse,
    ActionPreviewItem,
    RecipientConfig,
    # ✅ PHASE 3.1: Notification Template schemas
    NotificationTemplate,
    NotificationTemplateBase,
    NotificationTemplateCreate,
    NotificationTemplateUpdate,
    NotificationTemplatesPage,
    # ✅ Edge Case #4: Condition validation schemas
    SimpleCondition,
    CompoundCondition,
    Condition,
    # ✅ Phase 2: Condition field metadata schema
    ConditionFieldSchema,
)

# --- Từ notification_delivery.py ---
from .notification_delivery import (
    NotificationDeliveryResponse,
    NotificationDeliveriesPage,
    ReplayResponse,
    DeliveryStatsResponse,
    FailureReasonCount,
    DeliveryFailureSummary,
    QuotaResponse,
    QuotaListResponse,
    CircuitBreakerState,
    CircuitBreakerListResponse,
    TimeSeriesBucket,
    TimeSeriesResponse,
    TopEventStats,
    TopEventsResponse,
    LatencyStats,
    ChannelHealthItem,
    HealthSummaryResponse,
)

# --- Từ notification_consent.py ---
from .notification_consent import (
    NotificationConsentUpsert,
    NotificationConsentResponse,
    NotificationConsentsPage,
    NotificationConsentImportResult,
    ConsentHistoryResponse,
    ConsentHistoryPage,
)

# --- Từ notification_preference.py ---
from .notification_preference import (
    NotificationPreference,
    NotificationPreferenceBase,
    NotificationPreferenceCreate,
    NotificationPreferenceUpdate,
    NotificationTypePreference,
)
from .officer import (
    AvailabilityUpdate,
    AvailabilityResponse,
    OfficerDashboardStats,
    ActionableLists,
    WorkloadStats,
    TrendPoint,
    FunnelStage,
    UpcomingConsultation,
    # Phase 1: Enhanced Dashboard
    TrendInfo,
    KPIStats,
    PriorityAction,
    OfficerDashboardEnhanced,
    LeadPreview,
    # Phase 4: Leaderboard
    LeaderboardEntry,
    WeeklyLeaderboard,
    # Phase 6: Team Stats + Annual Progress
    TeamStats,
    AnnualProgressInfo,
    # Gap 2: Monthly KPI Plan Breakdown
    OfficerPlanMonthSummary,
    OfficerKpiPlanResponse,
    # V12 Phase B: Drill-down schemas
    DrillDownMetadata,
    ConsultationDrillDownRow,
    TransitionDrillDownRow,
    CohortDrillDownRow,
    DrillDownResponse,
)

# --- Từ tuition_discount_policy.py ---
from .tuition_discount_policy import (
    DiscountType,
    ApplicableScope,
    TargetCriteria,
    TuitionDiscountPolicy,
    TuitionDiscountPolicyBase,
    TuitionDiscountPolicyCreate,
    TuitionDiscountPolicyUpdate,
    TuitionDiscountPolicyWithCreator,
    TuitionDiscountPolicyListResponse,
    DiscountCalculationRequest,
    DiscountCalculationResponse,
    AppliedDiscount,
)