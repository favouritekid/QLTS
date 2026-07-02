// src/components/sms/admin/labels.ts
/**
 * Nhãn tiếng Việt cho enum SMS Marketing (carrier / opt-out source /
 * campaign status / granularity). Dùng cho mọi trang admin PR-6.
 *
 * Thin-client: BE là nguồn sự thật của status; UI chỉ tra nhãn hiển thị và
 * LUÔN có fallback cho giá trị enum lạ (hiển thị raw) — không suy luận.
 */
import { format, parseISO } from "date-fns"
import { vi } from "date-fns/locale"

import {
  SMS_CARRIER_BUCKETS,
  SMS_CONSENT_BASES,
  SMS_GROUP_TYPES,
  SMS_LANDING_TYPES,
  SMS_MANUAL_OPT_OUT_SOURCES,
  SMS_REVOKE_SOURCES,
  type SmsAttestationKind,
  type SmsCampaign,
  type SmsCarrierBucket,
  type SmsConsentBasis,
  type SmsGranularity,
  type SmsGroupType,
  type SmsLandingType,
  type SmsManualOptOutSource,
  type SmsRevokeSource,
} from "@/lib/zod/sms"

export const CARRIER_LABELS: Record<string, string> = {
  viettel: "Viettel",
  vinaphone: "VinaPhone",
  mobifone: "MobiFone",
  vietnamobile: "Vietnamobile",
  gmobile: "Gmobile",
  unknown: "Không xác định",
}

export function carrierLabel(value: string): string {
  return CARRIER_LABELS[value] ?? value
}

/**
 * Nguồn opt-out — gồm cả `landing_optout` (số tự hủy qua trang, KHÔNG nằm
 * trong nhóm thêm-thủ-công nhưng có thể xuất hiện ở danh sách).
 */
export const OPT_OUT_SOURCE_LABELS: Record<string, string> = {
  manual: "Thủ công",
  sms_reply: "Trả lời SMS",
  phone_call: "Điện thoại",
  external_suppression: "Chặn ngoài hệ thống",
  landing_optout: "Hủy qua trang đích",
}

export function optOutSourceLabel(value: string): string {
  return OPT_OUT_SOURCE_LABELS[value] ?? value
}

/**
 * Nguồn cho FORM thêm thủ công (khớp SmsManualOptOutSource ở BE). Derive từ
 * enum + label map để nhãn không lệch giữa form và danh sách.
 */
export const MANUAL_OPT_OUT_SOURCE_OPTIONS: {
  value: SmsManualOptOutSource
  label: string
}[] = SMS_MANUAL_OPT_OUT_SOURCES.map((value) => ({
  value,
  label: OPT_OUT_SOURCE_LABELS[value],
}))

export const CAMPAIGN_STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  ready: "Sẵn sàng",
  exported: "Đã xuất",
  handed_off: "Đã bàn giao",
  closed: "Đã đóng",
}

export function campaignStatusLabel(value: string): string {
  return CAMPAIGN_STATUS_LABELS[value] ?? value
}

export const GRANULARITY_OPTIONS: { value: SmsGranularity; label: string }[] = [
  { value: "day", label: "Theo ngày" },
  { value: "month", label: "Theo tháng" },
  { value: "year", label: "Theo năm" },
]

/** Tùy chọn filter nhà mạng — derive từ enum + CARRIER_LABELS (DRY). */
export const CARRIER_FILTER_OPTIONS: {
  value: SmsCarrierBucket
  label: string
}[] = SMS_CARRIER_BUCKETS.map((value) => ({
  value,
  label: CARRIER_LABELS[value],
}))

/** Định dạng số nguyên kiểu Việt (1.234.567). */
export function formatInt(n: number): string {
  return n.toLocaleString("vi-VN")
}

/** Định dạng phần trăm CTR (BE trả sẵn dạng %; tối đa 1 chữ số thập phân). */
export function formatPercent(n: number): string {
  return `${n.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`
}

/** Định dạng dwell (giây) → "M phút S giây" / "S giây" (Phase 2 report). */
export function formatDwell(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} giây`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem === 0 ? `${m} phút` : `${m} phút ${rem} giây`
}

/**
 * Định dạng ISO datetime → "dd/MM/yyyy HH:mm" (giờ trình duyệt). An toàn,
 * không crash render: giá trị rỗng (null/undefined/"") → "—"; chuỗi không
 * parse được → trả lại chính chuỗi gốc (hiển thị raw).
 */
export function formatDateTimeVN(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return format(parseISO(iso), "dd/MM/yyyy HH:mm", { locale: vi })
  } catch {
    return iso
  }
}

/**
 * "Bây giờ" ở dạng value của <input type="datetime-local"> (YYYY-MM-DDTHH:mm,
 * giờ địa phương). Dùng cho `max` để chặn chọn thời điểm consent ở tương lai
 * (BE `validate_consent_datetime` từ chối tương lai → tránh 422 bất ngờ).
 */
export function nowDatetimeLocal(): string {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16)
}

/**
 * ISO tz-aware (UTC) → value cho <input type="datetime-local"> theo GIỜ ĐỊA
 * PHƯƠNG. Dùng khi nạp lại form sửa: BE trả UTC, input hiểu giờ local → phải
 * đổi UTC→local trước khi slice, nếu không sẽ lệch offset (bug link_expires_at).
 */
export function isoToDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16)
}

// =====================================================================
// Campaign / Preflight (PR-6d)
// =====================================================================
export const LANDING_TYPE_LABELS: Record<string, string> = {
  qlts_hosted: "Trang đích QLTS",
  external: "Liên kết ngoài",
}
export function landingTypeLabel(v: string): string {
  return LANDING_TYPE_LABELS[v] ?? v
}
export const LANDING_TYPE_OPTIONS: { value: SmsLandingType; label: string }[] =
  SMS_LANDING_TYPES.map((value) => ({ value, label: LANDING_TYPE_LABELS[value] }))

/** Lý do recipient bị loại ở build/preflight (excluded_by_reason keys). */
export const EXCLUDED_REASON_LABELS: Record<string, string> = {
  no_consent: "Chưa đồng ý",
  opted_out: "Đã từ chối nhận tin",
  dnc_suppressed: "Trong danh sách chặn (DNC)",
  frequency_capped: "Vượt tần suất gửi",
  over_limit: "Tin vượt 1 đoạn",
  missing_data: "Thiếu dữ liệu",
}
export function excludedReasonLabel(v: string): string {
  return EXCLUDED_REASON_LABELS[v] ?? v
}

// --- Attestation + Export (PR-6e) ---
export const ATTESTATION_KIND_LABELS: Record<string, string> = {
  consent: "Xác nhận đã có đồng ý (consent)",
  dnc: "Xác nhận đã lọc danh sách chặn (DNC)",
  optout_channel: "Xác nhận kênh từ chối hoạt động",
}
export function attestationKindLabel(v: string): string {
  return ATTESTATION_KIND_LABELS[v] ?? v
}

export const EXPORT_STATUS_LABELS: Record<string, string> = {
  pending: "Đang tạo",
  generated: "Đã tạo",
  handed_off: "Đã bàn giao",
  failed: "Thất bại",
  purged: "Đã xoá file",
  invalidated: "Vô hiệu (đã build lại)",
}
export function exportStatusLabel(v: string): string {
  return EXPORT_STATUS_LABELS[v] ?? v
}
export function exportStatusVariant(
  v: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (v === "handed_off") return "default"
  if (v === "failed") return "destructive"
  if (v === "purged" || v === "invalidated") return "secondary"
  return "outline"
}

/**
 * Attestation của `kind` hợp lệ khi khớp bản dựng hiện tại (build lại → vô
 * hiệu). Index typed theo `${kind}_checked_build_revision` (không cast unknown).
 */
export function isAttestationValid(
  c: SmsCampaign,
  kind: SmsAttestationKind,
): boolean {
  const rev = c[`${kind}_checked_build_revision`]
  return rev != null && rev === c.build_revision
}

// =====================================================================
// Contact / Group / Consent (PR-6b)
// =====================================================================
export const GROUP_TYPE_LABELS: Record<string, string> = {
  parent: "Phụ huynh",
  student: "Học sinh",
  teacher: "Giáo viên",
  lead: "Lead",
  custom: "Tùy chỉnh",
}
export function groupTypeLabel(v: string): string {
  return GROUP_TYPE_LABELS[v] ?? v
}
export const GROUP_TYPE_OPTIONS: { value: SmsGroupType; label: string }[] =
  SMS_GROUP_TYPES.map((value) => ({ value, label: GROUP_TYPE_LABELS[value] }))

export const CONSENT_STATUS_LABELS: Record<string, string> = {
  unknown: "Chưa rõ",
  granted: "Đã đồng ý",
  revoked: "Đã từ chối",
}
export function consentStatusLabel(v: string): string {
  return CONSENT_STATUS_LABELS[v] ?? v
}
/** Badge variant cho trạng thái consent (shadcn Badge). */
export function consentStatusVariant(
  v: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (v === "granted") return "default"
  if (v === "revoked") return "destructive"
  return "secondary"
}

export const CONSENT_BASIS_LABELS: Record<string, string> = {
  explicit_form: "Form điền rõ ràng",
  signed_form: "Phiếu có chữ ký",
  recorded_call: "Cuộc gọi ghi âm",
  imported_proof: "Bằng chứng nhập sẵn",
}
export function consentBasisLabel(v: string): string {
  return CONSENT_BASIS_LABELS[v] ?? v
}
export const CONSENT_BASIS_OPTIONS: { value: SmsConsentBasis; label: string }[] =
  SMS_CONSENT_BASES.map((value) => ({
    value,
    label: CONSENT_BASIS_LABELS[value],
  }))

/** Nguồn REVOKE — tái dùng nhãn opt-out source (cùng tập + landing_optout). */
export const REVOKE_SOURCE_OPTIONS: { value: SmsRevokeSource; label: string }[] =
  SMS_REVOKE_SOURCES.map((value) => ({
    value,
    label: optOutSourceLabel(value),
  }))

export const CONSENT_EVENT_TYPE_LABELS: Record<string, string> = {
  granted: "Đồng ý",
  revoked: "Từ chối",
}
export function consentEventTypeLabel(v: string): string {
  return CONSENT_EVENT_TYPE_LABELS[v] ?? v
}
