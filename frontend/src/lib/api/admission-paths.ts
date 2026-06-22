/**
 * Admission Paths API Client
 * API functions for Admission Configuration Console
 * 
 * Phase 2.2: API Client implementation
 */

import { api } from '@/lib/api/client'
import type {
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
// ADMISSION PATHS CRUD
// ============================================
// NOTE (PR matrix-funnel cleanup): `getAcademicYears` + `listAdmissionPaths`
// đã gỡ — 0 consumer sau khi PR-2 hợp nhất matrix flow (năm lấy từ
// admissions.ts getAcademicYears; danh sách path lấy qua per-major matrix).

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

/**
 * Archive (soft-delete) a draft or inactive admission path → "archived".
 * Active paths must be deactivated first. Archived is terminal & immutable.
 */
export async function archiveAdmissionPath(
  pathId: number
): Promise<AdmissionPathResponse> {
  const response = await api.post<AdmissionPathResponse>(
    `/api/admission-config/paths/${pathId}/archive`
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
// PHASE 3 MULTI-NV ADD-CHOICE DIALOG SUPPORT
// ============================================

/**
 * List active paths in a round (multi-NV AddChoiceDialog dropdown).
 * Cross-academic_info — candidate có thể thêm NV ở ngành khác cùng đợt.
 */
export async function getPathsByRound(
  roundId: number,
  profileId?: number,
): Promise<{ total: number; items: AdmissionPathResponse[] }> {
  // profileId (optional): BE lọc phương thức theo trình độ văn hóa
  // (cultural_education_level) của hồ sơ → TN THCS không thấy đường yêu cầu
  // THPT. Bỏ trống / hồ sơ chưa khai trình độ → BE không lọc.
  const response = await api.get<{ total: number; items: AdmissionPathResponse[] }>(
    `/api/admission-config/paths/by-round/${roundId}`,
    profileId != null ? { params: { profile_id: profileId } } : undefined,
  )
  return response.data
}

/** Subject in a sg_config (nested response from BE custom shape). */
export interface PathSubjectGroupConfigSubject {
  subject_id: number
  subject_code: string
  subject_name: string
  max_score: number
  min_possible_score: number
  position: number
}

/** Sg_config with nested subjects (multi-NV AddChoiceDialog dropdown 2). */
export interface PathSubjectGroupConfigForChoice {
  id: number
  admission_path_id: number
  subject_group_id: number
  subject_group_code: string | null
  subject_group_name: string | null
  min_score: number | null
  min_subject_score: number | null
  group_quota: number | null
  subjects: PathSubjectGroupConfigSubject[]
}

/**
 * List sg_configs of a path with nested subjects (multi-NV AddChoiceDialog).
 * User picks 1 sg_config → render N score inputs per subjects[].
 */
export async function getPathSubjectGroupConfigs(
  pathId: number
): Promise<{ total: number; items: PathSubjectGroupConfigForChoice[] }> {
  const response = await api.get<{
    total: number
    items: PathSubjectGroupConfigForChoice[]
  }>(`/api/admission-config/paths/${pathId}/subject-group-configs`)
  return response.data
}

// ============================================
// ADMIN — PATH SUBJECT GROUP CONFIG CRUD (#7 "Tổ hợp môn" tab)
// ============================================
// Separate types from PathSubjectGroupConfigForChoice (officer GET) — that
// shape feeds AddChoiceDialog and must stay untouched. Scores arrive as JSON
// number (BE serializes Decimal→float; see admin GET).

const ADMIN_SG_BASE = '/api/v2/admin'

/** Item of an admin sg_config (principal + per-item min score). */
export interface PathSubjectGroupItemAdmin {
  id: number
  path_subject_group_config_id: number
  subject_group_subject_id: number
  is_principal: boolean
  min_subject_score: number | null
}

/** Subject of the config's subject_group (for the principal-item picker). */
export interface PathSubjectGroupConfigSubjectAdmin {
  subject_id: number
  subject_code: string
  subject_name: string
  subject_group_subject_id: number
  max_score: number
  min_possible_score: number
  position: number
}

/** Enriched admin config: subject_group label + items + subjects. */
export interface PathSubjectGroupConfigAdmin {
  id: number
  admission_path_id: number
  subject_group_id: number
  subject_group_code: string | null
  subject_group_name: string | null
  min_score: number | null
  min_subject_score: number | null
  group_quota: number | null
  items: PathSubjectGroupItemAdmin[]
  subjects: PathSubjectGroupConfigSubjectAdmin[]
}

/** Base config returned by POST/PATCH (no enrichment — FE refetches list). */
export interface PathSubjectGroupConfigBaseResponse {
  id: number
  admission_path_id: number
  subject_group_id: number
  min_score: number | null
  min_subject_score: number | null
  group_quota: number | null
  items: PathSubjectGroupItemAdmin[]
}

export interface PathSubjectGroupItemPayload {
  subject_group_subject_id: number
  is_principal?: boolean
  min_subject_score?: number | null
}

export interface PathSubjectGroupConfigCreatePayload {
  subject_group_id: number
  min_score?: number | null
  min_subject_score?: number | null
  group_quota?: number | null
  items?: PathSubjectGroupItemPayload[]
}

export interface PathSubjectGroupConfigUpdatePayload {
  min_score?: number | null
  min_subject_score?: number | null
  group_quota?: number | null
}

/** Item PATCH — omit a field to leave unchanged; do NOT send is_principal:null. */
export interface PathSubjectGroupItemUpdatePayload {
  is_principal?: boolean
  min_subject_score?: number | null
}

export async function getPathSubjectGroupConfigsAdmin(
  pathId: number,
): Promise<{ total: number; items: PathSubjectGroupConfigAdmin[] }> {
  const response = await api.get<{
    total: number
    items: PathSubjectGroupConfigAdmin[]
  }>(`${ADMIN_SG_BASE}/admission-paths/${pathId}/subject-group-configs`)
  return response.data
}

export async function createPathSubjectGroupConfig(
  pathId: number,
  data: PathSubjectGroupConfigCreatePayload,
): Promise<PathSubjectGroupConfigBaseResponse> {
  const response = await api.post<PathSubjectGroupConfigBaseResponse>(
    `${ADMIN_SG_BASE}/admission-paths/${pathId}/subject-group-configs`,
    data,
  )
  return response.data
}

export async function updatePathSubjectGroupConfig(
  configId: number,
  data: PathSubjectGroupConfigUpdatePayload,
): Promise<PathSubjectGroupConfigBaseResponse> {
  const response = await api.patch<PathSubjectGroupConfigBaseResponse>(
    `${ADMIN_SG_BASE}/path-subject-group-configs/${configId}`,
    data,
  )
  return response.data
}

export async function deletePathSubjectGroupConfig(
  configId: number,
): Promise<void> {
  await api.delete(`${ADMIN_SG_BASE}/path-subject-group-configs/${configId}`)
}

export async function addPathSubjectGroupItem(
  configId: number,
  data: PathSubjectGroupItemPayload,
): Promise<PathSubjectGroupItemAdmin> {
  const response = await api.post<PathSubjectGroupItemAdmin>(
    `${ADMIN_SG_BASE}/path-subject-group-configs/${configId}/items`,
    data,
  )
  return response.data
}

export async function updatePathSubjectGroupItem(
  configId: number,
  itemId: number,
  data: PathSubjectGroupItemUpdatePayload,
): Promise<PathSubjectGroupItemAdmin> {
  const response = await api.patch<PathSubjectGroupItemAdmin>(
    `${ADMIN_SG_BASE}/path-subject-group-configs/${configId}/items/${itemId}`,
    data,
  )
  return response.data
}

export async function deletePathSubjectGroupItem(
  configId: number,
  itemId: number,
): Promise<void> {
  await api.delete(
    `${ADMIN_SG_BASE}/path-subject-group-configs/${configId}/items/${itemId}`,
  )
}

// ============================================
// EXPORT DEFAULT OBJECT
// ============================================

export const admissionPathsApi = {
  // CRUD
  getPathsForOffering,
  getAdmissionPath,
  createAdmissionPath,
  updateAdmissionPath,
  updateCriteria,
  updatePathDocuments,
  // Actions (Admin only)
  activateAdmissionPath,
  deactivateAdmissionPath,
  archiveAdmissionPath,
  // Validation & Documents
  validatePathActivation,
  getPathDocuments,
  // Matrix
  getCoverageMatrix,
  // Phase 3 multi-NV AddChoiceDialog
  getPathsByRound,
  getPathSubjectGroupConfigs,
  // Admin "Tổ hợp môn" tab CRUD (#7)
  getPathSubjectGroupConfigsAdmin,
  createPathSubjectGroupConfig,
  updatePathSubjectGroupConfig,
  deletePathSubjectGroupConfig,
  addPathSubjectGroupItem,
  updatePathSubjectGroupItem,
  deletePathSubjectGroupItem,
}

export default admissionPathsApi
