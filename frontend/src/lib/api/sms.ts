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
  smsConsentEventListSchema,
  smsConsentEventSchema,
  smsContactGroupListSchema,
  smsContactGroupSchema,
  smsContactListSchema,
  smsContactSchema,
  smsImportResultSchema,
  smsLandingResponseSchema,
  smsOptOutListSchema,
  smsOptOutSchema,
  smsPublicOptOutResponseSchema,
  type SmsCampaignDashboard,
  type SmsCampaignList,
  type SmsClickReport,
  type SmsConsentEvent,
  type SmsConsentEventCreateInput,
  type SmsConsentEventList,
  type SmsContact,
  type SmsContactCreateInput,
  type SmsContactGroup,
  type SmsContactGroupCreateInput,
  type SmsContactGroupList,
  type SmsContactGroupUpdateInput,
  type SmsContactList,
  type SmsContactUpdateInput,
  type SmsGranularity,
  type SmsImportResult,
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

// =====================================================================
// Admin — Contact groups / Contacts / Consent (PR-6b, require_admin)
// =====================================================================

export interface SmsContactGroupListParams {
  skip?: number
  limit?: number
  group_type?: string
  is_active?: boolean
  search?: string
}

export async function listSmsContactGroups(
  params: SmsContactGroupListParams = {},
): Promise<SmsContactGroupList> {
  const res = await api.get<SmsContactGroupList>(`/api/sms/contact-groups`, {
    params,
  })
  return smsContactGroupListSchema.parse(res.data)
}

export async function getSmsContactGroup(
  groupId: number,
): Promise<SmsContactGroup> {
  const res = await api.get<SmsContactGroup>(
    `/api/sms/contact-groups/${groupId}`,
  )
  return smsContactGroupSchema.parse(res.data)
}

export async function createSmsContactGroup(
  payload: SmsContactGroupCreateInput,
): Promise<SmsContactGroup> {
  const res = await api.post<SmsContactGroup>(
    `/api/sms/contact-groups`,
    payload,
  )
  return smsContactGroupSchema.parse(res.data)
}

export async function updateSmsContactGroup(
  groupId: number,
  payload: SmsContactGroupUpdateInput,
): Promise<SmsContactGroup> {
  const res = await api.patch<SmsContactGroup>(
    `/api/sms/contact-groups/${groupId}`,
    payload,
  )
  return smsContactGroupSchema.parse(res.data)
}

export interface UploadContactsPayload {
  file: File
  source_label?: string
  consent_basis?: string
  consent_disclosure_version?: string
  consent_proof_ref?: string
  /** ISO tz-aware datetime; thời điểm đồng ý cho cả lô. */
  consent_obtained_at?: string
}

/** Import CSV/XLSX vào nhóm (multipart). `api` tự set header multipart. */
export async function uploadContactsToGroup(
  groupId: number,
  payload: UploadContactsPayload,
): Promise<SmsImportResult> {
  const form = new FormData()
  form.append("file", payload.file)
  if (payload.source_label) form.append("source_label", payload.source_label)
  if (payload.consent_basis) form.append("consent_basis", payload.consent_basis)
  if (payload.consent_disclosure_version)
    form.append("consent_disclosure_version", payload.consent_disclosure_version)
  if (payload.consent_proof_ref)
    form.append("consent_proof_ref", payload.consent_proof_ref)
  if (payload.consent_obtained_at)
    form.append("consent_obtained_at", payload.consent_obtained_at)
  const res = await api.post<SmsImportResult>(
    `/api/sms/contact-groups/${groupId}/contacts/upload`,
    form,
  )
  return smsImportResultSchema.parse(res.data)
}

export interface SmsContactListParams {
  skip?: number
  limit?: number
  search?: string
  consent_status?: string
}

export async function listGroupContacts(
  groupId: number,
  params: SmsContactListParams = {},
): Promise<SmsContactList> {
  const res = await api.get<SmsContactList>(
    `/api/sms/contact-groups/${groupId}/contacts`,
    { params },
  )
  return smsContactListSchema.parse(res.data)
}

export async function listSmsContacts(
  params: SmsContactListParams = {},
): Promise<SmsContactList> {
  const res = await api.get<SmsContactList>(`/api/sms/contacts`, { params })
  return smsContactListSchema.parse(res.data)
}

export async function createSmsContact(
  payload: SmsContactCreateInput,
): Promise<SmsContact> {
  const res = await api.post<SmsContact>(`/api/sms/contacts`, payload)
  return smsContactSchema.parse(res.data)
}

export async function updateSmsContact(
  contactId: number,
  payload: SmsContactUpdateInput,
): Promise<SmsContact> {
  const res = await api.patch<SmsContact>(
    `/api/sms/contacts/${contactId}`,
    payload,
  )
  return smsContactSchema.parse(res.data)
}

export async function appendConsentEvent(
  contactId: number,
  payload: SmsConsentEventCreateInput,
): Promise<SmsConsentEvent> {
  const res = await api.post<SmsConsentEvent>(
    `/api/sms/contacts/${contactId}/consent-events`,
    payload,
  )
  return smsConsentEventSchema.parse(res.data)
}

export async function listConsentEvents(
  contactId: number,
  params: { skip?: number; limit?: number } = {},
): Promise<SmsConsentEventList> {
  const res = await api.get<SmsConsentEventList>(
    `/api/sms/contacts/${contactId}/consent-events`,
    { params },
  )
  return smsConsentEventListSchema.parse(res.data)
}

/** Thêm contact vào nhóm; BE trả contact (trạng thái mới). */
export async function addContactToGroup(
  contactId: number,
  payload: { group_id: number; note?: string },
): Promise<SmsContact> {
  const res = await api.post<SmsContact>(
    `/api/sms/contacts/${contactId}/groups`,
    payload,
  )
  return smsContactSchema.parse(res.data)
}

export async function removeContactFromGroup(
  contactId: number,
  groupId: number,
): Promise<void> {
  await api.delete(`/api/sms/contacts/${contactId}/groups/${groupId}`)
}
