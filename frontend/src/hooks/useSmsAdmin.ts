// src/hooks/useSmsAdmin.ts
/**
 * React Query hooks cho SMS Marketing admin (PR-6).
 *
 * Tiêu thụ router admin của PR-5 (Backend_FastAPI/app/routers/sms_reports.py
 * + sms_campaigns.py). Tất cả endpoint `require_admin` ở BE — đây là tầng
 * server-state, mọi gating hiển thị do sidebar/proxy lo (admin-only).
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"

import {
  createManualOptOut,
  getSmsCampaignDashboard,
  getSmsClickReport,
  listSmsCampaigns,
  listSmsOptOuts,
  type ManualOptOutPayload,
  type SmsCampaignListParams,
  type SmsClickReportParams,
  type SmsOptOutListParams,
} from "@/lib/api/sms"
import type { ApiErrorResponse } from "@/types/api.types"

// ---------------------------------------------------------------------
// Query-key factory
// ---------------------------------------------------------------------
export const smsAdminKeys = {
  all: ["sms-admin"] as const,
  clickReport: (params: SmsClickReportParams) =>
    [...smsAdminKeys.all, "click-report", params] as const,
  dashboard: (campaignId: number) =>
    [...smsAdminKeys.all, "dashboard", campaignId] as const,
  campaigns: (params: SmsCampaignListParams) =>
    [...smsAdminKeys.all, "campaigns", params] as const,
  optOuts: (params: SmsOptOutListParams) =>
    [...smsAdminKeys.all, "opt-outs", params] as const,
}

/** Trích thông điệp lỗi từ response BE (detail string | mảng | message). */
function extractErrorMessage(
  err: AxiosError<ApiErrorResponse>,
  fallback: string,
): string {
  const detail = err.response?.data?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail) && detail.length > 0 && detail[0]?.msg) {
    return detail[0].msg
  }
  if (err.response?.data?.message) return err.response.data.message
  return fallback
}

// ---------------------------------------------------------------------
// Reports + dashboard
// ---------------------------------------------------------------------
export function useSmsClickReport(params: SmsClickReportParams) {
  return useQuery({
    queryKey: smsAdminKeys.clickReport(params),
    queryFn: () => getSmsClickReport(params),
    staleTime: 60 * 1000,
  })
}

export function useSmsCampaignDashboard(campaignId: number | null) {
  return useQuery({
    queryKey: smsAdminKeys.dashboard(campaignId ?? 0),
    queryFn: () => getSmsCampaignDashboard(campaignId as number),
    enabled: campaignId != null,
    staleTime: 60 * 1000,
  })
}

export function useSmsCampaignList(params: SmsCampaignListParams = {}) {
  return useQuery({
    queryKey: smsAdminKeys.campaigns(params),
    queryFn: () => listSmsCampaigns(params),
    staleTime: 60 * 1000,
  })
}

// ---------------------------------------------------------------------
// Opt-out
// ---------------------------------------------------------------------
export function useSmsOptOuts(params: SmsOptOutListParams = {}) {
  return useQuery({
    queryKey: smsAdminKeys.optOuts(params),
    queryFn: () => listSmsOptOuts(params),
    staleTime: 30 * 1000,
  })
}

export function useCreateManualOptOut() {
  const queryClient = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof createManualOptOut>>,
    AxiosError<ApiErrorResponse>,
    ManualOptOutPayload
  >({
    mutationFn: createManualOptOut,
    onSuccess: () => {
      toast.success("Đã ghi nhận số từ chối nhận tin.")
      // Làm mới mọi danh sách opt-out (mọi filter/phân trang).
      queryClient.invalidateQueries({
        queryKey: [...smsAdminKeys.all, "opt-outs"],
      })
    },
    onError: (err) => {
      toast.error(
        extractErrorMessage(err, "Không thể ghi nhận số từ chối nhận tin."),
      )
    },
  })
}
