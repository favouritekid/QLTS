/**
 * React Query mutation hooks — UT evidence verify/reject (Phase E.3) +
 * upload/untick (Phase E.4 PR-2).
 *
 * Cache parity per memory ``react-query-mutation-cache-parity``:
 * onSuccess setQueryData + invalidateQueries cho admission detail key +
 * preview-priority-kv sibling cache.
 *
 * Stale-version 409 handled by caller — hook propagates error; toast +
 * refresh prompt rendered trong dialog/banner.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { priorityEvidenceApi } from "@/lib/api/priority-evidence"
import type {
  AdmissionProfileResponse,
  UntickPriorityEvidenceRequest,
} from "@/lib/zod/admissions"
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

/**
 * Q9 #07 Phase E.4 PR-2 — Upload priority evidence document mutation.
 *
 * POST multipart file upload. BE service preserves ADM-007 staging/finalize.
 * P1 contract: re-upload trên verified/rejected status sẽ tự reset JSONB
 * status='pending' + bump version (engine reads bonus eligibility từ JSONB).
 *
 * Cache invalidation per react-query-mutation-cache-parity memory:
 * setQueryData(admission detail) + invalidate preview-priority-kv sibling.
 */
export function useUploadPriorityEvidence(profileId: number, subCode: string) {
  const queryClient = useQueryClient()
  return useMutation<AdmissionProfileResponse, Error, { file: File }>({
    mutationFn: ({ file }) =>
      priorityEvidenceApi.upload(profileId, subCode, file),
    onSuccess: (updated) => invalidateRelated(queryClient, profileId, updated),
  })
}

/**
 * Q9 #07 Phase E.4 PR-2 — Untick UT code + cascade hard delete mutation.
 *
 * DELETE endpoint với version body (optimistic lock).
 * Decision #4 UI safety: FE confirm dialog BEFORE call invoke this hook.
 * Hook does NOT show dialog — caller responsible.
 *
 * BE atomic 4-mutation contract: codes/evidence JSONB cleanup + DELETE
 * profile_document row + INSERT priority_audit_log + S3 file unlink
 * (ADM-007 finalize post-commit).
 */
export function useUntickPriorityEvidence(profileId: number, subCode: string) {
  const queryClient = useQueryClient()
  return useMutation<
    AdmissionProfileResponse,
    Error,
    UntickPriorityEvidenceRequest
  >({
    mutationFn: ({ version }) =>
      priorityEvidenceApi.untick(profileId, subCode, version),
    onSuccess: (updated) => invalidateRelated(queryClient, profileId, updated),
  })
}
