/**
 * GĐ1b §5.2 / §5.9 — giữ `batch_id` của lô gần nhất trong `sessionStorage` (sống qua tải lại trang, chết khi đóng tab).
 *
 * CHỈ `batch_id` (UUID máy chủ sinh) — KHÔNG id hồ sơ / giấy, KHÔNG lý do, KHÔNG câu xác nhận. Đây là tệp DUY NHẤT của
 * GĐ1b được chạm `sessionStorage` (test tĩnh `document-review.static.test.ts` khoá). Mọi lần đọc phải SAU khi mount
 * (`useHasMounted`) để HTML máy chủ và lần vẽ đầu ở trình duyệt giống nhau (tránh #418).
 *
 * Storage có thể ném (chế độ riêng tư / hết hạn mức) ⇒ nuốt lỗi, coi như không có.
 */
const KEY = "qlts.gd1b.lastBatchId"
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export const LAST_BATCH_ID_KEY = KEY

export function isBatchId(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value)
}

/** Người nghe trong CÙNG tab (cho `useSyncExternalStore`) — sự kiện `storage` chỉ bắn ở tab khác. */
const listeners = new Set<() => void>()
function notify(): void {
  for (const l of listeners) l()
}
export function subscribeLastBatchId(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function saveLastBatchId(batchId: string): void {
  if (typeof window === "undefined" || !isBatchId(batchId)) return
  try {
    window.sessionStorage.setItem(KEY, batchId)
  } catch {
    // storage không dùng được — mất khả năng tra lại sau tải trang, danh sách "lô của tôi" vẫn còn (§5.8)
  }
  notify()
}

export function readLastBatchId(): string | null {
  if (typeof window === "undefined") return null
  try {
    const v = window.sessionStorage.getItem(KEY)
    return isBatchId(v) ? v : null
  } catch {
    return null
  }
}

export function clearLastBatchId(): void {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // như trên
  }
  notify()
}
