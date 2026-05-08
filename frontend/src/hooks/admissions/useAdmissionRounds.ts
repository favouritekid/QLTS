/**
 * useAdmissionRounds — React Query hooks for OfferingAdmissionRound CRUD
 * (Phase 2 PR-2A).
 *
 * Mirrors `useMasterData` toast + invalidation pattern.
 */
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import * as roundsApi from "@/lib/api/admission-rounds"
import type {
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

export function useAdmissionRounds(academicInfoId: number | null) {
  return useQuery({
    queryKey: [ROUNDS_KEY, "by-academic-info", academicInfoId],
    queryFn: () => roundsApi.listRoundsByAcademicInfo(academicInfoId as number),
    enabled: academicInfoId !== null,
  })
}

export function useCreateRound(academicInfoId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AdmissionRoundCreate) =>
      roundsApi.createRound(academicInfoId, payload),
    onSuccess: () => {
      toast.success("Đợt tuyển sinh đã được tạo")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-academic-info", academicInfoId],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể tạo đợt")
    },
  })
}

export function useUpdateRound(academicInfoId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AdmissionRoundUpdate }) =>
      roundsApi.updateRound(id, data),
    onSuccess: () => {
      toast.success("Đợt tuyển sinh đã được cập nhật")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-academic-info", academicInfoId],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể cập nhật đợt")
    },
  })
}

export function useSoftArchiveRound(academicInfoId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: roundsApi.softArchiveRound,
    onSuccess: () => {
      toast.success("Đợt đã được lưu trữ (soft-archive)")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-academic-info", academicInfoId],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể lưu trữ đợt")
    },
  })
}

export function useExtendRound(academicInfoId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AdmissionRoundExtend }) =>
      roundsApi.extendRound(id, data),
    onSuccess: () => {
      toast.success("Đợt đã được kéo dài thời gian")
      queryClient.invalidateQueries({
        queryKey: [ROUNDS_KEY, "by-academic-info", academicInfoId],
      })
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Không thể kéo dài đợt")
    },
  })
}
