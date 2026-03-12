/**
 * Lead Management - TypeScript Type Definitions
 * Based on Backend Models (verified in BACKEND_VERIFICATION_REPORT.md)
 */

import type { ConsultationStatus, PipelineStage } from "./pipeline.types";
import type { CollaboratorShallow } from "./collaborator.types";

// ============================================
// CORE LEAD TYPES
// ============================================

/**
 * Lead Status Enum
 * Represents the current status of a lead in the system
 */
export type LeadStatus =
  | "new"
  | "assigned"
  | "contacted"
  | "qualified"
  | "unqualified"
  | "converted"
  | "rejected";

/**
 * Lead Source Enum
 * Where the lead came from
 */
export type LeadSource =
  | "website"
  | "referral"
  | "social_media"
  | "walk_in"
  | "email"
  | "phone"
  | "event"
  | "other";

/**
 * Education Level Enum
 */
export type EducationLevel = "high_school" | "diploma" | "bachelor" | "master" | "phd" | "other";

/**
 * Consultation Method Enum
 * Aligned with backend ConsultationMethodEnum
 */
export type ConsultationMethod = "phone" | "email" | "sms" | "video_call" | "in_person";

/**
 * Assignment Method Enum
 */
export type AssignmentMethod = "manual" | "automatic" | "round_robin" | "skill_based";

// ============================================
// MAIN LEAD INTERFACE
// ============================================

/**
 * Complete Lead object from backend
 */
export interface Lead {
  id: number;
  full_name: string;
  email?: string | null; // Email is optional - not all leads have email
  phone: string;
  phone2?: string | null; // Số điện thoại phụ
  source: LeadSource;
  status: LeadStatus;
  assignment_status?: "pending" | "assigned" | "failed" | "reassign_pending";
  lead_score: number;
  education_level?: EducationLevel | null;
  gpa?: number | null;
  location?: string | null;
  officer_rating?: number | null;
  officer_summary?: string | null;
  created_at: string; // ISO datetime
  updated_at: string; // ISO datetime
  assigned_at?: string | null; // ISO datetime
  next_activity_at?: string | null; // ISO datetime - Quick Disposition bubble-up
  version: number; // Optimistic locking version

  // Fit Score fields
  birth_year?: number | null;
  location_proximity: number; // 0=Xa, 1=Lân cận, 2=Gần
  occupation_relevance: number; // 0=Không, 1=Gián tiếp, 2=Trực tiếp
  academic_performance: number; // 0=Yếu, 1=TB, 2=Khá, 3=Giỏi

  // =========================================================================
  // CACHED METRICS (Lead Insights Upgrade)
  // Auto-updated by LeadCacheService after consultation changes
  // =========================================================================
  last_consultation_at?: string | null; // ISO datetime - Ngày tư vấn cuối
  consultation_count: number; // Số lần tư vấn
  cached_urgency_score: number; // Điểm khẩn cấp 0-100
  is_hot_lead: boolean; // lead_score >= 70
  is_overdue: boolean; // Chưa liên hệ theo lịch hẹn (next_activity_at đã qua)
  days_in_stage: number; // Số ngày trong giai đoạn hiện tại
  // =========================================================================

  // Foreign Keys
  offering_id?: number | null;
  unit_id: number;
  assigned_officer_id?: number | null;
  consultation_status_id?: string | null;
  pipeline_stage_id?: string | null;

  // Relationships (optional, loaded with joins)
  offering?: ProgramOffering | null;
  unit?: OrganizationUnit | null;
  assigned_officer?: User | null;
  consultation_status?: ConsultationStatus | null;
  pipeline_stage?: PipelineStage | null;
  consultations?: Consultation[];
  application?: Application | null;
  // NEW: AdmissionProfile (replacement for Application in admission module)
  admission_profile?: AdmissionProfileShallow | null;

  // Collaborator (CTV) fields
  referrer_id: number | null;
  validity_status: string | null;
  created_via: string | null;
  referrer: CollaboratorShallow | null;
}

/**
 * Lead creation payload
 *
 * Role-based behavior:
 * - Admin: Can set any unit_id, can assign to any officer or use auto-assignment
 * - Manager: Can assign to officers in their unit or use auto-assignment
 * - Officer: Auto-assigned to themselves, unit forced to their unit
 */
export interface LeadCreate {
  full_name: string;
  email?: string | null; // Email is optional - not all leads have email
  phone: string;
  phone2?: string | null; // Số điện thoại phụ
  source: LeadSource;
  education_level?: EducationLevel | null;
  gpa?: number | null;
  location?: string | null;
  offering_id?: number | null;
  // unit_id is optional for Admin when offering_id has distribution config (auto-determined)
  unit_id?: number | null;
  // Direct assignment: null = auto-assign (Celery), number = assign to specific officer
  assigned_officer_id?: number | null;
  // CTV referrer for source="referral"
  referrer_id?: number | null;
  // Fit Score fields
  birth_year?: number | null;
  location_proximity?: number;
  occupation_relevance?: number;
  academic_performance?: number;
}

/**
 * Lead update payload
 */
export interface LeadUpdate {
  full_name?: string;
  email?: string | null; // Email is optional and nullable
  phone?: string;
  phone2?: string | null; // Số điện thoại phụ
  source?: LeadSource;
  education_level?: EducationLevel | null;
  gpa?: number | null;
  location?: string | null;
  officer_rating?: number | null;
  officer_summary?: string | null;
  offering_id?: number | null;
  unit_id?: number | null; // Allow null for unit reassignment
  consultation_status_id?: string | null;
  pipeline_stage_id?: string | null;
  // CTV referrer for source="referral"
  referrer_id?: number | null;
  // Fit Score fields
  birth_year?: number | null;
  location_proximity?: number;
  occupation_relevance?: number;
  academic_performance?: number;
  // Optimistic locking - optional, when provided will check for concurrent updates
  version?: number;
}

/**
 * Lead assignment payload
 */
export interface AssignLead {
  officer_id: number;
  reason?: string;
}

/**
 * Bulk assignment payload
 */
export interface BulkAssignLeads {
  lead_ids: number[];
  officer_id: number;
  reason?: string;
}

/**
 * Bulk assignment result from backend
 */
export interface BulkAssignResult {
  total: number;
  successful: number;
  failed: number;
  assigned_lead_ids: number[];
  errors: Array<{ lead_id: number; error: string }>;
}

/**
 * Lead action type enum
 */
export type LeadActionType = "reject" | "reassign" | "convert";

/**
 * Lead action payload
 */
export interface LeadAction {
  action: LeadActionType;
  reason?: string;
  new_officer_id?: number; // For reassign
}

// ============================================
// CONSULTATION TYPES
// ============================================

/**
 * Consultation object
 */
export interface Consultation {
  id: number;
  lead_id: number;
  consultation_date: string; // ISO datetime
  scheduled_at?: string | null; // ISO datetime
  method: ConsultationMethod;
  notes?: string | null;
  duration_minutes?: number | null;
  officer_id: number;
  consultation_status_id?: string | null;
  created_at?: string | null; // ISO datetime
  updated_at?: string | null; // ISO datetime
  // Note: loss_reason_code/loss_reason_note are stored in LeadStatusHistory,
  // not on the Consultation record. Backend does not return these in the response.
  loss_reason_code?: string | null;
  loss_reason_note?: string | null;

  // Relationships
  officer?: User | null;
  consultation_status?: ConsultationStatus | null;
}

/**
 * Consultation creation payload
 */
export interface ConsultationCreate {
  consultation_date?: string; // ISO datetime
  scheduled_at?: string | null; // ISO datetime - for follow-up scheduling
  method?: ConsultationMethod;
  notes?: string;
  duration_minutes?: number;
  status_id: string; // Required - consultation status ID
  loss_reason_code?: string | null;
  loss_reason_note?: string;
}

/**
 * Consultation update payload
 * All fields are optional - only provided fields will be updated
 */
export interface ConsultationUpdate {
  method?: ConsultationMethod;
  notes?: string;
  duration_minutes?: number;
  status_id?: string; // consultation status ID
  scheduled_at?: string | null; // ISO datetime - for follow-up scheduling
}

// ============================================
// APPLICATION TYPES
// ============================================

/**
 * Application Status Enum
 */
export type ApplicationStatus =
  | "draft" // Nháp
  | "pending" // Chờ xử lý (mặc định)
  | "missing_documents" // Chờ bổ sung (do thiếu/lỗi checklist)
  | "completed" // Đã đủ hồ sơ
  | "passed" // Đạt
  | "failed" // Trượt
  | "submitted" // Đã nộp
  | "approved" // Đã duyệt
  | "rejected" // Từ chối
  | "resubmitted" // Nộp lại
  | "confirmed" // Đã xác nhận nhập học
  | "overridden" // Ngoại lệ
  | "enrolled"; // Đã nhập học

/**
 * Checklist Item for Application Documents
 */
export interface ChecklistItem {
  code: string; // mã hồ sơ (vd: "hoc_ba_thpt")
  label: string; // tên hồ sơ (vd: "Học bạ THPT")
  status: "missing" | "submitted" | "verified" | "rejected";
  submission_type: "N/A" | "photocopy" | "notarized" | "original" | "incomplete";
  notes: string;
}

/**
 * Application Documents Structure
 */
export interface ApplicationDocuments {
  scores?: Record<string, number | null> | null; // vd: {"Toan": 8.5, "Van": 7.0}
  checklist?: ChecklistItem[] | null;
}

/**
 * Application object (Hồ sơ Tuyển sinh)
 */
export interface Application {
  id: number;
  lead_id: number;
  status: ApplicationStatus;

  // Foreign Keys liên kết đến 3-Tier
  major_program_id: number | null;
  program_offering_id: number | null;
  criterion_id: string | null; // AdmissionCriterion.id là string

  // Trường JSON để lưu dữ liệu động
  documents: ApplicationDocuments | null;

  // Legacy field (for backward compatibility)
  officer_id?: number;

  // Relationships
  officer?: User | null;
  lead?: Lead | null;
}

/**
 * Application creation payload
 */
export interface ApplicationCreate {
  lead_id: number;
}

/**
 * Application update payload
 */
export interface ApplicationUpdate {
  status?: ApplicationStatus;
  major_program_id?: number | null;
  program_offering_id?: number | null;
  criterion_id?: string | null;
  documents?: ApplicationDocuments | null;
}

// ============================================
// ADMISSION PROFILE TYPES (NEW)
// ============================================

/**
 * AdmissionProfileShallow - Minimal info for Lead response
 * Used by frontend to show "View Profile" vs "Create Profile" button
 * Backend source: AdmissionProfile model
 */
export interface AdmissionProfileShallow {
  id: number;
  status: string; // draft, submitted, approved, rejected, enrolled, etc.
  student_code?: string | null; // If enrolled
  created_at: string; // ISO datetime
}

// ============================================
// WORKFLOW CONTEXT TYPES (Phase-Based Workflow)
// ============================================

/**
 * Lead Phase - Business lifecycle stage
 */
export type LeadPhase = "consultation" | "admission" | "fee" | "enrolled";

/**
 * Allowed status option in workflow context
 */
export interface WorkflowAllowedStatus {
  id: string;
  name: string;
  phase: string;
  color_code: string;
  outcome_type: string;
  is_universal: boolean;
}

/**
 * Workflow context for a lead - Phase-Based Workflow
 * Used by frontend to dynamically filter status dropdowns
 */
export interface WorkflowContext {
  lead_id: number;
  current_phase: LeadPhase;
  current_status_id?: string | null;
  current_stage_id?: string | null;
  
  // Allowed statuses for current phase
  allowed_statuses: WorkflowAllowedStatus[];
  
  // Phase constraints
  is_terminal_phase: boolean;
  can_change_status: boolean;
  
  // Admission profile info
  has_admission_profile: boolean;
  admission_status?: string | null;
}


// ============================================
// CRM INTERACTION TYPES
// ============================================

/**
 * CRM Interaction object
 */
export interface CRMInteraction {
  id: number;
  lead_id: number;
  type: string;
  details?: Record<string, unknown> | null; // JSON field
  created_at: string; // ISO datetime
}

// ============================================
// ASSIGNMENT LOG TYPES
// ============================================

/**
 * Assignment Log object
 */
export interface AssignmentLog {
  id: number;
  lead_id: number;
  method: AssignmentMethod;
  timestamp: string; // ISO datetime
  reason?: string | null;
  officer_id: number;

  // Relationships
  officer?: User | null;
}

// ============================================
// TIMELINE TYPES
// ============================================

/**
 * Timeline item type enum
 */
export type TimelineItemType =
  | "lead_created"
  | "status_changed"
  | "assigned"
  | "assignment" // Backend sends this for assignment logs
  | "consultation" // Backend sends this for consultations
  | "consultation_added"
  | "consultation_updated"
  | "application_submitted"
  | "pipeline_moved"
  | "note_added";

/**
 * Timeline item for lead history
 * Backend contract: only `type`, `timestamp`, `data` are returned.
 * Fields below marked @deprecated are NOT sent by backend — kept as optional
 * to avoid breaking existing code that may reference them defensively.
 */
export interface TimelineItem {
  /** Backend sends "consultation" | "assignment" */
  type: TimelineItemType;
  timestamp: string; // ISO datetime
  /** Typed event payload — Consultation or AssignmentLog object */
  data: Consultation | AssignmentLog | Record<string, unknown>;

  // Legacy / defensive fields — NOT sent by backend, kept optional for safety
  /** @deprecated Not in backend contract */
  id?: number;
  /** @deprecated Not in backend contract — use `type` instead */
  event_type?: TimelineItemType;
  /** @deprecated Not in backend contract — derive from data fields */
  description?: string;
  /** @deprecated Not in backend contract — use data.officer */
  actor?: {
    id: number;
    full_name: string;
  } | null;
  actor_id?: number | null;
  metadata?: Record<string, unknown>;
}

// ============================================
// TIMELINE EVENT DATA TYPES
// ✅ TECHNICAL DEBT FIX: Proper discriminated union types
// ============================================

/**
 * Consultation event data
 */
export interface ConsultationEventData {
  method?: ConsultationMethod;
  notes?: string | null;
  duration_minutes?: number | null;
  consultation_date?: string;
  scheduled_at?: string | null;
  consultation_status?: ConsultationStatus | null;
  officer?: {
    id: number;
    full_name: string;
  } | null;
}

/**
 * Assignment event data
 */
export interface AssignmentEventData {
  method?: AssignmentMethod;
  reason?: string | null;
  officer?: {
    id: number;
    full_name: string;
  } | null;
  previous_officer?: {
    id: number;
    full_name: string;
  } | null;
}

/**
 * Status change event data
 */
export interface StatusChangeEventData {
  old_status?: string | null;
  new_status?: string | null;
  old_stage?: string | null;
  new_stage?: string | null;
}

/**
 * Lead created event data
 */
export interface LeadCreatedEventData {
  source?: LeadSource;
  created_by?: {
    id: number;
    full_name: string;
  } | null;
}

/**
 * Unified timeline event data type
 * Discriminated union for type-safe event data handling
 */
export type TimelineEventData = 
  | ConsultationEventData
  | AssignmentEventData
  | StatusChangeEventData
  | LeadCreatedEventData
  | Record<string, unknown>; // Fallback for unknown event types

// ============================================
// INSIGHTS TYPES
// ============================================

/**
 * Lead score breakdown
 */
export interface LeadScoreBreakdown {
  education_level: number;
  gpa: number;
  source: number;
  location: number;
  total: number;
}

/**
 * Engagement metrics
 */
export interface EngagementMetrics {
  consultations_count: number;
  interactions_count: number;
  response_rate: number;
  avg_response_time_hours: number;
  last_interaction_date?: string | null;
  email_opens?: number;
  email_clicks?: number;
  website_visits?: number;
  form_submissions?: number;
  last_activity_days?: number;
}

/**
 * Recommended action
 */
export interface RecommendedAction {
  action: string;
  priority: "low" | "medium" | "high" | "urgent";
  description: string;
  reason: string;
}

/**
 * Lead insights (360-degree view)
 * Matches backend schema: engagement_score, fit_score, urgency_score, overall_score
 */
export interface LeadInsights {
  engagement_score: number;
  fit_score: number;
  urgency_score: number;
  overall_score: number;
  officer_rating?: number | null;
  officer_summary?: string | null;
}

// ============================================
// PAGINATION & FILTERING
// ============================================

/**
 * Pagination parameters
 */
export interface PaginationParams {
  page?: number;
  page_size?: number;
}

/**
 * Lead list filter parameters
 */
export interface LeadListParams extends PaginationParams {
  status?: string; // Comma-separated
  assigned_officer_id?: number | string; // Single ID or comma-separated "1,2,3"
  unit_id?: number;
  offering_id?: number | string; // Single ID or comma-separated "1,2,3"
  source?: string; // Comma-separated
  search?: string;
  sort_by?: string;
  order?: "asc" | "desc";
  // === DATE RANGE FILTER ===
  date_from?: string; // ISO datetime
  date_to?: string; // ISO datetime
  date_field?: "created_at" | "updated_at" | "last_consultation_at";
  // === SCORE RANGE FILTER ===
  score_min?: number;
  score_max?: number;
  // === VALIDITY STATUS FILTER ===
  validity_status?: string; // Comma-separated
  // === SELECTIVE EXPORT ===
  lead_ids?: string; // Comma-separated lead IDs
}

/**
 * Paginated leads response
 */
export interface LeadsPage {
  total_count: number;
  leads: Lead[];
}

// ============================================
// IMPORT/EXPORT TYPES
// ============================================

/**
 * Lead import result
 * Aligned with backend LeadImportResult schema
 */
export interface LeadImportResult {
  total_rows_processed: number;
  successful_imports: number;
  failed_imports: number;
  created_lead_ids?: number[];
  errors: Array<{
    row_number: number;
    error_message: string;
    row_data?: Record<string, unknown>;
  }>;
}

/**
 * Export format options
 */
export type ExportFormat = "csv" | "excel";

// ============================================
// SUPPORTING TYPES
// ============================================

/**
 * User (minimal for relationships)
 */
export interface User {
  id: number;
  username: string;
  email: string;
  full_name: string;
  role: string;
  availability_status?: string;
  max_capacity?: number;
}

/**
 * Organization Unit
 */
export interface OrganizationUnit {
  id: number;
  name: string;
  code: string;
  type: string;
  parent_id?: number | null;
}

/**
 * Major Program (shallow for nested use)
 */
export interface MajorProgramShallow {
  id: number;
  name: string;
  degree_level: string;
  code: string;
  is_active: boolean;
}

/**
 * Program Offering
 */
export interface ProgramOffering {
  id: number;
  program_id: number;
  offering_type: string;
  duration_semesters?: number | null;
  total_credits?: number | null;
  is_active: boolean;
  program?: MajorProgramShallow | null;
}

/**
 * Consultation Status & Pipeline Stage
 * Re-exported from pipeline.types.ts to avoid duplication
 */
export type { ConsultationStatus, PipelineStage, OutcomeType } from "./pipeline.types";

// ============================================
// UTILITY TYPES
// ============================================

/**
 * API Error response
 */
export interface APIError {
  detail:
    | string
    | Array<{
        loc: string[];
        msg: string;
        type: string;
      }>;
}

/**
 * Success message response
 */
export interface SuccessResponse {
  message: string;
}
