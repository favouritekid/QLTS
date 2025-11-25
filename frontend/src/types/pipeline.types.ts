/**
 * Pipeline Management - TypeScript Type Definitions
 * Based on Backend Models (verified in BACKEND_VERIFICATION_REPORT.md)
 */

import type { Lead } from './lead.types'

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
  id: string
  name: string
  order: number
  is_final_stage: boolean // Whether this is a final stage (Won/Lost/Closed)

  // Statistics (when loaded with full pipeline)
  lead_count?: number
  conversion_rate?: number
}

/**
 * Pipeline stage creation payload
 */
export interface PipelineStageCreate {
  id: string // e.g., 'new_lead', 'contacted'
  name: string // e.g., 'New Lead', 'Contacted'
  order: number // Position in pipeline (0-based)
  is_final_stage?: boolean // Default: false
}

/**
 * Pipeline stage update payload
 */
export interface PipelineStageUpdate {
  name?: string
  order?: number
  is_final_stage?: boolean
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
 * Consultation Status
 * Status for consultations within a pipeline stage
 *
 * CRM Standards:
 * - Each status belongs to one stage
 * - Status has outcome_type: positive/neutral/negative
 * - Final statuses (end of lifecycle) marked with is_final_status=true
 */
export interface ConsultationStatus {
  id: string
  name: string
  color_code: string // Hex color (e.g., '#4CAF50')
  color?: string // Alias for color_code (for backward compatibility)
  stage_id: string // Foreign key to PipelineStage
  outcome_type: OutcomeType // Outcome classification
  is_final_status: boolean // Whether this status marks end of lead lifecycle
  legacy_status?: string | null // Maps to lead.status for backward compatibility (Hybrid Approach)

  // ✅ Universal status support (Phase 1 - Option B)
  is_universal?: boolean // True nếu status có thể dùng ở mọi pipeline stage (VD: Không nghe máy, Thuê bao)
  updates_pipeline?: boolean // False nếu chỉ ghi nhận activity, không thay đổi pipeline progression

  // Relationship
  stage?: PipelineStage

  // Optional computed fields
  lead_count?: number
}

/**
 * Consultation status creation payload
 */
export interface ConsultationStatusCreate {
  id: string
  name: string
  color_code: string
  stage_id: string
  outcome_type?: OutcomeType // Default: neutral
  is_final_status?: boolean // Default: false
  legacy_status?: string | null // Maps to lead.status for backward compatibility
  is_universal?: boolean // Default: false
  updates_pipeline?: boolean // Default: true
}

/**
 * Consultation status update payload
 */
export interface ConsultationStatusUpdate {
  name?: string
  color_code?: string
  stage_id?: string
  outcome_type?: OutcomeType
  is_final_status?: boolean
  legacy_status?: string | null // Maps to lead.status for backward compatibility
  is_universal?: boolean
  updates_pipeline?: boolean
}

// ============================================
// ALLOWED TRANSITION TYPES
// ============================================

/**
 * Allowed Status Transition
 * Workflow rules for status changes (HubSpot standard)
 */
export interface AllowedTransition {
  id: number
  from_status_id: string
  to_status_id: string
  created_at: string
  updated_at: string

  // Optional relationships
  from_status?: ConsultationStatus
  to_status?: ConsultationStatus
}

/**
 * Allowed transition creation payload
 */
export interface AllowedTransitionCreate {
  from_status_id: string
  to_status_id: string
}

/**
 * Allowed transition update payload
 */
export interface AllowedTransitionUpdate {
  from_status_id?: string
  to_status_id?: string
}

// ============================================
// FULL PIPELINE TYPES
// ============================================

/**
 * Pipeline stage with associated statuses and statistics
 */
export interface PipelineStageWithStats extends PipelineStage {
  lead_count: number
  statuses: ConsultationStatus[]
  leads?: Lead[] // Optional: leads in this stage
  conversion_rate?: number // Percentage converted to next stage
  avg_time_in_stage_days?: number
}

/**
 * Full pipeline response
 * Complete pipeline with all stages, statuses, and statistics
 */
export interface FullPipeline {
  stages: PipelineStageWithStats[]
  total_leads: number
  conversion_rate?: number // Overall conversion rate (optional)
  avg_time_in_pipeline_days?: number // Average time across all stages (optional)
}

// ============================================
// KANBAN BOARD TYPES
// ============================================

/**
 * Kanban column (represents a pipeline stage)
 */
export interface KanbanColumn {
  id: string
  name: string
  order: number
  leads: Lead[]
  lead_count: number
  limit?: number // Optional: WIP limit
}

/**
 * Kanban board configuration
 */
export interface KanbanBoard {
  columns: KanbanColumn[]
  total_leads: number
}

/**
 * Move lead between stages payload
 */
export interface MoveLeadPayload {
  lead_id: number
  from_stage_id: string
  to_stage_id: string
  reason?: string
}

// ============================================
// PIPELINE STATISTICS TYPES
// ============================================

/**
 * Stage-specific statistics
 */
export interface StageStatistics {
  stage_id: string
  stage_name: string
  total_leads: number
  active_leads: number
  converted_leads: number
  dropped_leads: number
  conversion_rate: number
  avg_time_in_stage_days: number
  trend: 'up' | 'down' | 'stable'
}

/**
 * Pipeline funnel data (for visualization)
 */
export interface PipelineFunnel {
  stages: Array<{
    stage_id: string
    stage_name: string
    lead_count: number
    conversion_rate: number
    drop_off_rate: number
  }>
}

/**
 * Pipeline metrics over time
 */
export interface PipelineMetrics {
  date: string // ISO date
  total_leads: number
  new_leads: number
  converted_leads: number
  conversion_rate: number
}

/**
 * Pipeline trends (for charts)
 */
export interface PipelineTrends {
  daily: PipelineMetrics[]
  weekly: PipelineMetrics[]
  monthly: PipelineMetrics[]
}

// ============================================
// FILTER & QUERY TYPES
// ============================================

/**
 * Pipeline filter parameters
 */
export interface PipelineFilterParams {
  officer_id?: number
  unit_id?: number
  offering_id?: number
  date_from?: string // ISO date
  date_to?: string // ISO date
}

/**
 * Pipeline query parameters (for full pipeline endpoint)
 */
export interface PipelineQueryParams extends PipelineFilterParams {
  include_leads?: boolean // Whether to include leads in response
  include_stats?: boolean // Whether to include statistics
}

// ============================================
// DRAG & DROP TYPES
// ============================================

/**
 * Drag event data for kanban
 */
export interface DragData {
  leadId: number
  sourceStageId: string
  sourceIndex: number
}

/**
 * Drop event data for kanban
 */
export interface DropData {
  targetStageId: string
  targetIndex: number
}

/**
 * Drag and drop result
 */
export interface DnDResult {
  success: boolean
  lead?: Lead
  error?: string
}

// ============================================
// CONFIGURATION TYPES
// ============================================

/**
 * Pipeline configuration
 */
export interface PipelineConfig {
  enable_auto_progression: boolean
  require_consultation_for_progression: boolean
  max_time_in_stage_days?: number
  notification_enabled: boolean
  notification_thresholds: {
    stuck_in_stage_days: number
    high_priority_response_hours: number
  }
}

/**
 * Stage trigger configuration
 */
export interface StageTrigger {
  id: number
  stage_id: string
  trigger_type: 'email' | 'task' | 'webhook' | 'notification'
  trigger_when: 'enter' | 'exit' | 'timeout'
  config: Record<string, unknown>
  is_active: boolean
}

// ============================================
// UTILITY TYPES
// ============================================

/**
 * Pipeline stage color mapping (for UI)
 */
export const STAGE_COLORS: Record<string, string> = {
  new_lead: '#E3F2FD', // Light Blue
  contacted: '#FFF9C4', // Light Yellow
  consultation_scheduled: '#FFE0B2', // Light Orange
  consultation_completed: '#C8E6C9', // Light Green
  application_submitted: '#B2DFDB', // Light Teal
  enrolled: '#4CAF50', // Green
  lost: '#FFCDD2', // Light Red
}

/**
 * Pipeline stage icons (for UI)
 */
export const STAGE_ICONS: Record<string, string> = {
  new_lead: 'user-plus',
  contacted: 'phone',
  consultation_scheduled: 'calendar',
  consultation_completed: 'check-circle',
  application_submitted: 'file-text',
  enrolled: 'award',
  lost: 'x-circle',
}

/**
 * Export type for pipeline data
 */
export type PipelineExportFormat = 'csv' | 'excel' | 'json'

/**
 * Pipeline export result
 */
export interface PipelineExportResult {
  url: string
  filename: string
  format: PipelineExportFormat
  size_bytes: number
  expires_at: string // ISO datetime
}
