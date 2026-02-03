/**
 * React Query Hooks for Fee Management
 *
 * @see lib/api/fees.ts
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { feesApi, type FeePaginatedResponse } from "@/lib/api/fees"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  Fee,
  FeeDetail,
  FeeFilters,
  FeeCalculateRequest,
  FeeWaiveRequest,
  ProfileFinanceSummary,
} from "@/types/finance.types"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const feesKeys = {
  all: ["fees"] as const,
  lists: () => [...feesKeys.all, "list"] as const,
  list: (filters?: FeeFilters) => [...feesKeys.lists(), filters] as const,
  details: () => [...feesKeys.all, "detail"] as const,
  detail: (id: number) => [...feesKeys.details(), id] as const,
  byProfile: (profileId: number) => [...feesKeys.all, "by-profile", profileId] as const,
  profileSummary: (profileId: number) => [...feesKeys.all, "profile-summary", profileId] as const,
}

// =====================================================================
// QUERY INVALIDATION HELPERS
// =====================================================================

type FeeInvalidationOptions = {
  detail?: boolean
  lists?: boolean
  byProfile?: number
  profileSummary?: number
  dashboard?: boolean
}

const invalidateFeeQueries = async (
  queryClient: ReturnType<typeof useQueryClient>,
  feeId: number,
  options: FeeInvalidationOptions = {}
) => {
  const {
    detail = true,
    lists = true,
    byProfile,
    profileSummary,
    dashboard = true,
  } = options

  const invalidations: Promise<void>[] = []

  if (detail) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: feesKeys.detail(feeId) })
    )
  }
  if (lists) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: feesKeys.lists(),
        refetchType: "active",
      })
    )
  }
  if (byProfile) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: feesKeys.byProfile(byProfile) })
    )
  }
  if (profileSummary) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: feesKeys.profileSummary(profileSummary),
      })
    )
  }
  if (dashboard) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    )
  }

  return Promise.all(invalidations)
}

// =====================================================================
// QUERIES (READ)
// =====================================================================

/**
 * Get paginated fees list with optional filters
 *
 * @param filters - Filter parameters
 * @param options - Query options including initialData
 *
 * @example
 * ```tsx
 * const { data, isLoading } = useFees({ status: 'pending', page: 1 })
 * ```
 */
export function useFees(
  filters?: FeeFilters,
  options?: { initialData?: FeePaginatedResponse; enabled?: boolean }
) {
  return useQuery<FeePaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: feesKeys.list(filters),
    queryFn: () => feesApi.getFees(filters),
    staleTime: 1000 * 30, // 30 seconds
    gcTime: 1000 * 60 * 5, // 5 minutes
    initialData: options?.initialData,
    enabled: options?.enabled ?? true,
  })
}

/**
 * Get a single fee by ID with full details
 *
 * @param id - Fee ID
 * @param options - Query options
 *
 * @example
 * ```tsx
 * const { data: fee, isLoading } = useFeeDetail(123)
 * ```
 */
export function useFeeDetail(
  id: number,
  options?: { enabled?: boolean; initialData?: FeeDetail }
) {
  return useQuery<FeeDetail, AxiosError<ApiErrorResponse>>({
    queryKey: feesKeys.detail(id),
    queryFn: () => feesApi.getFee(id),
    enabled: (options?.enabled ?? true) && !!id,
    initialData: options?.initialData,
    staleTime: 1000 * 30,
  })
}

/**
 * Get fees by admission profile ID
 *
 * @param profileId - Admission profile ID
 *
 * @example
 * ```tsx
 * const { data: fees } = useFeesByProfile(456)
 * ```
 */
export function useFeesByProfile(profileId: number, options?: { enabled?: boolean }) {
  return useQuery<Fee[], AxiosError<ApiErrorResponse>>({
    queryKey: feesKeys.byProfile(profileId),
    queryFn: () => feesApi.getFeesByProfile(profileId),
    enabled: (options?.enabled ?? true) && !!profileId,
    staleTime: 1000 * 30,
  })
}

/**
 * Get finance summary for an admission profile
 * Used for cross-reference from Admission Detail
 *
 * @param profileId - Admission profile ID
 *
 * @example
 * ```tsx
 * const { data: summary } = useProfileFinanceSummary(456)
 * ```
 */
export function useProfileFinanceSummary(
  profileId: number,
  options?: { enabled?: boolean }
) {
  return useQuery<ProfileFinanceSummary, AxiosError<ApiErrorResponse>>({
    queryKey: feesKeys.profileSummary(profileId),
    queryFn: () => feesApi.getProfileFinanceSummary(profileId),
    enabled: (options?.enabled ?? true) && !!profileId,
    staleTime: 1000 * 60, // 1 minute
  })
}

// =====================================================================
// MUTATIONS (WRITE)
// =====================================================================

/**
 * Calculate fee for an admission profile
 *
 * @example
 * ```tsx
 * const { mutate: calculateFee, isPending } = useCalculateFee()
 *
 * calculateFee({
 *   admission_profile_id: 123,
 *   fee_type: 'tuition',
 *   installment_plan_code: 'FULL_PAYMENT'
 * })
 * ```
 */
export function useCalculateFee() {
  const queryClient = useQueryClient()

  return useMutation<FeeDetail, AxiosError<ApiErrorResponse>, FeeCalculateRequest>({
    mutationFn: (data) => feesApi.calculateFee(data),
    onSuccess: (fee) => {
      toast.success("Đã tính phí thành công")
      // Invalidate related queries
      invalidateFeeQueries(queryClient, fee.id, {
        byProfile: fee.admission_profile_id,
        profileSummary: fee.admission_profile_id,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể tính phí. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Waive (discount) a portion of the fee
 *
 * @example
 * ```tsx
 * const { mutate: waiveFee, isPending } = useWaiveFee()
 *
 * waiveFee({
 *   feeId: 123,
 *   data: { waive_amount: '1000000', reason: 'Học bổng xuất sắc' }
 * })
 * ```
 */
export function useWaiveFee() {
  const queryClient = useQueryClient()

  return useMutation<
    Fee,
    AxiosError<ApiErrorResponse>,
    { feeId: number; data: FeeWaiveRequest }
  >({
    mutationFn: ({ feeId, data }) => feesApi.waiveFee(feeId, data),
    onSuccess: (fee) => {
      toast.success("Đã miễn giảm phí thành công")
      invalidateFeeQueries(queryClient, fee.id, {
        byProfile: fee.admission_profile_id,
        profileSummary: fee.admission_profile_id,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể miễn giảm phí. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Cancel a fee
 *
 * @example
 * ```tsx
 * const { mutate: cancelFee, isPending } = useCancelFee()
 *
 * cancelFee({ feeId: 123, reason: 'Hủy hồ sơ' })
 * ```
 */
export function useCancelFee() {
  const queryClient = useQueryClient()

  return useMutation<
    Fee,
    AxiosError<ApiErrorResponse>,
    { feeId: number; reason: string }
  >({
    mutationFn: ({ feeId, reason }) => feesApi.cancelFee(feeId, reason),
    onSuccess: (fee) => {
      toast.success("Đã hủy phí thành công")
      invalidateFeeQueries(queryClient, fee.id, {
        byProfile: fee.admission_profile_id,
        profileSummary: fee.admission_profile_id,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể hủy phí. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Recalculate fee amounts
 *
 * @example
 * ```tsx
 * const { mutate: recalculateFee, isPending } = useRecalculateFee()
 *
 * recalculateFee(123)
 * ```
 */
export function useRecalculateFee() {
  const queryClient = useQueryClient()

  return useMutation<FeeDetail, AxiosError<ApiErrorResponse>, number>({
    mutationFn: (feeId) => feesApi.recalculateFee(feeId),
    onSuccess: (fee) => {
      toast.success("Đã tính lại phí thành công")
      invalidateFeeQueries(queryClient, fee.id, {
        byProfile: fee.admission_profile_id,
        profileSummary: fee.admission_profile_id,
      })
      // Also invalidate invoices since they may have changed
      queryClient.invalidateQueries({ queryKey: ["invoices"] })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể tính lại phí. Vui lòng thử lại."
      toast.error(message)
    },
  })
}
