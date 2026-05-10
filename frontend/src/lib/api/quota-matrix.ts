// frontend/src/lib/api/quota-matrix.ts
// Phase 2 v8.2 PR-2D.1 v2 — Quota matrix overview API client.

import { api } from "./client"

export interface QuotaMatrixRound {
  id: number
  round_code: string
  round_name: string
  is_active: boolean
}

export interface QuotaMatrixCell {
  admission_round_id: number
  round_code: string
  total_admit_quota: number
  total_round_quota: number
  total_submission_count: number
  path_count: number
}

export interface QuotaMatrixRow {
  academic_info_id: number
  academic_year: number
  program_name: string
  program_code: string | null
  degree_level: string | null
  annual_admission_quota: number | null
  cells_by_round_id: Record<number, QuotaMatrixCell>
  sum_admit_allocated: number
  sum_remaining: number | null
}

export interface QuotaMatrixResponse {
  academic_year: number
  rounds: QuotaMatrixRound[]
  rows: QuotaMatrixRow[]
  total_rows: number
}

export interface AdmissionPathQuotaUpdate {
  round_quota: number | null
  admit_quota: number | null
}

/**
 * Get quota matrix overview cho năm tuyển sinh.
 * Aggregation: rows = academic_info × academic_year, cols = rounds,
 * cells = ∑ admit_quota across paths.
 */
export async function getQuotaMatrix(
  academicYear: number,
): Promise<QuotaMatrixResponse> {
  const response = await api.get<QuotaMatrixResponse>(
    `/api/v2/admin/years/${academicYear}/quota-matrix`,
  )
  return response.data
}

/**
 * Update path quota cho QuotaMatrix drawer/inline edit.
 * Tier 1+2 chain validated server-side.
 */
export async function updatePathQuota(
  pathId: number,
  data: AdmissionPathQuotaUpdate,
): Promise<unknown> {
  const response = await api.patch(
    `/api/v2/admin/admission-paths/${pathId}/quota`,
    data,
  )
  return response.data
}
