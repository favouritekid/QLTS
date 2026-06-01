/**
 * Bảng nhãn tiếng Việt cho admission path trong matrix UI.
 * Phase 2 v8.2 PR-2D.1 v4a — i18n shim cho status/visibility raw từ API.
 */

export const PATH_STATUS_LABEL: Record<string, string> = {
  draft: "Bản nháp",
  active: "Đang hoạt động",
  inactive: "Đã ngưng",
  archived: "Đã lưu trữ",
}

export function pathStatusLabel(s: string | null | undefined): string {
  if (!s) return "—"
  return PATH_STATUS_LABEL[s] ?? s
}

/**
 * Màu chấm trạng thái (dot) cho ô ma trận phễu.
 *
 * Keyed theo AdmissionPath status (draft/active/inactive/archived) — KHÁC
 * AdmissionProfile status nên KHÔNG dùng được ADMISSION_BADGE_CONFIG (chỉ
 * trùng "draft"). Tailwind bg-* classes; fallback bg-muted-foreground.
 */
export const PATH_STATUS_DOT: Record<string, string> = {
  draft: "bg-slate-400",
  active: "bg-emerald-500",
  inactive: "bg-amber-500",
  archived: "bg-zinc-400",
}

export function pathStatusDot(s: string | null | undefined): string {
  if (!s) return "bg-muted-foreground"
  return PATH_STATUS_DOT[s] ?? "bg-muted-foreground"
}

export const VISIBILITY_LABEL: Record<string, string> = {
  public: "Công khai (storefront)",
  internal: "Nội bộ (chỉ admin)",
}
