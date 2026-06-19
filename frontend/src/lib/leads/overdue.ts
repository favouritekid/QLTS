// src/lib/leads/overdue.ts
import type { Lead } from "@/types/lead.types";

/**
 * Lead có quá hạn liên hệ hay không — tính TRỰC TIẾP từ `next_activity_at`.
 *
 * Nguồn sự thật là `next_activity_at < now`, KHÔNG tin field cache
 * `lead.is_overdue`. Field cache đó chỉ được set khi có mutation consultation
 * hoặc nightly cron 00:05, nên có thể "tàng hình" tới ~14h sau khi một lead
 * vừa quá hạn. Cách này khớp với backend list filter (cố ý tính trực tiếp
 * `next_activity_at < now()` thay vì đọc cột materialized — xem
 * `lead_repository.py`).
 *
 * Chỉ dùng cho HIỂN THỊ phía client (component "use client"). Với chỗ có thể
 * SSR (vd ActionBanner trong LeadDetailClient), TRUYỀN `now` từ `useClientNow()`
 * (trả `null` khi SSR + first render) thay vì để default `Date.now()` — gọi
 * `Date.now()` trong render path SSR gây hydration mismatch khi `next_activity_at`
 * nằm sát thời điểm hiện tại. Trong `useEffect` (client-only) thì default an toàn.
 *
 * Lưu ý domain: CHỈ áp dụng cho Lead. KHÔNG dùng cho `fee.is_overdue` /
 * `invoice.is_overdue` (Finance có ngữ nghĩa quá hạn riêng).
 */
export function isLeadOverdue(
  lead: Pick<Lead, "next_activity_at">,
  now: number = Date.now(),
): boolean {
  if (!lead.next_activity_at) return false;
  return new Date(lead.next_activity_at).getTime() < now;
}
