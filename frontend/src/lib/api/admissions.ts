/**
 * Admissions API Client
 * API functions for Admission Management
 * Uses axios client with auto-refresh interceptors
 */

import { api } from '@/lib/api/client'
import type {
  AdmissionProfileCreate,
  AdmissionProfileResponse,
  AdmissionProfileUpdate,
  AdmissionSubmitResponse,
  EnrollStudentResponse,
  AdmissionsPage,
  AdmissionListParams,
  AdmissionStatusCounts,
  AdmissionStats,
  BulkApproveRequest,
  BulkRejectRequest,
  BulkAssignRequest,
  BulkActionResponse,
} from '@/lib/zod/admissions'

// ============================================
// ADMISSION CRUD OPERATIONS
// ============================================

/**
 * Get list of admissions with pagination and filters
 */
export async function listAdmissions(
  params?: AdmissionListParams
): Promise<AdmissionsPage> {
  const response = await api.get<AdmissionsPage>('/api/admissions', { params })
  return response.data
}

/**
 * Get single admission profile by ID
 */
export async function getAdmission(id: number): Promise<AdmissionProfileResponse> {
  const response = await api.get<AdmissionProfileResponse>(`/api/admissions/${id}`)
  return response.data
}

/**
 * Create new admission profile
 */
export async function createAdmission(
  data: AdmissionProfileCreate
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>('/api/admissions', data)
  return response.data
}

/**
 * Update admission profile (draft only)
 */
export async function updateAdmission(
  id: number,
  data: AdmissionProfileUpdate
): Promise<AdmissionProfileResponse> {
  const response = await api.put<AdmissionProfileResponse>(`/api/admissions/${id}`, data)
  return response.data
}

// ============================================
// ADMISSION ACTIONS
// ============================================

/**
 * Submit admission profile
 */
export async function submitAdmission(
  id: number
): Promise<AdmissionSubmitResponse> {
  const response = await api.post<AdmissionSubmitResponse>(`/api/admissions/${id}/submit`)
  return response.data
}

/**
 * Enroll student
 */
export async function enrollStudent(
  id: number
): Promise<EnrollStudentResponse> {
  const response = await api.post<EnrollStudentResponse>(`/api/admissions/${id}/enroll`)
  return response.data
}

/**
 * Delete admission profile (draft only)
 */
export async function deleteAdmission(id: number): Promise<void> {
  await api.delete(`/api/admissions/${id}`)
}

/**
 * Approve admission profile (Manager/Admin action)
 * POST /api/admissions/{id}/approve
 * 
 * Transitions status from submitted/resubmitted → approved
 * Requires version for optimistic locking
 */
export async function approveAdmission(
  id: number,
  data: { notes?: string; version: number }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/approve`,
    data
  )
  return response.data
}

/**
 * Reject admission profile (Manager/Admin action)
 * POST /api/admissions/{id}/reject
 * 
 * Transitions status from submitted/resubmitted → rejected
 * Requires rejection reason and version for optimistic locking
 */
export async function rejectAdmission(
  id: number,
  data: { reason: string; version: number }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/reject`,
    data
  )
  return response.data
}

/**
 * Upload admission document
 */
export interface DocumentUploadResponse {
  file_path: string;
  uploaded_at: string;
}

export async function uploadAdmissionDocument(
  id: number,
  docCode: string,
  file: File,
  actualSubmissionFormat?: string
): Promise<DocumentUploadResponse> {
    const formData = new FormData()
    formData.append("file", file)
    if (actualSubmissionFormat) {
      formData.append("actual_submission_format", actualSubmissionFormat)
    }

    // Note: No explicit Content-Type header needed, axios/browser sets it with boundary
    const response = await api.post<DocumentUploadResponse>(
        `/api/admissions/${id}/documents/${docCode}/upload`,
        formData
    )
    return response.data
}

// ============================================
// EXPORT DEFAULT OBJECT (Lead Pattern)
// ============================================

/**
 * Mark document as paper submitted (officer confirms receipt)
 */
export interface PaperSubmittedResponse {
  code: string
  status: string
  paper_submitted_at: string | null
  paper_submitted_by_id: number
}

export async function markPaperSubmitted(
  id: number,
  docCode: string,
  actualSubmissionFormat: string
): Promise<PaperSubmittedResponse> {
  const response = await api.post<PaperSubmittedResponse>(
    `/api/admissions/${id}/documents/${docCode}/paper-submitted`,
    { actual_submission_format: actualSubmissionFormat }
  )
  return response.data
}



/**
 * Verify document physical format (Officer action)
 */
export interface DocumentFormatVerifyResponse {
  code: string
  verified_format: string
  is_format_verified: boolean
}

export async function verifyDocumentFormat(
  id: number,
  docCode: string,
  format: string
): Promise<DocumentFormatVerifyResponse> {
  const response = await api.patch<DocumentFormatVerifyResponse>(
    `/api/admissions/${id}/documents/${docCode}/verify-format`,
    { format }
  )
  return response.data
}

/**
 * Reject document with reason
 */
export interface DocumentRejectResponse {
  code: string
  status: string
  rejection_reason: string
  rejected_at: string | null
  rejected_by_id: number
}

export async function rejectDocument(
  id: number,
  docCode: string,
  reason: string
): Promise<DocumentRejectResponse> {
  const response = await api.post<DocumentRejectResponse>(
    `/api/admissions/${id}/documents/${docCode}/reject`,
    { reason }
  )
  return response.data
}

/**
 * Reset document to missing status (undo submission)
 */
export interface DocumentResetResponse {
  code: string
  status: string
}

export async function resetDocument(
  id: number,
  docCode: string
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/documents/${docCode}/reset`
  )
  return response.data
}

// ============================================
// AGGREGATE ENDPOINTS
// ============================================

/**
 * Get distinct academic years with data
 * GET /api/admissions/academic-years
 */
export async function getAcademicYears(): Promise<number[]> {
  const response = await api.get<number[]>('/api/admissions/academic-years')
  return response.data
}

/**
 * Get status counts grouped by status (for tab badges)
 * GET /api/admissions/status-counts
 */
export async function getStatusCounts(
  params?: Omit<AdmissionListParams, 'page' | 'page_size' | 'status' | 'sort_by' | 'order'>
): Promise<AdmissionStatusCounts> {
  const response = await api.get<AdmissionStatusCounts>('/api/admissions/status-counts', { params })
  return response.data
}

/**
 * Get aggregate admission statistics
 * GET /api/admissions/stats
 */
export async function getAdmissionStats(
  params?: { academic_year?: number }
): Promise<AdmissionStats> {
  const response = await api.get<AdmissionStats>('/api/admissions/stats', { params })
  return response.data
}

// ============================================
// BULK ACTIONS
// ============================================

/**
 * Bulk approve multiple admission profiles
 * POST /api/admissions/bulk/approve
 *
 * Permissions: Manager or Admin only
 */
export async function bulkApproveAdmissions(
  data: BulkApproveRequest
): Promise<BulkActionResponse> {
  const response = await api.post<BulkActionResponse>(
    '/api/admissions/bulk/approve',
    data
  )
  return response.data
}

/**
 * Bulk reject multiple admission profiles
 * POST /api/admissions/bulk/reject
 *
 * Permissions: Manager or Admin only
 */
export async function bulkRejectAdmissions(
  data: BulkRejectRequest
): Promise<BulkActionResponse> {
  const response = await api.post<BulkActionResponse>(
    '/api/admissions/bulk/reject',
    data
  )
  return response.data
}

/**
 * Bulk assign multiple admission profiles to an officer
 * POST /api/admissions/bulk/assign
 *
 * Permissions: Manager or Admin only
 */
export async function bulkAssignAdmissions(
  data: BulkAssignRequest
): Promise<BulkActionResponse> {
  const response = await api.post<BulkActionResponse>(
    '/api/admissions/bulk/assign',
    data
  )
  return response.data
}

/**
 * Export admissions to CSV
 * GET /api/admissions/export
 *
 * Returns: Blob for file download
 */
export async function exportAdmissionsCsv(
  params?: Omit<AdmissionListParams, 'page' | 'page_size'>
): Promise<Blob> {
  const response = await api.get('/api/admissions/export', {
    params,
    responseType: 'blob',
  })
  return response.data
}

export const admissionsApi = {
  listAdmissions,
  getAdmission,
  createAdmission,
  updateAdmission,
  submitAdmission,
  approveAdmission,
  rejectAdmission,
  enrollStudent,
  deleteAdmission,
  uploadAdmissionDocument,
  markPaperSubmitted,
  verifyDocumentFormat,
  rejectDocument,
  resetDocument,
  // Aggregate
  getAcademicYears,
  getStatusCounts,
  getAdmissionStats,
  // Bulk actions
  bulkApproveAdmissions,
  bulkRejectAdmissions,
  bulkAssignAdmissions,
  exportAdmissionsCsv,
}

export default admissionsApi
