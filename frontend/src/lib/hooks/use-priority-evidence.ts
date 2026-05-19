/**
 * React Query mutation hooks — UT evidence verify/reject (Phase E.3).
 *
 * Cache parity per memory ``react-query-mutation-cache-parity``:
 * onSuccess setQueryData + invalidateQueries cho admission detail key +
 * preview-priority-kv sibling cache.
 *
 * Stale-version 409 handled by caller (UtEvidenceTab) — hook propagates
 * error; toast + refresh prompt rendered trong dialog.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { priorityEvidenceApi } from "@/lib/api/priority-evidence"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type {
  RejectObjectEvidenceRequest,
  VerifyObjectEvidenceRequest,
} from "@/lib/zod/priority-evidence"

const admissionDetailKey = (id: number) => ["admission", id] as const

function invalidateRelated(
  queryClient: ReturnType<typeof useQueryClient>,
  profileId: number,
  updated: AdmissionProfileResponse,
) {
  queryClient.setQueryData(admissionDetailKey(profileId), updated)
  queryClient.invalidateQueries({ queryKey: admissionDetailKey(profileId) })
  queryClient.invalidateQueries({
    predicate: (q) =>
      Array.isArray(q.queryKey) &&
      q.queryKey[0] === "preview-priority-kv" &&
      q.queryKey[1] === profileId,
  })
}

export function useVerifyObjectEvidence(profileId: number, subCode: string) {
  const queryClient = useQueryClient()
  return useMutation<
    AdmissionProfileResponse,
    Error,
    VerifyObjectEvidenceRequest
  >({
    mutationFn: (body) => priorityEvidenceApi.verify(profileId, subCode, body),
    onSuccess: (updated) => invalidateRelated(queryClient, profileId, updated),
  })
}

export function useRejectObjectEvidence(profileId: number, subCode: string) {
  const queryClient = useQueryClient()
  return useMutation<
    AdmissionProfileResponse,
    Error,
    RejectObjectEvidenceRequest
  >({
    mutationFn: (body) => priorityEvidenceApi.reject(profileId, subCode, body),
    onSuccess: (updated) => invalidateRelated(queryClient, profileId, updated),
  })
}
