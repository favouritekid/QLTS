/**
 * Phase 3 PR-3D-B FE Wave B — React Query hooks for AdmissionProfileChoice.
 *
 * Memory `react-query-mutation-cache-parity`: every mutation MUST invalidate
 * or set the detail key when UI consumers display fields the mutation
 * affects. Choice CRUD touches profile.available_actions_v2 + choices list
 * so invalidate both keys.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  createChoice,
  deleteChoice,
  rejectWaitlistedChoice,
  replaceChoiceScores,
  updateChoiceDisplayOrder,
} from "@/lib/api/admission-choices"
import type {
  AdmissionProfileChoiceCreate,
  ChoiceScoresReplaceRequest,
  ChoiceUpdateDisplayOrderRequest,
} from "@/lib/zod/admission-choices"

// =========================================================
// QUERY KEYS — co-located w/ admission detail key so mutation
// callbacks can invalidate both with a single helper.
// =========================================================

export const admissionChoiceKeys = {
  all: ["admission-choices"] as const,
  forProfile: (profileId: number) =>
    [...admissionChoiceKeys.all, "profile", profileId] as const,
}

/** Detail key used by AdmissionDetailPanel — invalidate so available_actions
 *  + computed step_status refresh after a choice mutation. */
function admissionDetailKey(profileId: number) {
  return ["admissions", "detail", profileId] as const
}

function invalidateAfterChoiceMutation(
  queryClient: ReturnType<typeof useQueryClient>,
  profileId: number,
) {
  void queryClient.invalidateQueries({
    queryKey: admissionChoiceKeys.forProfile(profileId),
  })
  void queryClient.invalidateQueries({
    queryKey: admissionDetailKey(profileId),
  })
}

// =========================================================
// MUTATION HOOKS
// =========================================================

export function useCreateChoice(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AdmissionProfileChoiceCreate) =>
      createChoice(profileId, payload),
    onSuccess: () => {
      invalidateAfterChoiceMutation(queryClient, profileId)
    },
  })
}

export function useDeleteChoice(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (choiceId: number) => deleteChoice(profileId, choiceId),
    onSuccess: () => {
      invalidateAfterChoiceMutation(queryClient, profileId)
    },
  })
}

export function useUpdateChoiceDisplayOrder(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      choiceId,
      payload,
    }: {
      choiceId: number
      payload: ChoiceUpdateDisplayOrderRequest
    }) => updateChoiceDisplayOrder(profileId, choiceId, payload),
    onSuccess: () => {
      invalidateAfterChoiceMutation(queryClient, profileId)
    },
  })
}

export function useReplaceChoiceScores(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      choiceId,
      payload,
    }: {
      choiceId: number
      payload: ChoiceScoresReplaceRequest
    }) => replaceChoiceScores(profileId, choiceId, payload),
    onSuccess: () => {
      invalidateAfterChoiceMutation(queryClient, profileId)
    },
  })
}

/**
 * Wave 5 ship 2026-05-16 — T11 waitlist-reject hook.
 *
 * Manager/admin manually finalize 1 NV dự bị → trượt khi đợt closes +
 * slot không mở. Pattern mirror useDeleteChoice (mutation by choiceId)
 * but with required `reason` payload (BE Pydantic min_length=10).
 *
 * Mutation invalidates both choices list + admission detail (profile.status
 * may flip waitlisted → rejected per state machine T11 edge).
 */
export function useRejectWaitlistedChoice(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      choiceId,
      reason,
    }: {
      choiceId: number
      reason: string
    }) =>
      rejectWaitlistedChoice(profileId, {
        choice_id: choiceId,
        reason,
      }),
    onSuccess: () => {
      invalidateAfterChoiceMutation(queryClient, profileId)
    },
  })
}
