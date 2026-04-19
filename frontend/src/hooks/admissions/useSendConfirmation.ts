/**
 * Send magic-link confirmation hook (officer/admin-facing).
 *
 * Calls POST /api/admissions/{id}/send-confirmation. The backend generates
 * (or regenerates) a confirmation token, queues the email to the applicant
 * if the lead has an email on file, and returns the full `confirm_url` so
 * the officer can share it manually (Zalo, SMS, phone) when email is not
 * available.
 */

import { useMutation } from "@tanstack/react-query"

import { api } from "@/lib/api/client"

export interface SendConfirmationResponse {
  message: string
  token_expires_at: string
  sent_to_email: string | null
  phone: string | null
  token_value: string | null
  confirm_url: string | null
}

export function useSendConfirmation() {
  return useMutation({
    mutationFn: async (profileId: number): Promise<SendConfirmationResponse> => {
      const { data } = await api.post<SendConfirmationResponse>(
        `/api/admissions/${profileId}/send-confirmation`,
        {},
      )
      return data
    },
  })
}
