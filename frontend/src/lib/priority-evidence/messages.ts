/**
 * GĐ2-F1 — câu tiếng Việt cho mã máy chủ của thao tác minh chứng ưu tiên (duyệt / từ chối / ghi nhận bản giấy).
 *
 * Chỉ ÁNH XẠ mã → câu (trình bày). Không quyết định nghiệp vụ: luật "người tải / người nhận không tự duyệt / từ chối" và
 * "không rõ người nhận ⇒ cam kết + lý do" nằm ở máy chủ (`document_review_rules.decide_priority_evidence`); mã lạ ⇒ câu
 * chung, không lộ chuỗi nội bộ. Không `console.*`, không storage (lỗi axios mang thân yêu cầu — có lý do người dùng gõ).
 *
 * Mã lý do DÙNG CHUNG với giấy tờ GĐ1b (`own_submission` / `unknown_submitter`) nhưng câu RIÊNG cho minh chứng: không có
 * "Đặt lại", không có lô / duyệt chéo.
 */
import { PROFILE_VERSION_CONFLICT_ERROR_CODE } from "@/lib/api/error-codes"
import { readApiError } from "@/lib/error-handler"

export type PriorityEvidenceAction = "verify" | "reject" | "paper"

/** Câu cho 409 của cổng duyệt / từ chối (theo `reason_code`). */
export const PRIORITY_EVIDENCE_REASON_MESSAGES: Readonly<Record<string, string>> = {
  own_submission:
    "Bạn là người tải tệp / người nhận bản giấy minh chứng này nên không tự duyệt hay từ chối được — cần Quản lý trong đơn vị hoặc Admin khác.",
  unknown_submitter:
    "Không rõ ai đã tải tệp / nhận bản giấy minh chứng này — cần tích ô cam kết và ghi lý do; hoặc tải lại tệp / để người nhận ghi nhận bản giấy rồi người khác duyệt.",
}

/** Câu giải thích khi máy chủ báo `review_block_reason` (ẩn nút Duyệt / Từ chối). */
const BLOCK_REASON_MESSAGES: Readonly<Record<string, string>> = {
  own_submission:
    "Bạn đã tải tệp / nhận bản giấy minh chứng này nên không tự duyệt hay từ chối được — cần Quản lý trong đơn vị hoặc Admin khác.",
  unknown_submitter: "Không rõ người tải tệp minh chứng này — tải lại tệp để người khác duyệt.",
}

export function priorityEvidenceBlockText(code: string): string {
  return BLOCK_REASON_MESSAGES[code] ?? "Bạn không duyệt / từ chối được minh chứng này."
}

const BAD_REQUEST_MESSAGES: Readonly<Record<PriorityEvidenceAction, string>> = {
  verify: "Không duyệt được: hồ sơ hoặc diện ưu tiên không ở trạng thái cho phép — tải lại trang để xem trạng thái mới.",
  reject: "Không từ chối được: hồ sơ hoặc diện ưu tiên không ở trạng thái cho phép — tải lại trang để xem trạng thái mới.",
  paper:
    "Không ghi nhận được: mã diện đã có minh chứng (tệp hoặc bản giấy), hoặc hồ sơ không ở trạng thái cho sửa giấy — tải lại trang để xem trạng thái mới.",
}

export function describePriorityEvidenceError(error: unknown, action: PriorityEvidenceAction): string {
  const e = readApiError(error)
  if (!e.hasResponse) {
    return "Không kết nối được máy chủ — chưa rõ thao tác đã ghi hay chưa. Tải lại trang để xem trạng thái minh chứng."
  }
  if (e.frozen) return "Tuyển sinh đang tạm đóng băng — thao tác chưa được ghi."
  if (e.status === 409) {
    const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : e.errorCode?.toLowerCase()
    if (reasonCode && PRIORITY_EVIDENCE_REASON_MESSAGES[reasonCode]) return PRIORITY_EVIDENCE_REASON_MESSAGES[reasonCode]
    // Owner 22-11 (câu 409): xung đột phiên bản hồ sơ ⇒ hiện NGUYÊN câu của máy chủ.
    if (e.errorCode === PROFILE_VERSION_CONFLICT_ERROR_CODE && e.detail) return e.detail
    if (e.errorCode === "CONFLICT") return "Hồ sơ vừa được người khác cập nhật — tải lại trang rồi làm lại."
    return "Không thực hiện được với minh chứng này — tải lại trang để xem trạng thái mới."
  }
  if (e.status === 400) return BAD_REQUEST_MESSAGES[action]
  if (e.status === 422) return "Thiếu hoặc sai thông tin (lý do / cam kết) — kiểm tra lại rồi gửi."
  if (e.status === 403) {
    return action === "paper"
      ? "Bạn không có quyền ghi nhận minh chứng cho hồ sơ này."
      : "Chỉ Quản lý trong đơn vị của hồ sơ hoặc Admin được duyệt / từ chối minh chứng ưu tiên."
  }
  if (e.status === 404) return "Không tìm thấy hồ sơ, hoặc bạn không có quyền với hồ sơ này."
  if (e.status === 429) return "Thao tác quá nhanh — thử lại sau ít phút."
  return "Máy chủ gặp lỗi — thử lại sau."
}
