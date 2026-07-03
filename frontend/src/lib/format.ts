// src/lib/format.ts
// Formatter số/thời lượng thuần (không phụ thuộc domain) — dùng chung mọi
// module (admin SMS report, lead detail…). Trước đây ở components/sms/admin/
// labels.ts gây coupling leads→sms/admin; tách ra đây (labels re-export lại).

/** Định dạng số nguyên kiểu Việt (1.234.567). */
export function formatInt(n: number): string {
  return n.toLocaleString("vi-VN")
}

/** Định dạng phần trăm (giá trị đã ở dạng %; tối đa 1 chữ số thập phân). */
export function formatPercent(n: number): string {
  return `${n.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`
}

/** Định dạng thời lượng (giây) → "M phút S giây" / "S giây". */
export function formatDwell(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} giây`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem === 0 ? `${m} phút` : `${m} phút ${rem} giây`
}
