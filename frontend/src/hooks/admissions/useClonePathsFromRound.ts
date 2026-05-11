/**
 * Hook bulk clone admission paths theo Q6 deep-copy.
 *
 * Invalidate cả admission-paths + quota-matrix sau success vì 2 surface
 * cùng đọc admission_path data, drift = stale UI.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query"

import {
  clonePathsFromRound,
  type ClonePathsRequest,
} from "@/lib/api/admission-path-clone"

import { admissionPathKeys } from "./useAdmissionPaths"
import { quotaMatrixKeys } from "./useQuotaMatrix"

interface MutationVars {
  targetRoundId: number
  sourceRoundId: number
  payload: ClonePathsRequest
}

export function useClonePathsFromRound() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ targetRoundId, sourceRoundId, payload }: MutationVars) =>
      clonePathsFromRound(targetRoundId, sourceRoundId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
    },
  })
}
