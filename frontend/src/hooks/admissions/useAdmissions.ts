/**
 * TanStack Query Hooks for Admissons
 * Mirrored from useLeads.ts pattern
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
import type { ApiErrorResponse } from "@/types/api.types"

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
// MUTATIONS
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
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" 
          ? detail 
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Đã có lỗi xảy ra"
      
      toast.error("Lỗi tạo hồ sơ", {
        description: message,
      })
    },
  })
}

export function useUpdateAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: AdmissionProfileUpdate) => admissionsApi.updateAdmission(id, data),
    onSuccess: (data) => {
      toast.success("Cập nhật thành công")
      queryClient.setQueryData(admissionsKeys.detail(id), data)
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Đã có lỗi xảy ra"

      toast.error("Lỗi cập nhật", {
        description: message,
      })
    },
  })
}

export function useSubmitAdmission(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => admissionsApi.submitAdmission(id),
    onSuccess: (data) => {
      if (data.status === 'approved') {
        toast.success("Hồ sơ đã được duyệt")
      } else {
        toast.error("Hồ sơ bị từ chối", {
           description: `${data.errors?.length} lỗi được tìm thấy`
        })
      }
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Đã có lỗi xảy ra"

      toast.error("Lỗi nộp hồ sơ", {
        description: message,
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
      toast.success("Nhập học thành công")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
      // Delay navigation
      setTimeout(() => {
        router.push(`/students/${data.student_id}`)
      }, 1500)
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Đã có lỗi xảy ra"

      toast.error("Lỗi nhập học", {
        description: message,
      })
    },
  })
}

export function useUploadAdmissionDocument(id: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (variables: { docCode: string, file: File }) => 
        admissionsApi.uploadAdmissionDocument(id, variables.docCode, variables.file),
    onSuccess: () => {
      toast.success("Tải liệu đã được tải lên")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
    },
    onError: (error: AxiosError<ApiErrorResponse>) => {
        const detail = error.response?.data?.detail
        const message =
          typeof detail === "string"
            ? detail
            : "Lỗi tải lên tài liệu"
        toast.error(message)
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
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Đã có lỗi xảy ra"

      toast.error("Lỗi xóa hồ sơ", {
        description: message,
      })
    },
  })
}
