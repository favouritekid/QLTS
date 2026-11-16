/**
 * Văn bản Hội đồng — giải nghĩa GIAO THỨC lượt gửi ghi nhận (đặc tả bản 2 mục 3.7.4 – 3.7.5).
 *
 * Đây KHÔNG phải luật nghiệp vụ: chỉ là việc đọc đúng điều máy chủ NÓI để giao diện không tự suy một kết luận
 * mà máy chủ chưa nói. Nguyên tắc bất biến (mỗi điều có test khoá):
 *   1. Giao diện chỉ kết luận "ĐÃ ghi" / "CHƯA ghi" khi nhận được 2xx có `ket_qua` rõ nghĩa của máy chủ.
 *   2. Mất mạng, hết giờ, 5xx, 404, lỗi đọc phản hồi 2xx, mã `ket_qua` lạ ⇒ LUÔN là "chưa xác định".
 *      Chưa bao giờ suy "chưa ghi" từ một lỗi.
 *   3. Chỉ một vài mã trạng thái HTTP được coi là máy chủ ĐÃ TỪ CHỐI dứt khoát (yêu cầu bị chặn trước khi ghi);
 *      mọi mã khác ⇒ "chưa xác định" (thiên về an toàn: người dùng bấm "Kiểm tra trên máy chủ").
 *
 * ⚠️ Không có `console.*`, không storage: mã lượt chỉ ở bộ nhớ (xem `useRecordDecision`).
 */
import { councilErrorCode } from "@/lib/api/council-documents"
import { readApiError } from "@/lib/error-handler"
import type {
  CouncilDecisionWrite,
  CouncilSubmission,
  CouncilSubmissionResolve,
} from "@/lib/zod/council-documents"

// ── kết quả phân xử ──────────────────────────────────────────────────────────
export type AdjudicationResult =
  /** máy chủ báo ĐÃ ghi, kèm DTO văn bản (khung kết quả chỉ vẽ từ DTO này) */
  | { kind: "da_ghi"; decision: CouncilDecisionWrite }
  /** máy chủ báo ĐÃ ghi nhưng KHÔNG kèm DTO (sai hợp đồng) — vẫn là "đã ghi", không có chi tiết để vẽ */
  | { kind: "da_ghi_thieu_chi_tiet" }
  /** lượt đã bị chặn: chắc chắn CHƯA có văn bản, và gửi muộn sẽ bị từ chối */
  | { kind: "chua_ghi_da_chan" }
  /** máy chủ chưa kết luận được (giao dịch ghi còn giữ lượt) — thử lại sau */
  | { kind: "dang_xu_ly" }
  /** `ket_qua` lạ — không suy */
  | { kind: "van_chua_ro" }

export function explainAdjudication(out: CouncilSubmissionResolve): AdjudicationResult {
  switch (out.ket_qua) {
    case "da_ghi":
      return out.quyet_dinh
        ? { kind: "da_ghi", decision: out.quyet_dinh }
        : { kind: "da_ghi_thieu_chi_tiet" }
    case "chua_ghi_da_chan":
      return { kind: "chua_ghi_da_chan" }
    case "dang_xu_ly":
      return { kind: "dang_xu_ly" }
    default:
      return { kind: "van_chua_ro" }
  }
}

// ── lỗi khi GỬI ghi nhận ─────────────────────────────────────────────────────
export type SubmissionErrorKind = "bi_tu_choi" | "chua_xac_dinh"

/** Mã HTTP mà máy chủ / lớp trước nó trả khi yêu cầu bị chặn TRƯỚC khi ghi bất cứ gì. */
const HARD_REJECT_STATUSES: ReadonlySet<number> = new Set([400, 403, 409, 413, 422, 429])

export function classifySubmissionError(error: unknown): SubmissionErrorKind {
  const e = readApiError(error)
  if (!e.isAxios || !e.hasResponse || e.status === undefined) return "chua_xac_dinh"
  if (e.frozen) return "bi_tu_choi" // đóng băng tuyển sinh chặn từ middleware, trước handler
  return HARD_REJECT_STATUSES.has(e.status) ? "bi_tu_choi" : "chua_xac_dinh"
}

export type SubmissionErrorHandling =
  /** lượt vẫn `cho_gui`: sửa biểu mẫu rồi gửi lại CÙNG mã */
  | "sua_va_gui_lai"
  /** lượt đã bị chặn: cần mở lượt MỚI trước lần gửi sau */
  | "mo_luot_moi"
  /** đã có văn bản với nội dung khác cho lượt này: phân xử để xem văn bản */
  | "phan_xu"
  /** lượt không hợp lệ với bộ này: đọc lại trạng thái bộ */
  | "tai_lai_bo"

/** Chỉ gọi khi `classifySubmissionError(error) === "bi_tu_choi"`. */
export function submissionErrorHandling(error: unknown): SubmissionErrorHandling {
  switch (councilErrorCode(error).errorCode) {
    case "luot_da_chan":
      return "mo_luot_moi"
    case "luot_da_dung_noi_dung_khac":
      return "phan_xu"
    case "luot_khong_hop_le":
      return "tai_lai_bo"
    default:
      return "sua_va_gui_lai"
  }
}

// ── trạng thái các lượt của bộ (khôi phục sau tải lại trang) ──────────────────
/** Lượt đang chờ (kết quả chưa rõ) — `trang_thai` đúng bằng `cho_gui`. Lạ ⇒ không coi là chờ (không suy). */
export function pendingSubmission(submissions: readonly CouncilSubmission[]): CouncilSubmission | undefined {
  return submissions.find((x) => x.trang_thai === "cho_gui")
}

/** Lượt đã ghi mới nhất (có `decision_id`). */
export function recordedSubmission(submissions: readonly CouncilSubmission[]): CouncilSubmission | undefined {
  const recorded = submissions.filter((x) => x.trang_thai === "da_ghi" && x.decision_id != null)
  return recorded.length === 0
    ? undefined
    : recorded.reduce((a, b) => (a.tao_luc >= b.tao_luc ? a : b))
}

// ── nhãn hiển thị ────────────────────────────────────────────────────────────
/** Nhãn khi lượt chưa rõ. KHÔNG bao giờ chứa "chưa ghi nhận" (đặc tả 5.6.1: nhãn đó nói sai khi lượt chưa rõ). */
export const UNDETERMINED_LABEL = "Chưa xác định"
