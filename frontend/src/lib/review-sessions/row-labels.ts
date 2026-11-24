/**
 * GĐ2-B F4 — nhãn + định dạng cho DÒNG kết quả (E9 `RowOut`) ở M5 bốn tab và ngăn chi tiết M6. Chỉ ÁNH XẠ mã / giá trị máy chủ →
 * câu (trình bày): KHÔNG tính điểm, KHÔNG suy tab / lý do / quyền. Mã lạ ⇒ câu chung CÓ mã (HĐ4 §1.8); `null` ⇒ "—", KHÔNG đổi thành 0
 * (`frontend/CLAUDE.md` "Default business values").
 *
 * Nguồn câu: thiết kế giao diện GĐ2-B Phụ lục A (chờ owner duyệt G8). Đây là phương án (b) của KT-1 ("từ điển FE") vì máy chủ CHƯA có
 * route danh mục câu (S2 / KT-1 a) — NỢ: khi có S2, đổi sang câu máy chủ (một nguồn) và bỏ bảng ở đây. Câu GĐ1 (`BLOCK_REASONS` của
 * máy chủ) KHÔNG chép sang ⇒ mã GĐ1 hiện câu chung có mã.
 */
import { getReasonLabel, REASON_CODE_LABELS } from "@/lib/admission/eligibility"
import { SELECTION_KIND_LABEL } from "@/lib/review-selections/messages"
import { ADMISSION_STATUS_CONFIG } from "@/lib/status-config"
import type { ReviewRow } from "@/lib/zod/review-sessions"

import { floorScoreDisplay } from "./floor-draft"
import { majorLabel } from "./messages"

/** Phụ lục A "Lý do" — tab "Chưa đủ điều kiện" + tab khác (HĐ4 §4.7–§4.9). */
export const REVIEW_REASON_LABEL: Record<string, string> = {
  status_not_in_pool: "Trạng thái hồ sơ không thuộc tập xét (đang yêu cầu bổ sung)",
  legacy_approved_without_decision: "Đã \"Phê duyệt\" theo luồng cũ, chưa có Quyết định trong phần mềm",
  legacy_engine_state: "Hồ sơ đang ở luồng nguyện vọng cũ (Đã công bố / Danh sách chờ) — liệt kê riêng",
  tuition_not_cleared: "Chưa đủ học phí học kỳ 1 theo cổng nhập học",
  application_fee_not_cleared: "Chưa đủ lệ phí xét tuyển",
  document_config_missing: "Hồ sơ thiếu cấu hình giấy tờ bắt buộc",
  document_config_invalid: "Cấu hình giấy tờ bắt buộc của hồ sơ không hợp lệ",
  mandatory_document_missing: "Chưa có giấy bắt buộc",
  mandatory_document_not_verified: "Giấy bắt buộc chưa được duyệt",
  academic_info_deleted: "Ngành / loại hình của nguyện vọng đã bị xoá",
  choice_academic_year_mismatch: "Nguyện vọng thuộc năm tuyển sinh khác năm của lần xét",
  quota_not_configured: "Ngành chưa có chỉ tiêu",
  group_missing: "Ngành chưa thuộc nhóm chỉ tiêu nào",
  floor_missing: "Lần xét chưa có điểm sàn cho ngành này",
  choice_config_incomplete: "Nguyện vọng thiếu cấu hình (đường xét / tổ hợp / ngành)",
  target_level_not_configured: "Ngành chưa cấu hình trình độ đào tạo",
  all_choices_failed: "Không nguyện vọng nào đạt",
  quota_closed: "Ngành đã đóng tuyển (chỉ tiêu 0)",
  over_major_quota: "Vượt chỉ tiêu ngành",
  tie_at_last_seat: "Bằng điểm ở chỗ cuối",
  tuition_major_mismatch: "Khoản học phí học kỳ 1 gắn ngành khác ngành được xếp",
  ethnic_priority_undetermined: "Chưa xác định được ưu tiên dân tộc",
  reserved_in_other_session: "Đang giữ chỗ ở lần xét khác đã khoá",
}

const ELIGIBILITY_FAIL_PREFIX = "ELIGIBILITY_FAIL:"

/**
 * Câu cho một mã lý do: Phụ lục A → mã engine (`REASON_CODE_LABELS`, một nguồn phía FE) → `ELIGIBILITY_FAIL:<x>` → câu chung có mã
 * (thiết kế §3.7 "mã lạ ⇒ 'Lý do khác (mã: …)'").
 */
export function reasonLabel(code: string): string {
  const own = REVIEW_REASON_LABEL[code]
  if (own !== undefined) return own
  if (Object.prototype.hasOwnProperty.call(REASON_CODE_LABELS, code)) return getReasonLabel(code)
  if (code.startsWith(ELIGIBILITY_FAIL_PREFIX)) {
    return `Không đạt điều kiện trình độ văn hoá (${code.slice(ELIGIBILITY_FAIL_PREFIX.length)})`
  }
  return `Lý do khác (mã: ${code})`
}

/** Phụ lục A "Cờ" (HĐ4 §4.8). */
export const REVIEW_FLAG_LABEL: Record<string, string> = {
  residence_proof_missing: "Thiếu giấy xác nhận cư trú — đang tạm cộng theo mã xã",
  dau_trung_tuyen_appsheet: "Có dấu trúng tuyển từ hệ AppSheet",
  quota_closed: "Có nguyện vọng vào ngành đã đóng tuyển",
  offering_inactive: "Loại hình đang ngừng",
  major_inactive: "Ngành đang ngừng",
  same_citizen_admitted_previous_year: "Có hồ sơ chiếm chỗ hoặc có Quyết định trúng tuyển ở năm trước",
  selected_in_other_draft_session: "Đang được máy đề xuất ở một lần xét nháp khác",
  ethnic_priority_undetermined: "Chưa xác định được ưu tiên dân tộc",
}
/** [ĐX] cờ lạ. */
export function flagLabel(code: string): string {
  return REVIEW_FLAG_LABEL[code] ?? `Cờ khác (mã: ${code})`
}

/** Phụ lục A "Gợi ý": dùng ĐÚNG nhãn lựa chọn của C2 (`SELECTION_KIND_LABEL` — một nguồn: gợi ý và lựa chọn trùng mã). */
export function hintLabel(code: string): string {
  return (SELECTION_KIND_LABEL as Record<string, string>)[code] ?? `Gợi ý khác (mã: ${code})`
}

/** Phụ lục A "Ưu tiên dân tộc" (HĐ4 §4.6). `null` ⇒ "—". Lạ ⇒ câu chung có mã [ĐX]. */
export const ETHNIC_PRIORITY_LABEL: Record<string, string> = {
  not_applicable: "Không áp dụng",
  full_evidence: "Đủ minh chứng",
  provisional_by_commune: "Tạm cộng theo mã xã (thiếu giấy cư trú)",
  undetermined: "Chưa xác định",
}
export function ethnicPriorityLabel(state: string | null): string {
  if (state === null) return "—"
  return ETHNIC_PRIORITY_LABEL[state] ?? `Khác (mã: ${state})`
}

/** Phụ lục A "Từng nguyện vọng" (HĐ4 §4.6b, danh mục đóng; lạ ⇒ chữ máy chủ). */
export const PER_CHOICE_STATUS_LABEL: Record<string, string> = {
  passed_floor: "Đạt sàn (nguyện vọng được xếp)",
  below_floor: "Dưới điểm sàn",
  failed_gate: "Không đạt điều kiện nguyện vọng",
  config_missing: "Thiếu cấu hình — dừng xét",
  quota_closed: "Ngành đóng tuyển (chỉ tiêu 0)",
  not_considered: "Không xét (đã xếp nguyện vọng trước)",
  not_reached: "Chưa xét tới (dừng ở nguyện vọng trước)",
}
export function perChoiceStatusLabel(status: string): string {
  return PER_CHOICE_STATUS_LABEL[status] ?? status
}

/** Trạng thái hồ sơ lúc chạy — CÙNG nhãn ứng dụng (`ADMISSION_STATUS_CONFIG`, R10); lạ ⇒ chữ máy chủ. */
export function profileStatusLabel(status: string): string {
  return ADMISSION_STATUS_CONFIG[status]?.label ?? status
}

/** Thiết kế §3.6: `within_seats`. `null` ⇒ "—". */
export function withinSeatsLabel(within: boolean | null): string {
  if (within === null) return "—"
  return within ? "Trong số chỗ (giữ chỗ tạm)" : "Ngoài số chỗ"
}

/** Điểm là CHUỖI máy chủ (HĐ3) — chỉ đổi dấu thập phân để hiển thị; `null` ⇒ "—". */
export function scoreLabel(score: string | null): string {
  return score === null ? "—" : floorScoreDisplay(score)
}

/** Số nguyên máy chủ (hạng…); `null` ⇒ "—". */
export function numberLabel(n: number | null): string {
  return n === null ? "—" : String(n)
}

/** [ĐX] Đơn vị: máy chủ chỉ trả `unit_id` (S7 `unit_name` chưa có — đính chính 1 §5) ⇒ "Đơn vị #id"; `null` ⇒ "—". */
export function unitRef(unitId: number | null): string {
  return unitId === null ? "—" : `Đơn vị #${unitId}`
}

/** Thiết kế §3.6 / HĐ4 §3.5: `full_name = null` ⇒ hồ sơ không còn. */
export const PROFILE_GONE = "Hồ sơ không còn."

/** NV được xếp: "NV{số} · <mã> — <tên ngành> · <loại hình>" (nhãn máy chủ); `null` ⇒ "—". */
export function consideredChoiceLabel(choice: ReviewRow["considered_choice"]): string {
  if (choice === null) return "—"
  return `NV${choice.display_order} · ${majorLabel(choice.major_code, choice.major_name)} · ${choice.offering_type ?? "—"}`
}

/** Tóm tắt từng NV theo ĐÚNG thứ tự máy chủ trả (không sắp lại): "NV1: … · NV2: …"; rỗng ⇒ "—". */
export function perChoiceSummary(perChoice: ReviewRow["per_choice"]): string {
  if (perChoice.length === 0) return "—"
  return perChoice.map((c) => `NV${c.display_order}: ${perChoiceStatusLabel(c.status)}`).join(" · ")
}

/** Thiết kế §3.7: `document_gaps = null` + lý do `document_config_*` ⇒ câu riêng (không xác định được giấy bắt buộc). */
export const DOCUMENT_CONFIG_UNKNOWN = "Không xác định được giấy nào bắt buộc (cấu hình hỏng / thiếu)"
const DOCUMENT_CONFIG_REASONS: readonly string[] = ["document_config_missing", "document_config_invalid"]

/**
 * Giấy thiếu / chưa duyệt (`document_gaps`). Tên loại giấy: máy chủ chỉ trả MÃ — chưa có danh mục tên (S2 / KT-3) ⇒ hiện mã [ĐX].
 */
export function documentGapsText(row: Pick<ReviewRow, "document_gaps" | "reason_codes">): string {
  const gaps = row.document_gaps
  if (gaps === null) {
    return row.reason_codes.some((c) => DOCUMENT_CONFIG_REASONS.includes(c)) ? DOCUMENT_CONFIG_UNKNOWN : "—"
  }
  const parts: string[] = []
  if (gaps.missing.length) parts.push(`Thiếu: ${gaps.missing.join(", ")}`)
  if (gaps.not_verified.length) parts.push(`Chưa duyệt: ${gaps.not_verified.join(", ")}`)
  return parts.length ? parts.join(" · ") : "—"
}

/** Danh sách nhãn nối "; " — rỗng ⇒ "—". */
export function labelList(codes: readonly string[], label: (code: string) => string): string {
  return codes.length ? codes.map(label).join("; ") : "—"
}

/** Phụ lục A cờ A13 (`admission_review_rules.py:169`). */
export const PRIOR_YEAR_TITLE = "Có hồ sơ chiếm chỗ hoặc có Quyết định trúng tuyển ở năm trước"
/** [ĐX] căn cứ A13 (`basis`). Lạ ⇒ chữ máy chủ. */
export const PRIOR_YEAR_BASIS_LABEL: Record<string, string> = {
  admission_decision: "Có Quyết định trúng tuyển",
  occupying_status: "Hồ sơ đang chiếm chỗ",
}
/** "Năm {năm} — {căn cứ} — trạng thái {nhãn}" (trạng thái `null` ⇒ "—"). */
export function priorYearLine(f: ReviewRow["prior_year_findings"][number]): string {
  const basis = PRIOR_YEAR_BASIS_LABEL[f.basis] ?? f.basis
  return `Năm ${f.year} — ${basis} — trạng thái ${f.status === null ? "—" : profileStatusLabel(f.status)}`
}
