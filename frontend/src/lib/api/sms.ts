/**
 * SMS Marketing API client.
 *
 * - Public landing endpoints (PR-5): no auth header, CSRF-exempt
 *   `/api/public/` prefix (Backend_FastAPI/app/middleware/csrf.py).
 * - Admin endpoints (PR-6 tiêu thụ router PR-5): yêu cầu đăng nhập +
 *   `require_admin` ở BE; `api` tự gắn cookie + CSRF cho mutation.
 *
 * Mọi response được validate bằng Zod mirror trước khi trả (thin-client).
 */
import { api } from "@/lib/api/client"
import {
  smsCampaignDashboardSchema,
  smsCampaignListSchema,
  smsClickReportSchema,
  smsLandingResponseSchema,
  smsOptOutListSchema,
  smsOptOutSchema,
  smsPublicOptOutResponseSchema,
  type SmsCampaignDashboard,
  type SmsCampaignList,
  type SmsClickReport,
  type SmsGranularity,
  type SmsLandingResponse,
  type SmsManualOptOutSource,
  type SmsOptOut,
  type SmsOptOutList,
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

// =====================================================================
// Admin — Reports + Dashboard + Opt-out (require_admin ở BE)
// =====================================================================

export interface SmsClickReportParams {
  granularity: SmsGranularity
  campaign_id?: number
  carrier?: string
  group_id?: number
  /** ISO datetime (kèm offset) — khoảng clicked_at. */
  date_from?: string
  date_to?: string
}

/** Báo cáo click tổng hợp theo ngày/tháng/năm + CTR (§9). */
export async function getSmsClickReport(
  params: SmsClickReportParams,
): Promise<SmsClickReport> {
  const res = await api.get<SmsClickReport>(`/api/sms/reports/clicks`, {
    params,
  })
  return smsClickReportSchema.parse(res.data)
}

/** Dashboard 1 chiến dịch: CTR + phân bố nhà mạng + danh sách số đã click. */
export async function getSmsCampaignDashboard(
  campaignId: number,
): Promise<SmsCampaignDashboard> {
  const res = await api.get<SmsCampaignDashboard>(
    `/api/sms/campaigns/${campaignId}/dashboard`,
  )
  return smsCampaignDashboardSchema.parse(res.data)
}

export interface SmsCampaignListParams {
  skip?: number
  limit?: number
  status?: string
  search?: string
}

/** Danh sách campaign (picker dashboard + filter report). */
export async function listSmsCampaigns(
  params: SmsCampaignListParams = {},
): Promise<SmsCampaignList> {
  const res = await api.get<SmsCampaignList>(`/api/sms/campaigns`, { params })
  return smsCampaignListSchema.parse(res.data)
}

export interface SmsOptOutListParams {
  skip?: number
  limit?: number
  search?: string
  source?: string
}

/** Danh sách số từ chối nhận tin (suppression toàn cục). */
export async function listSmsOptOuts(
  params: SmsOptOutListParams = {},
): Promise<SmsOptOutList> {
  const res = await api.get<SmsOptOutList>(`/api/sms/opt-out`, { params })
  return smsOptOutListSchema.parse(res.data)
}

export interface ManualOptOutPayload {
  phone: string
  source: SmsManualOptOutSource
  source_reference?: string
  reason?: string
}

/** Admin ghi opt-out thủ công (đối tác/điện thoại/SMS reply). */
export async function createManualOptOut(
  payload: ManualOptOutPayload,
): Promise<SmsOptOut> {
  const res = await api.post<SmsOptOut>(`/api/sms/opt-out/manual`, payload)
  return smsOptOutSchema.parse(res.data)
}
