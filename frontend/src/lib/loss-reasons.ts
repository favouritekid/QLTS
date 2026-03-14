// src/lib/loss-reasons.ts
/**
 * Loss Reason Taxonomy - Frontend Fallback
 *
 * The canonical source of truth lives in the backend (pipeline_service.LOSS_REASONS).
 * This file provides a static fallback for:
 *   - Initial render before the API responds
 *   - Error/offline states
 *   - Non-hook contexts (utility functions, server components)
 *
 * Components that need live data should use the useLossReasons() hook
 * from @/hooks/usePipeline which fetches from GET /api/pipeline/loss-reasons.
 */

export interface LossReason {
  code: string;
  label: string;
  icon: string;
  category: string;
  is_recoverable: boolean;
  action_hint: string;
}

export const LOSS_REASONS: LossReason[] = [
  { code: "PRICE_HIGH", label: "Học phí", icon: "💰", category: "price", is_recoverable: true, action_hint: "Xem xét chính sách học bổng/ưu đãi" },
  { code: "LOCATION_FAR", label: "Xa nhà", icon: "📍", category: "logistics", is_recoverable: true, action_hint: "Hỗ trợ thông tin ký túc xá/di chuyển" },
  { code: "CHOSE_COMPETITOR", label: "Trường khác", icon: "🎓", category: "competitor", is_recoverable: false, action_hint: "Phân tích USP và cải thiện pitch" },
  { code: "NO_CONTACT", label: "K.liên lạc", icon: "📞", category: "contact", is_recoverable: true, action_hint: "Cải thiện quy trình follow-up" },
  { code: "TIMING_BAD", label: "Chưa sẵn sàng", icon: "⏰", category: "timing", is_recoverable: true, action_hint: "Nurture leads chưa ready" },
  { code: "OTHER", label: "Khác", icon: "❓", category: "other", is_recoverable: true, action_hint: "Phân tích và có chiến lược xử lý" },
];

/**
 * Get a formatted label for a loss reason code (e.g. "icon label").
 * Uses the static fallback array -- safe for non-hook contexts.
 */
export function getLossReasonLabel(code: string | null | undefined): string {
  if (!code) return "";
  const reason = LOSS_REASONS.find((r) => r.code === code);
  return reason ? `${reason.icon} ${reason.label}` : code;
}

/**
 * Build a Record<code, {label, icon}> map.
 * When `reasons` is provided (from useLossReasons() hook), uses dynamic data.
 * Otherwise falls back to static LOSS_REASONS array.
 */
export function getLossReasonMap(reasons?: LossReason[]): Record<string, { label: string; icon: string }> {
  const source = reasons ?? LOSS_REASONS;
  const map: Record<string, { label: string; icon: string }> = {};
  for (const r of source) {
    map[r.code] = { label: r.label, icon: r.icon };
  }
  return map;
}

/**
 * Build a Record<code, label> map.
 * When `reasons` is provided (from useLossReasons() hook), uses dynamic data.
 * Otherwise falls back to static LOSS_REASONS array.
 */
export function getLossReasonLabelMap(reasons?: LossReason[]): Record<string, string> {
  const source = reasons ?? LOSS_REASONS;
  const map: Record<string, string> = {};
  for (const r of source) {
    map[r.code] = r.label;
  }
  return map;
}
