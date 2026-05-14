/**
 * PR-CO-2-FE / PR-3E — Multi-action magic-link React Query hook.
 *
 * Public flow — no auth context. The mutation key carries the action +
 * token so multiple in-flight consumes (extremely unlikely from a
 * single candidate browser) stay isolated.
 */
import { useMutation } from "@tanstack/react-query"
import type { AxiosError } from "axios"

import { consumeMagicLinkToken } from "@/lib/api/magic-link"
import type { ApiErrorResponse } from "@/lib/error-handler"
import type {
  MagicLinkAction,
  MagicLinkConsumeRequest,
  MagicLinkConsumeResponse,
} from "@/lib/zod/magic-link"

export const magicLinkKeys = {
  consume: (action: MagicLinkAction, token: string) =>
    ["magic-link-consume", action, token] as const,
}

export function useMagicLinkConsume(
  action: MagicLinkAction,
  token: string,
) {
  return useMutation<
    MagicLinkConsumeResponse,
    AxiosError<ApiErrorResponse>,
    MagicLinkConsumeRequest
  >({
    mutationKey: magicLinkKeys.consume(action, token),
    mutationFn: (body) => consumeMagicLinkToken(action, token, body),
  })
}
