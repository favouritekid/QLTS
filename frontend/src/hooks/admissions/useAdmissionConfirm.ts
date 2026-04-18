/**
 * Magic-link admission confirmation hooks (public flow).
 *
 * Used by `src/app/confirm/[token]/page.tsx` — unauthenticated applicants
 * land there from the email they received, fetch token info, and submit
 * the last 4 digits of their citizen ID to confirm admission.
 */

import { useMutation, useQuery } from "@tanstack/react-query"

import {
  confirmAdmissionByToken,
  getConfirmTokenInfo,
} from "@/lib/api/admissions"
import type { ConfirmTokenVerifyRequest } from "@/lib/zod/admissions"

export const admissionConfirmKeys = {
  tokenInfo: (token: string) => ["admission-confirm-token-info", token] as const,
}

/**
 * Fetch token info once on mount so the page can decide whether to render
 * the CCCD form or a banner (locked / expired / already used).
 */
export function useConfirmTokenInfo(token: string) {
  return useQuery({
    queryKey: admissionConfirmKeys.tokenInfo(token),
    queryFn: () => getConfirmTokenInfo(token),
    retry: false,
    staleTime: 30_000,
    enabled: Boolean(token) && token !== "__placeholder__",
  })
}

/**
 * Verify CCCD digits → profile transitions to `confirmed`.
 *
 * Caller should invalidate `admissionConfirmKeys.tokenInfo(token)` in its
 * onError handler so `attempts_remaining` / `locked` / `already_used` reflect
 * the backend-committed state after a wrong-digit 400 or rate-limit 429.
 */
export function useConfirmAdmission(token: string) {
  return useMutation({
    mutationFn: (body: ConfirmTokenVerifyRequest) =>
      confirmAdmissionByToken(token, body),
  })
}
