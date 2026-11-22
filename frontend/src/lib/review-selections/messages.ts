/**
 * GĐ2-C C2 — câu tiếng Việt cho ô chọn của Ban thư ký. Chỉ ÁNH XẠ mã máy chủ → câu; mã lạ ⇒ câu chung, không lộ chuỗi nội bộ.
 * Mã lý do: `app/services/admission_review_selection_service.py` (`reason_code`) + `REVIEW_SESSION_NOT_DRAFT` của GĐ2-B.
 * Câu MỚI — chờ owner duyệt (bàn giao C2 §câu chữ).
 */
import { readApiError } from "@/lib/error-handler"
import type { SelectionKind } from "@/lib/zod/review-selections"

/** Nhãn sáu loại (owner C5: "Vẫn giữ" / "Loại khỏi lần này"; owner C6: "Chờ bổ sung"; ca biên B11, C3). */
export const SELECTION_KIND_LABEL: Record<SelectionKind, string> = {
  admit_over_major_quota: "Trúng vượt chỉ tiêu ngành",
  consider_next_choice: "Xét nguyện vọng kế",
  defer_supplement: "Chờ bổ sung",
  admit_without_ethnic_bonus: "Xét không cộng điểm dân tộc",
  exclude_this_session: "Loại khỏi lần này",
  keep_despite_inactive: "Vẫn giữ",
}

export const INACTIVE_FLAG_WARNING =
  "Ngành hoặc loại hình của nguyện vọng này đang ngừng — Ban thư ký phải chọn \"Vẫn giữ\" hoặc \"Loại khỏi lần này\"."
export const NOTE_REQUIRED_HINT = "Bắt buộc ghi lý do với \"Loại khỏi lần này\" và \"Chờ bổ sung\"."
export const STALE_BADGE = "Đã cũ — kết quả của hồ sơ đã đổi sau lần chọn này"

const REASON_TEXT: Record<string, string> = {
  selection_reason_required: "Lựa chọn \"Loại khỏi lần này\" và \"Chờ bổ sung\" phải ghi lý do.",
  selection_kind_not_applicable: "Lựa chọn này không áp dụng cho hồ sơ ở kết quả hiện tại — tải lại kết quả rồi chọn lại.",
  selection_row_not_found: "Hồ sơ không có trong lượt kiểm hồ sơ mới nhất của lần xét này — tải lại kết quả.",
  selection_stale: "Kết quả của hồ sơ này đã đổi sau khi bạn mở (có lượt kiểm hồ sơ mới) — tải lại rồi chọn lại.",
  selection_changed: "Lựa chọn của hồ sơ này vừa được người khác đổi — tải lại rồi chọn lại.",
  review_session_not_draft: "Lần xét không còn ở trạng thái nháp — không ghi lựa chọn được nữa.",
  review_session_not_found: "Không tìm thấy lần xét.",
}

export function describeReviewSelectionError(error: unknown): string {
  const e = readApiError(error)
  if (!e.hasResponse) return "Không kết nối được máy chủ — chưa rõ đã ghi hay chưa, hãy tải lại kết quả."
  if (e.frozen) return "Đang đóng băng tuyển sinh — tạm thời chưa ghi lựa chọn được."
  const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : undefined
  if (reasonCode && REASON_TEXT[reasonCode]) return REASON_TEXT[reasonCode]
  if (e.status === 404) return "Không tìm thấy (hoặc bạn không còn quyền Thư ký Hội đồng)."
  if (e.status === 422) return "Thông tin chưa hợp lệ — tải lại kết quả rồi chọn lại."
  return "Máy chủ gặp lỗi — thử lại sau."
}
