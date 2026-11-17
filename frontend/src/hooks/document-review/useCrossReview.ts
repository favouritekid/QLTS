/**
 * GĐ1b §2.2 — hook duyệt chéo tạm thời: quyền của chính người gọi, hàng đợi hẹp, lệnh duyệt / từ chối, quản lý quyền
 * (Admin). Ẩn / hiện theo phản hồi máy chủ (`eligible`, `grant_id_by_action`), KHÔNG theo `user.role`.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import axios from "axios"

import { CROSS_REVIEW_QUEUE_KEY } from "@/hooks/document-review/useBulkVerify"
import {
  createCrossReviewGrant,
  crossReviewReject,
  crossReviewVerify,
  getCrossReviewEligibility,
  getCrossReviewQueue,
  listCrossReviewGrants,
  revokeCrossReviewGrant,
  type CrossReviewGrantFilter,
} from "@/lib/api/document-cross-review"
import type { CrossReviewActionBody, CrossReviewGrantCreateBody } from "@/lib/zod/document-review"

export const crossReviewKeys = {
  all: ["cross-review"] as const,
  eligibility: () => [...crossReviewKeys.all, "eligibility"] as const,
  queue: () => CROSS_REVIEW_QUEUE_KEY,
  grants: () => [...crossReviewKeys.all, "grants"] as const,
  grantList: (f: CrossReviewGrantFilter) => [...crossReviewKeys.grants(), f] as const,
}

function noRetryOn4xx(failureCount: number, error: unknown): boolean {
  if (axios.isAxiosError(error) && error.response && error.response.status < 500) return false
  return failureCount < 2
}

/** Cờ cho trang / mục thanh bên "Duyệt chéo". Đang tải / lỗi ⇒ coi như KHÔNG có quyền (fail-closed). */
export function useCrossReviewEligibility(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: crossReviewKeys.eligibility(),
    queryFn: getCrossReviewEligibility,
    enabled: options?.enabled ?? true,
    staleTime: 60_000,
    retry: noRetryOn4xx,
  })
}

export function useCrossReviewQueue(enabled: boolean) {
  return useInfiniteQuery({
    queryKey: crossReviewKeys.queue(),
    queryFn: ({ pageParam }) => getCrossReviewQueue(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
    staleTime: 0,
    retry: noRetryOn4xx,
  })
}

function useCrossAction(fn: (body: CrossReviewActionBody) => Promise<void>) {
  const queryClient = useQueryClient()
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: crossReviewKeys.queue() })
    void queryClient.invalidateQueries({ queryKey: crossReviewKeys.eligibility() })
  }
  return useMutation({
    mutationFn: fn,
    retry: false,
    gcTime: 0,
    onSuccess: refresh,
    onError: (error) => {
      // 409 actor_not_authorized / version_changed, 404 ⇒ quyền hoặc giấy đã đổi ⇒ làm mới hàng đợi + quyền
      if (axios.isAxiosError(error) && (error.response?.status === 409 || error.response?.status === 404)) refresh()
    },
  })
}

export function useCrossReviewVerify() {
  return useCrossAction(crossReviewVerify)
}

export function useCrossReviewReject() {
  return useCrossAction(crossReviewReject)
}

// ── Admin ──

export function useCrossReviewGrants(filter: CrossReviewGrantFilter) {
  return useQuery({
    queryKey: crossReviewKeys.grantList(filter),
    queryFn: () => listCrossReviewGrants(filter),
    staleTime: 0,
    retry: noRetryOn4xx,
  })
}

export function useCreateCrossReviewGrant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CrossReviewGrantCreateBody) => createCrossReviewGrant(body),
    retry: false,
    gcTime: 0,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: crossReviewKeys.grants() }),
  })
}

export function useRevokeCrossReviewGrant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ grantId, reason }: { grantId: number; reason: string }) => revokeCrossReviewGrant(grantId, reason),
    retry: false,
    gcTime: 0,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: crossReviewKeys.grants() }),
  })
}
