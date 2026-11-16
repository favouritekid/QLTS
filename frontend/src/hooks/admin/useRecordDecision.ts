/**
 * Văn bản Hội đồng — bộ điều khiển bước 6 "Ghi nhận" (đặc tả 5.6 + bản 2 mục 3.7.5, 5.6.1).
 *
 * Bất biến (test `useRecordDecision.test.tsx` khoá từng điều):
 *   • Lượt gửi được mở NGAY trước khi gửi, không mở khi vào bước 6 (vào rồi bỏ đi sẽ để lại lượt treo).
 *   • Mã lượt CHỈ nằm trong bộ nhớ (`useRef`) — không storage, không URL, không log. Tải lại trang ⇒ lấy lại qua
 *     `GET /sets/{id}/luot-ghi-nhan` (`restore`).
 *   • Bị từ chối dứt khoát (4xx đã định) ⇒ mở khoá biểu mẫu, gửi lại CÙNG mã (lượt vẫn `cho_gui`).
 *   • Mất mạng / hết giờ / 5xx / 404 / 2xx không đọc được ⇒ "Chưa xác định". KHÔNG bao giờ suy "chưa ghi", và KHÔNG
 *     có đường "gửi lại" từ trạng thái này — chỉ có "Kiểm tra trên máy chủ" (phân xử).
 *   • Phân xử cũng có thể mất phản hồi, hoặc bị đóng băng tuyển sinh chặn (503) ⇒ vẫn "Chưa xác định" (gọi lại được: máy chủ
 *     luỹ đẳng) — không bao giờ suy "chưa ghi". Giờ của lượt (`luc`) GIỮ NGUYÊN qua các lần phân xử không kết luận (không bị
 *     thay bằng giờ bấm kiểm); phân xử ra "đã chặn" thì làm mới bộ + danh sách lượt để dòng "Tình trạng" theo máy chủ (bước đang xem do trang giữ, không bị
 *     kéo đi khi danh sách lượt đổi — F281).
 *   • Mã của lượt đã `da_ghi` chỉ bị bỏ SAU KHI máy chủ xác nhận huỷ ghi nhận (`startNewSubmissionAfterCancel`); lỗi nghiệp vụ khi gửi
 *     KHÔNG bỏ mã (lượt vẫn `cho_gui`) — F276.
 *   • Chống bấm đúp bằng cờ đồng bộ (không chờ React render).
 *
 * ⚠️ KHÔNG dùng `useMutation`: biến số (scan, số hồ sơ gõ lại, ghi chú) không được nằm trong MutationCache.
 */
import { useCallback, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import {
  createCouncilDecision,
  councilErrorCode,
  listCouncilSubmissions,
  openCouncilSubmission,
  resolveCouncilSubmission,
  type CreateCouncilDecisionInput,
} from "@/lib/api/council-documents"
import {
  explainAdjudication,
  submissionErrorHandling,
  pendingSubmission,
  classifySubmissionError,
  type SubmissionErrorHandling,
} from "@/lib/council-submission"
import { readApiError } from "@/lib/error-handler"
import type { CouncilDecisionWrite, CouncilSubmission } from "@/lib/zod/council-documents"

import { councilDocumentKeys } from "./useCouncilDocuments"

/** Vì sao đang "chưa xác định" — chỉ để chọn câu hướng dẫn, không đổi nghĩa. */
export type UnclearReason =
  | "gui" // mất phản hồi / lỗi lúc gửi
  | "mo_luot" // đã có lượt `cho_gui` (mở trùng, hoặc mất phản hồi lúc mở)
  | "tai_lai_trang" // khôi phục từ `GET /sets/{id}/luot-ghi-nhan`
  | "dang_xu_ly" // phân xử: giao dịch ghi còn giữ lượt
  | "phan_xu_loi" // phân xử mất phản hồi
  | "dong_bang" // phân xử bị đóng băng tuyển sinh chặn (503 ADMISSION_FROZEN): vẫn chưa rõ, đợi hết đóng băng
  | "van_chua_ro" // phân xử trả `ket_qua` lạ

export type RecordStatus =
  | { kind: "nhap" }
  | { kind: "dang_gui" }
  /** máy chủ TỪ CHỐI dứt khoát; `huong` cho biết bước tiếp theo hợp lệ */
  | { kind: "bi_tu_choi"; failure: unknown; handling: SubmissionErrorHandling }
  /** không mở được lượt — CHƯA gửi gì, thử lại an toàn */
  | { kind: "loi_mo_luot"; failure: unknown }
  /** bộ không còn (404 khi mở lượt) */
  | { kind: "bo_khong_con" }
  | { kind: "chua_xac_dinh"; code: string; at: string; reason: UnclearReason }
  | { kind: "dang_phan_xu"; code: string; at: string }
  /** `decision` null = máy chủ báo ĐÃ ghi mà không kèm chi tiết */
  | { kind: "da_ghi"; decision: CouncilDecisionWrite | null }
  /** lượt đã bị chặn: chắc chắn CHƯA có văn bản */
  | { kind: "chua_ghi_da_chan" }

export type RecordSubmissionData = Omit<CreateCouncilDecisionInput, "set_id" | "ma_luot_gui">

/** Giờ của lượt gửi đang mang trong trạng thái chưa rõ / đang phân xử; không có thì giờ hiện tại. */
function submissionTime(t: RecordStatus): string {
  return t.kind === "chua_xac_dinh" || t.kind === "dang_phan_xu" ? t.at : new Date().toISOString()
}

type OpenSubmissionResult =
  | { kind: "ok"; code: string }
  | { kind: "chua_xac_dinh"; code: string }
  | { kind: "bo_khong_con" }
  | { kind: "loi"; failure: unknown }

export function useRecordDecision(setId: number) {
  const qc = useQueryClient()
  const [status, setStatus] = useState<RecordStatus>({ kind: "nhap" })
  const codeRef = useRef<string | null>(null)
  const running = useRef(false)

  const refreshAfterRecord = useCallback(() => {
    void qc.invalidateQueries({ queryKey: councilDocumentKeys.sets() })
    void qc.invalidateQueries({ queryKey: councilDocumentKeys.decisions() })
  }, [qc])

  const openSubmission = useCallback(async (): Promise<OpenSubmissionResult> => {
    try {
      const r = await openCouncilSubmission(setId)
      return { kind: "ok", code: r.ma }
    } catch (error) {
      const c = councilErrorCode(error)
      const status = readApiError(error).status
      if (status === 409 && c.errorCode === "luot_dang_cho" && c.submissionCode) return { kind: "chua_xac_dinh", code: c.submissionCode }
      if (status === 404) return { kind: "bo_khong_con" }
      // `luot_dang_thay_doi` hoặc mất phản hồi / 5xx lúc mở: lượt có thể ĐÃ được tạo mà ta chưa biết mã ⇒ đọc lại.
      try {
        const pending = pendingSubmission(await listCouncilSubmissions(setId))
        if (pending) return { kind: "chua_xac_dinh", code: pending.ma }
      } catch {
        /* không đọc lại được: CHƯA gửi gì, báo lỗi mở lượt (thử lại an toàn) */
      }
      return { kind: "loi", failure: error }
    }
  }, [setId])

  const submit = useCallback(
    async (data: RecordSubmissionData) => {
      if (running.current) return
      running.current = true
      setStatus({ kind: "dang_gui" })
      try {
        let code = codeRef.current
        if (code === null) {
          const r = await openSubmission()
          if (r.kind === "chua_xac_dinh") {
            codeRef.current = r.code
            setStatus({ kind: "chua_xac_dinh", code: r.code, at: new Date().toISOString(), reason: "mo_luot" })
            return
          }
          if (r.kind === "bo_khong_con") {
            setStatus({ kind: "bo_khong_con" })
            return
          }
          if (r.kind === "loi") {
            setStatus({ kind: "loi_mo_luot", failure: r.failure })
            return
          }
          code = r.code
          codeRef.current = code
        }
        try {
          const recordedDecision = await createCouncilDecision({ ...data, set_id: setId, ma_luot_gui: code })
          setStatus({ kind: "da_ghi", decision: recordedDecision })
          refreshAfterRecord()
        } catch (error) {
          if (classifySubmissionError(error) === "bi_tu_choi") {
            const handling = submissionErrorHandling(error)
            if (handling === "mo_luot_moi") codeRef.current = null
            setStatus({ kind: "bi_tu_choi", failure: error, handling })
          } else {
            setStatus({ kind: "chua_xac_dinh", code, at: new Date().toISOString(), reason: "gui" })
          }
        }
      } finally {
        running.current = false
      }
    },
    [openSubmission, setId, refreshAfterRecord],
  )

  const adjudicate = useCallback(async () => {
    const code = codeRef.current
    if (code === null || running.current) return
    running.current = true
    // `luc` = GIỜ CỦA LƯỢT GỬI (khung "Chưa xác định" ghi "Lượt gửi lúc …"), KHÔNG phải giờ bấm kiểm: lấy từ trạng thái đang
    // đứng (chưa rõ / đang kiểm) và giữ nguyên qua mọi lần phân xử không kết luận. Chỉ khi trạng thái hiện tại không mang giờ
    // (không xảy ra qua giao diện) mới lấy giờ hiện tại. Đọc qua hàm cập nhật để không phụ thuộc bản chụp cũ của trạng thái.
    setStatus((prev) => ({ kind: "dang_phan_xu", code, at: submissionTime(prev) }))
    try {
      const result = explainAdjudication(await resolveCouncilSubmission(code))
      switch (result.kind) {
        case "da_ghi":
          setStatus({ kind: "da_ghi", decision: result.decision })
          refreshAfterRecord()
          break
        case "da_ghi_thieu_chi_tiet":
          setStatus({ kind: "da_ghi", decision: null })
          refreshAfterRecord()
          break
        case "chua_ghi_da_chan":
          codeRef.current = null
          setStatus({ kind: "chua_ghi_da_chan" })
          // Máy chủ vừa đổi tình trạng của bộ (từ `chua_xac_dinh` sang `chua_ghi_nhan`) và đóng lượt (`da_chan`): làm mới bộ + danh
          // sách lượt, nếu không dòng "Tình trạng" đầu trang còn nguyên bản đã tải lúc lượt chưa rõ (Đ2-2) và bản lưu của danh sách
          // lượt còn `cho_gui` cũ (khôi phục nhầm "Chưa xác định" khi vào lại trang). Làm mới cả danh sách lượt AN TOÀN vì bước đang
          // xem do trang giữ (F281: `CouncilSetDetailClient` không suy lại bước từ dữ liệu) — cùng đường với `da_ghi`.
          refreshAfterRecord()
          break
        case "dang_xu_ly":
          setStatus((prev) => ({ kind: "chua_xac_dinh", code, at: submissionTime(prev), reason: "dang_xu_ly" }))
          break
        default:
          setStatus((prev) => ({ kind: "chua_xac_dinh", code, at: submissionTime(prev), reason: "van_chua_ro" }))
      }
    } catch (error) {
      // mất mạng / hết giờ / 404 / 5xx / phản hồi không đọc được: KHÔNG kết luận gì. Đóng băng tuyển sinh (503 ADMISSION_FROZEN)
      // chặn CẢ việc phân xử: máy chủ vẫn trả lời nên không phải "mất mạng" — nói riêng để người dùng biết đợi hết đóng băng.
      const reason: UnclearReason = readApiError(error).frozen ? "dong_bang" : "phan_xu_loi"
      setStatus((prev) => ({ kind: "chua_xac_dinh", code, at: submissionTime(prev), reason }))
    } finally {
      running.current = false
    }
  }, [refreshAfterRecord])

  /** Tải lại trang: thấy lượt `cho_gui` ⇒ vào thẳng "Chưa xác định" (chỉ khi đang ở `nhap`). */
  const restore = useCallback((submissions: readonly CouncilSubmission[]) => {
    const pending = pendingSubmission(submissions)
    if (!pending) return
    setStatus((prev) => {
      if (prev.kind !== "nhap") return prev
      codeRef.current = pending.ma
      return { kind: "chua_xac_dinh", code: pending.ma, at: pending.tao_luc, reason: "tai_lai_trang" }
    })
  }, [])

  /**
   * Về biểu mẫu sau khi lượt đã bị CHẶN (`chua_ghi_da_chan`, mã đã bỏ lúc phân xử). CHỈ đổi trạng thái: KHÔNG đụng mã, nên
   * KHÔNG dùng sau khi huỷ ghi nhận (xem `startNewSubmissionAfterCancel`).
   */
  const backToForm = useCallback(() => setStatus({ kind: "nhap" }), [])

  /**
   * Gọi CHỈ SAU KHI máy chủ đã xác nhận huỷ ghi nhận văn bản của lượt này (`CouncilCancelDialog.onXong`: huỷ thành công, hoặc
   * đọc lại thấy văn bản đã huỷ). Lượt cũ đã `da_ghi` — mã của nó đã "dùng hết": gửi lại cùng mã thì máy chủ (luỹ đẳng) trả lại
   * đúng văn bản ĐÃ HUỶ, khác nội dung thì 409 (F276). Bỏ mã cũ để lần gửi kế tiếp mở lượt MỚI, và về biểu mẫu.
   *
   * KHÔNG mở lượt ngay ở đây (lượt chỉ mở NGAY trước khi gửi — vào bước rồi bỏ đi sẽ để lại lượt treo). KHÔNG gọi khi huỷ
   * chưa được xác nhận, và KHÔNG gọi ở nhánh lỗi nghiệp vụ khi gửi (lượt vẫn `cho_gui`, gửi lại CÙNG mã).
   */
  const startNewSubmissionAfterCancel = useCallback(() => {
    codeRef.current = null
    setStatus({ kind: "nhap" })
  }, [])

  return { status, submit: submit, adjudicate, restore: restore, backToForm, startNewSubmissionAfterCancel }
}
