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
} from '@/lib/zod/admissions'

// ============================================
// ADMISSION CRUD OPERATIONS
// ============================================

/**
 * Get list of admissions with pagination and filters
 */
export async function listAdmissions(
  params?: { page?: number; page_size?: number; status?: string }
): Promise<AdmissionProfileResponse[]> {
  const response = await api.get<AdmissionProfileResponse[]>('/api/admissions', { params })
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
 * Upload admission document
 */
export async function uploadAdmissionDocument(
  id: number,
  docCode: string,
  file: File
): Promise<any> {
    const formData = new FormData()
    formData.append("file", file)
    
    // Note: No explicit Content-Type header needed, axios/browser sets it with boundary
    const response = await api.post(
        `/api/admissions/${id}/documents/${docCode}/upload`, 
        formData
    )
    return response.data
}

// ============================================
// EXPORT DEFAULT OBJECT (Lead Pattern)
// ============================================

export const admissionsApi = {
  listAdmissions,
  getAdmission,
  createAdmission,
  updateAdmission,
  submitAdmission,
  enrollStudent,
  deleteAdmission,
  uploadAdmissionDocument,
}

export default admissionsApi
