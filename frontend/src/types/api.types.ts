/**
 * Server API Response Types
 *
 * Architecture: Type-safe API client for Next.js Server Components
 *
 * This file defines TypeScript interfaces for all backend API responses,
 * ensuring type safety and data consistency between frontend and backend.
 *
 * Organization:
 * - User & Authentication Types
 * - Admin Management Types
 * - Pipeline & Organization Types
 * - Notification Types
 * - Configuration Types
 * - Statistics & Metrics Types
 */

// ============================================
// USER & AUTHENTICATION TYPES
// ============================================

export interface User {
  id: number;
  username: string;
  email: string;
  full_name: string | null;
  phone_number: string | null;
  role: 'admin' | 'officer' | 'manager';
  is_active: boolean;
  avatar_url: string | null;
  organization_unit_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface UsersPage {
  users: User[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface UserStatistics {
  total_users: number;
  active_users: number;
  inactive_users: number;
  by_role: {
    admin: number;
    officer: number;
    manager: number;
  };
  recent_registrations: number;
}

// ============================================
// PIPELINE & ORGANIZATION TYPES
// ============================================

export interface ConsultationStatus {
  id: number;
  code: string;
  label: string;
  color: string;
  stage_id: number;
  order_index: number;
  is_initial: boolean;
  is_final: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PipelineStage {
  id: number;
  name: string;
  code: string;
  description: string | null;
  order_index: number;
  is_active: boolean;
  statuses?: ConsultationStatus[];
  created_at: string;
  updated_at: string;
}

export interface PipelineWithStages {
  stages: PipelineStage[];
  total_stages: number;
  active_stages: number;
}

export interface OrganizationUnit {
  id: number;
  code: string;
  name: string;
  unit_type: string;
  parent_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  children?: OrganizationUnit[];
}

export interface OrganizationTreeWithAggregation extends OrganizationUnit {
  lead_count?: number;
  officer_count?: number;
}

export interface MajorProgram {
  id: number;
  code: string;
  name: string;
  organization_unit_id: number;
  degree_level_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProgramOffering {
  id: number;
  major_program_id: number;
  offering_type_id: number | null;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ============================================
// NOTIFICATION TYPES
// ============================================

export interface NotificationTemplate {
  id: number;
  code: string;
  name: string;
  channel: 'email' | 'sms' | 'socket' | 'all';
  subject_template: string | null;
  body_template: string;
  variables: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface NotificationTemplatesPage {
  templates: NotificationTemplate[];
  total: number;
  page: number;
  page_size: number;
}

export interface NotificationRule {
  id: number;
  event_code: string;
  template_id: number;
  priority: 'low' | 'medium' | 'high' | 'critical';
  is_active: boolean;
  conditions: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  template?: NotificationTemplate;
}

export interface NotificationRulesPage {
  rules: NotificationRule[];
  total: number;
  page: number;
  page_size: number;
}

export interface EventGroup {
  group_code: string;
  group_label: string;
  events: {
    code: string;
    label: string;
    description: string;
  }[];
}

export interface NotificationPreferences {
  user_id: number;
  email_enabled: boolean;
  sms_enabled: boolean;
  socket_enabled: boolean;
  event_preferences: Record<string, unknown>;
  updated_at: string;
}

export interface NotificationsPage {
  notifications: Notification[];
  total_count: number;
  unread_count: number;
}

// ============================================
// CONFIGURATION TYPES
// ============================================

export interface AssignmentConfig {
  id: number;
  organization_unit_id: number;
  auto_assign_enabled: boolean;
  round_robin_enabled: boolean;
  skill_based_enabled: boolean;
  max_leads_per_officer: number | null;
  created_at: string;
  updated_at: string;
}

export interface SkillRule {
  id: number;
  skill_name: string;
  skill_value: string;
  priority: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DistributionRule {
  id: number;
  name: string;
  priority: number;
  is_active: boolean;
  conditions: Record<string, unknown>;
  actions: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DistributionStats {
  total_rules: number;
  active_rules: number;
  inactive_rules: number;
  total_distributions: number;
  successful_distributions: number;
  failed_distributions: number;
}

export interface DegreeLevel {
  id: number;
  code: string;
  name: string;
  order_index: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface OfferingType {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DocumentType {
  id: number;
  code: string;
  name: string;
  is_required: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ============================================
// TUITION & DISCOUNT TYPES
// ============================================

export interface TuitionDiscountPolicy {
  id: number;
  code: string;
  name: string;
  discount_type: 'percentage' | 'fixed';
  discount_value: number;
  conditions: Record<string, unknown>;
  priority: number;
  is_active: boolean;
  valid_from: string | null;
  valid_to: string | null;
  created_at: string;
  updated_at: string;
}

export interface TuitionDiscountPoliciesPage {
  policies: TuitionDiscountPolicy[];
  total: number;
  page: number;
  page_size: number;
}

// ============================================
// PERMISSIONS & ROLES TYPES
// ============================================

export interface PermissionStatistics {
  total_policies: number;
  total_roles: number;
  total_grouping_policies: number;
  policies_by_resource: Record<string, number>;
  users_by_role: Record<string, number>;
}

// ============================================
// SESSION TYPES
// ============================================

export interface ActiveSession {
  id: number;
  user_id: number;
  refresh_jti: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  revoked_at: string | null;
}

// ============================================
// GENERIC API RESPONSE TYPES
// ============================================

export interface ApiResponse<T> {
  data: T;
  message?: string;
  success: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ApiError {
  detail: string;
  error_code?: string;
  status_code: number;
}
