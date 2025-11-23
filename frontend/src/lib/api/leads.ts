/**
 * Leads API Client
 * API functions for Lead Management
 * Uses axios client with auto-refresh interceptors
 */

import { api } from './client'
import type {
  Lead,
  LeadCreate,
  LeadUpdate,
  AssignLead,
  BulkAssignLeads,
  LeadAction,
  LeadsPage,
  LeadListParams,
  Consultation,
  ConsultationCreate,
  ConsultationUpdate,
  TimelineItem,
  LeadInsights,
  LeadImportResult,
} from '@/types/lead.types'

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
 * Get single lead by ID
 *
 * @throws {AxiosError} 404 if lead not found, 403 if no permission
 */
export async function getLead(leadId: number): Promise<Lead> {
  const response = await api.get<Lead>(`/api/leads/${leadId}`)
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
 * Bulk assign leads to officer(s)
 * Admin only endpoint
 *
 * @throws {AxiosError} 403 if not admin
 *
 * @example
 * ```ts
 * // Auto-assign
 * await leadsApi.bulkAssignLeads({
 *   lead_ids: [1, 2, 3, 4, 5],
 *   method: 'automatic'
 * })
 *
 * // Manual assign to specific officer
 * await leadsApi.bulkAssignLeads({
 *   lead_ids: [1, 2, 3],
 *   officer_id: 5,
 *   method: 'manual'
 * })
 * ```
 */
export async function bulkAssignLeads(
  data: BulkAssignLeads
): Promise<{ message: string; assigned_count: number }> {
  const response = await api.post<{ message: string; assigned_count: number }>(
    '/api/admin/leads/bulk-assign',
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
): Promise<Consultation> {
  const response = await api.post<Consultation>(
    `/api/leads/${leadId}/consultations`,
    data
  )
  return response.data
}

/**
 * Update consultation (admin: any, officer: most recent only)
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
 * Delete consultation (admin: any, officer: most recent only)
 *
 * @throws {AxiosError} 404 if not found, 403 if no permission
 */
export async function deleteConsultation(
  leadId: number,
  consultationId: number
): Promise<void> {
  await api.delete(`/api/leads/${leadId}/consultations/${consultationId}`)
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
    '/api/admin/leads/import',
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
export async function exportLeads(params?: LeadListParams): Promise<Blob> {
  const response = await api.get('/api/admin/leads/export', {
    params,
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

  // Actions
  performLeadAction,

  // Consultations
  addConsultation,
  updateConsultation,
  deleteConsultation,

  // Data Access
  getLeadTimeline,
  getLeadInsights,

  // Import/Export
  importLeads,
  exportLeads,

  // Distribution
  getDistributionPreview,
}

// Default export for convenience
export default leadsApi
