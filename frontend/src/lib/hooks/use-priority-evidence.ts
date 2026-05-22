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
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import type {
  AdmissionProfileResponse,
  UntickPriorityEvidenceRequest,
} from "@/lib/zod/admissions"
import type {
  RejectObjectEvidenceRequest,
  VerifyObjectEvidenceRequest,
} from "@/lib/zod/priority-evidence"

// Followup fix: trước đây dùng `["admission", id]` (singular) → drift với
// `useAdmissions.admissionsKeys.detail(id)` = `["admissions","detail",id]`
// → invalidate không trigger refetch detail thực tế. Dùng shared key
// constant để FE giữ cache parity.
function invalidateRelated(
  queryClient: ReturnType<typeof useQueryClient>,
  profileId: number,
  updated: AdmissionProfileResponse,
) {
  const detailKey = admissionsKeys.detail(profileId)
  queryClient.setQueryData(detailKey, updated)
  queryClient.invalidateQueries({ queryKey: detailKey })
  // Sibling preview-priority-kv cache key: chính xác là "priority-kv-preview"
  // (xem `use-preview-priority-kv.ts:16`). Predicate cũ "preview-priority-kv"
  // reversed → không match, preview stale sau verify/reject/upload.
  queryClient.invalidateQueries({
    predicate: (q) =>
      Array.isArray(q.queryKey) &&
      q.queryKey[0] === "priority-kv-preview" &&
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
