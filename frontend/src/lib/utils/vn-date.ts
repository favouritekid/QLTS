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
