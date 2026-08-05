// src/lib/utils/vn-date.ts
/**
 * Timezone-aware date utilities for Vietnam (Asia/Ho_Chi_Minh).
 *
 * Ensures SSR (running in UTC) and client both produce the same
 * YYYY-MM-DD string for "today" relative to Vietnamese local time.
 */

const VN_TZ = "Asia/Ho_Chi_Minh";

/**
 * Get "today" as a YYYY-MM-DD string in Vietnam timezone.
 * Safe for both server (UTC) and client (any timezone).
 */
export function todayVN(now: Date = new Date()): string {
  return now.toLocaleDateString("sv-SE", { timeZone: VN_TZ });
  // sv-SE locale gives ISO format YYYY-MM-DD
}

/**
 * `Date` người dùng bấm trên lịch → `"YYYY-MM-DD"` của **đúng ô ngày họ bấm**.
 *
 * Không dùng `toISOString()` cho việc này. `react-day-picker` trả về 00:00 giờ
 * địa phương, mà `toISOString()` quy về UTC — ở Việt Nam (UTC+7) thì 05/08
 * 00:00 thành `2026-08-04T17:00:00Z`, và `.split("T")[0]` cho ra **04/08**.
 * Nghĩa là mọi lần kế toán tự chọn ngày, hệ thống ghi lùi một ngày. Đã đo:
 * `TZ=Asia/Ho_Chi_Minh`, `new Date(2026, 7, 5).toISOString()` → `2026-08-04T17:00:00.000Z`.
 *
 * Đọc thẳng các thành phần địa phương là cách duy nhất giữ nguyên ý định của
 * người bấm — chuyển múi giờ ở đây bao giờ cũng là chuyển sai thứ gì đó, vì
 * "ngày trên tờ giấy nộp tiền" không phải một mốc thời gian, nó là một ô lịch.
 */
export function calendarDateToISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Mốc ISO từ máy chủ → `DD/MM/YYYY` theo **ngày lịch Việt Nam**.
 *
 * Đừng cắt chuỗi (`iso.slice(0, 10)`): mốc trong cơ sở dữ liệu là UTC, và một
 * khoản thu ngày 05/08 giờ Việt Nam được lưu là `2026-08-04T17:00:00Z` — cắt
 * mười ký tự đầu cho ra **04/08**, tức lùi đúng một ngày cho mọi phiếu ghi
 * trong ngày. Ở khối cảnh báo trùng thì đó là lỗi chí mạng: người ghi thấy
 * "phiếu kia ngày 04/08" trong khi mình đang nhập 05/08 và kết luận đây là hai
 * khoản khác nhau.
 *
 * `timeZone` cố định (không theo máy người dùng) để khớp đúng múi giờ mà luật
 * dò trùng ở máy chủ đang dùng.
 */
export function formatNgayVN(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: VN_TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(d);
}

/**
 * Subtract `days` from a Vietnam-local date string and return YYYY-MM-DD.
 */
export function subDaysVN(dateStr: string, days: number): string {
  // Parse the date as noon UTC to avoid DST edge cases
  const d = new Date(`${dateStr}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/**
 * Get the first day of the month for a Vietnam-local date string.
 */
export function startOfMonthVN(dateStr: string): string {
  return dateStr.slice(0, 8) + "01";
}

/** "YYYY-MM-DD" → "DD/MM" — nhãn ngày gọn (trục biểu đồ / tuần). */
export function dmVN(dateStr: string): string {
  return `${dateStr.slice(8, 10)}/${dateStr.slice(5, 7)}`;
}

/**
 * ISO-8601 week-numbering YEAR of a YYYY-MM-DD date. The ISO year is the year of
 * the Thursday in that date's week, so late-December days can belong to next
 * year's week 1 (and early-January days to the prior year's last week). Mirrors
 * the backend's `week.iso_year`; used to keep week navigation inside the academic
 * year (the report rejects a week whose iso_year != academic_year).
 */
export function isoWeekYearVN(dateStr: string): number {
  const d = new Date(`${dateStr}T12:00:00Z`);
  const day = d.getUTCDay() || 7; // Mon=1 … Sun=7
  d.setUTCDate(d.getUTCDate() + 4 - day); // Thursday of this ISO week
  return d.getUTCFullYear();
}
