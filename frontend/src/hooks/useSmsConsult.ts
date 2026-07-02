// src/hooks/useSmsConsult.ts
/**
 * React Query hooks P2-4b — consult officer (tiêu thụ BE P2-3).
 * Endpoint gate `CasbinAuth` + `get_lead_for_user` IDOR ở BE (officer chỉ lead
 * được giao). FE thin-client: hiển thị, để BE gác quyền (403/404 → ẩn/lỗi).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"

import {
  createSmsConsultLink,
  getSmsLeadInterests,
} from "@/lib/api/sms"
import { parseApiError } from "@/lib/utils/api-errors"
import type { ApiErrorResponse } from "@/types/api.types"
import type { SmsConsultLinkResponse } from "@/lib/zod/sms"

export const smsConsultKeys = {
  all: ["sms-consult"] as const,
  leadInterests: (leadId: number) =>
    [...smsConsultKeys.all, "lead-interests", leadId] as const,
}

/** Interest ngành của 1 lead. `enabled` để chỉ query khi mở section. */
export function useLeadSmsInterests(leadId: number, enabled = true) {
  return useQuery({
    queryKey: smsConsultKeys.leadInterests(leadId),
    queryFn: () => getSmsLeadInterests(leadId),
    enabled: enabled && leadId > 0,
    staleTime: 60 * 1000,
    // 403/404 (không quyền / ngoài IDOR) không retry.
    retry: false,
  })
}

/** Tạo link tư vấn — trả code/url (component hiển thị + copy). */
export function useCreateConsultLink() {
  const queryClient = useQueryClient()
  return useMutation<
    SmsConsultLinkResponse,
    AxiosError<ApiErrorResponse>,
    number
  >({
    mutationFn: (leadId: number) => createSmsConsultLink(leadId),
    onSuccess: (_data, leadId) => {
      toast.success("Đã tạo link tư vấn. Sao chép để gửi cho khách.")
      // Interest có thể phát sinh sau khi khách bấm link — làm mới khi quay lại.
      queryClient.invalidateQueries({
        queryKey: smsConsultKeys.leadInterests(leadId),
      })
    },
    onError: (err) => {
      toast.error(parseApiError(err, "Không thể tạo link tư vấn."))
    },
  })
}
