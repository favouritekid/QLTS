/**
 * Admission Rounds API client year-level (Phase 2 v8.2 PR-2A v2).
 *
 * Mirrors backend `app/routers/admin_v2_admission_round.py`:
 * - POST   /api/v2/admin/years/{academic_year}/rounds (create)
 * - POST   /api/v2/admin/years/{academic_year}/rounds/bulk-create (atomic 4 đợt)
 * - GET    /api/v2/admin/years/{academic_year}/rounds (list per year)
 * - GET    /api/v2/admin/rounds/{id} (single)
 * - PATCH  /api/v2/admin/rounds/{id} (update time-window/lifecycle)
 * - DELETE /api/v2/admin/rounds/{id} (soft-archive)
 * - POST   /api/v2/admin/rounds/{id}/extend (extend với reason ≥10 chars)
 */
import { api } from "@/lib/api/client"
import type {
  AdmissionRoundBulkCreate,
  AdmissionRoundBulkCreateResponse,
  AdmissionRoundCreate,
  AdmissionRoundExtend,
  AdmissionRoundListResponse,
  AdmissionRoundResponse,
  AdmissionRoundUpdate,
} from "@/lib/zod/admission-rounds"

const BASE = "/api/v2/admin"

export async function listRoundsByYear(
  academicYear: number
): Promise<AdmissionRoundListResponse> {
  const res = await api.get<AdmissionRoundListResponse>(
    `${BASE}/years/${academicYear}/rounds`
  )
  return res.data
}

export async function createRound(
  academicYear: number,
  payload: AdmissionRoundCreate
): Promise<AdmissionRoundResponse> {
  const res = await api.post<AdmissionRoundResponse>(
    `${BASE}/years/${academicYear}/rounds`,
    payload
  )
  return res.data
}

export async function bulkCreateRounds(
  academicYear: number,
  payload: AdmissionRoundBulkCreate
): Promise<AdmissionRoundBulkCreateResponse> {
  const res = await api.post<AdmissionRoundBulkCreateResponse>(
    `${BASE}/years/${academicYear}/rounds/bulk-create`,
    payload
  )
  return res.data
}

export async function getRound(roundId: number): Promise<AdmissionRoundResponse> {
  const res = await api.get<AdmissionRoundResponse>(`${BASE}/rounds/${roundId}`)
  return res.data
}

export async function updateRound(
  roundId: number,
  payload: AdmissionRoundUpdate
): Promise<AdmissionRoundResponse> {
  const res = await api.patch<AdmissionRoundResponse>(
    `${BASE}/rounds/${roundId}`,
    payload
  )
  return res.data
}

export async function softArchiveRound(
  roundId: number
): Promise<AdmissionRoundResponse> {
  const res = await api.delete<AdmissionRoundResponse>(`${BASE}/rounds/${roundId}`)
  return res.data
}

export async function extendRound(
  roundId: number,
  payload: AdmissionRoundExtend
): Promise<AdmissionRoundResponse> {
  const res = await api.post<AdmissionRoundResponse>(
    `${BASE}/rounds/${roundId}/extend`,
    payload
  )
  return res.data
}
