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

/**
 * Record an application-fee cash payment.
 *
 * Backend contract intentionally uses query params, not a JSON body.
 */
export async function recordApplicationFeePayment(
  id: number,
  p: { transaction_id: string; amount: number; payment_method_code?: string }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/record-fee-payment`,
    null,
    {
      params: {
        transaction_id: p.transaction_id,
        amount: p.amount,
        payment_method_code: p.payment_method_code ?? "cash",
      },
    }
  )
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
 * Apply post-approval minor correction (Officer/Manager/Admin)
 * POST /api/admissions/{id}/minor-correction
 *
 * Allowed only on profiles in approved/confirmed status. Backend
 * enforces SAFE catalog ∩ AdmissionPath allowlist; FE renders fields
 * from ``profile.minor_correction_fields`` so the dialog never offers
 * a key the server would reject.
 */
export async function minorCorrection(
  id: number,
  data: { version: number; reason: string; changes: Record<string, unknown> }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/minor-correction`,
    data
  )
  return response.data
}

/**
 * Phase 3 multi-NV: Publish result — trigger engine cascade (Manager/Admin)
 * POST /api/v2/admissions/{id}/publish-result
 *
 * Engine xét tuần tự choices theo display_order, mark decision per NV,
 * transition profile.status (submitted/reviewing) → reviewing →
 * result_published → admitted/rejected. BE auto-transition
 * submitted→reviewing internal nếu cần (1-click flow per user
 * clarification 2026-05-15; bỏ T2 start-review explicit YAGNI).
 */
export async function publishAdmissionResult(
  id: number
): Promise<{
  profile_id: number
  final_status: string
  admitted_choice_id: number | null
  admitted_display_order: number | null
  per_choice_decisions: Array<{ choice_id: number; decision: string }>
}> {
  const response = await api.post<{
    profile_id: number
    final_status: string
    admitted_choice_id: number | null
    admitted_display_order: number | null
    per_choice_decisions: Array<{ choice_id: number; decision: string }>
  }>(`/api/v2/admissions/${id}/publish-result`, {})
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
 * Request revision on admission profile (Manager/Admin action)
 * POST /api/admissions/{id}/request-revision
 *
 * Transitions status from submitted/resubmitted → revision_requested
 * Requires reason and version for optimistic locking
 */
export async function requestRevision(
  id: number,
  data: { reason: string; version: number }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/request-revision`,
    data
  )
  return response.data
}

/**
 * Resubmit rejected admission profile (Officer action)
 * POST /api/admissions/{id}/resubmit
 *
 * Transitions status from rejected/revision_requested → resubmitted
 */
export async function resubmitAdmission(
  id: number,
  data: { version: number; notes?: string }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/resubmit`,
    data
  )
  return response.data
}

/**
 * Mark enrolled student as dropped out (Manager/Admin action)
 * POST /api/admissions/{id}/drop
 *
 * Side-channel: status stays "enrolled", sets is_dropped=true
 * Requires reason and version for optimistic locking
 */
export async function dropStudent(
  id: number,
  data: { reason: string; version: number }
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/drop`,
    data
  )
  return response.data
}

/**
 * Upload admission document
 */
export async function uploadAdmissionDocument(
  id: number,
  docCode: string,
  file: File,
  actualSubmissionFormat?: string
): Promise<AdmissionProfileResponse> {
    const formData = new FormData()
    formData.append("file", file)
    if (actualSubmissionFormat) {
      formData.append("actual_submission_format", actualSubmissionFormat)
    }

    // Note: No explicit Content-Type header needed, axios/browser sets it with boundary
    const response = await api.post<AdmissionProfileResponse>(
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
export async function markPaperSubmitted(
  id: number,
  docCode: string,
  actualSubmissionFormat: string,
  // PR #13 — only meaningful for bang_tot_nghiep_thpt; backend ignores them
  // on other doc codes. provisional_cert requires supplementDueDate.
  graduationProofKind?: "official_diploma" | "provisional_cert",
  supplementDueDate?: string
): Promise<AdmissionProfileResponse> {
  const body: Record<string, unknown> = {
    actual_submission_format: actualSubmissionFormat,
  }
  if (graduationProofKind) {
    body.graduation_proof_kind = graduationProofKind
    if (supplementDueDate) {
      body.supplement_due_date = supplementDueDate
    }
  }
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/documents/${docCode}/paper-submitted`,
    body
  )
  return response.data
}

/**
 * Update graduation proof kind (PR #13).
 *
 * Officer records that the candidate brought the official diploma after
 * previously submitting a provisional certificate. The document status is
 * NOT changed; the backend clears the supplement due date for official_diploma.
 */
export async function updateGraduationProof(
  id: number,
  docCode: string,
  kind: "official_diploma" | "provisional_cert"
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    `/api/admissions/${id}/documents/${docCode}/graduation-proof`,
    { kind }
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

/**
 * Get major programs that have admission profiles
 * GET /api/admission-config/programs
 */
export async function getAdmissionPrograms(): Promise<
  Array<{ id: number; name: string; code: string; degree_level: string }>
> {
  const response = await api.get('/api/admission-config/programs')
  return response.data
}

/**
 * Claim admission profile for review (Officer action)
 * POST /api/admissions/{id}/claim
 *
 * Assigns the current user as reviewer
 * Requires version for optimistic locking
 */
async function claimAdmissionProfile(id: number, data: { version: number }) {
  const response = await api.post(`/api/admissions/${id}/claim`, data)
  return response.data
}

/**
 * Unclaim admission profile (release review assignment)
 * POST /api/admissions/{id}/unclaim
 *
 * Removes the current user as reviewer
 * Requires version for optimistic locking
 */
async function unclaimAdmissionProfile(id: number, data: { version: number }) {
  const response = await api.post(`/api/admissions/${id}/unclaim`, data)
  return response.data
}

// ============================================
// MAGIC-LINK CONFIRMATION (Public flow)
// ============================================
// Backend exempts /api/admissions/confirm/* from CSRF (middleware/csrf.py:58),
// so the shared axios instance works for unauthenticated applicants.

import type {
  ConfirmTokenInfoResponse,
  ConfirmTokenResponse,
  ConfirmTokenVerifyRequest,
} from '@/lib/zod/admissions'

/**
 * GET /api/admissions/confirm/{token}
 * Returns token state so the page can render form / locked / expired / used banners.
 */
export async function getConfirmTokenInfo(
  token: string,
): Promise<ConfirmTokenInfoResponse> {
  const response = await api.get<ConfirmTokenInfoResponse>(
    `/api/admissions/confirm/${encodeURIComponent(token)}`,
  )
  return response.data
}

/**
 * POST /api/admissions/confirm/{token}
 * Verify last 4 CCCD digits → status transitions to 'confirmed'.
 */
export async function confirmAdmissionByToken(
  token: string,
  body: ConfirmTokenVerifyRequest,
): Promise<ConfirmTokenResponse> {
  const response = await api.post<ConfirmTokenResponse>(
    `/api/admissions/confirm/${encodeURIComponent(token)}`,
    body,
  )
  return response.data
}

export const admissionsApi = {
  listAdmissions,
  getAdmission,
  createAdmission,
  updateAdmission,
  recordApplicationFeePayment,
  submitAdmission,
  resubmitAdmission,
  requestRevision,
  approveAdmission,
  rejectAdmission,
  minorCorrection,
  dropStudent,
  enrollStudent,
  deleteAdmission,
  uploadAdmissionDocument,
  markPaperSubmitted,
  updateGraduationProof,
  verifyDocumentFormat,
  rejectDocument,
  resetDocument,
  // Aggregate & Config
  getAcademicYears,
  getStatusCounts,
  getAdmissionStats,
  getAdmissionPrograms,
  // Claim/unclaim
  claimAdmissionProfile,
  unclaimAdmissionProfile,
  // Bulk actions
  bulkApproveAdmissions,
  bulkRejectAdmissions,
  bulkAssignAdmissions,
  exportAdmissionsCsv,
  // Magic-link confirmation (public)
  getConfirmTokenInfo,
  confirmAdmissionByToken,
  // Phase 3 multi-NV publish (Wave 2 — declared in API + hook ngày trước
  // nhưng quên thêm vào export object → CI tsc bắt lỗi
  // `Property 'publishAdmissionResult' does not exist`)
  publishAdmissionResult,
}

export default admissionsApi
