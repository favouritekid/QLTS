/**
 * Pipeline Management - TypeScript Type Definitions
 * Based on Backend Models (verified in BACKEND_VERIFICATION_REPORT.md)
 */

import type { Lead } from "./lead.types";

// ============================================
// PIPELINE STAGE TYPES
// ============================================

/**
 * Pipeline Stage
 * Represents a stage in the lead conversion pipeline
 *
 * CRM Standards (Salesforce/HubSpot):
 * - Stages represent major milestones in the funnel
 * - Final stages (Won/Lost) are marked with is_final_stage=true
 */
export interface PipelineStage {
  id: string;
  name: string;
  order: number;
  is_final_stage: boolean; // Whether this is a final stage (Won/Lost/Closed)
  color_code?: string; // Hex color for stage (e.g., '#4CAF50')

  // Statistics (when loaded with full pipeline)
  lead_count?: number;
  conversion_rate?: number;
}

/**
 * Pipeline stage creation payload
 */
export interface PipelineStageCreate {
  id: string; // e.g., 'new_lead', 'contacted'
  name: string; // e.g., 'New Lead', 'Contacted'
  order: number; // Position in pipeline (0-based)
  is_final_stage?: boolean; // Default: false
}

/**
 * Pipeline stage update payload
 */
export interface PipelineStageUpdate {
  name?: string;
  order?: number;
  is_final_stage?: boolean;
}

// ============================================
// CONSULTATION STATUS TYPES
// ============================================

/**
 * Outcome Type (CRM Standard)
 * Classification of consultation status outcome
 */
export enum OutcomeType {
  POSITIVE = "positive", // Lead is moving forward (e.g., "Agreed", "Enrolled")
  NEUTRAL = "neutral", // In progress, no clear outcome (e.g., "Contacted", "Waiting")
  NEGATIVE = "negative", // Rejected or failed (e.g., "Refused", "Wrong number")
}

/**
 * Status Type (FSM v3.0)
 * Classification of status behavior in FSM
 */
export enum StatusType {
  TRANSITION = "transition", // Normal workflow status, follows FSM rules
  ACTIVITY = "activity", // Activity tracking, doesn't affect workflow
  SYSTEM = "system", // System-controlled, not user-selectable
}

/**
 * Selectable Mode (FSM v3.0)
 * Who can select this status
 */
export enum SelectableMode {
  USER = "user", // Any authenticated user (officer+)
  ROLE = "role", // Only manager/admin roles
  SYSTEM = "system", // Only backend system (not UI selectable)
}

/**
 * Trigger Type (FSM v3.0)
 * What triggers a transition
 */
export enum TriggerType {
  USER = "user", // UI action by any user
  ROLE = "role", // UI action by manager/admin
  SYSTEM = "system", // Backend system action
  EVENT = "event", // External event (webhook, cron, etc.)
}

/**
 * Consultation Status (FSM v3.0)
 * Status for consultations within a pipeline stage
 *
 * FSM v3.0 Features:
 * - Phase-based workflow (consultation/admission/fee/enrolled/universal)
 * - Status types: transition/activity/system
 * - Selectable modes: user/role/system
 * - Universal statuses bypass FSM rules
 */
export interface ConsultationStatus {
  id: string;
  name: string;
  color_code: string; // Hex color (e.g., '#4CAF50')
  color?: string; // Alias for color_code (for backward compatibility)
  stage_id: string | null; // Foreign key to PipelineStage (NULL for universal)
  outcome_type: OutcomeType; // Outcome classification

  // ✅ FSM v3.0 fields
  code?: string; // Machine-readable code (e.g., NOT_CONTACTED, ENROLLED)
  is_final: boolean; // Whether this status marks end of lead lifecycle
  status_type: StatusType; // transition/activity/system
  selectable_mode: SelectableMode; // user/role/system
  phase: string; // consultation/admission/fee/enrolled/universal
  description?: string; // Optional description
  display_order: number; // Sort order for UI

  // Universal & Pipeline flags
  is_universal: boolean; // True for activity statuses that bypass FSM
  updates_pipeline: boolean; // False if only records activity
  counts_for_funnel: boolean; // True if counted in funnel analytics

  legacy_status?: string | null;

  // Relationship
  stage?: PipelineStage;

  // Optional computed fields
  lead_count?: number;
}

/**
 * Consultation status creation payload (FSM v3.0)
 */
export interface ConsultationStatusCreate {
  id: string;
  name: string;
  color_code: string;
  stage_id?: string | null; // NULL for universal statuses
  outcome_type?: OutcomeType; // Default: neutral

  // FSM v3.0 fields
  code?: string;
  is_final?: boolean; // Default: false
  status_type?: StatusType; // Default: transition
  selectable_mode?: SelectableMode; // Default: user
  phase?: string; // Default: consultation
  description?: string;
  display_order?: number; // Default: 0
  is_universal?: boolean; // Default: false
  updates_pipeline?: boolean; // Default: true
  counts_for_funnel?: boolean; // Default: true

  legacy_status?: string | null;
}

/**
 * Consultation status update payload (FSM v3.0)
 */
export interface ConsultationStatusUpdate {
  name?: string;
  color_code?: string;
  stage_id?: string | null;
  outcome_type?: OutcomeType;

  // FSM v3.0 fields
  code?: string;
  is_final?: boolean;
  status_type?: StatusType;
  selectable_mode?: SelectableMode;
  phase?: string;
  description?: string;
  display_order?: number;
  is_universal?: boolean;
  updates_pipeline?: boolean;
  counts_for_funnel?: boolean;

  legacy_status?: string | null;
}

// ============================================
// ALLOWED TRANSITION TYPES
// ============================================

/**
 * Allowed Status Transition (FSM v3.0)
 * Workflow rules for status changes
 */
export interface AllowedTransition {
  id: number;
  from_status_id: string;
  to_status_id: string;
  created_at: string;
  updated_at: string;

  // ✅ FSM v3.0 fields
  trigger_type: TriggerType; // user/role/system/event
  required_phase?: string; // Target phase (must match to_status.phase)
  is_active: boolean; // Whether transition is enabled
  description?: string; // Human-readable description

  // Optional relationships
  from_status?: ConsultationStatus;
  to_status?: ConsultationStatus;
}

/**
 * Allowed transition creation payload
 */
export interface AllowedTransitionCreate {
  from_status_id: string;
  to_status_id: string;
  trigger_type?: TriggerType; // Default: user
  required_phase?: string;
  is_active?: boolean; // Default: true
  description?: string;
}

/**
 * Allowed transition update payload
 */
export interface AllowedTransitionUpdate {
  from_status_id?: string;
  to_status_id?: string;
  trigger_type?: TriggerType;
  required_phase?: string;
  is_active?: boolean;
  description?: string;
}

// ============================================
// FULL PIPELINE TYPES
// ============================================

/**
 * Pipeline stage with associated statuses and statistics
 */
export interface PipelineStageWithStats extends PipelineStage {
  lead_count: number;
  statuses: ConsultationStatus[];
  leads?: Lead[]; // Optional: leads in this stage
  conversion_rate?: number; // Percentage converted to next stage
  avg_time_in_stage_days?: number;
}

/**
 * Full pipeline response
 * Complete pipeline with all stages, statuses, and statistics
 */
export interface FullPipeline {
  stages: PipelineStageWithStats[];
  total_leads: number;
  conversion_rate?: number; // Overall conversion rate (optional)
  avg_time_in_pipeline_days?: number; // Average time across all stages (optional)
}

// ============================================
// KANBAN BOARD TYPES
// ============================================

/**
 * Kanban column (represents a pipeline stage)
 */
export interface KanbanColumn {
  id: string;
  name: string;
  order: number;
  leads: Lead[];
  lead_count: number;
  limit?: number; // Optional: WIP limit
}

/**
 * Kanban board configuration
 */
export interface KanbanBoard {
  columns: KanbanColumn[];
  total_leads: number;
}

/**
 * Move lead between stages payload
 */
export interface MoveLeadPayload {
  lead_id: number;
  from_stage_id: string;
  to_stage_id: string;
  reason?: string;
}

// ============================================
// PIPELINE STATISTICS TYPES
// ============================================

/**
 * Stage-specific statistics
 */
export interface StageStatistics {
  stage_id: string;
  stage_name: string;
  total_leads: number;
  active_leads: number;
  converted_leads: number;
  dropped_leads: number;
  conversion_rate: number;
  avg_time_in_stage_days: number;
  trend: "up" | "down" | "stable";
}

/**
 * Pipeline funnel data (for visualization)
 */
export interface PipelineFunnel {
  stages: Array<{
    stage_id: string;
    stage_name: string;
    lead_count: number;
    conversion_rate: number;
    drop_off_rate: number;
  }>;
}

/**
 * Pipeline metrics over time
 */
export interface PipelineMetrics {
  date: string; // ISO date
  total_leads: number;
  new_leads: number;
  converted_leads: number;
  conversion_rate: number;
}

/**
 * Pipeline trends (for charts)
 */
export interface PipelineTrends {
  daily: PipelineMetrics[];
  weekly: PipelineMetrics[];
  monthly: PipelineMetrics[];
}

// ============================================
// FILTER & QUERY TYPES
// ============================================

/**
 * Pipeline filter parameters
 */
export interface PipelineFilterParams {
  officer_id?: number;
  unit_id?: number;
  offering_id?: number;
  date_from?: string; // ISO date
  date_to?: string; // ISO date
}

/**
 * Pipeline query parameters (for full pipeline endpoint)
 */
export interface PipelineQueryParams extends PipelineFilterParams {
  include_leads?: boolean; // Whether to include leads in response
  include_stats?: boolean; // Whether to include statistics
}

// ============================================
// DRAG & DROP TYPES
// ============================================

/**
 * Drag event data for kanban
 */
export interface DragData {
  leadId: number;
  sourceStageId: string;
  sourceIndex: number;
}

/**
 * Drop event data for kanban
 */
export interface DropData {
  targetStageId: string;
  targetIndex: number;
}

/**
 * Drag and drop result
 */
export interface DnDResult {
  success: boolean;
  lead?: Lead;
  error?: string;
}

// ============================================
// CONFIGURATION TYPES
// ============================================

/**
 * Pipeline configuration
 */
export interface PipelineConfig {
  enable_auto_progression: boolean;
  require_consultation_for_progression: boolean;
  max_time_in_stage_days?: number;
  notification_enabled: boolean;
  notification_thresholds: {
    stuck_in_stage_days: number;
    high_priority_response_hours: number;
  };
}

/**
 * Stage trigger configuration
 */
export interface StageTrigger {
  id: number;
  stage_id: string;
  trigger_type: "email" | "task" | "webhook" | "notification";
  trigger_when: "enter" | "exit" | "timeout";
  config: Record<string, unknown>;
  is_active: boolean;
}

// ============================================
// UTILITY TYPES
// ============================================

/**
 * Pipeline stage color mapping (for UI)
 * Maps stage IDs to background colors
 */
export const STAGE_COLORS: Record<string, string> = {
  // Database stage IDs (stg01-stg07)
  stg01: "#3B82F6", // Blue - Chưa tư vấn
  stg02: "#F59E0B", // Amber - Đang tư vấn
  stg03: "#8B5CF6", // Purple - Đã nộp hồ sơ
  stg04: "#06B6D4", // Cyan - Chuẩn bị nhập học
  stg05: "#10B981", // Emerald - Đã nộp học phí
  stg06: "#22C55E", // Green - Đã nhập học
  stg07: "#EF4444", // Red - Không theo học

  // Legacy string-based IDs (fallback)
  new_lead: "#3B82F6", // Blue
  contacted: "#F59E0B", // Amber
  consultation_scheduled: "#8B5CF6", // Purple
  consultation_completed: "#06B6D4", // Cyan
  application_submitted: "#10B981", // Emerald
  enrolled: "#22C55E", // Green
  lost: "#EF4444", // Red
};

/**
 * Pipeline stage icons (for UI)
 */
export const STAGE_ICONS: Record<string, string> = {
  new_lead: "user-plus",
  contacted: "phone",
  consultation_scheduled: "calendar",
  consultation_completed: "check-circle",
  application_submitted: "file-text",
  enrolled: "award",
  lost: "x-circle",
};

/**
 * Export type for pipeline data
 */
export type PipelineExportFormat = "csv" | "excel" | "json";

/**
 * Pipeline export result
 */
export interface PipelineExportResult {
  url: string;
  filename: string;
  format: PipelineExportFormat;
  size_bytes: number;
  expires_at: string; // ISO datetime
}
