/**
 * Đoàn 3c (24-11) — rà Codex L5 NỢ-1: thẻ KV không được hiện MÃ THÔ của máy chủ.
 *
 * Danh sách mã dưới đây CHÉP TAY từ `Backend_FastAPI/app/services/priority_service.py` (rà §6 ngày 24-11 trên
 * `release/doan-3c-20261124`): mọi giá trị máy chủ có thể đặt vào `reason` / `basis_reason` / `pathway` /
 * `rule_applied` của kết quả tính KV. Máy chủ thêm mã mới mà quên bảng `kv-labels.ts` ⇒ test này KHÔNG tự biết
 * (chưa có khoá chéo BE ↔ FE — ghi NỢ ở bàn giao đoàn 3c).
 */
import { describe, expect, it } from "vitest"

import {
  PATHWAY_LABEL_VI,
  REASON_PREFIX_VI,
  REASON_VI,
  RULE_LABEL_VI,
  localizeReason,
} from "./kv-labels"

/** `reason=` khi CHƯA tính được KV (`_kv_resolution_steps`, `_kv_thcs_history_steps`; nhánh INSUFFICIENT_DATA trả
 * chính `basis_reason`). Hiện ở xem trước (hồ sơ nháp) và ảnh chụp. */
const MA_LY_DO_CHUA_TINH = [
  "special_case_no_commune_code",
  "commune_code_not_in_catalog",
  "admin_set_kv_directly",
  "cultural_not_set",
  "profile_missing_permanent_commune_code",
  "kv_basis_needs_manual_verification",
  "no_qualifying_thpt_history_entries",
  "history_entries_inconsistent",
  "all_school_lookups_failed",
  "some_school_lookups_failed",
  "tied_graduation_year_and_grade",
  "graduation_school_lookup_failed",
  "thcs_history_missing",
  "thcs_school_not_in_catalog",
  "thcs_history_inconsistent",
  "thcs_school_kv_missing",
  "thcs_tied_graduation_school",
  "thcs_school_dtnt",
  "tc_chinh_quy_cultural_insufficient_for_kv_basis",
  "tc_lien_thong_cultural_insufficient_for_kv_basis",
  "cd_chinh_quy_cultural_insufficient_for_kv_basis",
  "cd_lien_thong_cultural_insufficient_for_kv_basis",
] as const

/** `basis_reason` (`_derive_kv_matrix_basis` + `_derive_kv_basis_level`) — dòng "Lý do" của hồ sơ đã nộp. Mã cao đẳng
 * ghép loại hình (`cd_{loại}_…`): chỉ hai loại `chinh_quy` / `lien_thong` (loại khác giữ mã — ghi ở bàn giao). */
const MA_CAN_CU = [
  "admin_set_kv_directly",
  "permanent_address_special_override",
  "cultural_not_set",
  "legacy_unknown_cultural",
  "legacy_thpt_pathway",
  "legacy_completed_thpt_no_vocational",
  "legacy_thcs_pathway_uses_commune",
  "legacy_thcs_pathway_kv_needs_verification",
  "sc_uses_commune",
  "sc_no_cultural_uses_commune",
  "sc_kv_needs_verification",
  "sc_no_cultural_kv_needs_verification",
  "tc_chinh_quy_post_thcs_uses_commune",
  "tc_chinh_quy_post_thcs_uses_thcs_school_history",
  "tc_chinh_quy_post_thpt_uses_school_history",
  "tc_chinh_quy_cultural_insufficient_for_kv_basis",
  "tc_lien_thong_post_thcs_with_voc_uses_commune",
  "tc_lien_thong_post_thcs_with_voc_uses_thcs_school_history",
  "tc_lien_thong_post_thpt_uses_school_history",
  "tc_lien_thong_cultural_insufficient_for_kv_basis",
  "cd_chinh_quy_post_thpt_uses_school_history",
  "cd_chinh_quy_completed_thpt_uses_school_history",
  "cd_chinh_quy_cultural_insufficient_for_kv_basis",
  "cd_lien_thong_post_thpt_uses_school_history",
  "cd_lien_thong_completed_thpt_uses_school_history",
  "cd_lien_thong_cultural_insufficient_for_kv_basis",
  "cd_lien_thong_khoi_luong_with_thpt_history",
  "cd_lien_thong_khoi_luong_no_thpt_history_fallback",
] as const

/** Mã ghép `<mã>:<chi tiết>`: ảnh chụp ấn định tay bị từ chối (đủ 8 lý do của `verify_manual_override_provenance`)
 * và căn cứ trình độ đào tạo chưa hỗ trợ. */
const MA_CO_CHI_TIET = [
  "manual_override_unverified:no_audit_row",
  "manual_override_unverified:audit_row_mismatch_actor",
  "manual_override_unverified:audit_row_mismatch_kv",
  "manual_override_unverified:actor_role_not_allowed",
  "manual_override_unverified:audit_row_missing_timestamp",
  "manual_override_unverified:timestamp_out_of_band",
  "manual_override_unverified:provenance_incomplete_no_fingerprint",
  "manual_override_unverified:stale_inputs",
  "unsupported_target_level:dai_hoc",
] as const

/** `pathway=` hiện hành. */
const MA_DUONG_TINH = [
  "commune_special",
  "manual",
  "not_resolved",
  "insufficient_data",
  "thuong_tru",
  "lich_su_thpt",
  "lich_su_thcs",
  "cho_xac_minh",
] as const

/** `rule_applied=` hiện hành (+ `manual_override_unverified` của ảnh chụp). */
const MA_QUY_TAC = [
  "address_not_normalized",
  "catalog_gap_commune",
  "catalog_gap_school",
  "commune_lookup",
  "manual_override",
  "manual_override_unverified",
  "not_resolved",
  "insufficient_data",
  "longest_duration",
  "tiebreak_graduation_school",
  "ambiguous_requires_manual",
  "kv_pending_verification",
] as const

const coKhoaRieng = (bang: Record<string, string>, khoa: string) =>
  Object.prototype.hasOwnProperty.call(bang, khoa)

describe("kv-labels — mọi mã lý do máy chủ có câu tiếng Việt (Codex L5 NỢ-1)", () => {
  it.each([...MA_LY_DO_CHUA_TINH, ...MA_CAN_CU, ...MA_CO_CHI_TIET])(
    "mã %s ⇒ câu tiếng Việt, không phải mã thô",
    (ma) => {
      const cau = localizeReason(ma)
      expect(typeof cau).toBe("string")
      expect(cau).not.toBe(ma)
      // Câu cho người đọc — không còn dấu gạch dưới của mã máy.
      expect(cau).not.toMatch(/_/)
      expect((cau as string).length).toBeGreaterThan(15)
    },
  )

  it("mã chính xác nằm trong bảng mã (không đi đường tra theo dấu hai chấm)", () => {
    for (const ma of [...MA_LY_DO_CHUA_TINH, ...MA_CAN_CU]) {
      expect(coKhoaRieng(REASON_VI, ma)).toBe(true)
    }
  })

  it("mọi mã đường tính và quy tắc hiện hành đều có nhãn riêng", () => {
    for (const ma of MA_DUONG_TINH) expect(coKhoaRieng(PATHWAY_LABEL_VI, ma)).toBe(true)
    for (const ma of MA_QUY_TAC) expect(coKhoaRieng(RULE_LABEL_VI, ma)).toBe(true)
  })
})

describe("kv-labels — câu của các mã dừng L3 nói cán bộ phải làm gì", () => {
  it("THPT/GDTX ghi “Lớp cuối” ngoài 10–12 (history_entries_inconsistent): sửa theo học bạ hoặc ấn định tay", () => {
    const cau = localizeReason("history_entries_inconsistent") as string
    expect(cau).toContain("“Lớp cuối” không phải 10, 11 hay 12")
    expect(cau).toContain("sửa theo học bạ")
    expect(cau).toContain("ấn định KV thủ công")
  })

  it("THCS ghi “Lớp cuối” 0 / âm / từ 10 (thcs_history_inconsistent): câu nêu đúng ca mới", () => {
    const cau = localizeReason("thcs_history_inconsistent") as string
    expect(cau).toContain("“Lớp cuối” ghi 0, số âm hoặc từ 10 trở lên")
    expect(cau).toContain("ấn định KV thủ công")
  })

  it("THPT hoà thời gian mà thiếu “Lớp cuối” (tied_graduation_year_and_grade): câu nhắc ô “Lớp cuối”", () => {
    expect(localizeReason("tied_graduation_year_and_grade")).toContain("chưa ghi “Lớp cuối”")
  })
})

/** Câu owner ghi NGUYÊN VĂN ở `doan-tau-3c\QUYET-DINH-OWNER-DOAN-3C-CAU-KV-2026-11-25.md` câu 1 (sha256 `42f3ae52…`) — chép tay, có
 * cả dấu chấm cuối như trong tệp quyết định. */
const CAU_OWNER_LUONG_THCS_CU = "Khu vực cần xác minh từ học bạ và ấn định thủ công (nhóm THCS / hồ sơ không rõ trình độ)."

describe("kv-labels — câu owner chốt 25-11", () => {
  it("legacy_thcs_pathway_kv_needs_verification ⇒ đúng NGUYÊN VĂN câu owner (luồng THCS cũ, không phải sơ cấp)", () => {
    expect(localizeReason("legacy_thcs_pathway_kv_needs_verification")).toBe(CAU_OWNER_LUONG_THCS_CU)
  })

  it("các mã sơ cấp vẫn giữ câu “sơ cấp”, KHÔNG bị đổi theo câu owner của luồng THCS", () => {
    for (const ma of ["kv_basis_needs_manual_verification", "sc_kv_needs_verification", "sc_no_cultural_kv_needs_verification"]) {
      const cau = localizeReason(ma)
      expect(cau).toContain("(sơ cấp / hồ sơ không rõ trình độ)")
      expect(cau).not.toBe(CAU_OWNER_LUONG_THCS_CU)
    }
  })
})

describe("kv-labels — localizeReason chỉ ÁNH XẠ mã → câu", () => {
  it("mã có chi tiết sau dấu hai chấm: tra theo phần trước dấu hai chấm", () => {
    expect(localizeReason("manual_override_unverified:stale_inputs")).toBe(
      REASON_PREFIX_VI.manual_override_unverified,
    )
    expect(localizeReason("unsupported_target_level:dai_hoc")).toBe(REASON_PREFIX_VI.unsupported_target_level)
  })

  it("phần trước dấu hai chấm chỉ tra bảng mã-có-chi-tiết, không tra bảng mã thường", () => {
    expect(localizeReason("cultural_not_set:x")).toBe("cultural_not_set:x")
    expect(localizeReason(":manual_override_unverified")).toBe(":manual_override_unverified")
  })

  it("mã lạ giữ nguyên (không đoán câu)", () => {
    expect(localizeReason("ma_tuong_lai_chua_co")).toBe("ma_tuong_lai_chua_co")
  })

  it("khoá kế thừa của object (constructor, toString, __proto__…) KHÔNG bị coi là mã", () => {
    for (const ma of ["constructor", "toString", "__proto__", "hasOwnProperty", "constructor:x"]) {
      expect(localizeReason(ma)).toBe(ma)
    }
  })

  it("rỗng / null / undefined ⇒ null", () => {
    expect(localizeReason("")).toBeNull()
    expect(localizeReason(null)).toBeNull()
    expect(localizeReason(undefined)).toBeNull()
  })
})
