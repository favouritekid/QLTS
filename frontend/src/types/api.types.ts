// src/types/api.types.ts

// Định nghĩa cấu trúc User dựa trên backend model (app/models/user.py)
// và response schema (app/schemas/user.py -> User)
export interface User {
  id: number; // Backend dùng Integer
  username: string;
  email: string;
  full_name?: string | null; // Có thể null
  avatar_url?: string | null; // Có thể null
  phone_number?: string | null; // Có thể null
  role: string; // Dynamic roles from Casbin (e.g., "user", "admin", "manager", "support", etc.)
  status: "active" | "pending" | "banned"; // Các status có trong backend
  unit_id?: number | null; // Có thể null
  skills?: string[] | null; // User skills
  availability_status?: string | null; // Availability status
  max_capacity?: number | null; // Max capacity
  password_reset_required?: boolean; // Security: Set true after "Secure Account" action
  mfa_enabled?: boolean; // MFA: Whether TOTP MFA is enabled
}

// Kiểu dữ liệu cho request body khi login (khớp schemas/user.py -> LoginSchema)
export interface LoginRequest {
  username: string; // Backend dùng username thay vì email
  password: string;
}

// ✅ SECURITY FIX: Updated to match new HttpOnly cookie implementation
// Backend now returns user object in response body
// Refresh token is in HttpOnly cookie (not in response body)

// R1+R2: Suspicious login notification data included in login response
export interface LoginNotification {
  type: "SUSPICIOUS_LOGIN";
  login_id: number;
  notification_id?: number;  // R1+R2: Added for frontend markAsRead support
  ip_address: string;
  location?: string | null;
  device?: string | null;
  browser?: string | null;
  os?: string | null;
  risk_score: number;
  anomalies: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User; // ✅ User object now returned directly from /login
  login_notification?: LoginNotification | null;  // R1+R2: Optional suspicious login notification
  // refresh_token removed - now in HttpOnly cookie
  // MFA fields (present when mfa_required=true)
  mfa_required?: boolean;
  mfa_token?: string;
}

// Kiểu dữ liệu cho response từ /users/me
export type MeResponse = User;

// Kiểu dữ liệu chung cho lỗi API (có thể mở rộng)
export interface ApiErrorResponse {
  detail?: string | { msg: string; type: string }[]; // FastAPI validation errors
  message?: string; // Hoặc dùng 'message' nếu backend trả về
}

// Một phần tử trong mảng detail của Pydantic validation error (422)
export interface PydanticValidationError {
  loc?: string[];
  msg?: string;
}

// Schema for user registration - matches backend UserCreate
// Note: confirm_password is validated on frontend only, not sent to backend
export interface UserCreate {
  username: string;
  email: string;
  password: string;
  full_name?: string | null;
}

// Schema for forgot password request
export interface ForgotPasswordSchema {
  email: string;
}

// Schema for reset password - matches backend ResetPasswordSchema
// Note: confirm_new_password is validated on frontend only, not sent to backend
export interface ResetPasswordSchema {
  token: string;
  new_password: string;
}

// Schema for change password - matches backend ChangePasswordSchema
// Note: confirm_new_password is validated on frontend only, not sent to backend
export interface ChangePasswordSchema {
  old_password: string;
  new_password: string;
}

// Schema for updating user profile
export interface UserUpdateProfile {
  full_name?: string | null;
  phone_number?: string | null;
  email?: string;
  avatar?: File;
}

// Admin - User Management Types
export interface UsersPage {
  total_count: number;
  users: User[];
}

export interface AdminUserCreate {
  username: string;
  email: string;
  password: string;
  full_name?: string | null;
  role?: string; // Dynamic roles from Casbin
  status?: "active" | "pending" | "banned";
  avatar?: File;
}

export interface AdminUserUpdate {
  full_name?: string | null;
  email?: string;
  phone_number?: string | null;
  role?: string; // Dynamic roles from Casbin
  status?: "active" | "pending" | "banned";
  avatar?: File;
  skills?: string[];
  max_capacity?: number;
  unit_id?: number | null; // Organizational unit assignment
}

export interface AdminSetPassword {
  new_password: string;
}

// Admin - Permissions Types
export interface RoleAssignment {
  user_id: number;
  role: string;
}

export interface PolicyCreate {
  subject: string;
  object: string;
  action: string;
}

// Advanced Permission Tools Types
export interface WhoCanAccessResponse {
  object: string;
  action: string;
  allowed_subjects: string[];
  total_count: number;
}

export interface PermissionSimulateRequest {
  subject: string;
  object: string;
  action: string;
}

export interface PermissionSimulateResponse {
  subject: string;
  object: string;
  action: string;
  is_allowed: boolean;
  message: string;
}

export interface FeatureStatus {
  feature_id: string;
  display_name: string;
  enabled: boolean;
  policy_count: number;
}

export interface RoleFeaturesResponse {
  role: string;
  features: FeatureStatus[];
}

export interface ToggleFeatureRequest {
  feature_id: string;
  enabled: boolean;
}

export interface BulkAction {
  action: "delete" | "change_status";
  user_ids: number[];
  status?: "active" | "pending" | "banned";
}

// Activity Log Types
export interface UserActivityLog {
  id: number;
  actor_id: number | null;
  target_user_id: number | null;
  action: string;
  resource_type: string;
  resource_id: number | null;
  description: string | null;
  changes: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  actor_username: string | null;
  actor_full_name: string | null;
  target_username: string | null;
  target_full_name: string | null;
}

export interface ActivityLogsPage {
  total_count: number;
  logs: UserActivityLog[];
}

export interface UserStatistics {
  total_users: number;
  active_users: number;
  pending_users: number;
  banned_users: number;
  new_users_last_7_days: number;
  new_users_last_30_days: number;
  users_by_role: Record<string, number>;
  recent_activities: UserActivityLog[];
}

// Notification Types
export interface Notification {
  id: number;
  user_id: number;
  type: "info" | "success" | "warning" | "error" | "admin_update" | "system" | "reminder";
  title: string;
  message: string;
  link: string | null;
  data: Record<string, unknown> | null;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
}

export interface NotificationsPage {
  total_count: number;
  unread_count: number;
  notifications: Notification[];
}

export interface MarkAsReadRequest {
  notification_ids: number[];
}

// Event Group Preference Types
export interface EventGroupInfo {
  id: string;
  name_en: string;
  name_vi: string;
  description_en: string;
  description_vi: string;
}

export interface EventGroupPreferencesResponse {
  groups: EventGroupInfo[];
  preferences: Record<string, Record<string, boolean>>;
}

export interface UpdateGroupPreferenceRequest {
  event_group: string;
  channel: string;
  enabled: boolean;
}

// Notification Preference Types
export interface NotificationTypePreference {
  email: boolean;
  browser: boolean;
  sound: boolean;
}

export interface NotificationPreference {
  id: number;
  user_id: number;
  email_enabled: boolean;
  sound_enabled: boolean;
  browser_enabled: boolean;
  email_digest: "instant" | "daily" | "weekly" | "disabled";
  type_preferences: Record<string, NotificationTypePreference> | null;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string | null; // HH:mm format
  quiet_hours_end: string | null; // HH:mm format
}

// Alias for consistency with server.ts
export type NotificationPreferences = NotificationPreference;

export interface NotificationPreferenceUpdate {
  email_enabled?: boolean;
  sound_enabled?: boolean;
  browser_enabled?: boolean;
  email_digest?: "instant" | "daily" | "weekly" | "disabled";
  type_preferences?: Record<string, NotificationTypePreference>;
  quiet_hours_enabled?: boolean;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
}

// ============================================
// ✅ PHASE 2.4: NOTIFICATION RULES (Admin)
// ============================================

// ✅ NOTIFICATION 2.0: Multi-Step Workflow Support
export interface NotificationAction {
  id: number;
  rule_id: number;
  step: number;
  channel: string; // "browser" | "email" | "zalo" | "sms"
  template_code: string | null;
  delay_minutes: number;
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationActionCreate {
  step: number;
  channel: string;
  template_code?: string | null;
  delay_minutes?: number;
  config?: Record<string, unknown> | null;
}

export interface NotificationRule {
  id: number;
  event: string;
  title_template: string;
  message_template: string;
  notification_type: string;
  link_template: string | null;
  channels: string[]; // DEPRECATED: derived from actions
  recipient_config: Record<string, unknown>;
  condition: Record<string, unknown> | null;
  enabled: boolean;
  template_id: number | null;
  actions: NotificationAction[];
  created_at: string;
  updated_at: string;
}

export interface NotificationRuleCreate {
  event: string;
  title_template: string;
  message_template: string;
  notification_type: string;
  link_template?: string | null;
  channels: string[];
  recipient_config: Record<string, unknown>;
  condition?: Record<string, unknown> | null;
  enabled?: boolean;
  template_id?: number | null;
  actions?: NotificationActionCreate[];
}

export interface NotificationRuleUpdate {
  title_template?: string;
  message_template?: string;
  notification_type?: string;
  link_template?: string | null;
  channels?: string[];
  recipient_config?: Record<string, unknown>;
  condition?: Record<string, unknown> | null;
  enabled?: boolean;
  actions?: NotificationActionCreate[]; // ✅ NOTIFICATION 2.0: Multi-step workflow
}

export interface NotificationRulesPage {
  total_count: number;
  rules: NotificationRule[];
}

// ============================================
// ✅ PHASE 3.1: NOTIFICATION TEMPLATES (Admin)
// ============================================

export interface NotificationTemplate {
  id: number;
  name: string;
  template_code: string;
  description: string | null;
  title_template: string;
  message_template: string;
  link_template: string | null;
  variables: string[] | null;
  category: string | null;
  supported_channels: string[];
  allowed_events: string[] | null;
  template_type: string;
  is_system: boolean;
  usage_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationTemplateCreate {
  name: string;
  template_code: string;
  description?: string | null;
  title_template: string;
  message_template: string;
  link_template?: string | null;
  variables?: string[] | null;
  category?: string | null;
  supported_channels?: string[];
  allowed_events?: string[] | null;
  template_type?: string;
  is_system?: boolean;
}

export interface NotificationTemplateUpdate {
  name?: string;
  template_code?: string;
  description?: string | null;
  title_template?: string;
  message_template?: string;
  link_template?: string | null;
  variables?: string[] | null;
  category?: string | null;
  supported_channels?: string[];
  allowed_events?: string[] | null;
  template_type?: string;
}

export interface NotificationTemplatesPage {
  total_count: number;
  templates: NotificationTemplate[];
}

// ============================================
// ✅ PHASE B8: NOTIFICATION DELIVERY OPS
// ============================================

export interface NotificationDelivery {
  id: number;
  notification_id: number | null;
  event: string;
  channel: string;
  recipient_kind: string; // "internal" | "external"
  user_id: number | null;
  source_type: string | null;
  source_id: number | null;
  destination: string | null;
  status: string; // "queued" | "sent" | "failed" | "skipped"
  error_reason: string | null;
  dedupe_key: string | null;
  rule_id: number | null;
  action_step: number | null;
  template_code: string | null;
  payload_snapshot: Record<string, unknown> | null;
  provider_message_id: string | null;
  scheduled_for: string | null;
  attempt_count: number;
  last_attempt_at: string | null;
  next_retry_at: string | null;
  max_retries: number;
  dead_lettered_at: string | null;
  created_at: string;
  updated_at: string;
  sent_at: string | null;
}

export interface NotificationDeliveriesPage {
  total_count: number;
  deliveries: NotificationDelivery[];
}

// ============================================
// ✅ PHASE B7: NOTIFICATION CONSENT
// ============================================

export interface NotificationConsent {
  id: number;
  channel: string;
  source_type: string;
  source_id: number;
  normalized_phone: string | null;
  normalized_email: string | null;
  consent_status: string; // "granted" | "revoked"
  consent_source: string;
  granted_by: number | null;
  granted_at: string | null;
  revoked_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationConsentsPage {
  total_count: number;
  consents: NotificationConsent[];
}

export interface NotificationConsentUpsert {
  channel: string;
  source_type: string;
  source_id: number;
  consent_status?: string;
  normalized_phone?: string | null;
  normalized_email?: string | null;
  consent_source?: string;
  notes?: string | null;
}

export interface NotificationConsentImportResult {
  processed: number;
  granted: number;
  revoked: number;
  skipped: number;
  errors: Array<Record<string, unknown>>;
}

// ============================================
// ✅ NOTIFICATION 2.0: METADATA FOR DYNAMIC BUILDER
// ============================================

export interface ConditionField {
  path: string;
  type: string;
  description: string;
  operators: string[];
}

export interface EventVariable {
  name: string;
  type: string; // "string" | "integer" | "datetime" | "boolean" | "float"
  description: string;
  required?: boolean;
}

export interface EventMetadata {
  event: string; // SystemEvents enum value
  display_name: string;
  description: string;
  variables: EventVariable[];
  condition_fields: ConditionField[];
  filter_fields: string[];
  default_channels: string[];
  category: string; // "lead" | "application" | "consultation" | "finance" | etc.
}

export interface ResolverTypeOption {
  value: string;
  label: string;
  description: string;
}

export interface OperatorOption {
  value: string; // "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "in" | "not_in" | "contains"
  label: string;
}

export interface ChannelInfo {
  value: string;
  status: "live" | "planned";
}

export interface NotificationMetadata {
  events: EventMetadata[];
  channels: ChannelInfo[];
  resolver_types: ResolverTypeOption[];
  operators: OperatorOption[];
}

// ============================================
// RE-EXPORTS FROM OTHER TYPE FILES
// ============================================

// Pipeline types
export type {
  ConsultationStatus,
  PipelineStage,
  OutcomeType,
} from './pipeline.types';

// Organization types
export type {
  OrganizationUnit,
  MajorProgram,
  ProgramOffering,
  OrganizationTreeNodeWithAggregation as OrganizationTreeWithAggregation,
  AssignmentConfig,
  ConfigDegreeLevel as DegreeLevel,
  ConfigOfferingType as OfferingType,
  ConfigDocumentType as DocumentType,
} from './organization.types';

// Tuition discount types
export type {
  TuitionDiscountPolicy,
  TuitionDiscountPolicyListResponse as TuitionDiscountPoliciesPage,
} from './tuition-discount.types';

// Distribution Rule (for lead distribution)
export interface DistributionRule {
  id: number;
  offering_id: number;
  unit_id: number;
  weight: number;
  priority: number;
  is_active: boolean;
  offering_name?: string;
  unit_name?: string;
  created_at?: string;
  updated_at?: string;
}

// Session types
export type {
  UserSession as ActiveSession,
  UserSession,
} from './session';

// User Session List Response (for sessions page)
export interface UserSessionListResponse {
  sessions: import('./session').UserSession[];
  total: number;
  current_session_id: number | null;
}

// Additional types needed by server.ts
export interface PipelineWithStages {
  stages: import('./pipeline.types').PipelineStage[];
  total_stages: number;
  active_stages: number;
  total_leads: number;
}

export interface EventGroup {
  group_code: string;
  group_label: string;
  events: Array<{
    code: string;
    label: string;
    description: string;
  }>;
}

export interface DistributionStats {
  total_rules: number;
  active_rules: number;
  inactive_rules: number;
  total_distributions: number;
  successful_distributions: number;
  failed_distributions: number;
}

// Policy types
export type {
  PolicyStatistics as PermissionStatistics,
} from './policy.types';
