/**
 * Phase 3 PR-3D-B FE Wave B Bundle 3 — React Query hooks for admin backfill queue.
 *
 * Read hook: useBackfillExceptions(filters)
 * Mutations: useResolveBackfillException, useBulkResolveBackfillExceptions
 *
 * All mutations invalidate the list key so the queue UI refreshes counters
 * after resolve. Memory `react-query-mutation-cache-parity` applied.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  bulkResolveBackfillExceptions,
  listBackfillExceptions,
  resolveBackfillException,
} from "@/lib/api/admission-backfill"
import type {
  BackfillExceptionBulkResolveRequest,
  BackfillExceptionResolveRequest,
  BackfillListFilters,
} from "@/lib/zod/admission-backfill"

export const admissionBackfillKeys = {
  all: ["admission-backfill"] as const,
  lists: () => [...admissionBackfillKeys.all, "list"] as const,
  list: (filters: BackfillListFilters) =>
    [...admissionBackfillKeys.lists(), filters] as const,
}

export function useBackfillExceptions(filters: BackfillListFilters = {}) {
  return useQuery({
    queryKey: admissionBackfillKeys.list(filters),
    queryFn: () => listBackfillExceptions(filters),
    staleTime: 30_000,
  })
}

function invalidateAllBackfillLists(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  void queryClient.invalidateQueries({
    queryKey: admissionBackfillKeys.lists(),
  })
}

export function useResolveBackfillException() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      exceptionId,
      payload,
    }: {
      exceptionId: number
      payload: BackfillExceptionResolveRequest
    }) => resolveBackfillException(exceptionId, payload),
    onSuccess: () => {
      invalidateAllBackfillLists(queryClient)
    },
  })
}

export function useBulkResolveBackfillExceptions() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: BackfillExceptionBulkResolveRequest) =>
      bulkResolveBackfillExceptions(payload),
    onSuccess: () => {
      invalidateAllBackfillLists(queryClient)
    },
  })
}
