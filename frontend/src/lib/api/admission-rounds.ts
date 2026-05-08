/**
 * Admission Rounds API client (Phase 2 PR-2A).
 *
 * Mirrors backend `app/routers/admin_v2_admission_round.py`:
 * - POST   /api/v2/admin/academic-info/{id}/rounds
 * - GET    /api/v2/admin/academic-info/{id}/rounds
 * - GET    /api/v2/admin/rounds/{id}
 * - PATCH  /api/v2/admin/rounds/{id}
 * - DELETE /api/v2/admin/rounds/{id}  (soft-archive)
 * - POST   /api/v2/admin/rounds/{id}/extend
 */
import { api } from "@/lib/api/client"
import type {
  AdmissionRoundCreate,
  AdmissionRoundExtend,
  AdmissionRoundListResponse,
  AdmissionRoundResponse,
  AdmissionRoundUpdate,
} from "@/lib/zod/admission-rounds"

const BASE = "/api/v2/admin"

export async function listRoundsByAcademicInfo(
  academicInfoId: number
): Promise<AdmissionRoundListResponse> {
  const res = await api.get<AdmissionRoundListResponse>(
    `${BASE}/academic-info/${academicInfoId}/rounds`
  )
  return res.data
}

export async function createRound(
  academicInfoId: number,
  payload: AdmissionRoundCreate
): Promise<AdmissionRoundResponse> {
  const res = await api.post<AdmissionRoundResponse>(
    `${BASE}/academic-info/${academicInfoId}/rounds`,
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
