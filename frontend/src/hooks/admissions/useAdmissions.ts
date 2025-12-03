/**
 * TanStack Query Hooks for Admission Module
 *
 * Architecture:
 * - Query Keys: Hierarchical structure (admissionsKeys)
 * - Queries: useQuery for GET operations
 * - Mutations: useMutation for CREATE/UPDATE/DELETE operations
 * - Cache Management: Auto-invalidation on mutations
 *
 * Integration:
 * - Uses API client from @/lib/api/admissions
 * - Toast notifications via sonner
 * - Query invalidation for real-time updates
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { useRouter } from "next/navigation"

import * as admissionsApi from "@/lib/api/admissions"
import type {
  AdmissionProfileCreate,
  AdmissionProfileResponse,
  AdmissionProfileUpdate,
  AdmissionSubmitResponse,
  EnrollStudentResponse,
} from "@/lib/zod/admissions"
import type { ApiErrorResponse } from "@/types/api.types"

// ==============================================================================
// QUERY KEYS
// ==============================================================================

/**
 * Query keys for admissions
 * Hierarchical structure for efficient invalidation
 */
export const admissionsKeys = {
  all: ["admissions"] as const,
  lists: () => [...admissionsKeys.all, "list"] as const,
  list: (filters?: any) => [...admissionsKeys.lists(), filters] as const,
  details: () => [...admissionsKeys.all, "detail"] as const,
  detail: (id: number) => [...admissionsKeys.details(), id] as const,
}

// ==============================================================================
// QUERIES
// ==============================================================================

/**
 * Get admission profile by ID
 *
 * @param id - AdmissionProfile ID
 * @param enabled - Enable/disable query (default: true)
 *
 * @example
 * ```tsx
 * const { data: profile, isLoading, error } = useGetAdmission(456)
 * if (isLoading) return <Loading />
 * if (error) return <Error />
 * return <div>{profile.status}</div>
 * ```
 */
export function useGetAdmission(id: number, enabled: boolean = true) {
  return useQuery<AdmissionProfileResponse, AxiosError<ApiErrorResponse>>({
    queryKey: admissionsKeys.detail(id),
    queryFn: async () => await admissionsApi.getAdmission(id),
    enabled: enabled && !!id && id > 0,
    staleTime: 60_000, // 1 minute
    gcTime: 300_000, // 5 minutes
    retry: (failureCount, error) => {
      // Don't retry on 404 or 403
      if (error.response?.status === 404 || error.response?.status === 403) {
        return false
      }
      return failureCount < 3
    },
  })
}

// ==============================================================================
// MUTATIONS
// ==============================================================================

/**
 * Create new admission profile
 *
 * @example
 * ```tsx
 * const createAdmission = useCreateAdmission()
 *
 * const handleCreate = () => {
 *   createAdmission.mutate({ lead_id: 123 })
 * }
 * ```
 */
export function useCreateAdmission() {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation<
    AdmissionProfileResponse,
    AxiosError<ApiErrorResponse>,
    AdmissionProfileCreate
  >({
    mutationFn: (data) => admissionsApi.createAdmission(data),

    onSuccess: (newProfile) => {
      toast.success("Tạo hồ sơ tuyển sinh thành công!", {
        description: `Hồ sơ ID: ${newProfile.id} - Trạng thái: Nháp`,
      })

      // Set detail query data (optimistic update)
      queryClient.setQueryData(
        admissionsKeys.detail(newProfile.id),
        newProfile
      )

      // Invalidate lists
      queryClient.invalidateQueries({
        queryKey: admissionsKeys.lists(),
      })

      // Navigate to profile page
      router.push(`/admissions/${newProfile.id}`)
    },

    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : "Không thể tạo hồ sơ tuyển sinh"
      toast.error("Lỗi", { description: message })
    },
  })
}

/**
 * Update admission profile (draft only)
 *
 * @param profileId - AdmissionProfile ID
 *
 * @example
 * ```tsx
 * const updateAdmission = useUpdateAdmission(456)
 *
 * const handleSave = () => {
 *   updateAdmission.mutate({
 *     citizen_id: "001234567890",
 *     family_info: [...],
 *     admission_scores: { gpa: 8.5 }
 *   })
 * }
 * ```
 */
export function useUpdateAdmission(profileId: number) {
  const queryClient = useQueryClient()

  return useMutation<
    AdmissionProfileResponse,
    AxiosError<ApiErrorResponse>,
    AdmissionProfileUpdate
  >({
    mutationFn: (data) => admissionsApi.updateAdmission(profileId, data),

    onMutate: async (newData) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({
        queryKey: admissionsKeys.detail(profileId),
      })

      // Snapshot previous value
      const previousProfile = queryClient.getQueryData<AdmissionProfileResponse>(
        admissionsKeys.detail(profileId)
      )

      // Optimistically update
      if (previousProfile) {
        queryClient.setQueryData<AdmissionProfileResponse>(
          admissionsKeys.detail(profileId),
          {
            ...previousProfile,
            ...newData,
            updated_at: new Date().toISOString(),
          }
        )
      }

      return { previousProfile }
    },

    onSuccess: (updatedProfile) => {
      toast.success("Đã lưu hồ sơ!", {
        description: "Thông tin hồ sơ đã được cập nhật",
      })

      // Update detail query data
      queryClient.setQueryData(
        admissionsKeys.detail(profileId),
        updatedProfile
      )
    },

    onError: (error, _newData, context) => {
      // Rollback optimistic update
      if (context?.previousProfile) {
        queryClient.setQueryData(
          admissionsKeys.detail(profileId),
          context.previousProfile
        )
      }

      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : "Không thể cập nhật hồ sơ"
      toast.error("Lỗi", { description: message })
    },
  })
}

/**
 * Submit admission profile for evaluation
 *
 * @param profileId - AdmissionProfile ID
 *
 * @example
 * ```tsx
 * const submitAdmission = useSubmitAdmission(456)
 *
 * const handleSubmit = () => {
 *   submitAdmission.mutate()
 * }
 *
 * // In component:
 * {submitAdmission.isSuccess && result.status === "approved" && (
 *   <Alert>Hồ sơ đã được duyệt!</Alert>
 * )}
 * {submitAdmission.isSuccess && result.status === "rejected" && (
 *   <Alert variant="destructive">
 *     {result.errors?.map(e => <div key={e}>{e}</div>)}
 *   </Alert>
 * )}
 * ```
 */
export function useSubmitAdmission(profileId: number) {
  const queryClient = useQueryClient()

  return useMutation<
    AdmissionSubmitResponse,
    AxiosError<ApiErrorResponse>,
    void
  >({
    mutationFn: () => admissionsApi.submitAdmission(profileId),

    onSuccess: (result) => {
      if (result.status === "approved") {
        toast.success("Hồ sơ đã được duyệt!", {
          description: result.message || "Bạn có thể tiến hành nhập học",
          duration: 5000,
        })
      } else if (result.status === "rejected") {
        toast.error("Hồ sơ không đạt yêu cầu", {
          description: `${result.errors?.length || 0} lỗi cần sửa`,
          duration: 7000,
        })
      }

      // Invalidate profile to refetch (status changed)
      queryClient.invalidateQueries({
        queryKey: admissionsKeys.detail(profileId),
      })
    },

    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : "Không thể nộp hồ sơ. Vui lòng thử lại"
      toast.error("Lỗi", { description: message })
    },
  })
}

/**
 * Enroll student (ACID transaction)
 *
 * @param profileId - AdmissionProfile ID
 *
 * @example
 * ```tsx
 * const enrollStudent = useEnrollStudent(456)
 *
 * const handleEnroll = () => {
 *   enrollStudent.mutate()
 * }
 * ```
 */
export function useEnrollStudent(profileId: number) {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation<EnrollStudentResponse, AxiosError<ApiErrorResponse>, void>(
    {
      mutationFn: () => admissionsApi.enrollStudent(profileId),

      onSuccess: (result) => {
        toast.success("Nhập học thành công!", {
          description: `Mã học viên: ${result.student_code}`,
          duration: 5000,
        })

        // Invalidate profile (status changed to 'enrolled')
        queryClient.invalidateQueries({
          queryKey: admissionsKeys.detail(profileId),
        })

        // Navigate to student profile after short delay
        setTimeout(() => {
          router.push(`/students/${result.student_id}`)
        }, 2000)
      },

      onError: (error) => {
        const detail = error.response?.data?.detail
        let message = "Không thể nhập học. Vui lòng thử lại"

        // Handle specific error codes
        if (error.response?.status === 409) {
          message =
            typeof detail === "string"
              ? detail
              : "Mã học viên hoặc CCCD đã tồn tại"
        } else if (error.response?.status === 429) {
          message = "Bạn đã gửi quá nhiều yêu cầu. Vui lòng đợi một chút"
        } else if (typeof detail === "string") {
          message = detail
        }

        toast.error("Lỗi", { description: message, duration: 7000 })
      },
    }
  )
}

// ==============================================================================
// UTILITY HOOKS (optional, for convenience)
// ==============================================================================

/**
 * Get admission profile with auto-refetch on window focus
 * Useful for detail pages
 */
export function useAdmissionProfile(id: number) {
  return useGetAdmission(id)
}

/**
 * Check if profile is in editable state
 */
export function useIsProfileEditable(profile?: AdmissionProfileResponse) {
  return profile?.status === "draft"
}

/**
 * Check if profile can be submitted
 */
export function useCanSubmitProfile(profile?: AdmissionProfileResponse) {
  return profile?.status === "draft"
}

/**
 * Check if student can be enrolled
 */
export function useCanEnrollStudent(profile?: AdmissionProfileResponse) {
  return profile?.status === "approved"
}
