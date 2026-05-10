/**
 * Admission Paths API Client
 * API functions for Admission Configuration Console
 * 
 * Phase 2.2: API Client implementation
 */

import { api } from '@/lib/api/client'
import type {
  AcademicYearListResponse,
  AdmissionPathCreate,
  AdmissionPathResponse,
  AdmissionPathUpdate,
  AdmissionCriteriaCreate,
  AdmissionPathDocumentUpsert,
  ActivationValidationResponse,
  ResolvedDocumentResponse,
  ResolvedDocumentListResponse,
} from '@/lib/zod/admission-path'
import type { CoverageMatrixResponse } from '@/app/(dashboard)/admin/admission-config/_components/shared/types'

// ============================================
// ACADEMIC YEARS
// ============================================

/**
 * Get all distinct academic years
 */
export async function getAcademicYears(): Promise<AcademicYearListResponse> {
  const response = await api.get<AcademicYearListResponse>('/api/admission-config/years')
  return response.data
}

// ============================================
// ADMISSION PATHS CRUD
// ============================================

/**
 * List admission paths for a specific academic info
 */
export async function listAdmissionPaths(
  academicInfoId: number
): Promise<{ total: number; items: AdmissionPathResponse[] }> {
  const response = await api.get<{ total: number; items: AdmissionPathResponse[] }>('/api/admission-config/paths', {
    params: { academic_info_id: academicInfoId }
  })
  return response.data
}

/**
 * Get ACTIVE admission paths for a ProgramOffering
 * Used by LeadApplicationForm dropdown
 */
export async function getPathsForOffering(
  offeringId: number
): Promise<AdmissionPathResponse[]> {
  const response = await api.get<{ items: AdmissionPathResponse[] }>(
    `/api/admission-config/paths/for-offering/${offeringId}`
  )
  return response.data.items
}

/**
 * Get single admission path by ID
 */
export async function getAdmissionPath(pathId: number): Promise<AdmissionPathResponse> {
  const response = await api.get<AdmissionPathResponse>(`/api/admission-config/paths/${pathId}`)
  return response.data
}

/**
 * Create new admission path (draft status)
 */
export async function createAdmissionPath(
  data: AdmissionPathCreate
): Promise<AdmissionPathResponse> {
  const response = await api.post<AdmissionPathResponse>('/api/admission-config/paths', data)
  return response.data
}

/**
 * Update admission path
 * Note: Manager can only update draft paths, Admin can update any non-archived
 */
export async function updateAdmissionPath(
  pathId: number,
  data: AdmissionPathUpdate
): Promise<AdmissionPathResponse> {
  const response = await api.put<AdmissionPathResponse>(
    `/api/admission-config/paths/${pathId}`,
    data
  )
  return response.data
}

/**
 * Update Admission Criteria
 */
export async function updateCriteria(
  pathId: number,
  data: AdmissionCriteriaCreate
): Promise<AdmissionPathResponse> {
  const response = await api.put<AdmissionPathResponse>(
    `/api/admission-config/paths/${pathId}/criteria`,
    data
  )
  return response.data
}

/**
 * Update Path Document Requirements
 */
export async function updatePathDocuments(
  pathId: number,
  data: AdmissionPathDocumentUpsert[]
): Promise<ResolvedDocumentListResponse> { // Returns Resolved List
  const response = await api.put<ResolvedDocumentListResponse>(
    `/api/admission-config/paths/${pathId}/documents`,
    data // List[AdmissionPathDocumentUpsert]
  )
  return response.data
}

// ============================================
// ACTIVATION / DEACTIVATION (Admin only)
// ============================================

/**
 * Activate an admission path
 * Requires all validation checks to pass
 */
export async function activateAdmissionPath(
  pathId: number
): Promise<AdmissionPathResponse> {
  const response = await api.post<AdmissionPathResponse>(
    `/api/admission-config/paths/${pathId}/activate`
  )
  return response.data
}

/**
 * Deactivate an admission path
 */
export async function deactivateAdmissionPath(
  pathId: number
): Promise<AdmissionPathResponse> {
  const response = await api.post<AdmissionPathResponse>(
    `/api/admission-config/paths/${pathId}/deactivate`
  )
  return response.data
}

// ============================================
// VALIDATION & DOCUMENTS
// ============================================

/**
 * Validate if path can be activated
 * Returns can_activate and validation_errors
 */
export async function validatePathActivation(
  pathId: number
): Promise<ActivationValidationResponse> {
  const response = await api.get<ActivationValidationResponse>(
    `/api/admission-config/paths/${pathId}/validate-activation`
  )
  return response.data
}

/**
 * Get resolved document requirements for a path
 * Applies document override resolution rule:
 * - Method-specific overrides shared (admission_method_id = NULL)
 */
export async function getPathDocuments(
  pathId: number
): Promise<ResolvedDocumentResponse[]> {
  const response = await api.get<ResolvedDocumentListResponse>(
    `/api/admission-config/paths/${pathId}/documents`
  )
  return response.data.documents
}

// ============================================
// COVERAGE MATRIX (Phase 2.5)
// ============================================

/**
 * Get coverage matrix for a specific academic info
 */
export async function getCoverageMatrix(
  academicInfoId: number
): Promise<CoverageMatrixResponse> {
  const response = await api.get<CoverageMatrixResponse>('/api/admission-config/coverage-matrix', {
    params: { academic_info_id: academicInfoId }
  })
  return response.data
}

// ============================================
// PHASE 2 v8.2 PR-2D.1 — QuotaMatrix per-path quota PATCH
// ============================================

export interface AdmissionPathQuotaUpdate {
  round_quota: number | null
  admit_quota: number | null
}

/**
 * Update path quota fields (round_quota + admit_quota) cho QuotaMatrix
 * inline edit. Tier 1+2 chain re-validated server-side.
 *
 * BusinessRuleViolation raised từ backend nếu chain violated.
 */
export async function updatePathQuota(
  pathId: number,
  data: AdmissionPathQuotaUpdate
): Promise<AdmissionPathResponse> {
  const response = await api.patch<AdmissionPathResponse>(
    `/api/v2/admin/admission-paths/${pathId}/quota`,
    data
  )
  return response.data
}


// ============================================
// EXPORT DEFAULT OBJECT
// ============================================

export const admissionPathsApi = {
  // Academic Years
  getAcademicYears,
  // CRUD
  listAdmissionPaths,
  getPathsForOffering,
  getAdmissionPath,
  createAdmissionPath,
  updateAdmissionPath,
  updateCriteria,
  updatePathDocuments,
  // Actions (Admin only)
  activateAdmissionPath,
  deactivateAdmissionPath,
  // Validation & Documents
  validatePathActivation,
  getPathDocuments,
  // Matrix
  getCoverageMatrix,
  // Phase 2 v8.2 PR-2D.1
  updatePathQuota,
}

export default admissionPathsApi
