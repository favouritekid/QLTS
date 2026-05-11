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

export const VISIBILITY_LABEL: Record<string, string> = {
  public: "Công khai (storefront)",
  internal: "Nội bộ (chỉ admin)",
}
