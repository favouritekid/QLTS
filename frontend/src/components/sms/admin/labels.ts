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

import type {
  SmsCarrierBucket,
  SmsGranularity,
  SmsManualOptOutSource,
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

/** Nguồn cho FORM thêm thủ công (khớp SmsManualOptOutSource ở BE). */
export const MANUAL_OPT_OUT_SOURCE_OPTIONS: {
  value: SmsManualOptOutSource
  label: string
}[] = [
  { value: "manual", label: "Thủ công" },
  { value: "sms_reply", label: "Trả lời SMS" },
  { value: "phone_call", label: "Điện thoại" },
  { value: "external_suppression", label: "Chặn ngoài hệ thống" },
]

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

export const CARRIER_FILTER_OPTIONS: { value: SmsCarrierBucket; label: string }[] =
  [
    { value: "viettel", label: "Viettel" },
    { value: "vinaphone", label: "VinaPhone" },
    { value: "mobifone", label: "MobiFone" },
    { value: "vietnamobile", label: "Vietnamobile" },
    { value: "gmobile", label: "Gmobile" },
    { value: "unknown", label: "Không xác định" },
  ]

/** Định dạng số nguyên kiểu Việt (1.234.567). */
export function formatInt(n: number): string {
  return n.toLocaleString("vi-VN")
}

/** Định dạng phần trăm CTR (BE trả sẵn dạng %; tối đa 1 chữ số thập phân). */
export function formatPercent(n: number): string {
  return `${n.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`
}

/**
 * Định dạng ISO datetime → "dd/MM/yyyy HH:mm" (giờ trình duyệt). An toàn:
 * giá trị null/parse lỗi → "—" (không crash render).
 */
export function formatDateTimeVN(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return format(parseISO(iso), "dd/MM/yyyy HH:mm", { locale: vi })
  } catch {
    return iso
  }
}
