/**
 * Bỏ dấu tiếng Việt + lowercase để so khớp tìm kiếm KHÔNG phân biệt dấu
 * (officer thường gõ không dấu, vd "ke toan" → "Kế toán").
 *
 * - normalize("NFD") tách dấu kết hợp khỏi nguyên âm (á = a + U+0301).
 * - Strip combining marks (U+0300–U+036F).
 * - đ/Đ là KÝ TỰ RIÊNG (không tách qua NFD) nên map thủ công sang d/D.
 */
export function foldVietnamese(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[đĐ]/g, (c) => (c === "đ" ? "d" : "D"))
    .toLowerCase()
}
