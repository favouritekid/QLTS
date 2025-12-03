/**
 * API Client for Admission Module
 *
 * Provides typed API functions for AdmissionProfile workflow.
 * All functions use axios client with auto-refresh and httpOnly cookies.
 *
 * Architecture:
 * - Uses axios instance from @/lib/api/client
 * - Returns typed responses (Zod schemas for runtime validation)
 * - Error handling via axios interceptors
 *
 * Endpoints:
 * - POST /api/admissions - Create admission profile
 * - GET /api/admissions/{id} - Get admission profile
 * - PUT /api/admissions/{id} - Update admission profile (draft only)
 * - POST /api/admissions/{id}/submit - Submit for evaluation
 * - POST /api/admissions/{id}/enroll - Enroll student
 */

import { api } from "@/lib/api/client"
import type {
  AdmissionProfileCreate,
  AdmissionProfileResponse,
  AdmissionProfileUpdate,
  AdmissionSubmitResponse,
  EnrollStudentResponse,
} from "@/lib/zod/admissions"

// ==============================================================================
// API FUNCTIONS
// ==============================================================================

/**
 * Create new AdmissionProfile for a Lead
 *
 * @param data - { lead_id: number }
 * @returns Created AdmissionProfile with status='draft'
 *
 * @example
 * ```ts
 * const profile = await createAdmission({ lead_id: 123 })
 * console.log(profile.status) // 'draft'
 * console.log(profile.documents_checklist) // Auto-generated from mandatory_docs
 * ```
 */
export async function createAdmission(
  data: AdmissionProfileCreate
): Promise<AdmissionProfileResponse> {
  const response = await api.post<AdmissionProfileResponse>(
    "/api/admissions",
    data
  )
  return response.data
}

/**
 * Get AdmissionProfile by ID
 *
 * @param id - AdmissionProfile ID
 * @returns AdmissionProfile with relationships (lead, student)
 *
 * @throws 404 - Profile not found
 * @throws 403 - User doesn't have access (IDOR protection)
 *
 * @example
 * ```ts
 * const profile = await getAdmission(456)
 * console.log(profile.lead.full_name)
 * console.log(profile.status) // 'draft' | 'approved' | 'rejected' | 'enrolled'
 * ```
 */
export async function getAdmission(
  id: number
): Promise<AdmissionProfileResponse> {
  const response = await api.get<AdmissionProfileResponse>(
    `/api/admissions/${id}`
  )
  return response.data
}

/**
 * Update AdmissionProfile (only when status='draft')
 *
 * @param id - AdmissionProfile ID
 * @param data - Partial update data
 * @returns Updated AdmissionProfile
 *
 * @throws 404 - Profile not found
 * @throws 403 - User doesn't have access
 * @throws 400 - Profile is not in draft status
 *
 * @example
 * ```ts
 * const updated = await updateAdmission(456, {
 *   citizen_id: "001234567890",
 *   family_info: [
 *     { relationship: "father", full_name: "Nguyen Van A", ... }
 *   ],
 *   admission_scores: { gpa: 8.5, math_score: 9.0 }
 * })
 * ```
 */
export async function updateAdmission(
  id: number,
  data: AdmissionProfileUpdate
): Promise<AdmissionProfileResponse> {
  const response = await api.put<AdmissionProfileResponse>(
    `/api/admissions/${id}`,
    data
  )
  return response.data
}

/**
 * Submit AdmissionProfile for auto-evaluation
 *
 * Validates against snapshot applied_rules:
 * - GPA >= min_gpa
 * - All mandatory_docs uploaded
 * - citizen_id unique
 *
 * @param id - AdmissionProfile ID
 * @returns { status: "approved"|"rejected", message?, errors? }
 *
 * @throws 404 - Profile not found
 * @throws 403 - User doesn't have access
 * @throws 400 - Profile is not in draft status
 *
 * @example
 * ```ts
 * const result = await submitAdmission(456)
 * if (result.status === "approved") {
 *   console.log(result.message) // "Hồ sơ đã được duyệt tự động"
 * } else {
 *   console.log(result.errors) // ["GPA không đạt yêu cầu", ...]
 * }
 * ```
 */
export async function submitAdmission(
  id: number
): Promise<AdmissionSubmitResponse> {
  const response = await api.post<AdmissionSubmitResponse>(
    `/api/admissions/${id}/submit`
  )
  return response.data
}

/**
 * Enroll student (create Student + StudentDocument records)
 *
 * ACID transaction:
 * - Generate unique student_code (SV + YYYY + random)
 * - Create Student record
 * - Create StudentDocument records
 * - Update AdmissionProfile.status = 'enrolled'
 * - Update Lead.status = 'converted'
 *
 * @param id - AdmissionProfile ID
 * @returns { student_id, student_code, enrollment_date }
 *
 * @throws 404 - Profile not found
 * @throws 403 - User doesn't have access
 * @throws 400 - Profile is not approved
 * @throws 409 - Unique constraint violation (student_code or citizen_id)
 * @throws 429 - Rate limit exceeded (10 req/min)
 *
 * @example
 * ```ts
 * const result = await enrollStudent(456)
 * console.log(result.student_code) // "SV20250034"
 * console.log(result.student_id) // 789
 * // Navigate to student profile: /students/{result.student_id}
 * ```
 */
export async function enrollStudent(
  id: number
): Promise<EnrollStudentResponse> {
  const response = await api.post<EnrollStudentResponse>(
    `/api/admissions/${id}/enroll`
  )
  return response.data
}

// ==============================================================================
// HELPER FUNCTIONS (optional, for convenience)
// ==============================================================================

/**
 * Check if profile can be updated
 * (status must be 'draft')
 */
export function canUpdateProfile(status: string): boolean {
  return status === "draft"
}

/**
 * Check if profile can be submitted
 * (status must be 'draft')
 */
export function canSubmitProfile(status: string): boolean {
  return status === "draft"
}

/**
 * Check if profile can be enrolled
 * (status must be 'approved')
 */
export function canEnrollStudent(status: string): boolean {
  return status === "approved"
}

/**
 * Get next action based on status
 */
export function getNextAction(status: string): string {
  switch (status) {
    case "draft":
      return "Hoàn thiện hồ sơ và nộp"
    case "approved":
      return "Nhập học"
    case "rejected":
      return "Xem lại và sửa"
    case "enrolled":
      return "Đã hoàn tất"
    default:
      return "Không xác định"
  }
}
