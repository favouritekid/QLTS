/**
 * SMS Marketing public landing API client (PR-5).
 *
 * Public endpoints — no auth header, CSRF-exempt `/api/public/` prefix
 * (Backend_FastAPI/app/middleware/csrf.py). Validates BE response with the
 * mirror Zod schema before returning (thin-client contract).
 */
import { api } from "@/lib/api/client"
import {
  smsLandingResponseSchema,
  smsPublicOptOutResponseSchema,
  type SmsLandingResponse,
  type SmsPublicOptOutResponse,
} from "@/lib/zod/sms"

/**
 * Lấy nội dung landing cho 1 bearer code.
 * @throws AxiosError 404 — code sai/hết hạn (hiển thị trang lỗi thân thiện).
 */
export async function getSmsLanding(
  code: string,
): Promise<SmsLandingResponse> {
  const res = await api.get<SmsLandingResponse>(
    `/api/public/sms/landing/${encodeURIComponent(code)}`,
  )
  return smsLandingResponseSchema.parse(res.data)
}

/**
 * Hủy nhận tin (opt-out) — idempotent; hoạt động kể cả khi link đã hết hạn.
 * @throws AxiosError 404 — code sai.
 */
export async function postSmsOptOut(
  code: string,
): Promise<SmsPublicOptOutResponse> {
  const res = await api.post<SmsPublicOptOutResponse>(
    `/api/public/sms/opt-out`,
    { code },
  )
  return smsPublicOptOutResponseSchema.parse(res.data)
}
