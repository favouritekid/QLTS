/**
 * TanStack Query Hooks for Admissons
 * 
 * Phase 7: Refactored for Frontend Thin Client compliance
 * - Uses handleApiError() for centralized error handling (ADR-FE-004)
 * - Uses getStatusConfig() for async-first workflow (ADR-FE-003)
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { useRouter } from "next/navigation"

import { admissionsApi } from "@/lib/api/admissions"
import type {
  AdmissionProfileResponse,
  AdmissionProfileUpdate,
  AdmissionListParams,
  AdmissionsPage,
  AdmissionStatusCounts,
  AdmissionStats,
  BulkApproveRequest,
  BulkRejectRequest,
  BulkAssignRequest,
} from "@/lib/zod/admissions"

// Phase 7: Architecture Standards
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"
import { getStatusConfig } from "@/lib/status-config"

// ============================================
// QUERY KEYS
// ============================================

export const admissionsKeys = {
  all: ["admissions"] as const,
  lists: () => [...admissionsKeys.all, "list"] as const,
  list: (filters?: Record<string, unknown>) => [...admissionsKeys.lists(), filters] as const,
  details: () => [...admissionsKeys.all, "detail"] as const,
  detail: (id: number) => [...admissionsKeys.details(), id] as const,
  academicYears: () => [...admissionsKeys.all, "academic-years"] as const,
  statusCounts: (filters?: Record<string, unknown>) => [...admissionsKeys.all, "status-counts", filters] as const,
  stats: (academicYear?: number) => [...admissionsKeys.all, "stats", academicYear] as const,
}

// ============================================
// QUERIES
// ============================================

export function useListAdmissions(
  filters?: AdmissionListParams,
  options?: { initialData?: AdmissionsPage }
) {
  return useQuery({
    queryKey: admissionsKeys.list(filters as Record<string, unknown> | undefined),
    queryFn: () => admissionsApi.listAdmissions({
      page: filters?.page ?? 1,
      page_size: filters?.page_size ?? 20,
      status: filters?.status,
      search: filters?.search,
      major_id: filters?.major_id,
      academic_year: filters?.academic_year,
      degree_level: filters?.degree_level,
      payment_status: filters?.payment_status,
      date_from: filters?.date_from,
      date_to: filters?.date_to,
      sort_by: filters?.sort_by,
      order: filters?.order,
    }),
    staleTime: 15000, // 15 seconds
    gcTime: 5 * 60 * 1000, // 5 min — keep cached pages for back-navigation
    placeholderData: (previousData) => previousData, // Keep showing old data while fetching new page
    initialData: options?.initialData,
  })
}

export function useAcademicYears() {
  return useQuery({
    queryKey: admissionsKeys.academicYears(),
    queryFn: () => admissionsApi.getAcademicYears(),
    staleTime: 60 * 60 * 1000, // 1 hour - data rarely changes
  })
}

/**
 * Fetch degree levels via public admission-config endpoint
 * (accessible to all authenticated staff, not admin-only)
 */
export function useDegreeLevelsPublic() {
  return useQuery<Array<{ id: number; code: string; name: string }>>({
    queryKey: ["admission-config", "degree-levels"],
    queryFn: async () => {
      const { api } = await import("@/lib/api/client")
      const response = await api.get("/api/admission-config/degree-levels")
      return response.data
    },
    staleTime: 60 * 60 * 1000, // 1 hour
  })
}

export function useAdmissionStatusCounts(
  filters?: Omit<AdmissionListParams, 'page' | 'page_size' | 'status' | 'sort_by' | 'order'>
) {
  return useQuery({
    queryKey: admissionsKeys.statusCounts(filters as Record<string, unknown> | undefined),
    queryFn: () => admissionsApi.getStatusCounts(filters),
    staleTime: 30_000, // 30 seconds
  })
}

export function useAdmissionStats(academicYear?: number) {
  return useQuery({
    queryKey: admissionsKeys.stats(academicYear),
    queryFn: () => admissionsApi.getAdmissionStats(
      academicYear !== undefined ? { academic_year: academicYear } : undefined
    ),
    staleTime: 30_000, // 30 seconds
  })
}

/**
 * Fetch major programs that have admission profiles.
 * Uses admission-config endpoint (accessible to all staff, no CasbinAuth).
 */
export function useAdmissionPrograms() {
  return useQuery<Array<{ id: number; name: string; code: string; degree_level: string }>>({
    queryKey: [...admissionsKeys.all, "programs"],
    queryFn: () => admissionsApi.getAdmissionPrograms(),
    staleTime: 60 * 60 * 1000, // 1 hour - programs rarely change
  })
}

export function useGetAdmission(
  id: number,
  options?: {
    enabled?: boolean;
    initialData?: AdmissionProfileResponse;
    staleTime?: number;
  }
) {
  return useQuery({
    queryKey: admissionsKeys.detail(id),
    queryFn: () => admissionsApi.getAdmission(id),
    enabled: (options?.enabled ?? true) && !!id,
    initialData: options?.initialData,
    staleTime: options?.staleTime ?? 15000, // 15 seconds
  })
}

// ============================================
// MUTATIONS (Phase 7: Centralized Error Handling)
// ============================================

export function useCreateAdmission() {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation({
    mutationFn: admissionsApi.createAdmission,
    onSuccess: (data) => {
      toast.success("Tạo hồ sơ thành công")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
      router.push(`/admissions/${data.id}`)
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "tạo hồ sơ" })
    },
  })
}

export function useUpdateAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: AdmissionProfileUpdate) => admissionsApi.updateAdmission(id, data),
    onSuccess: () => {
      toast.success("Cập nhật thành công")
      // Invalidate to refetch fresh data from server
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      // Phase 7: Use centralized handler with 409 conflict support
      handleApiError(error, { 
        queryClient,
        invalidateKeys: [[...admissionsKeys.detail(id)]],
        context: "cập nhật hồ sơ"
      })
    },
  })
}

export function useSubmitAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => admissionsApi.submitAdmission(id),
    onSuccess: (data) => {
      // Phase 7: Use status-config for async-first workflow (ADR-FE-003)
      // Backend only returns "draft" (validation failed) or "submitted" (success)
      // Other statuses (approved, rejected) come from separate action endpoints
      
      if (data.status === 'submitted') {
        // Success: Profile is now pending approval
        const config = getStatusConfig('submitted')
        toast.info(config.bannerMessage || "Hồ sơ đã được nộp, đang chờ duyệt")
      } else if (data.validation_errors && data.validation_errors.length > 0) {
        // Validation failed (still draft status)
        toast.error("Hồ sơ chưa đủ điều kiện", {
          description: `${data.validation_errors.length} lỗi cần được khắc phục`
        })
      } else if (data.status === 'draft') {
        // Draft without explicit errors
        toast.warning("Hồ sơ chưa thể nộp", {
          description: "Vui lòng kiểm tra lại thông tin"
        })
      }
      
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { 
        queryClient,
        invalidateKeys: [[...admissionsKeys.detail(id)]],
        context: "nộp hồ sơ"
      })
    },
  })
}

/**
 * Approve Admission Hook
 * Manager/Admin action - transitions from submitted/resubmitted → approved
 * 
 * Architecture Compliance:
 * - Uses centralized error handling (handleApiError)
 * - Handles 409 Conflict (optimistic locking)
 * - Displays status-driven toast messages
 * - Invalidates cache on success
 */
export function useApproveAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: { notes?: string; version: number }) =>
      admissionsApi.approveAdmission(id, data),
    onSuccess: (data) => {
      // Status-driven messaging (FRONTEND_ARCHITECTURE_V3.md 2.3)
      if (data.status === 'approved') {
        toast.success("Hồ sơ đã được phê duyệt", {
          description: `Trạng thái: ${getStatusConfig('approved').label || data.status}`
        })
      } else {
        // Handle unexpected status (async-first principle)
        toast.info("Yêu cầu phê duyệt đã được xử lý", {
          description: `Trạng thái hiện tại: ${data.status}`
        })
      }
      
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      // Centralized error handler with 409 Conflict support
      handleApiError(error, {
        queryClient,
        invalidateKeys: [[...admissionsKeys.detail(id)]],
        context: "phê duyệt hồ sơ"
      })
    },
  })
}

/**
 * Reject Admission Hook
 * Manager/Admin action - transitions from submitted/resubmitted → rejected
 * 
 * Architecture Compliance:
 * - Uses centralized error handling (handleApiError)
 * - Handles 409 Conflict (optimistic locking)
 * - Displays status-driven toast messages
 * - Invalidates cache on success
 */
export function useRejectAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: { reason: string; version: number }) =>
      admissionsApi.rejectAdmission(id, data),
    onSuccess: (data) => {
      // Status-driven messaging (FRONTEND_ARCHITECTURE_V3.md 2.3)
      if (data.status === 'rejected') {
        toast.success("Hồ sơ đã bị từ chối", {
          description: data.rejection_reason || "Đã gửi lý do từ chối"
        })
      } else {
        // Handle unexpected status (async-first principle)
        toast.info("Yêu cầu từ chối đã được xử lý", {
          description: `Trạng thái hiện tại: ${data.status}`
        })
      }
      
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      // Centralized error handler with 409 Conflict support
      handleApiError(error, {
        queryClient,
        invalidateKeys: [[...admissionsKeys.detail(id)]],
        context: "từ chối hồ sơ"
      })
    },
  })
}

export function useEnrollStudent(id: number) {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation({
    mutationFn: () => admissionsApi.enrollStudent(id),
    onSuccess: (data) => {
      toast.success("Nhập học thành công", {
        description: `Mã sinh viên: ${data.student_code}`
      })
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      // Delay navigation
      setTimeout(() => {
        router.push(`/students/${data.student_id}`)
      }, 1500)
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { 
        queryClient,
        invalidateKeys: [[...admissionsKeys.detail(id)]],
        context: "nhập học"
      })
    },
  })
}

export function useUploadAdmissionDocument(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (variables: { docCode: string, file: File, actualSubmissionFormat?: string }) =>
        admissionsApi.uploadAdmissionDocument(id, variables.docCode, variables.file, variables.actualSubmissionFormat),
    onSuccess: (updatedProfile, variables) => {
      toast.success("Tài liệu đã được tải lên")

      // ✅ Backend now returns full AdmissionProfileResponse with updated validation_summary
      // Update cache directly (no need to refetch)
      queryClient.setQueryData(admissionsKeys.detail(id), updatedProfile)
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "tải lên tài liệu" })
    }
  })
}

export function useDeleteAdmission(id: number) {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation({
    mutationFn: () => admissionsApi.deleteAdmission(id),
    onSuccess: () => {
      toast.success("Xóa hồ sơ thành công")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
      router.push("/admissions")
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "xóa hồ sơ" })
    },
  })
}

export function useMarkPaperSubmitted(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (variables: { docCode: string, actualSubmissionFormat: string }) =>
      admissionsApi.markPaperSubmitted(id, variables.docCode, variables.actualSubmissionFormat),
    onSuccess: (updatedProfile, variables) => {
      toast.success("Đã xác nhận nhận giấy tờ")

      // ✅ Backend now returns full AdmissionProfileResponse with updated validation_summary
      // Update cache directly (no need to refetch)
      queryClient.setQueryData(admissionsKeys.detail(id), updatedProfile)
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "xác nhận giấy tờ" })
    }
  })
}

export function useVerifyDocument(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (variables: { docCode: string, format: string }) =>
      admissionsApi.verifyDocumentFormat(id, variables.docCode, variables.format),
    onSuccess: (data, variables) => {
      toast.success("Đã xác nhận tài liệu")
      
      // Update cache optimistically or invalidate
      queryClient.setQueryData(admissionsKeys.detail(id), (oldData: AdmissionProfileResponse | undefined) => {
        if (!oldData) return oldData
        
        const updatedChecklist = oldData.documents_checklist?.map(doc => 
          doc.code === variables.docCode
            ? { 
                ...doc, 
                status: "verified" as const, 
                submission_format: variables.format 
              }
            : doc
        ) || []
        
        return { ...oldData, documents_checklist: updatedChecklist }
      })
      
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "xác nhận tài liệu" })
    }
  })
}

export function useRejectDocument(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (variables: { docCode: string, reason: string }) =>
      admissionsApi.rejectDocument(id, variables.docCode, variables.reason),
    onSuccess: (data, variables) => {
      toast.success("Đã từ chối tài liệu")

      // Optimistic update
      queryClient.setQueryData(admissionsKeys.detail(id), (oldData: AdmissionProfileResponse | undefined) => {
        if (!oldData) return oldData

        const updatedChecklist = oldData.documents_checklist?.map(doc =>
          doc.code === variables.docCode
            ? { ...doc, status: "rejected" as const, rejection_reason: variables.reason }
            : doc
        ) || []

        return { ...oldData, documents_checklist: updatedChecklist }
      })

      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "từ chối tài liệu" })
    }
  })
}

export function useResetDocument(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (docCode: string) =>
      admissionsApi.resetDocument(id, docCode),
    onSuccess: (updatedProfile, docCode) => {
      toast.success("Đã hoàn tác tài liệu")

      // Update cache with full profile response
      queryClient.setQueryData(admissionsKeys.detail(id), updatedProfile)
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "hoàn tác tài liệu" })
    }
  })
}

// ============================================
// BULK ACTION MUTATIONS
// ============================================

/**
 * Bulk Approve Hook
 * Manager/Admin action - approve multiple profiles at once
 */
export function useBulkApproveAdmissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: BulkApproveRequest) =>
      admissionsApi.bulkApproveAdmissions(data),
    onSuccess: (result) => {
      if (result.success_count > 0) {
        toast.success(`Đã phê duyệt ${result.success_count} hồ sơ`, {
          description: result.failed_count > 0
            ? `${result.failed_count} hồ sơ thất bại`
            : undefined
        })
      } else {
        toast.error("Không thể phê duyệt hồ sơ nào", {
          description: result.message
        })
      }
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "phê duyệt hàng loạt" })
    },
  })
}

/**
 * Bulk Reject Hook
 * Manager/Admin action - reject multiple profiles at once
 */
export function useBulkRejectAdmissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: BulkRejectRequest) =>
      admissionsApi.bulkRejectAdmissions(data),
    onSuccess: (result) => {
      if (result.success_count > 0) {
        toast.success(`Đã từ chối ${result.success_count} hồ sơ`, {
          description: result.failed_count > 0
            ? `${result.failed_count} hồ sơ thất bại`
            : undefined
        })
      } else {
        toast.error("Không thể từ chối hồ sơ nào", {
          description: result.message
        })
      }
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "từ chối hàng loạt" })
    },
  })
}

/**
 * Bulk Assign Hook
 * Manager/Admin action - assign multiple profiles to an officer
 */
export function useBulkAssignAdmissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: BulkAssignRequest) =>
      admissionsApi.bulkAssignAdmissions(data),
    onSuccess: (result) => {
      if (result.success_count > 0) {
        toast.success(`Đã phân công ${result.success_count} hồ sơ`, {
          description: result.failed_count > 0
            ? `${result.failed_count} hồ sơ thất bại`
            : undefined
        })
      } else {
        toast.error("Không thể phân công hồ sơ nào", {
          description: result.message
        })
      }
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "phân công hàng loạt" })
    },
  })
}

/**
 * Claim Admission Hook
 * Officer action - claim a profile for review
 *
 * Architecture Compliance:
 * - Uses centralized error handling (handleApiError)
 * - Handles 409 Conflict (optimistic locking)
 * - Invalidates cache on success
 */
export function useClaimAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: { version: number }) =>
      admissionsApi.claimAdmissionProfile(id, data),
    onSuccess: () => {
      toast.success("Đã nhận duyệt hồ sơ")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "nhận duyệt hồ sơ" })
    },
  })
}

/**
 * Unclaim Admission Hook
 * Officer action - release review assignment
 *
 * Architecture Compliance:
 * - Uses centralized error handling (handleApiError)
 * - Handles 409 Conflict (optimistic locking)
 * - Invalidates cache on success
 */
export function useUnclaimAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: { version: number }) =>
      admissionsApi.unclaimAdmissionProfile(id, data),
    onSuccess: () => {
      toast.success("Đã bỏ nhận duyệt hồ sơ")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "bỏ nhận duyệt hồ sơ" })
    },
  })
}

/**
 * Export Admissions Hook
 * Download admissions as CSV file
 */
export function useExportAdmissions() {
  return useMutation({
    mutationFn: (params?: Omit<AdmissionListParams, 'page' | 'page_size'>) =>
      admissionsApi.exportAdmissionsCsv(params),
    onSuccess: (blob) => {
      // Create download link
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `admissions_export_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)

      toast.success("Xuất file CSV thành công")
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      handleApiError(error, { context: "xuất file CSV" })
    },
  })
}
