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
} from '@/lib/zod/admissions'

// ============================================
// ADMISSION CRUD OPERATIONS
// ============================================

/**
 * Get list of admissions with pagination and filters
 */
export async function listAdmissions(
  params?: { page?: number; page_size?: number; status?: string }
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

export const admissionsApi = {
  listAdmissions,
  getAdmission,
  createAdmission,
  updateAdmission,
  submitAdmission,
  approveAdmission,  // ✅ NEW
  rejectAdmission,   // ✅ NEW
  enrollStudent,
  deleteAdmission,
  uploadAdmissionDocument,
  markPaperSubmitted,
  verifyDocumentFormat,
  rejectDocument,
  resetDocument,
}

export default admissionsApi
