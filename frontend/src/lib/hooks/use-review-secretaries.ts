/**
 * GĐ2-C C1 — React Query cho quyền "Thư ký Hội đồng" (Admin). Khuôn `useCrossReview` (quyền duyệt chéo GĐ1b): gán xong ⇒
 * làm mới danh sách; thu hồi xong HAY lỗi (409 đã thu hồi, 404) ⇒ làm mới danh sách.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import axios from "axios"

import {
  createReviewSecretaryGrant,
  listReviewSecretaryGrants,
  revokeReviewSecretaryGrant,
  type ReviewSecretaryGrantFilter,
} from "@/lib/api/review-secretaries"
import type { ReviewSecretaryGrantCreateBody } from "@/lib/zod/review-secretaries"

export const reviewSecretaryKeys = {
  all: ["review-secretaries"] as const,
  list: (f: ReviewSecretaryGrantFilter) => [...reviewSecretaryKeys.all, f] as const,
}

function noRetryOn4xx(failureCount: number, error: unknown): boolean {
  if (axios.isAxiosError(error) && error.response && error.response.status < 500) return false
  return failureCount < 2
}

export function useReviewSecretaryGrants(filter: ReviewSecretaryGrantFilter) {
  return useQuery({
    queryKey: reviewSecretaryKeys.list(filter),
    queryFn: () => listReviewSecretaryGrants(filter),
    staleTime: 0,
    retry: noRetryOn4xx,
  })
}

export function useCreateReviewSecretaryGrant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReviewSecretaryGrantCreateBody) => createReviewSecretaryGrant(body),
    retry: false,
    gcTime: 0,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: reviewSecretaryKeys.all }),
  })
}

export function useRevokeReviewSecretaryGrant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ grantId, reason }: { grantId: number; reason: string }) => revokeReviewSecretaryGrant(grantId, reason),
    retry: false,
    gcTime: 0,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: reviewSecretaryKeys.all }),
  })
}
