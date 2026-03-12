/**
 * Pipeline API Client
 * API functions for Pipeline Management
 * Uses axios client with auto-refresh interceptors
 */

import { api } from './client'
import type {
  PipelineStage,
  PipelineStageCreate,
  PipelineStageUpdate,
  ConsultationStatus,
  ConsultationStatusCreate,
  ConsultationStatusUpdate,
  FullPipeline,
  PipelineQueryParams,
  MoveLeadPayload,
  AllowedTransition as AllowedTransitionType,
  AllowedTransitionCreate as AllowedTransitionCreateType,
} from '@/types/pipeline.types'
import type { Lead, SuccessResponse } from '@/types/lead.types'

// ============================================
// PIPELINE STAGE OPERATIONS (Public)
// ============================================

/**
 * Get all pipeline stages (read-only, available to all authenticated users)
 *
 * @example
 * ```ts
 * const stages = await pipelineApi.getStages()
 * // Returns: [{ id: 'new_lead', name: 'New Lead', order: 1 }, ...]
 * ```
 */
export async function getStages(): Promise<PipelineStage[]> {
  const response = await api.get<PipelineStage[]>('/api/pipeline/stages')
  return response.data
}

/**
 * Get full pipeline with statistics
 * Returns all stages with associated statuses and lead counts
 *
 * @param params - Query parameters for filtering
 *
 * @example
 * ```ts
 * // Get full pipeline
 * const pipeline = await pipelineApi.getFullPipeline()
 *
 * // Get filtered pipeline
 * const filtered = await pipelineApi.getFullPipeline({
 *   officer_id: 5,
 *   date_from: '2025-01-01',
 *   date_to: '2025-01-31',
 *   include_leads: true
 * })
 * ```
 */
export async function getFullPipeline(
  params?: PipelineQueryParams
): Promise<FullPipeline> {
  const response = await api.get<FullPipeline>('/api/pipeline/board', { params })
  return response.data
}

/**
 * Get allowed next statuses from current status (FSM v3.0)
 * Returns only valid next statuses based on:
 * - Workflow transitions (allowed_transitions table)
 * - Phase guards (user/role cannot cross phases)
 * - Trigger type (hide system-only statuses)
 * - Lead phase (derived from admission_profile)
 *
 * @param currentStatusId - Current consultation status ID (null for new leads)
 * @param leadId - Lead ID to derive phase from admission_profile (optional)
 *
 * @example
 * ```ts
 * // Get allowed next statuses for a lead
 * const nextStatuses = await pipelineApi.getAllowedNextStatuses('sts01', 123)
 *
 * // Get initial status for new lead (NULL → NOT_CONTACTED only)
 * const initialStatuses = await pipelineApi.getAllowedNextStatuses(null)
 * ```
 */
export async function getAllowedNextStatuses(
  currentStatusId: string | null,
  leadId?: number
): Promise<ConsultationStatus[]> {
  const params: Record<string, string | number> = {}

  if (currentStatusId) {
    params.current_status_id = currentStatusId
  }
  if (leadId) {
    params.lead_id = leadId
  }

  const response = await api.get<ConsultationStatus[]>(
    '/api/pipeline/allowed-next-statuses',
    { params }
  )
  return response.data
}

// ============================================
// PIPELINE STAGE OPERATIONS (Admin Only)
// ============================================

/**
 * Create new pipeline stage
 * Admin only
 *
 * @throws {AxiosError} 403 if not admin, 422 for validation errors
 *
 * @example
 * ```ts
 * const stage = await pipelineApi.createStage({
 *   id: 'documents_review',
 *   name: 'Documents Review',
 *   order: 5
 * })
 * ```
 */
export async function createStage(
  data: PipelineStageCreate
): Promise<PipelineStage> {
  const response = await api.post<PipelineStage>(
    '/api/admin/pipeline-stages',
    data
  )
  return response.data
}

/**
 * Update pipeline stage
 * Admin only
 *
 * @throws {AxiosError} 404 if not found, 403 if not admin
 *
 * @example
 * ```ts
 * const updated = await pipelineApi.updateStage('new_lead', {
 *   name: 'Initial Contact',
 *   order: 2
 * })
 * ```
 */
export async function updateStage(
  stageId: string,
  data: PipelineStageUpdate
): Promise<PipelineStage> {
  const response = await api.put<PipelineStage>(
    `/api/admin/pipeline-stages/${stageId}`,
    data
  )
  return response.data
}

/**
 * Delete pipeline stage
 * Admin only
 *
 * @throws {AxiosError} 404 if not found, 403 if not admin, 400 if stage has leads
 *
 * @example
 * ```ts
 * await pipelineApi.deleteStage('old_stage')
 * ```
 */
export async function deleteStage(stageId: string): Promise<SuccessResponse> {
  const response = await api.delete<SuccessResponse>(
    `/api/admin/pipeline-stages/${stageId}`
  )
  return response.data
}

// ============================================
// CONSULTATION STATUS OPERATIONS (Admin Only)
// ============================================

/**
 * Get all consultation statuses
 * Admin only
 *
 * @throws {AxiosError} 403 if not admin
 */
export async function getConsultationStatuses(): Promise<ConsultationStatus[]> {
  const response = await api.get<ConsultationStatus[]>(
    '/api/admin/consultation-statuses'
  )
  return response.data
}

/**
 * Get single consultation status
 * Admin only
 *
 * @throws {AxiosError} 404 if not found, 403 if not admin
 */
export async function getConsultationStatus(
  statusId: string
): Promise<ConsultationStatus> {
  const response = await api.get<ConsultationStatus>(
    `/api/admin/consultation-statuses/${statusId}`
  )
  return response.data
}

/**
 * Create new consultation status
 * Admin only
 *
 * @throws {AxiosError} 403 if not admin, 422 for validation errors
 *
 * @example
 * ```ts
 * const status = await pipelineApi.createConsultationStatus({
 *   id: 'rescheduled',
 *   name: 'Rescheduled',
 *   color_code: '#2196F3',
 *   stage_id: 'consultation_scheduled'
 * })
 * ```
 */
export async function createConsultationStatus(
  data: ConsultationStatusCreate
): Promise<ConsultationStatus> {
  const response = await api.post<ConsultationStatus>(
    '/api/admin/consultation-statuses',
    data
  )
  return response.data
}

/**
 * Update consultation status
 * Admin only
 *
 * @throws {AxiosError} 404 if not found, 403 if not admin
 */
export async function updateConsultationStatus(
  statusId: string,
  data: ConsultationStatusUpdate
): Promise<ConsultationStatus> {
  const response = await api.put<ConsultationStatus>(
    `/api/admin/consultation-statuses/${statusId}`,
    data
  )
  return response.data
}

/**
 * Delete consultation status
 * Admin only
 *
 * @throws {AxiosError} 404 if not found, 403 if not admin, 400 if in use
 */
export async function deleteConsultationStatus(
  statusId: string
): Promise<SuccessResponse> {
  const response = await api.delete<SuccessResponse>(
    `/api/admin/consultation-statuses/${statusId}`
  )
  return response.data
}

// ============================================
// LEAD PIPELINE OPERATIONS
// ============================================

/**
 * Move lead to different pipeline stage
 * Used for kanban drag-and-drop
 *
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 *
 * @example
 * ```ts
 * const updated = await pipelineApi.moveLeadToStage({
 *   lead_id: 123,
 *   from_stage_id: 'contacted',
 *   to_stage_id: 'consultation_scheduled',
 *   reason: 'Consultation booked for next week'
 * })
 * ```
 */
export async function moveLeadToStage(data: MoveLeadPayload): Promise<Lead> {
  const { lead_id, to_stage_id, reason } = data

  const response = await api.put<Lead>(`/api/leads/${lead_id}`, {
    pipeline_stage_id: to_stage_id,
    ...(reason && { officer_summary: reason }),
  })

  return response.data
}

/**
 * Get leads in specific pipeline stage
 *
 * @example
 * ```ts
 * const leads = await pipelineApi.getLeadsInStage('new_lead')
 * ```
 */
export async function getLeadsInStage(stageId: string): Promise<Lead[]> {
  const response = await api.get<{ leads: Lead[] }>('/api/leads', {
    params: {
      pipeline_stage_id: stageId,
      page_size: 100, // Adjust as needed
    },
  })

  return response.data.leads
}

// ============================================
// REVERT OPERATIONS (Admin Only)
// ============================================

/**
 * Revert lead to previous status
 * Admin only
 *
 * @throws {AxiosError} 404 if lead not found, 403 if not admin, 400 if no previous status
 *
 * @example
 * ```ts
 * const reverted = await pipelineApi.revertLeadStatus(123)
 * ```
 */
export async function revertLeadStatus(leadId: number): Promise<Lead> {
  const response = await api.post<Lead>(
    `/api/admin/leads/${leadId}/revert-status`
  )
  return response.data
}

// ============================================
// STATISTICS & ANALYTICS
// ============================================

/**
 * Get pipeline conversion statistics
 *
 * @example
 * ```ts
 * const stats = await pipelineApi.getPipelineStats({
 *   date_from: '2025-01-01',
 *   date_to: '2025-01-31'
 * })
 * ```
 */
export async function getPipelineStats(
  params?: PipelineQueryParams
): Promise<{
  total_leads: number
  conversion_rate?: number
  avg_time_in_pipeline_days?: number
  stage_statistics: Array<{
    stage_id: string
    stage_name: string
    lead_count: number
    stage_distribution_pct: number
  }>
}> {
  const pipeline = await getFullPipeline(params)

  return {
    total_leads: pipeline.total_leads,
    conversion_rate: pipeline.conversion_rate,
    avg_time_in_pipeline_days: pipeline.avg_time_in_pipeline_days,
    stage_statistics: pipeline.stages.map((stage) => ({
      stage_id: stage.id,
      stage_name: stage.name,
      lead_count: stage.lead_count,
      stage_distribution_pct: stage.stage_distribution_pct ?? 0,
    })),
  }
}

// ============================================
// ALLOWED TRANSITIONS OPERATIONS (Admin Only)
// ============================================

// Re-export types for convenience
export type AllowedTransition = AllowedTransitionType
export type AllowedTransitionCreate = AllowedTransitionCreateType

/**
 * Get all allowed transitions
 * Admin only
 *
 * @throws {AxiosError} 403 if not admin
 */
export async function getAllowedTransitions(): Promise<AllowedTransition[]> {
  const response = await api.get<AllowedTransition[]>(
    '/api/admin/allowed-transitions'
  )
  return response.data
}

/**
 * Create new allowed transition (FSM v3.0)
 * Admin only
 *
 * @throws {AxiosError} 403 if not admin, 422 for validation errors
 *
 * @example
 * ```ts
 * const transition = await pipelineApi.createAllowedTransition({
 *   from_status_id: 'sts00',
 *   to_status_id: 'sts02',
 *   trigger_type: 'user',
 *   required_phase: 'consultation',
 *   description: 'Contact lead'
 * })
 * ```
 */
export async function createAllowedTransition(
  data: AllowedTransitionCreate
): Promise<AllowedTransition> {
  const response = await api.post<AllowedTransition>(
    '/api/admin/allowed-transitions',
    data
  )
  return response.data
}

/**
 * Delete allowed transition
 * Admin only
 *
 * @throws {AxiosError} 404 if not found, 403 if not admin
 */
export async function deleteAllowedTransition(
  transitionId: number
): Promise<SuccessResponse> {
  const response = await api.delete<SuccessResponse>(
    `/api/admin/allowed-transitions/${transitionId}`
  )
  return response.data
}

// ============================================
// CACHE INVALIDATION
// ============================================

/**
 * Invalidate pipeline cache (admin only)
 * Forces fresh data load on next request
 *
 * @throws {AxiosError} 403 if not admin
 */
export async function invalidatePipelineCache(): Promise<SuccessResponse> {
  const response = await api.post<SuccessResponse>(
    '/api/admin/pipeline/invalidate-cache'
  )
  return response.data
}

// ============================================
// AGGREGATED EXPORTS
// ============================================

/**
 * Pipeline API object with all methods
 * Preferred way to import for better tree-shaking
 */
export const pipelineApi = {
  // Public: Stages
  getStages,
  getFullPipeline,
  getAllowedNextStatuses,

  // Admin: Stage Management
  createStage,
  updateStage,
  deleteStage,

  // Admin: Consultation Status Management
  getConsultationStatuses,
  getConsultationStatus,
  createConsultationStatus,
  updateConsultationStatus,
  deleteConsultationStatus,

  // Admin: Allowed Transitions Management
  getAllowedTransitions,
  createAllowedTransition,
  deleteAllowedTransition,

  // Lead Pipeline Operations
  moveLeadToStage,
  getLeadsInStage,

  // Admin: Revert
  revertLeadStatus,

  // Analytics
  getPipelineStats,

  // Cache
  invalidatePipelineCache,
}

// Default export for convenience
export default pipelineApi
