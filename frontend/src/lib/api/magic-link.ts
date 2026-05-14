/**
 * PR-CO-2-FE / PR-3E — Multi-action magic-link API client.
 *
 * Wraps the BE v2 consume endpoint:
 *   POST /api/v2/admissions/magic-link/{action}/{token}
 *
 * Public endpoint — no auth header, CSRF-exempt prefix (registered in
 * `Backend_FastAPI/app/middleware/csrf.py`). Validates the BE response
 * with the mirror Zod schema before returning — surfaces drift fast
 * per FRONTEND_ARCHITECTURE_V3.md thin-client contract.
 */
import { api } from "@/lib/api/client"
import {
  magicLinkConsumeResponseSchema,
  type MagicLinkAction,
  type MagicLinkConsumeRequest,
  type MagicLinkConsumeResponse,
} from "@/lib/zod/magic-link"

/**
 * Consume a magic-link token for the specified action.
 *
 * @param action - One of: submit | resubmit | confirm | withdraw.
 *                 MUST match the action_type the BE stamped on the
 *                 token row when it was issued; mismatch → 404.
 * @param token  - URL-safe random token from the email link.
 * @param body   - `{ cccd: '1234' }` last 4 digits of candidate's CCCD.
 *
 * @throws AxiosError 400 — CCCD wrong / expired / locked / not-yet-wired
 * @throws AxiosError 404 — token unknown OR action_type mismatch
 * @throws AxiosError 429 — slowapi global/per-IP rate limit
 */
export async function consumeMagicLinkToken(
  action: MagicLinkAction,
  token: string,
  body: MagicLinkConsumeRequest,
): Promise<MagicLinkConsumeResponse> {
  const response = await api.post<MagicLinkConsumeResponse>(
    `/api/v2/admissions/magic-link/${action}/${encodeURIComponent(token)}`,
    body,
  )
  return magicLinkConsumeResponseSchema.parse(response.data)
}
