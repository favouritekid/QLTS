/**
 * Văn bản Hội đồng — tên bước trong URL.
 *
 * URL của luồng chỉ mang `setId` và TÊN BƯỚC (`?buoc=…`) — không bao giờ mang tên / CCCD / mã hồ sơ (đặc tả 5, luật
 * chung). Tên bước đọc ở trang máy chủ (`[setId]/page.tsx`, prop `searchParams`) rồi kiểm theo DANH SÁCH ĐÓNG này;
 * giá trị lạ ⇒ `null` (vào bước mặc định). Client KHÔNG đọc query string (test tĩnh cấm `useSearchParams`).
 */
export const VALID_STEPS = ["tai", "doi-chieu", "ghi-nhan"] as const
export type StepName = (typeof VALID_STEPS)[number]

/** `?buoc=` ⇒ tên bước hợp lệ hoặc `null`. Mảng (lặp khoá) hoặc giá trị lạ ⇒ `null`. */
export function readStep(value: string | string[] | undefined): StepName | null {
  if (typeof value !== "string") return null
  return (VALID_STEPS as readonly string[]).includes(value) ? (value as StepName) : null
}
