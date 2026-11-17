/**
 * GĐ1b — câu tiếng Việt cho mã máy chủ (tiếng Anh) + phân loại lỗi của các lệnh GĐ1b.
 *
 * Chỉ ÁNH XẠ mã → câu (trình bày). Không quyết định nghiệp vụ: mọi mã đến từ máy chủ; mã lạ ⇒ câu chung, không lộ
 * chuỗi nội bộ. Không `console.*`, không storage (lỗi axios mang thân yêu cầu — có thể có lý do người dùng gõ).
 */
import { readApiError } from "@/lib/error-handler"
import type { BatchItemResult, BatchStatus } from "@/lib/zod/document-review"

/** Câu ở §5.9 — giấy lệch phiên bản (đã được xử lý ở lô / thao tác khác). */
export const VERSION_CHANGED_MESSAGE =
  "Giấy này đã được xử lý ở lô khác hoặc thao tác khác sau khi bạn xem trước — hãy xem trước lại"

/** Mã lý do của `transition_document` + mã riêng của lô (hợp đồng §1, §2.1). */
export const DOCUMENT_REASON_MESSAGES: Readonly<Record<string, string>> = {
  version_changed: VERSION_CHANGED_MESSAGE,
  own_submission: "Người nhận / người tải giấy không tự duyệt, từ chối hay Đặt lại giấy đã duyệt của mình",
  unknown_submitter: "Không rõ người nhận giấy — nút lẻ cần cam kết kèm lý do; giấy này không vào lô / duyệt chéo",
  missing_format: "Chưa ghi hình thức lúc nhận — duyệt từng giấy",
  outside_config: "Giấy ngoài cấu hình hiện tại — chỉ Quản lý / Admin Đặt lại được",
  not_pending: "Hồ sơ hoặc giấy không ở trạng thái chờ xét",
  cross_no_reset: "Duyệt chéo không có thao tác Đặt lại",
  not_resettable: "Giấy chưa nộp — không có gì để Đặt lại",
  file_missing_on_disk: "Tệp của giấy không còn trên ổ lưu trữ — không duyệt được",
  actor_not_authorized: "Bạn không còn quyền thực hiện thao tác này",
  not_permitted: "Bạn không có quyền thao tác giấy này",
  profile_over_document_cap: "Hồ sơ có quá nhiều giấy cho một lô — duyệt hồ sơ này riêng",
  profile_busy: "Hồ sơ đang bận (thao tác khác đang giữ) — hồ sơ này chưa được ghi",
  system_error: "Lỗi hệ thống khi xử lý hồ sơ này — lô đã dừng",
}

export function documentReasonText(code: string | null | undefined): string {
  if (!code) return "Không rõ lý do"
  return DOCUMENT_REASON_MESSAGES[code] ?? "Không thực hiện được với giấy này"
}

/**
 * Câu cho MỘT mục lô: mã đã biết ⇒ câu của đặc tả (vd `version_changed` ⇒ câu §5.9); mã lạ ⇒ câu máy chủ ghi kèm
 * (`message`); không có gì ⇒ rỗng.
 */
export function batchItemText(item: { reason_code: string | null; message: string | null }): string {
  if (item.reason_code && DOCUMENT_REASON_MESSAGES[item.reason_code]) return DOCUMENT_REASON_MESSAGES[item.reason_code]
  if (item.message && item.message.trim()) return item.message
  return item.reason_code ? documentReasonText(item.reason_code) : ""
}

export const BATCH_STATUS_LABELS: Readonly<Record<BatchStatus, string>> = {
  not_started: "Chưa chạy",
  starting: "Đang bắt đầu",
  expired: "Bản xem trước đã hết hạn",
  running: "Đang chạy",
  unknown: "Chưa rõ trạng thái",
  interrupted_unfinalized: "Bị gián đoạn — chưa chốt",
  completed: "Đã xong",
  stopped: "Đã dừng",
  interrupted: "Bị gián đoạn — đã chốt",
}

export function batchStatusLabel(status: string): string {
  return (BATCH_STATUS_LABELS as Record<string, string>)[status] ?? status
}

export const BATCH_RESULT_LABELS: Readonly<Record<BatchItemResult, string>> = {
  recorded: "Đã ghi",
  error: "Lỗi",
  not_processed: "Chưa xử lý",
  pending: "Chưa rõ kết quả",
}

/**
 * Câu của ô xác nhận lô (đặc tả bản 2.2 "Ô xác nhận chung cho lô" — Codex 59 câu 7; bản 3.6 giữ "ô xác nhận lô").
 * `n` = số giấy MÁY CHỦ trả ở bản xem trước / lô — giao diện không tự đếm. Gửi NGUYÊN VĂN làm `confirmation_text`.
 * Ô này là cam kết thao tác, không chứng minh đã đối chiếu giấy thật.
 */
export function confirmationSentence(n: number): string {
  return `Tôi xác nhận đã đối chiếu giấy thật của ${n} giấy này. Phần mềm chỉ ghi lại kết quả kiểm của tôi.`
}

/** Trạng thái phải hỏi lại máy chủ (§5.9: 3 s rồi 10 s). */
export const POLLING_BATCH_STATUSES: ReadonlySet<string> = new Set(["starting", "running", "unknown"])
/** Trạng thái kết thúc — dòng kết quả bền, không đổi nữa. */
export const TERMINAL_BATCH_STATUSES: ReadonlySet<string> = new Set(["completed", "stopped", "interrupted"])

/**
 * Nhịp hỏi lại một lô (§5.9): lần hỏi lại ĐẦU sau 3 s, các lần sau 10 s; ngoài nhóm cần hỏi ⇒ không hỏi.
 * `fetchCount` = số lần đã nhận dữ liệu (`dataUpdateCount` của React Query).
 */
export function batchPollInterval(status: string | undefined, fetchCount: number): number | false {
  if (!status || !POLLING_BATCH_STATUSES.has(status)) return false
  return fetchCount <= 1 ? 3000 : 10000
}

const VIA_LABELS: Readonly<Record<string, string>> = {
  single: "Nút lẻ",
  batch: "Lô",
  cross: "Duyệt chéo",
  extra_cleanup: "Đặt lại giấy ngoài cấu hình",
}
export function viaLabel(via: string | null | undefined): string {
  if (!via) return ""
  return VIA_LABELS[via] ?? via
}

const HISTORY_ACTION_LABELS: Readonly<Record<string, string>> = {
  uploaded: "Tải lên",
  paper_submitted: "Ghi nhận bản giấy",
  verified: "Duyệt",
  rejected: "Từ chối",
  reset: "Đặt lại",
  downloaded: "Tải xuống",
}
export function historyActionLabel(action: string): string {
  return HISTORY_ACTION_LABELS[action] ?? action
}

const DOCUMENT_STATUS_LABELS: Readonly<Record<string, string>> = {
  missing: "Chưa nộp",
  uploaded: "Đã tải lên",
  paper_submitted: "Đã nhận bản giấy",
  verified: "Đã duyệt",
  rejected: "Bị từ chối",
}
export function documentStatusLabel(status: string | null | undefined): string {
  if (!status) return ""
  return DOCUMENT_STATUS_LABELS[status] ?? status
}

const FORMAT_LABELS: Readonly<Record<string, string>> = {
  original: "Bản chính",
  certified_copy: "Bản sao chứng thực",
  photo: "Bản photo",
}
export function formatLabel(format: string | null | undefined): string {
  if (!format) return "Chưa ghi"
  return FORMAT_LABELS[format] ?? format
}

/** Giờ hiển thị CỐ ĐỊNH múi Việt Nam (không phụ thuộc múi máy) — chỉ gọi ở thành phần đã mount. */
const VN_DATETIME = new Intl.DateTimeFormat("vi-VN", {
  timeZone: "Asia/Ho_Chi_Minh",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
})
export function formatDateTimeVN(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : VN_DATETIME.format(d)
}

// ═══════════════════════ Lỗi nút lẻ (409 / 422 / 404) ═══════════════════════

export type DocumentActionErrorKind =
  /** 409 VERSION_CHANGED ⇒ làm mới chi tiết, đóng hộp */
  | "version_changed"
  /** 409 khác (luật nghiệp vụ) ⇒ câu theo mã, làm mới chi tiết */
  | "conflict"
  /** 422 / 400 (thiếu lý do, sai dạng) ⇒ giữ hộp để sửa */
  | "invalid"
  /** 404 (IDOR / không tồn tại) */
  | "not_found"
  | "other"

export interface DocumentActionErrorView {
  kind: DocumentActionErrorKind
  message: string
}

export function describeDocumentActionError(error: unknown): DocumentActionErrorView {
  const e = readApiError(error)
  if (!e.hasResponse) {
    return { kind: "other", message: "Không kết nối được máy chủ — chưa rõ thao tác đã ghi hay chưa. Hãy tải lại trang để xem trạng thái giấy." }
  }
  const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : undefined
  if (e.status === 409) {
    const code = reasonCode ?? e.errorCode?.toLowerCase()
    if (code === "version_changed") return { kind: "version_changed", message: VERSION_CHANGED_MESSAGE }
    return { kind: "conflict", message: documentReasonText(code) }
  }
  if (e.status === 422 || e.status === 400) {
    return { kind: "invalid", message: "Thiếu hoặc sai thông tin (lý do / hình thức / cam kết) — kiểm tra lại rồi gửi" }
  }
  if (e.status === 404) return { kind: "not_found", message: "Không tìm thấy hồ sơ / giấy, hoặc bạn không có quyền với giấy này" }
  if (e.status === 403) return { kind: "other", message: "Bạn không có quyền thực hiện thao tác này" }
  if (e.status === 429) return { kind: "other", message: "Thao tác quá nhanh — thử lại sau ít phút" }
  if (e.frozen) return { kind: "other", message: "Tuyển sinh đang tạm đóng băng — thao tác chưa được ghi" }
  return { kind: "other", message: "Máy chủ gặp lỗi — thử lại sau" }
}

// ═══════════════════════ Lỗi lô (§5.2, §5.3, §5.7, §5.9) ═══════════════════════

const int = (v: unknown): number | undefined => (typeof v === "number" && Number.isInteger(v) ? v : undefined)

export function describePreviewError(error: unknown): string {
  const e = readApiError(error)
  if (!e.hasResponse) return "Không kết nối được máy chủ — bản xem trước chưa tạo được, hãy xem trước lại"
  if (e.errorCode === "TOO_MANY_PROFILES") {
    const n = int(e.data?.profile_count)
    const lim = int(e.data?.limit)
    return `Lựa chọn có ${n ?? "?"} hồ sơ, vượt trần ${lim ?? "?"} hồ sơ / lô — thu hẹp bộ lọc rồi xem trước lại`
  }
  if (e.errorCode === "TOO_MANY_DOCUMENTS") {
    const n = int(e.data?.document_count)
    const lim = int(e.data?.limit)
    return `Lựa chọn có ${n ?? "?"} giấy, vượt trần ${lim ?? "?"} giấy / lô — thu hẹp bộ lọc rồi xem trước lại`
  }
  if (e.errorCode === "TOO_MANY_PREVIEWS") return "Đang có lô chuẩn bị chạy — thử lại sau giây lát"
  if (e.status === 403 || e.status === 404) return "Bạn không có quyền duyệt hàng loạt các hồ sơ này"
  if (e.status === 422) return "Yêu cầu xem trước không hợp lệ — kiểm tra lại bộ lọc"
  if (e.status === 429) return "Thao tác quá nhanh — thử lại sau ít phút"
  return "Máy chủ gặp lỗi — bản xem trước chưa tạo được"
}

export type ExecuteOutcome =
  /** 409 BATCH_RUNNING / BATCH_EXISTS, mất mạng, 5xx, 504 ⇒ TRA LÔ (GET) — không bao giờ gửi lại `execute` */
  | { kind: "lookup"; message: string }
  /** 409 PREVIEW_EXPIRED ⇒ xem trước lại */
  | { kind: "expired"; message: string }
  /** 404 (không có / không phải người tạo / PREVIEW_GONE) ⇒ xem trước lại */
  | { kind: "gone"; message: string }
  /** 401 / 403 / 422 / 429 — máy chủ từ chối TRƯỚC khi ghi (§5.3 bước 4) */
  | { kind: "refused"; message: string }

export const PREVIEW_GONE_MESSAGE = "Bản xem trước không còn — xem trước lại"
export const UNKNOWN_RESULT_MESSAGE = "Chưa rõ kết quả — đang tra lô theo mã (không gửi lại lệnh duyệt)"

export function classifyExecuteError(error: unknown): ExecuteOutcome {
  const e = readApiError(error)
  if (!e.hasResponse) return { kind: "lookup", message: UNKNOWN_RESULT_MESSAGE }
  const status = e.status ?? 0
  if (status === 409) {
    if (e.errorCode === "PREVIEW_EXPIRED") {
      return { kind: "expired", message: "Bản xem trước đã hết hạn — xem trước lại" }
    }
    if (e.errorCode === "BATCH_RUNNING" || e.errorCode === "BATCH_EXISTS") {
      return { kind: "lookup", message: "Lô này đã được chạy hoặc đang chạy — đang tra kết quả" }
    }
    return { kind: "lookup", message: UNKNOWN_RESULT_MESSAGE }
  }
  if (status === 404) return { kind: "gone", message: PREVIEW_GONE_MESSAGE }
  if (status >= 500) return { kind: "lookup", message: UNKNOWN_RESULT_MESSAGE }
  if (status === 429) return { kind: "refused", message: "Thao tác quá nhanh — lô CHƯA chạy, thử lại sau ít phút" }
  if (status === 403 || status === 401) return { kind: "refused", message: "Bạn không có quyền chạy lô này — lô CHƯA chạy" }
  if (status === 422) return { kind: "refused", message: "Câu xác nhận không hợp lệ — lô CHƯA chạy" }
  return { kind: "lookup", message: UNKNOWN_RESULT_MESSAGE }
}

export function describeFinalizeError(error: unknown): string {
  const e = readApiError(error)
  if (!e.hasResponse) return "Không kết nối được máy chủ — chưa rõ đã chốt hay chưa, hãy tra lại lô"
  if (e.errorCode === "BATCH_RUNNING") return "Lô đang chạy — chưa chốt được"
  if (e.errorCode === "BATCH_NOT_STARTED") return "Lô chưa chạy — không có gì để chốt"
  if (e.status === 422) return "Cần nhập lý do chốt lô"
  if (e.status === 404) return "Không tìm thấy lô, hoặc bạn không có quyền chốt lô này"
  if (e.status === 503) return "Chưa kiểm được trạng thái lô — thử lại sau"
  return "Máy chủ gặp lỗi — chưa chốt được lô"
}

export function describeBatchLookupError(error: unknown): string {
  const e = readApiError(error)
  if (e.status === 404) return PREVIEW_GONE_MESSAGE
  if (e.status === 403) return "Bạn không có quyền xem lô duyệt giấy."
  if (!e.hasResponse) return "Không kết nối được máy chủ — thử tra lại"
  return "Không tra được lô — thử lại sau"
}

// ═══════════════════════ Duyệt chéo (§2.2) ═══════════════════════

export type CrossActionErrorKind = "refresh_queue" | "invalid" | "other"
export function describeCrossActionError(error: unknown): { kind: CrossActionErrorKind; message: string } {
  const e = readApiError(error)
  if (!e.hasResponse) return { kind: "other", message: "Không kết nối được máy chủ — chưa rõ đã ghi hay chưa, hãy tải lại hàng đợi" }
  const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : e.errorCode?.toLowerCase()
  if (e.status === 409) {
    // actor_not_authorized: quyền hết hạn / bị thu hồi / sai đơn vị / không cho đúng thao tác ⇒ làm mới hàng đợi
    return { kind: "refresh_queue", message: documentReasonText(reasonCode) }
  }
  if (e.status === 404) return { kind: "refresh_queue", message: "Giấy không còn trong phạm vi quyền duyệt chéo của bạn" }
  if (e.status === 422 || e.status === 400) return { kind: "invalid", message: "Thiếu hoặc sai thông tin — kiểm tra lý do rồi gửi lại" }
  return { kind: "other", message: "Máy chủ gặp lỗi — thử lại sau" }
}

export function describeGrantError(error: unknown): string {
  const e = readApiError(error)
  if (!e.hasResponse) return "Không kết nối được máy chủ — chưa rõ đã ghi hay chưa, hãy tải lại danh sách"
  if (e.status === 403 || e.status === 404) return "Chỉ Admin quản lý quyền duyệt chéo"
  if (e.status === 422) {
    const first = e.validation[0]?.msg
    return first
      ? `Thông tin chưa hợp lệ: ${first}`
      : "Thông tin chưa hợp lệ (hạn tối đa 14 ngày, cần lý do, người được cấp phải là Cán bộ đang hoạt động)"
  }
  if (e.status === 409) return "Quyền đã thay đổi — tải lại danh sách"
  return "Máy chủ gặp lỗi — thử lại sau"
}

// ═══════════════════════ Bản in Hội đồng — luật in v1.2 ═══════════════════════

/** Mã lỗi dữ liệu MỚI của GĐ1b (luật in v1.2) — `council_document_render_service.ERROR_VERIFIED_FORMAT_INVALID`. */
export const VERIFIED_FORMAT_INVALID = "verified_format_invalid"
export const VERIFIED_FORMAT_INVALID_MESSAGE =
  "Giấy đã duyệt nhưng hình thức đã xác nhận trống hoặc không hợp lệ — không dựng được văn bản (luật in v1.2). Cần kiểm tra lại giấy này trên hồ sơ."
