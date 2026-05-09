/**
 * useAdmissionRounds — React Query hooks for OfferingAdmissionRound CRUD
 * year-level (Phase 2 v8.2 PR-2A v2).
 *
 * Mirrors `useMasterData` toast + invalidation pattern.
 * Vietnamese toasts (workflow inversion review feedback).
 */
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import * as roundsApi from "@/lib/api/admission-rounds"
import type {
  AdmissionRoundBulkCreate,
  AdmissionRoundCreate,
  AdmissionRoundExtend,
  AdmissionRoundUpdate,
} from "@/lib/zod/admission-rounds"

interface ApiError {
  response?: {
    data?: {
      detail?: string
    }
  }
}

const ROUNDS_KEY = "admission-rounds"

export function useAdmissionRounds(academicYear: number | null) {
  return useQuery({
    queryKey: [ROUNDS_KEY, "by-year", academicYear],
    queryFn: () => roundsApi.listRoundsByYear(academicYear as number),
    enabled: academicYear !== null,
  })
}

export function useCreateRound(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AdmissionRoundCreate) =>
      roundsApi.createRound(academicYear, payload),
    onSuccess: () => {
      toast.success("Đã tạo đợt tuyển sinh")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-year", academicYear],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể tạo đợt")
    },
  })
}

export function useBulkCreateRounds(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AdmissionRoundBulkCreate) =>
      roundsApi.bulkCreateRounds(academicYear, payload),
    onSuccess: (res) => {
      if (res.skipped_duplicates > 0) {
        toast.success(
          `Đã tạo ${res.created} đợt mới (${res.skipped_duplicates} đã tồn tại)`,
        )
      } else {
        toast.success(`Đã tạo ${res.created} đợt tuyển sinh`)
      }
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-year", academicYear],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể tạo đợt hàng loạt")
    },
  })
}

export function useUpdateRound(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AdmissionRoundUpdate }) =>
      roundsApi.updateRound(id, data),
    onSuccess: () => {
      toast.success("Đã cập nhật đợt tuyển sinh")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-year", academicYear],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể cập nhật")
    },
  })
}

export function useSoftArchiveRound(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: roundsApi.softArchiveRound,
    onSuccess: () => {
      toast.success("Đã lưu trữ đợt tuyển sinh")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-year", academicYear],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể lưu trữ")
    },
  })
}

export function useExtendRound(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AdmissionRoundExtend }) =>
      roundsApi.extendRound(id, data),
    onSuccess: () => {
      toast.success("Đã gia hạn đợt tuyển sinh")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-year", academicYear],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể gia hạn")
    },
  })
}
