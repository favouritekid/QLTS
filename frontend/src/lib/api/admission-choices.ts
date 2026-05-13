/**
 * Phase 3 PR-3D-B FE Wave B — Admission Choice API client.
 *
 * Wraps 4 BE-1 endpoints under `/api/v2/admissions/{profile_id}/choices` +
 * runs response through Zod for runtime parity validation per
 * FRONTEND_ARCHITECTURE_V3.md.
 */
import { api } from "@/lib/api/client"
import {
  admissionProfileChoiceCreateSchema,
  admissionProfileChoiceResponseSchema,
  choiceDeleteResponseSchema,
  choiceScoresReplaceRequestSchema,
  choiceUpdateDisplayOrderRequestSchema,
  type AdmissionProfileChoiceCreate,
  type AdmissionProfileChoiceResponse,
  type ChoiceDeleteResponse,
  type ChoiceScoresReplaceRequest,
  type ChoiceUpdateDisplayOrderRequest,
} from "@/lib/zod/admission-choices"

/**
 * POST /api/v2/admissions/{profile_id}/choices
 *
 * Server enforces G7 prechecks (uses_choice_engine + status whitelist +
 * allow_multi_nv + max_choices) and subject-in-group anti-tampering.
 */
export async function createChoice(
  profileId: number,
  payload: AdmissionProfileChoiceCreate,
): Promise<AdmissionProfileChoiceResponse> {
  const validated = admissionProfileChoiceCreateSchema.parse(payload)
  const response = await api.post<AdmissionProfileChoiceResponse>(
    `/api/v2/admissions/${profileId}/choices`,
    validated,
  )
  return admissionProfileChoiceResponseSchema.parse(response.data)
}

/**
 * DELETE /api/v2/admissions/{profile_id}/choices/{choice_id}
 *
 * FK cascade clears ProfileChoiceScore rows. Service status whitelist
 * (draft/revision_requested) — returns 400 if profile already submitted.
 */
export async function deleteChoice(
  profileId: number,
  choiceId: number,
): Promise<ChoiceDeleteResponse> {
  const response = await api.delete<ChoiceDeleteResponse>(
    `/api/v2/admissions/${profileId}/choices/${choiceId}`,
  )
  return choiceDeleteResponseSchema.parse(response.data)
}

/**
 * PATCH /api/v2/admissions/{profile_id}/choices/{choice_id}
 *
 * Manual reorder one row at a time. DB UNIQUE(profile_id, display_order)
 * is the safety net for transient duplicates during batch reorder.
 */
export async function updateChoiceDisplayOrder(
  profileId: number,
  choiceId: number,
  payload: ChoiceUpdateDisplayOrderRequest,
): Promise<AdmissionProfileChoiceResponse> {
  const validated = choiceUpdateDisplayOrderRequestSchema.parse(payload)
  const response = await api.patch<AdmissionProfileChoiceResponse>(
    `/api/v2/admissions/${profileId}/choices/${choiceId}`,
    validated,
  )
  return admissionProfileChoiceResponseSchema.parse(response.data)
}

/**
 * PATCH /api/v2/admissions/{profile_id}/choices/{choice_id}/scores
 *
 * Idempotent replace — all existing scores cleared then re-inserted with
 * fresh snapshots from Subject + SubjectGroupSubject. Empty list valid as
 * "clear all" intent.
 */
export async function replaceChoiceScores(
  profileId: number,
  choiceId: number,
  payload: ChoiceScoresReplaceRequest,
): Promise<AdmissionProfileChoiceResponse> {
  const validated = choiceScoresReplaceRequestSchema.parse(payload)
  const response = await api.patch<AdmissionProfileChoiceResponse>(
    `/api/v2/admissions/${profileId}/choices/${choiceId}/scores`,
    validated,
  )
  return admissionProfileChoiceResponseSchema.parse(response.data)
}

export const admissionChoicesApi = {
  createChoice,
  deleteChoice,
  updateChoiceDisplayOrder,
  replaceChoiceScores,
}
