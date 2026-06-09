/**
 * Leads API Client
 * API functions for Lead Management
 * Uses axios client with auto-refresh interceptors
 */

import { api } from './client'
import type {
  Lead,
  LeadDetail,
  LeadCreate,
  LeadUpdate,
  AssignLead,
  BulkAssignLeads,
  BulkAssignResult,
  LeadAction,
  LeadsPage,
  LeadListParams,
  Consultation,
  ConsultationCreate,
  ConsultationCreateResult,
  ConsultationUpdate,
  BulkUpdateStageResult,
  TimelineItem,
  LeadInsights,

  LeadImportResult,
} from '@/types/lead.types'

export interface ReassignQuota {
  // ✅ T5 FIX: Match backend contract { allowed, used, limit, remaining }
  allowed: boolean;
  used: number;
  limit: number;
  remaining: number;
}

// ============================================
// LEAD CRUD OPERATIONS
// ============================================

/**
 * Get list of leads with pagination, filtering, search, and sorting
 *
 * @example
 * ```ts
 * const leads = await leadsApi.getLeads({
 *   page: 1,
 *   page_size: 10,
 *   status: 'new,assigned',
 *   search: 'nguyen',
 *   sort_by: 'created_at',
 *   order: 'desc'
 * })
 * ```
 */
export async function getLeads(params?: LeadListParams): Promise<LeadsPage> {
  const response = await api.get<LeadsPage>('/api/leads', { params })
  return response.data
}

/**
 * Get single lead by ID.
 *
 * Backend returns `LeadDetail` (Lead + permissions/available_actions/action_blockers).
 * These thin-client gate fields are populated only on this endpoint —
 * list/create/update endpoints return plain `Lead`.
 *
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 */
export async function getLead(leadId: number): Promise<LeadDetail> {
  const response = await api.get<LeadDetail>(`/api/leads/${leadId}`)
  return response.data
}

/**
 * Create new lead
 *
 * @throws {AxiosError} 422 for validation errors
 *
 * @example
 * ```ts
 * const newLead = await leadsApi.createLead({
 *   full_name: 'Nguyen Van A',
 *   email: 'nguyenvana@example.com',
 *   phone: '0901234567',
 *   source: 'website',
 *   unit_id: 1,
 * })
 * ```
 */
export async function createLead(data: LeadCreate): Promise<Lead> {
  const response = await api.post<Lead>('/api/leads', data)
  return response.data
}

/**
 * Update existing lead
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission, 422 for validation
 */
export async function updateLead(
  leadId: number,
  data: LeadUpdate
): Promise<Lead> {
  const response = await api.put<Lead>(`/api/leads/${leadId}`, data)
  return response.data
}

/**
 * Delete lead (admin only)
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission
 */
export async function deleteLead(leadId: number): Promise<void> {
  await api.delete(`/api/leads/${leadId}`)
}

// ============================================
// LEAD ASSIGNMENT OPERATIONS
// ============================================

/**
 * Assign lead to officer (manual assignment)
 *
 * @throws {AxiosError} 404 if lead/officer not found, 403 if no permission
 *
 * @example
 * ```ts
 * const assigned = await leadsApi.assignLead(123, {
 *   officer_id: 5,
 *   reason: 'Has expertise in this program'
 * })
 * ```
 */
export async function assignLead(
  leadId: number,
  data: AssignLead
): Promise<Lead> {
  const response = await api.post<Lead>(`/api/leads/${leadId}/assign`, data)
  return response.data
}

/**
 * Get reassign quota for current user
 */
export async function getReassignQuota(): Promise<ReassignQuota> {
  const response = await api.get<ReassignQuota>('/api/leads/my/reassign-quota')
  return response.data
}

/**
 * Bulk assign leads to a specific officer
 * Sends officer_id as query param, lead_ids in request body
 *
 * @throws {AxiosError} 403 if not admin/manager
 *
 * @example
 * ```ts
 * await leadsApi.bulkAssignLeads({
 *   lead_ids: [1, 2, 3],
 *   officer_id: 5,
 * })
 * ```
 */
export async function bulkAssignLeads(
  data: BulkAssignLeads
): Promise<BulkAssignResult> {
  if (!data.officer_id) throw new Error("officer_id is required for bulk assign");
  const response = await api.post<BulkAssignResult>(
    '/api/leads/bulk-assign',
    { lead_ids: data.lead_ids },
    { params: { officer_id: data.officer_id } }
  )
  return response.data
}

/**
 * Bulk update leads pipeline stage
 * Admin only endpoint
 *
 * @throws {AxiosError} 403 if not admin
 *
 * @example
 * ```ts
 * await leadsApi.bulkUpdateLeadsStage({
 *   lead_ids: [1, 2, 3],
 *   pipeline_stage_id: 'stage_2'
 * })
 * ```
 */
export async function bulkUpdateLeadsStage(
  data: { lead_ids: number[]; pipeline_stage_id: string }
): Promise<BulkUpdateStageResult> {
  const response = await api.post<BulkUpdateStageResult>(
    '/api/leads/bulk-update-stage',
    data
  )
  return response.data
}

/**
 * Bulk delete leads
 * Admin only endpoint
 *
 * @throws {AxiosError} 403 if not admin
 *
 * @example
 * ```ts
 * await leadsApi.bulkDeleteLeads({
 *   lead_ids: [1, 2, 3]
 * })
 * ```
 */
export async function bulkDeleteLeads(
  data: { lead_ids: number[] }
): Promise<{ message: string; deleted_count: number }> {
  const response = await api.post<{ message: string; deleted_count: number }>(
    '/api/leads/bulk-delete',
    data
  )
  return response.data
}

// ============================================
// LEAD ACTIONS
// ============================================

/**
 * Perform action on lead (reject, reassign, convert)
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission
 *
 * @example
 * ```ts
 * // Reject lead
 * await leadsApi.performLeadAction(123, {
 *   action: 'reject',
 *   reason: 'Not qualified'
 * })
 *
 * // Reassign lead
 * await leadsApi.performLeadAction(123, {
 *   action: 'reassign',
 *   new_officer_id: 7,
 *   reason: 'Officer on leave'
 * })
 * ```
 */
export async function performLeadAction(
  leadId: number,
  data: LeadAction
): Promise<Lead> {
  const response = await api.post<Lead>(`/api/leads/${leadId}/action`, data)
  return response.data
}

// ============================================
// CONSULTATION OPERATIONS
// ============================================

/**
 * Add consultation to lead
 *
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 *
 * @example
 * ```ts
 * const consultation = await leadsApi.addConsultation(123, {
 *   consultation_date: '2025-01-20T10:00:00Z',
 *   method: 'phone',
 *   notes: 'Interested in Business Admin program',
 *   outcome: 'interested',
 *   duration_minutes: 30
 * })
 * ```
 */
export async function addConsultation(
  leadId: number,
  data: ConsultationCreate
): Promise<ConsultationCreateResult> {
  const response = await api.post<ConsultationCreateResult>(
    `/api/leads/${leadId}/consultations`,
    data
  )
  return response.data
}

/**
 * Reopen a consultation-terminal lead (sts20 → sts04). Manager/admin only.
 *
 * Backend re-opens the lead, sets the re-engage marker so the SLA beat can
 * auto-close it again later. Returns the updated lead.
 *
 * @throws {AxiosError} 400 if lead not in a consultation-terminal state,
 *   404 if lead not found / out of IDOR scope, 403 if not allowed (Casbin).
 */
export async function reopenLead(
  leadId: number,
  data: { reason: string }
): Promise<Lead> {
  const response = await api.post<Lead>(`/api/leads/${leadId}/reopen`, data)
  return response.data
}

/** Một yêu cầu mở lại (Phase B) — officer xin, manager/admin duyệt. */
export interface ReopenRequestItem {
  id: number
  lead_id: number
  requested_by_id: number
  reason: string
  status: "pending" | "approved" | "rejected" | "cancelled"
  reviewed_by_id: number | null
  review_note: string | null
  created_at: string
  reviewed_at: string | null
  unit_id: number
  lead_name: string | null
  requested_by_name: string | null
  reviewed_by_name: string | null
}

/** Officer XIN mở lại lead (chờ duyệt). */
export async function createReopenRequest(
  leadId: number,
  data: { reason: string }
): Promise<ReopenRequestItem> {
  const r = await api.post<ReopenRequestItem>(
    `/api/leads/${leadId}/reopen-requests`,
    data
  )
  return r.data
}

/** Inbox duyệt (manager/admin) — IDOR-scoped ở backend. */
export async function listReopenRequests(
  status?: string
): Promise<ReopenRequestItem[]> {
  const r = await api.get<ReopenRequestItem[]>("/api/reopen-requests", {
    params: status ? { status } : undefined,
  })
  return r.data
}

export async function approveReopenRequest(
  requestId: number,
  data?: { note?: string }
): Promise<ReopenRequestItem> {
  const r = await api.post<ReopenRequestItem>(
    `/api/reopen-requests/${requestId}/approve`,
    data ?? {}
  )
  return r.data
}

export async function rejectReopenRequest(
  requestId: number,
  data: { note: string }
): Promise<ReopenRequestItem> {
  const r = await api.post<ReopenRequestItem>(
    `/api/reopen-requests/${requestId}/reject`,
    data
  )
  return r.data
}

/** Officer hủy yêu cầu pending của chính mình. */
export async function cancelReopenRequest(
  requestId: number
): Promise<ReopenRequestItem> {
  const r = await api.delete<ReopenRequestItem>(
    `/api/reopen-requests/${requestId}`
  )
  return r.data
}

/**
 * Update consultation (admin: all, officer: most recent only)
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission
 */
export async function updateConsultation(
  leadId: number,
  consultationId: number,
  data: ConsultationUpdate
): Promise<Consultation> {
  const response = await api.put<Consultation>(
    `/api/leads/${leadId}/consultations/${consultationId}`,
    data
  )
  return response.data
}

/**
 * Delete consultation (admin: all, officer: most recent only)
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission
 */
export async function deleteConsultation(
  leadId: number,
  consultationId: number
): Promise<void> {
  await api.delete(`/api/leads/${leadId}/consultations/${consultationId}`)
}

/**
 * Restore a soft-deleted consultation
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission
 */
export async function restoreConsultation(
  leadId: number,
  consultationId: number
): Promise<Consultation> {
  const response = await api.post<Consultation>(
    `/api/leads/${leadId}/consultations/${consultationId}/restore`
  )
  return response.data
}

// ============================================
// LEAD DATA ACCESS
// ============================================

/**
 * Get lead timeline (all activities)
 *
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 *
 * @example
 * ```ts
 * const timeline = await leadsApi.getLeadTimeline(123)
 * // Returns array of timeline items (status changes, consultations, etc.)
 * ```
 */
export async function getLeadTimeline(leadId: number): Promise<TimelineItem[]> {
  const response = await api.get<TimelineItem[]>(`/api/leads/${leadId}/timeline`)
  return response.data
}

/**
 * Get lead insights (360-degree view)
 *
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 *
 * @example
 * ```ts
 * const insights = await leadsApi.getLeadInsights(123)
 * // Returns: lead_score_breakdown, engagement_metrics, conversion_probability, etc.
 * ```
 */
export async function getLeadInsights(leadId: number): Promise<LeadInsights> {
  const response = await api.get<LeadInsights>(`/api/leads/${leadId}/insights`)
  return response.data
}

// ============================================
// WORKFLOW CONTEXT (Phase-Based Workflow)
// ============================================

import type { WorkflowContext } from '@/types/lead.types'

/**
 * Get workflow context for a lead - Phase-Based Workflow
 * 
 * Provides frontend with:
 * - Current phase (consultation, admission, fee, enrolled)
 * - Allowed statuses user can select
 * - Phase constraints and locked states
 * 
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 * 
 * @example
 * ```ts
 * const context = await leadsApi.getWorkflowContext(123)
 * // Filter status dropdown based on context.allowed_statuses
 * // Disable UI if context.is_terminal_phase
 * ```
 */
export async function getWorkflowContext(leadId: number): Promise<WorkflowContext> {
  const response = await api.get<WorkflowContext>(`/api/leads/${leadId}/workflow-context`)
  return response.data
}


// ============================================
// IMPORT/EXPORT OPERATIONS
// ============================================

/**
 * Import leads from CSV/Excel file
 * Admin only endpoint
 *
 * @throws {AxiosError} 403 if not admin, 422 for validation errors
 *
 * @example
 * ```ts
 * const fileInput = document.querySelector('input[type="file"]')
 * const file = fileInput.files[0]
 *
 * const result = await leadsApi.importLeads(file)
 * console.log(`Imported ${result.successful_imports} leads`)
 * console.log(`Failed ${result.failed_imports} rows`)
 * ```
 */
export async function importLeads(file: File): Promise<LeadImportResult> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await api.post<LeadImportResult>(
    '/api/leads/import',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  )
  return response.data
}

/**
 * Download import template (CSV/Excel)
 * Provides a pre-formatted template with correct headers for bulk import
 *
 * @param format - File format: 'csv' or 'xlsx'
 * @returns Blob of the template file
 *
 * @example
 * ```ts
 * const blob = await leadsApi.downloadImportTemplate('csv')
 * ```
 */
export async function downloadImportTemplate(format: 'csv' | 'xlsx' = 'csv'): Promise<Blob> {
  const response = await api.get('/api/leads/import/template', {
    params: { format },
    responseType: 'blob',
  })
  return response.data
}

/**
 * Export leads to CSV/Excel
 * Admin only endpoint
 *
 * @throws {AxiosError} 403 if not admin
 *
 * @example
 * ```ts
 * // Export all leads
 * const blob = await leadsApi.exportLeads()
 *
 * // Export filtered leads
 * const blob = await leadsApi.exportLeads({
 *   status: 'new,assigned',
 *   unit_id: 1
 * })
 *
 * // Download file
 * const url = window.URL.createObjectURL(blob)
 * const a = document.createElement('a')
 * a.href = url
 * a.download = 'leads.csv'
 * a.click()
 * ```
 */
export async function exportLeads(
  params?: LeadListParams,
  format: 'csv' | 'xlsx' = 'csv'
): Promise<Blob> {
  const response = await api.get('/api/leads/export', {
    params: { ...params, format },
    responseType: 'blob',
  })
  return response.data
}

// ============================================
// DISTRIBUTION PREVIEW
// ============================================

/**
 * Distribution preview response type
 */
export interface DistributionPreviewResponse {
  offering_id: number;
  has_config: boolean;
  next_unit_id: number | null;
  next_unit_name: string | null;
  configs: Array<{
    unit_id: number;
    unit_name: string;
    weight: number;
    priority: number;
  }>;
  total_slots: number;
  cursor_position: number | null;
}

/**
 * Get distribution preview for an offering
 * Shows which unit will receive the next lead based on distribution config
 *
 * @param offeringId - Program offering ID to preview
 * @returns Distribution preview data
 */
export async function getDistributionPreview(offeringId: number): Promise<DistributionPreviewResponse> {
  const response = await api.get<DistributionPreviewResponse>('/api/leads/distribution-preview', {
    params: { offering_id: offeringId }
  })
  return response.data
}

// ============================================
// REAL-TIME VALIDATION
// ============================================

export interface DuplicateCheckParams {
  phone?: string
  email?: string
  unit_id?: number
  exclude_id?: number  // For edit mode
}

export interface DuplicateCheckResult {
  phone_available: boolean
  email_available: boolean
  phone_conflict: string | null
  email_conflict: string | null
}

/**
 * Real-time duplicate check for phone/email
 *
 * - Phone: Checked globally (must be unique across ALL units)
 * - Email: Checked within same unit only
 *
 * @example
 * ```ts
 * const result = await leadsApi.checkDuplicate({ phone: '0901234567' })
 * if (!result.phone_available) {
 *   console.log(result.phone_conflict)  // "SĐT đã tồn tại: Nguyen Van A..."
 * }
 * ```
 */
export async function checkDuplicate(params: DuplicateCheckParams): Promise<DuplicateCheckResult> {
  const response = await api.get<DuplicateCheckResult>('/api/leads/check-duplicate', { params })
  return response.data
}

// ============================================
// AGGREGATED EXPORTS
// ============================================

/**
 * Leads API object with all methods
 * Preferred way to import for better tree-shaking
 */
export const leadsApi = {
  // CRUD
  getLeads,
  getLead,
  createLead,
  updateLead,
  deleteLead,

  // Assignment
  assignLead,
  bulkAssignLeads,
  getReassignQuota,
  bulkUpdateLeadsStage,
  bulkDeleteLeads,

  // Actions
  performLeadAction,

  // Consultations
  addConsultation,
  updateConsultation,
  deleteConsultation,
  restoreConsultation,

  // Reopen (Phase A)
  reopenLead,

  // Reopen request (Phase B)
  createReopenRequest,
  listReopenRequests,
  approveReopenRequest,
  rejectReopenRequest,
  cancelReopenRequest,

  // Data Access
  getLeadTimeline,
  getLeadInsights,
  getWorkflowContext,

  importLeads,
  downloadImportTemplate,
  exportLeads,

  // Distribution
  getDistributionPreview,

  // Validation
  checkDuplicate,
}

// Default export for convenience
export default leadsApi
