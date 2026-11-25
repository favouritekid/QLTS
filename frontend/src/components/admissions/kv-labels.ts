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
  // L3 (owner 22-11) — câu chữ CHỜ owner duyệt. BE: `priority_service.KV_PATHWAY_*`.
  lich_su_thcs: "Theo nơi học THCS (trường THCS trong danh mục)",
  cho_xac_minh: "Chờ xác minh",
  // Đoàn 3c (24-11) — mã BE HIỆN HÀNH (`priority_service._kv_resolution_steps`, `pathway=`); các khoá
  // `thpt_multi_school` / `tc_multi_school` / `commune_fallback` ở trên là tên CŨ, giữ cho ảnh chụp cũ.
  // Câu owner duyệt 25-11 (QUYET-DINH-OWNER-DOAN-3C-CAU-KV câu 1).
  lich_su_thpt: "Theo lịch sử học các trường THPT",
  thuong_tru: "Theo nơi thường trú",
  insufficient_data: "Chưa đủ dữ liệu để tính khu vực",
}

/** Rule applied enum → Vietnamese display label. */
export const RULE_LABEL_VI: Record<string, string> = {
  longest_duration: "Trường học lâu nhất",
  tiebreak_graduation_school: "Trường tốt nghiệp (khi thời gian học bằng nhau)",
  ambiguous_requires_manual: "Cần cán bộ xem xét (2 lựa chọn ngang nhau)",
  commune_lookup: "Tra cứu theo mã xã/phường nơi thường trú",
  manual_override: "Cán bộ ấn định thủ công",
  // L3 (owner 22-11) — BE `priority_service.KV_PENDING_VERIFICATION_RULE`; câu chữ CHỜ owner duyệt.
  kv_pending_verification: "KV chờ xác minh",
  // Đoàn 3c (24-11) — mã BE khi CHƯA tính được KV (`_kv_resolution_steps` `rule_applied=`; ảnh chụp:
  // `manual_override_unverified`). Câu owner duyệt 25-11.
  address_not_normalized: "Chưa có xã/phường nơi thường trú",
  catalog_gap_commune: "Xã/phường nơi thường trú chưa có khu vực trong danh mục",
  catalog_gap_school: "Trường đã học chưa có khu vực trong danh mục",
  not_resolved: "Chưa tính được khu vực",
  manual_override_unverified: "Ấn định thủ công chưa được xác nhận",
}

// Câu dùng chung cho nhiều mã (một câu — một chỗ). Đoàn 3c: owner duyệt 25-11 (QUYET-DINH-OWNER-DOAN-3C-CAU-KV).
const PENDING_MANUAL_VERIFICATION_VI =
  "Khu vực cần xác minh từ học bạ và ấn định thủ công (sơ cấp / hồ sơ không rõ trình độ)"
const BASIS_THPT_HISTORY_VI =
  "Tính theo các trường THPT đã học (trường học lâu nhất; thời gian bằng nhau thì theo trường tốt nghiệp)"
const BASIS_THCS_HISTORY_VI =
  "Tính theo các trường THCS đã học (trường học lâu nhất; thời gian bằng nhau thì theo trường tốt nghiệp)"
const BASIS_PERMANENT_COMMUNE_VI = "Tính theo xã/phường nơi thường trú"
const CD_CULTURAL_INSUFFICIENT_VI =
  "Trình độ văn hóa đã khai chưa đủ để tính khu vực cho cao đẳng (cần tốt nghiệp hoặc hoàn thành THPT) — kiểm tra lại trình độ văn hóa"

/**
 * Mã lý do KV của máy chủ → câu tiếng Việt cho cán bộ (thin client: CHỈ ánh xạ mã → câu).
 *
 * Hai nguồn mã cùng hiện ở dòng "Lý do" của thẻ KV (`priority/EngineResultCard.tsx` qua
 * `engineDisplay.resolveEngineDisplay`; `KvBreakdownCard`):
 *  - `reason` — vì sao CHƯA tính được KV (`priority_service._kv_resolution_steps`, `reason=`; xem trước
 *    khi soạn hồ sơ và ảnh chụp);
 *  - `basis_reason` — căn cứ tính KV (`_derive_kv_matrix_basis` / `_derive_kv_basis_level`), hiện ở
 *    hồ sơ đã nộp.
 */
export const REASON_VI: Record<string, string> = {
  cultural_not_set: "Chưa khai trình độ văn hóa",
  no_qualifying_entries: "Lịch sử học chưa đủ trường phù hợp với trình độ",
  // Đoàn 3c (24-11) SỬA câu cũ — L3 đưa thêm ca dòng THPT thiếu "Lớp cuối" khi thời gian học bằng nhau. Owner duyệt 25-11.
  tied_graduation_year_and_grade:
    "Thời gian học ở các trường THPT bằng nhau mà chưa chọn được trường tốt nghiệp (cùng năm, cùng lớp cuối, hoặc dòng THPT chưa ghi “Lớp cuối”) — kiểm tra “Lớp cuối” theo học bạ, hoặc đề nghị Quản lý / Admin ấn định KV thủ công",
  fallback_no_commune: "Chưa khai mã xã/phường nơi thường trú",
  special_case_no_commune: "Trường hợp đặc biệt nhưng chưa khai mã xã/phường",
  no_kv_lookup_succeeded: "Không tìm thấy KV cho các trường trong lịch sử (data MOET chưa đủ)",
  // L3 (owner 22-11) — BE `priority_service.KV_PENDING_REASON_*`; câu chữ CHỜ owner duyệt.
  kv_basis_needs_manual_verification: PENDING_MANUAL_VERIFICATION_VI,
  thcs_history_missing: "Chưa khai lịch sử học THCS — thêm các năm THCS theo học bạ",
  thcs_school_not_in_catalog:
    "Trường THCS chưa có trong danh mục — báo Admin thêm trường, rồi chọn lại trường trong lịch sử học",
  // Đoàn 3c (24-11) SỬA câu cũ — L3 (owner 24-11): dòng THCS ghi "Lớp cuối" 0, số âm hoặc từ 10 trở lên cũng dừng. Owner duyệt 25-11.
  thcs_history_inconsistent:
    "Dòng lịch sử học THCS chưa hợp lệ (0 năm học, năm ngược, “Lớp cuối” ghi 0, số âm hoặc từ 10 trở lên, trường liên cấp chưa ghi lớp cuối, chọn nhầm cấp trường…) — sửa theo học bạ; nếu học bạ đúng như vậy, đề nghị Quản lý / Admin ấn định KV thủ công",
  thcs_school_kv_missing:
    "Trường THCS chưa có khu vực cho đủ các năm học — báo Admin bổ sung khu vực của trường",
  thcs_tied_graduation_school:
    "Hai trường THCS ngang nhau về thời gian học và năm tốt nghiệp — cần cán bộ xác minh",
  thcs_school_dtnt:
    "Trường PT dân tộc nội trú — xác minh khu vực theo hộ khẩu và ấn định thủ công",

  // ── Đoàn 3c (24-11) — `reason` máy chủ trả khi CHƯA tính được KV mà bảng trên còn thiếu. Owner duyệt 25-11.
  special_case_no_commune_code:
    "Hồ sơ được đánh dấu trường hợp đặc biệt (tính theo nơi thường trú) nhưng chưa có xã/phường thường trú — nhập địa chỉ thường trú, chọn xã/phường trong danh mục",
  profile_missing_permanent_commune_code:
    "Chưa có xã/phường nơi thường trú — nhập địa chỉ thường trú, chọn xã/phường trong danh mục",
  commune_code_not_in_catalog:
    "Xã/phường nơi thường trú chưa có khu vực trong danh mục — báo Admin bổ sung khu vực cho xã/phường, hoặc đề nghị Quản lý / Admin ấn định KV thủ công",
  admin_set_kv_directly: "Khu vực do Quản lý / Admin ấn định thủ công",
  no_qualifying_thpt_history_entries:
    "Chưa có dòng lịch sử học cấp THPT (THPT, GDTX, hoặc liên cấp có lớp 10–12) chọn trường trong danh mục — thêm các năm học THPT theo học bạ, chọn trường trong danh mục",
  // L3 (owner 24-11): dòng THPT / GDTX ghi "Lớp cuối" ngoài 10–12 dừng ở đây (cùng mã với liên cấp thiếu lớp, 0 năm học).
  history_entries_inconsistent:
    "Có dòng lịch sử học THPT chưa hợp lệ (“Lớp cuối” không phải 10, 11 hay 12; trường liên cấp chưa ghi lớp cuối; năm bắt đầu trùng năm kết thúc) — sửa theo học bạ; nếu học bạ đúng như vậy, đề nghị Quản lý / Admin ấn định KV thủ công",
  all_school_lookups_failed:
    "Các trường THPT trong lịch sử học chưa có khu vực cho những năm đã học — báo Admin bổ sung khu vực của trường, hoặc đề nghị Quản lý / Admin ấn định KV thủ công",
  some_school_lookups_failed:
    "Một số trường THPT trong lịch sử học chưa có khu vực cho năm đã học — báo Admin bổ sung khu vực của trường cho đủ các năm",
  graduation_school_lookup_failed:
    "Thời gian học ở các trường THPT bằng nhau nhưng trường tốt nghiệp chưa có khu vực cho năm tốt nghiệp — báo Admin bổ sung khu vực của trường tốt nghiệp",
  tc_chinh_quy_cultural_insufficient_for_kv_basis:
    "Trình độ văn hóa đã khai chưa đủ để tính khu vực cho trung cấp (cần tốt nghiệp / hoàn thành THCS hoặc THPT) — kiểm tra lại trình độ văn hóa",
  tc_lien_thong_cultural_insufficient_for_kv_basis:
    "Trình độ văn hóa / trình độ chuyên môn đã khai chưa đủ để tính khu vực cho trung cấp liên thông — kiểm tra lại hai ô này",
  cd_chinh_quy_cultural_insufficient_for_kv_basis: CD_CULTURAL_INSUFFICIENT_VI,
  cd_lien_thong_cultural_insufficient_for_kv_basis: CD_CULTURAL_INSUFFICIENT_VI,
  legacy_unknown_cultural: "Không xác định được trình độ văn hóa khi tính khu vực — kiểm tra lại trình độ văn hóa",

  // ── Đoàn 3c (24-11) — `basis_reason` (căn cứ tính KV) hiện ở dòng "Lý do" của hồ sơ đã nộp. Owner duyệt 25-11.
  legacy_thpt_pathway: BASIS_THPT_HISTORY_VI,
  tc_chinh_quy_post_thpt_uses_school_history: BASIS_THPT_HISTORY_VI,
  tc_lien_thong_post_thpt_uses_school_history: BASIS_THPT_HISTORY_VI,
  cd_chinh_quy_post_thpt_uses_school_history: BASIS_THPT_HISTORY_VI,
  cd_lien_thong_post_thpt_uses_school_history: BASIS_THPT_HISTORY_VI,
  cd_chinh_quy_completed_thpt_uses_school_history: BASIS_THPT_HISTORY_VI,
  cd_lien_thong_completed_thpt_uses_school_history: BASIS_THPT_HISTORY_VI,
  cd_lien_thong_khoi_luong_with_thpt_history: BASIS_THPT_HISTORY_VI,
  tc_chinh_quy_post_thcs_uses_thcs_school_history: BASIS_THCS_HISTORY_VI,
  tc_lien_thong_post_thcs_with_voc_uses_thcs_school_history: BASIS_THCS_HISTORY_VI,
  tc_chinh_quy_post_thcs_uses_commune: BASIS_PERMANENT_COMMUNE_VI,
  tc_lien_thong_post_thcs_with_voc_uses_commune: BASIS_PERMANENT_COMMUNE_VI,
  sc_uses_commune: BASIS_PERMANENT_COMMUNE_VI,
  sc_no_cultural_uses_commune: BASIS_PERMANENT_COMMUNE_VI,
  legacy_thcs_pathway_uses_commune: BASIS_PERMANENT_COMMUNE_VI,
  legacy_completed_thpt_no_vocational: BASIS_PERMANENT_COMMUNE_VI,
  cd_lien_thong_khoi_luong_no_thpt_history_fallback:
    "Chưa khai lịch sử học THPT nên tính theo xã/phường nơi thường trú (cao đẳng liên thông, học khối lượng văn hóa THPT)",
  sc_no_cultural_kv_needs_verification: PENDING_MANUAL_VERIFICATION_VI,
  sc_kv_needs_verification: PENDING_MANUAL_VERIFICATION_VI,
  // Owner 25-11 (QUYET-DINH-OWNER-DOAN-3C-CAU-KV câu 1): mã là luồng THCS cũ, KHÔNG phải sơ cấp ⇒ câu RIÊNG, chép nguyên văn.
  legacy_thcs_pathway_kv_needs_verification:
    "Khu vực cần xác minh từ học bạ và ấn định thủ công (nhóm THCS / hồ sơ không rõ trình độ).",
  permanent_address_special_override: "Trường hợp đặc biệt cán bộ đã chọn: tính theo xã/phường nơi thường trú",
}

/**
 * Mã có phần chi tiết sau dấu hai chấm — máy chủ ghép `<mã>:<chi tiết>`: ảnh chụp
 * `manual_override_unverified:<lý do từ chối>` (`priority_service.freeze_priority_snapshot`) và căn cứ
 * `unsupported_target_level:<trình độ>` (`_derive_kv_matrix_basis`). Tra theo phần TRƯỚC dấu hai chấm,
 * CHỈ cho các mã khai ở đây. Owner duyệt 25-11.
 */
export const REASON_PREFIX_VI: Record<string, string> = {
  manual_override_unverified:
    "Khu vực ấn định thủ công chưa được xác nhận (dữ liệu hồ sơ đã đổi sau lần ấn định, hoặc thiếu bản ghi ấn định) — Quản lý / Admin ấn định lại KV",
  unsupported_target_level: "Trình độ đào tạo của hồ sơ chưa được hỗ trợ khi tính khu vực — báo bộ phận kỹ thuật",
}

const own = (map: Record<string, string>, key: string): string | undefined =>
  Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined

/**
 * Translate BE reason string → Vietnamese hint.
 * Returns raw reason as fallback when no mapping found (engineering edge case).
 * Chỉ khoá RIÊNG của bảng (không khoá kế thừa như `constructor` / `toString`).
 */
export function localizeReason(reason: string | null | undefined): string | null {
  if (!reason) return null
  const exact = own(REASON_VI, reason)
  if (exact !== undefined) return exact
  const colon = reason.indexOf(":")
  if (colon > 0) {
    const byPrefix = own(REASON_PREFIX_VI, reason.slice(0, colon))
    if (byPrefix !== undefined) return byPrefix
  }
  return reason
}
