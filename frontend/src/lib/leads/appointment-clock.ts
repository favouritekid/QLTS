// src/lib/leads/appointment-clock.ts
// =============================================================================
// Helper thuần cho "Nhịp hẹn" / "Trợ lý nhắc hẹn" — dùng chung giữa
// AppointmentReminder (bảng dropdown) và AppointmentAssistant (bong bóng + nudge).
// Không phụ thuộc React; đồng hồ đếm sống dùng `useServerNow` (hooks/useServerNow).
// =============================================================================

import { getDegreeLevelAbbr } from "@/constants";
import type { MyAppointmentItem } from "@/lib/api/leads";

/** ≤10 phút tới giờ hẹn = "đến giờ" (hổ phách). */
export const DUE_SOON_MS = 10 * 60 * 1000;

export type ApptState = "overdue" | "due" | "soon";

export const pad = (n: number) => String(n).padStart(2, "0");

// Giờ hẹn (server_time/scheduled_at) là instant UTC (backend `datetime.now(tz.utc)`).
// Format LUÔN theo giờ Việt Nam để không lệ thuộc múi giờ máy client (máy đặt sai
// TZ / đang ở nước ngoài vẫn hiện đúng giờ VN). Formatter dùng chung, cache 1 lần.
const VN_HHMM = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Ho_Chi_Minh",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** "HH:MM" theo giờ VN từ một mốc epoch-ms. */
export function hhmmFromMs(ms: number): string {
  return VN_HHMM.format(new Date(ms));
}

/** Khoảng cách (ms) từ bây giờ tới giờ hẹn; âm = đã quá hạn. */
export function apptDelta(scheduledAt: string, serverNow: number): number {
  return new Date(scheduledAt).getTime() - serverNow;
}

/** Trạng thái-thời-gian của một hẹn so với server_now. */
export function stateOf(scheduledAt: string, serverNow: number): ApptState {
  const delta = apptDelta(scheduledAt, serverNow);
  if (delta < 0) return "overdue";
  if (delta <= DUE_SOON_MS) return "due";
  return "soon";
}

/** Định dạng khoảng cách tới giờ hẹn: ngày → H:MM:SS → MM:SS (đếm sống). */
export function formatDelta(ms: number): string {
  // floor TRÊN trị tuyệt đối: delta âm (quá hạn) -300ms phải là 0s, không phải 1s.
  const s = Math.floor(Math.abs(ms) / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d >= 1) return `${d} ngày${h ? ` ${h}h` : ""}`;
  if (h >= 1) return `${h}:${pad(m)}:${pad(sec)}`;
  return `${pad(m)}:${pad(sec)}`;
}

export function hhmm(iso: string): string {
  return hhmmFromMs(new Date(iso).getTime());
}

/** Dòng ngành: "CĐ Dược" · "TC Kế toán" · fallback khi chưa chọn ngành. */
export function eduLine(item: MyAppointmentItem): string {
  const deg = getDegreeLevelAbbr(item.degree_level ?? undefined);
  const parts = [deg, item.major].filter(Boolean);
  return parts.length ? parts.join(" ") : "Chưa chọn ngành";
}

/** Dòng phụ: ngành · NV phụ trách (tên NV chỉ có khi admin/manager xem toàn bộ). */
export function metaLine(item: MyAppointmentItem): string {
  return item.officer_name ? `${eduLine(item)} · ${item.officer_name}` : eduLine(item);
}

/** Bảng class Tailwind theo trạng-thái-thời-gian (đỏ trễ → hổ phách → xanh). */
export const STATE_STYLE: Record<ApptState, { text: string; bar: string; pill: string }> = {
  overdue: {
    text: "text-red-600 dark:text-red-400",
    bar: "bg-red-500",
    pill: "text-red-600 dark:text-red-300 bg-red-500/10",
  },
  due: {
    text: "text-amber-600 dark:text-amber-400",
    bar: "bg-amber-500",
    pill: "text-amber-700 dark:text-amber-300 bg-amber-500/10",
  },
  soon: {
    text: "text-blue-600 dark:text-blue-400",
    bar: "bg-blue-500",
    pill: "text-blue-600 dark:text-blue-300 bg-blue-500/10",
  },
};
