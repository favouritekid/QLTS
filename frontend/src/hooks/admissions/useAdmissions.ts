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
}

// ============================================
// QUERIES
// ============================================

export function useListAdmissions(
  filters?: { status?: string; page?: number; page_size?: number }
) {
  return useQuery({
    queryKey: admissionsKeys.list(filters),
    queryFn: () => admissionsApi.listAdmissions(filters),
    staleTime: 15000, // 15 seconds
    refetchOnWindowFocus: true,
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
    refetchOnWindowFocus: true,
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
