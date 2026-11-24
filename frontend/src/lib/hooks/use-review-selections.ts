/**
 * GĐ2-C C2 — React Query cho lựa chọn của Ban thư ký. Ghi xong HAY lỗi (409 cũ / đã đổi, 404) ⇒ làm mới danh sách + lịch sử
 * của lần xét (khuôn `use-review-secretaries`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import axios from "axios"

import { getReviewSelectionHistory, listReviewSelections, putReviewSelection } from "@/lib/api/review-selections"
import type { SelectionPutBody } from "@/lib/zod/review-selections"

export const reviewSelectionKeys = {
  all: ["review-selections"] as const,
  session: (sessionId: number) => [...reviewSelectionKeys.all, sessionId] as const,
  list: (sessionId: number) => [...reviewSelectionKeys.session(sessionId), "list"] as const,
  history: (sessionId: number, profileId: number) =>
    [...reviewSelectionKeys.session(sessionId), "history", profileId] as const,
}

function noRetryOn4xx(failureCount: number, error: unknown): boolean {
  if (axios.isAxiosError(error) && error.response && error.response.status < 500) return false
  return failureCount < 2
}

export function useReviewSelections(sessionId: number) {
  return useQuery({
    queryKey: reviewSelectionKeys.list(sessionId),
    queryFn: () => listReviewSelections(sessionId),
    staleTime: 0,
    retry: noRetryOn4xx,
  })
}

export function useReviewSelectionHistory(sessionId: number, profileId: number, enabled = true) {
  return useQuery({
    queryKey: reviewSelectionKeys.history(sessionId, profileId),
    queryFn: () => getReviewSelectionHistory(sessionId, profileId),
    staleTime: 0,
    enabled,
    retry: noRetryOn4xx,
  })
}

export function usePutReviewSelection(sessionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ profileId, body }: { profileId: number; body: SelectionPutBody }) =>
      putReviewSelection(sessionId, profileId, body),
    retry: false,
    gcTime: 0,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: reviewSelectionKeys.session(sessionId) }),
  })
}
