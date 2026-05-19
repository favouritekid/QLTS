/**
 * KV (Khu vực ưu tiên) display labels — shared constants.
 *
 * Source of truth Vietnamese labels for KV codes + pathway + rule + reason
 * fields returned by BE engine `resolve_kv_for_profile()` (Phase C).
 *
 * Extracted from `PriorityTab.tsx` (Phase E.1) cho DRY:
 * - `KvBreakdownCard` (current snapshot display)
 * - `PriorityOverrideDialog` (E.2 override flow — preview before/after)
 *
 * BE source: `app/services/priority_service.py` `_derive_kv_basis_level()`
 * matrix + `resolve_kv_for_profile()` `pathway` + `rule_applied` enums.
 */

/** KV code → badge color + Vietnamese label (with bonus point hint). */
export const KV_BADGE: Record<string, { color: string; label: string }> = {
  KV1: { color: "bg-emerald-100 text-emerald-800 border-emerald-300", label: "KV1 (+0,75đ)" },
  "KV2-NT": { color: "bg-blue-100 text-blue-800 border-blue-300", label: "KV2-NT (+0,50đ)" },
  KV2: { color: "bg-amber-100 text-amber-800 border-amber-300", label: "KV2 (+0,25đ)" },
  KV3: { color: "bg-gray-100 text-gray-800 border-gray-300", label: "KV3 (không cộng)" },
}

/** Pathway enum (BE resolve_kv_for_profile) → Vietnamese display label. */
export const PATHWAY_LABEL_VI: Record<string, string> = {
  thpt_multi_school: "Theo lịch sử học các trường THPT (3 năm cấp 3)",
  tc_multi_school: "Theo thời gian học trung cấp",
  commune_fallback: "Theo nơi thường trú",
  commune_special: "Theo nơi thường trú (trường hợp đặc biệt)",
  manual: "Cán bộ ấn định thủ công",
  not_resolved: "Chưa xác định được",
}

/** Rule applied enum → Vietnamese display label. */
export const RULE_LABEL_VI: Record<string, string> = {
  longest_duration: "Trường học lâu nhất",
  tiebreak_graduation_school: "Trường tốt nghiệp (khi thời gian học bằng nhau)",
  ambiguous_requires_manual: "Cần cán bộ xem xét (2 lựa chọn ngang nhau)",
  commune_lookup: "Tra cứu theo mã xã/phường nơi thường trú",
  manual_override: "Cán bộ ấn định thủ công",
}

/** Failure reason → Vietnamese hint shown to candidate. */
export const REASON_VI: Record<string, string> = {
  cultural_not_set: "Chưa khai trình độ văn hóa",
  no_qualifying_entries: "Lịch sử học chưa đủ trường phù hợp với trình độ",
  tied_graduation_year_and_grade: "Có 2 trường ngang nhau về thời gian + lớp tốt nghiệp — cần cán bộ xem xét",
  fallback_no_commune: "Chưa khai mã xã/phường nơi thường trú",
  special_case_no_commune: "Trường hợp đặc biệt nhưng chưa khai mã xã/phường",
  no_kv_lookup_succeeded: "Không tìm thấy KV cho các trường trong lịch sử (data MOET chưa đủ)",
}

/**
 * Translate BE reason string → Vietnamese hint.
 * Returns raw reason as fallback when no mapping found (engineering edge case).
 */
export function localizeReason(reason: string | null | undefined): string | null {
  if (!reason) return null
  return REASON_VI[reason] ?? reason
}
