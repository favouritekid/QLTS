// src/hooks/useSmsExport.ts
/**
 * React Query hooks — SMS Attestation + Export lifecycle (PR-6e).
 * Attestation/export/handed-off đổi campaign (status + attestation fields) →
 * invalidate cả cụm sms-campaigns + danh sách export. require_admin ở BE.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"

import {
  addCampaignAttestation,
  downloadSmsExport,
  exportSmsCampaign,
  listSmsCampaignExports,
  markSmsExportHandedOff,
} from "@/lib/api/sms"
import { parseApiError } from "@/lib/utils/api-errors"
import { blobErrorMessage } from "@/lib/utils/download-blob"
import type { SmsAttestationCreateInput } from "@/lib/zod/sms"
import type { ApiErrorResponse } from "@/types/api.types"

import { smsCampaignKeys } from "./useSmsCampaigns"

type ApiError = AxiosError<ApiErrorResponse>

export const smsExportKeys = {
  all: ["sms-exports"] as const,
  list: (campaignId: number) =>
    [...smsExportKeys.all, "list", campaignId] as const,
}

function invalidateAfterMutation(
  qc: ReturnType<typeof useQueryClient>,
  campaignId: number,
) {
  // Campaign (status/attestation/build) + danh sách batch đều có thể đổi.
  qc.invalidateQueries({ queryKey: smsCampaignKeys.all })
  qc.invalidateQueries({ queryKey: smsExportKeys.list(campaignId) })
}

// ---------------------------------------------------------------------
export function useCampaignExports(campaignId: number | null, enabled = true) {
  return useQuery({
    queryKey: smsExportKeys.list(campaignId ?? 0),
    queryFn: () => listSmsCampaignExports(campaignId as number),
    enabled: campaignId != null && enabled,
    staleTime: 30 * 1000,
  })
}

export function useAddAttestation(campaignId: number) {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, SmsAttestationCreateInput>({
    mutationFn: (payload) => addCampaignAttestation(campaignId, payload),
    onSuccess: () => {
      toast.success("Đã ghi xác nhận.")
      invalidateAfterMutation(qc, campaignId)
    },
    onError: (e) =>
      toast.error(parseApiError(e, "Không thể ghi xác nhận.")),
  })
}

export function useExportCampaign(campaignId: number) {
  const qc = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof exportSmsCampaign>>,
    ApiError,
    void
  >({
    mutationFn: () => exportSmsCampaign(campaignId),
    onSuccess: (res) => {
      toast.success(res.message || "Đã tạo file export.")
      invalidateAfterMutation(qc, campaignId)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể export.")),
  })
}

export function useMarkExportHandedOff(campaignId: number) {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, { batchId: number }>({
    mutationFn: ({ batchId }) => markSmsExportHandedOff(campaignId, batchId),
    onSuccess: () => {
      toast.success("Đã đánh dấu bàn giao.")
      invalidateAfterMutation(qc, campaignId)
    },
    onError: (e) =>
      toast.error(parseApiError(e, "Không thể đánh dấu bàn giao.")),
  })
}

/** Tải file export (imperative, có loading state per lần bấm). */
export function useDownloadExport(campaignId: number) {
  return useMutation<
    void,
    ApiError,
    { batchId: number; fallbackName: string }
  >({
    mutationFn: ({ batchId, fallbackName }) =>
      downloadSmsExport(campaignId, batchId, fallbackName),
    // responseType:'blob' → body lỗi là Blob; blobErrorMessage đọc .text() ra detail.
    onError: async (e) =>
      toast.error(await blobErrorMessage(e, "Không thể tải file.")),
  })
}
