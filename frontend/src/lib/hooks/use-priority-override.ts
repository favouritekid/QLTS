/**
 * React Query mutation hook — Manual KV override (Q9 #07 Phase E.2).
 *
 * Wraps `priorityOverrideApi.overrideKv()` with proper cache invalidation
 * + 409 conflict handling per memory `react-query-mutation-cache-parity`.
 *
 * Cache parity requirements:
 * * onSuccess MUST invalidate the detail query key — both pessimistic
 *   `invalidateQueries(['admission', profileId])` AND
 *   `setQueryData(['admission', profileId], updated)` to surface fresh
 *   data immediately trong PriorityTab + sibling tabs reading the same
 *   profile (DocumentsTab, PriorityFinanceTab, FinalizeTab).
 * * onError với 409 should NOT clear cache — `react-query-mutation-cache-parity`
 *   says invalidate detail key + display refresh toast (caller's
 *   responsibility, hook just propagates the error).
 *
 * BE dispatches PRIORITY_KV_OVERRIDDEN event post-commit (Wave 1 catalog
 * seed) → consumers receive notification + socket data_updated broadcast.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { priorityOverrideApi } from "@/lib/api/priority-override"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { OverridePriorityKvRequest } from "@/lib/zod/priority-override"

/** Cache keys mirror existing admission detail convention. */
const admissionDetailKey = (id: number) => ["admission", id] as const

export function useOverridePriorityKv(profileId: number) {
  const queryClient = useQueryClient()

  return useMutation<
    AdmissionProfileResponse,
    Error,
    OverridePriorityKvRequest
  >({
    mutationFn: (body) => priorityOverrideApi.overrideKv(profileId, body),
    onSuccess: async (updated) => {
      // Cache parity per memory `react-query-mutation-cache-parity`:
      // set fresh data to surface immediately + invalidate to refetch
      // background (covers race với concurrent socket data_updated).
      queryClient.setQueryData(admissionDetailKey(profileId), updated)
      await queryClient.invalidateQueries({
        queryKey: admissionDetailKey(profileId),
      })
      // Sibling caches that depend on snapshot also need refresh —
      // e.g., PriorityTab live-preview query (preview-priority-kv).
      // Use predicate match để avoid hardcoding every key.
      await queryClient.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) &&
          query.queryKey[0] === "preview-priority-kv" &&
          query.queryKey[1] === profileId,
      })
    },
  })
}
