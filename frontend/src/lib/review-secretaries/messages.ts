/**
 * GĐ2-C C1 — câu tiếng Việt cho màn hình "Thư ký Hội đồng" (Admin gán / thu hồi). Chỉ ÁNH XẠ mã máy chủ → câu; mã lạ ⇒ câu
 * chung, không lộ chuỗi nội bộ. Mã lý do: `app/services/review_secretary_service.py` (`reason_code`).
 */
import { readApiError } from "@/lib/error-handler"

/** Nhãn vai của người được gán (máy chủ chỉ gán Quản lý / Cán bộ; vai khác hiện nguyên mã — quyền ấy đã tự thu hồi). */
export function roleLabel(role: string): string {
  if (role === "manager") return "Quản lý"
  if (role === "officer") return "Cán bộ"
  return role
}

const REASON_TEXT: Record<string, string> = {
  review_secretary_grantee_not_eligible: "Người được gán phải là Quản lý hoặc Cán bộ đang hoạt động.",
  review_secretary_already_active: "Người này đang là Thư ký Hội đồng — thu hồi quyền cũ trước nếu muốn gán lại.",
  review_secretary_grant_already_revoked: "Quyền này đã bị thu hồi — tải lại danh sách.",
  review_secretary_grant_not_found: "Không tìm thấy quyền này — tải lại danh sách.",
  review_secretary_reason_required: "Phải ghi lý do.",
}

export function describeReviewSecretaryError(error: unknown): string {
  const e = readApiError(error)
  if (!e.hasResponse) return "Không kết nối được máy chủ — chưa rõ đã ghi hay chưa, hãy tải lại danh sách."
  if (e.frozen) return "Đang đóng băng tuyển sinh — tạm thời chưa gán / thu hồi được."
  if (e.status === 403) return "Chỉ Admin quản lý quyền Thư ký Hội đồng."
  const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : undefined
  if (reasonCode && REASON_TEXT[reasonCode]) return REASON_TEXT[reasonCode]
  if (e.status === 422) {
    const first = e.validation[0]?.msg
    return first ? `Thông tin chưa hợp lệ: ${first}` : "Thông tin chưa hợp lệ (cần mã người dùng và lý do)."
  }
  if (e.status === 404 || e.status === 409) return "Danh sách đã thay đổi — tải lại danh sách."
  return "Máy chủ gặp lỗi — thử lại sau."
}
