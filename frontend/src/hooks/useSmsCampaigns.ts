// src/hooks/useSmsCampaigns.ts
/**
 * React Query hooks cho SMS Marketing — Campaign CRUD + Build/Preflight (PR-6d).
 * Tiêu thụ router PR-3 (sms_campaigns.py). Tất cả `require_admin` ở BE.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"

import {
  attachCampaignGroup,
  buildSmsCampaign,
  createSmsCampaign,
  detachCampaignGroup,
  getSmsCampaign,
  getSmsCampaignPreflight,
  listCampaignGroups,
  listSmsCampaignsFull,
  measureSmsTemplate,
  updateSmsCampaign,
  type SmsCampaignListParams,
} from "@/lib/api/sms"
import { parseApiError } from "@/lib/utils/api-errors"
import type {
  SmsCampaignCreateInput,
  SmsCampaignUpdateInput,
} from "@/lib/zod/sms"
import type { ApiErrorResponse } from "@/types/api.types"

type ApiError = AxiosError<ApiErrorResponse>

export const smsCampaignKeys = {
  all: ["sms-campaigns"] as const,
  list: (p: SmsCampaignListParams) =>
    [...smsCampaignKeys.all, "list", p] as const,
  detail: (id: number) => [...smsCampaignKeys.all, "detail", id] as const,
  groups: (id: number) => [...smsCampaignKeys.all, "groups", id] as const,
  preflight: (id: number) => [...smsCampaignKeys.all, "preflight", id] as const,
}

function invalidateCampaigns(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: smsCampaignKeys.all })
}

// ---------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------
export function useSmsCampaignsFull(params: SmsCampaignListParams = {}) {
  return useQuery({
    queryKey: smsCampaignKeys.list(params),
    queryFn: () => listSmsCampaignsFull(params),
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
  })
}

export function useSmsCampaign(campaignId: number | null) {
  return useQuery({
    queryKey: smsCampaignKeys.detail(campaignId ?? 0),
    queryFn: () => getSmsCampaign(campaignId as number),
    enabled: campaignId != null,
    staleTime: 30 * 1000,
  })
}

/** Nhóm đã gắn vào campaign (liệt kê + bỏ). */
export function useCampaignGroups(campaignId: number | null) {
  return useQuery({
    queryKey: smsCampaignKeys.groups(campaignId ?? 0),
    queryFn: () => listCampaignGroups(campaignId as number),
    enabled: campaignId != null,
    staleTime: 30 * 1000,
  })
}

/** Preflight bản build hiện tại — chỉ tải khi campaign đã build (enabled). */
export function useSmsCampaignPreflight(
  campaignId: number | null,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: smsCampaignKeys.preflight(campaignId ?? 0),
    queryFn: () => getSmsCampaignPreflight(campaignId as number),
    enabled: campaignId != null && (options.enabled ?? true),
    staleTime: 30 * 1000,
  })
}

/** Đo/preview template LIVE cho form soạn campaign. `template` nên là giá trị
 * đã DEBOUNCE (component lo debounce) — hook chỉ query khi non-rỗng. */
export function useMeasureSmsTemplate(
  template: string,
  sampleFullName?: string,
) {
  return useQuery({
    queryKey: [
      ...smsCampaignKeys.all,
      "measure",
      template,
      sampleFullName ?? "",
    ],
    queryFn: () =>
      measureSmsTemplate({
        template,
        sample_full_name: sampleFullName?.trim() || undefined,
      }),
    enabled: template.trim().length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

// ---------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------
export function useCreateSmsCampaign() {
  const qc = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof createSmsCampaign>>,
    ApiError,
    SmsCampaignCreateInput
  >({
    mutationFn: createSmsCampaign,
    onSuccess: () => {
      toast.success("Đã tạo chiến dịch.")
      invalidateCampaigns(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể tạo chiến dịch.")),
  })
}

export function useUpdateSmsCampaign() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { id: number; data: SmsCampaignUpdateInput }
  >({
    mutationFn: ({ id, data }) => updateSmsCampaign(id, data),
    onSuccess: () => {
      toast.success("Đã cập nhật chiến dịch.")
      invalidateCampaigns(qc)
    },
    onError: (e) =>
      toast.error(parseApiError(e, "Không thể cập nhật chiến dịch.")),
  })
}

export function useAttachCampaignGroup() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { campaignId: number; groupId: number }
  >({
    mutationFn: ({ campaignId, groupId }) =>
      attachCampaignGroup(campaignId, groupId),
    onSuccess: () => {
      toast.success("Đã gắn nhóm vào chiến dịch.")
      invalidateCampaigns(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể gắn nhóm.")),
  })
}

export function useDetachCampaignGroup() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { campaignId: number; groupId: number }
  >({
    mutationFn: ({ campaignId, groupId }) =>
      detachCampaignGroup(campaignId, groupId),
    onSuccess: () => {
      toast.success("Đã bỏ nhóm khỏi chiến dịch.")
      invalidateCampaigns(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể bỏ nhóm.")),
  })
}

export function useBuildSmsCampaign() {
  const qc = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof buildSmsCampaign>>,
    ApiError,
    number
  >({
    mutationFn: buildSmsCampaign,
    onSuccess: () => {
      // Preflight + campaign (build_revision/status) đổi → làm mới cả cụm.
      invalidateCampaigns(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể build chiến dịch.")),
  })
}
