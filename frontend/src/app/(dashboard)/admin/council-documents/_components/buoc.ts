/**
 * Văn bản Hội đồng — tên bước trong URL.
 *
 * URL của luồng chỉ mang `setId` và TÊN BƯỚC (`?buoc=…`) — không bao giờ mang tên / CCCD / mã hồ sơ (đặc tả 5, luật
 * chung). Tên bước đọc ở trang máy chủ (`[setId]/page.tsx`, prop `searchParams`) rồi kiểm theo DANH SÁCH ĐÓNG này;
 * giá trị lạ ⇒ `null` (vào bước mặc định). Client KHÔNG đọc query string (test tĩnh cấm `useSearchParams`).
 */
export const BUOC_HOP_LE = ["tai", "doi-chieu", "ghi-nhan"] as const
export type TenBuoc = (typeof BUOC_HOP_LE)[number]

/** `?buoc=` ⇒ tên bước hợp lệ hoặc `null`. Mảng (lặp khoá) hoặc giá trị lạ ⇒ `null`. */
export function docBuoc(giaTri: string | string[] | undefined): TenBuoc | null {
  if (typeof giaTri !== "string") return null
  return (BUOC_HOP_LE as readonly string[]).includes(giaTri) ? (giaTri as TenBuoc) : null
}
