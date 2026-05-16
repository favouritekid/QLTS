/**
 * W2-1 fix Wave 7 (2026-05-16) — Generate magic-link hook cho 3 candidate
 * self-service actions (submit/resubmit/withdraw).
 *
 * Mirror useSendConfirmation pattern. Calls POST
 * /api/admissions/{id}/send-magic-link với body `{action}`. BE generates
 * token + returns URL — officer copy URL từ FE dialog → share manual qua
 * Zalo/SMS (KHÔNG có Celery email auto-send cho Wave 7 MVP, defer FU
 * khi product clarify Vietnamese templates per action).
 */

import { useMutation } from "@tanstack/react-query"

import { api } from "@/lib/api/client"

export type MagicLinkAction = "submit" | "resubmit" | "withdraw"

export interface SendMagicLinkResponse {
  message: string
  action: MagicLinkAction
  token_expires_at: string
  sent_to_email: string | null
  phone: string | null
  token_value: string | null
  magic_link_url: string | null
}

export function useSendMagicLink() {
  return useMutation({
    mutationFn: async ({
      profileId,
      action,
    }: {
      profileId: number
      action: MagicLinkAction
    }): Promise<SendMagicLinkResponse> => {
      const { data } = await api.post<SendMagicLinkResponse>(
        `/api/admissions/${profileId}/send-magic-link`,
        { action },
      )
      return data
    },
  })
}
