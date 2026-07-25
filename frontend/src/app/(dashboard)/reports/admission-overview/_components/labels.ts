import type { ReportRow } from "@/lib/zod/reports";

/**
 * Bỏ hậu tố "(mã)" trùng ở label khi mã đã hiển thị riêng (cột/badge/tooltip).
 * Ví dụ label "Kế toán (6340301)" + code "6340301" → "Kế toán".
 */
export function cleanName(r: Pick<ReportRow, "code" | "label">): string {
  return r.code && r.label.endsWith(`(${r.code})`)
    ? r.label.slice(0, -(r.code.length + 2)).trimEnd()
    : r.label;
}
