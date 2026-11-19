/**
 * GĐ2-F1 — thẻ minh chứng ưu tiên theo CỜ MÁY CHỦ (thin client):
 *   - `requires_ack` ⇒ Duyệt mở hộp cam kết; gửi chỉ khi có CẢ cam kết LẪN lý do; thân mang `unknown_submitter_ack` + lý do;
 *   - `review_block_reason` ⇒ không nút Duyệt / Từ chối, hiện câu lý do;
 *   - Từ chối khi `requires_ack` ⇒ phải tích cam kết, thân mang cờ cam kết;
 *   - 409 `OWN_SUBMISSION` / `UNKNOWN_SUBMITTER` ⇒ câu tiếng Việt, không lộ mã.
 * Dữ liệu giả, không dữ liệu cá nhân.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { UtEvidenceCards } from "./UtEvidenceCards"

const URL_DUYET = `${API}/api/v2/admissions/42/priority-objects/04/verify`
const URL_TU_CHOI = `${API}/api/v2/admissions/42/priority-objects/04/reject`

function hoSo(muc: Record<string, unknown> = {}): AdmissionProfileResponse {
  return {
    id: 42,
    version: 5,
    status: "submitted",
    academic_year: 2026,
    priority_object_codes: ["04"],
    priority_object_evidence: { "04": { status: "pending" } },
    priority_object_evidence_display: null,
    missing_priority_evidence_codes: [],
    priority_evidence_documents: [
      {
        sub_code: "04",
        bonus_points: 1.0,
        label: "Giấy chứng nhận diện thử",
        document_id: 99,
        document_file_path: "uploads/admissions/42/priority_04.pdf",
        status: "uploaded",
        verification_status: "pending",
        can_mark_paper_submitted: false,
        requires_ack: false,
        review_block_reason: null,
        ...muc,
      },
    ],
    priority_resolution_snapshot: null,
    priority_audit_log: null,
    permissions: { verify_priority_object: true },
  } as unknown as AdmissionProfileResponse
}

function ve(profile: AdmissionProfileResponse) {
  return renderWithClient(
    <UtEvidenceCards profile={profile} canVerify isEditable={false} onNavigateToDocuments={() => {}} />,
  )
}

let than: unknown[] = []
beforeEach(() => {
  than = []
})
afterEach(() => {
  server.resetHandlers()
  vi.restoreAllMocks()
})

function batDuyet(status = 200, body: Record<string, unknown> = { id: 42 }) {
  server.use(
    http.patch(URL_DUYET, async ({ request }) => {
      than.push(await request.json())
      return HttpResponse.json(body, { status })
    }),
  )
}

function batTuChoi(status = 200, body: Record<string, unknown> = { id: 42 }) {
  server.use(
    http.patch(URL_TU_CHOI, async ({ request }) => {
      than.push(await request.json())
      return HttpResponse.json(body, { status })
    }),
  )
}

describe("UtEvidenceCards GĐ2-F1 — duyệt có cam kết", () => {
  it("requires_ack ⇒ Duyệt mở hộp cam kết, KHÔNG gửi ngay", async () => {
    batDuyet()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: true }))
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    expect(screen.getByTestId("ut-verify-ack-dialog-04")).toBeInTheDocument()
    expect(screen.getByTestId("hop-cam-ket-khong-ro-nguoi-nhan")).toBeInTheDocument()
    expect(than).toEqual([])
  })

  it("nút gửi khoá tới khi có CẢ cam kết LẪN lý do (lý do toàn khoảng trắng vẫn khoá) — không request nào", async () => {
    batDuyet()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: true }))
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    const nut = screen.getByTestId("ut-verify-ack-submit-04")
    expect(nut).toBeDisabled()
    await u.click(screen.getByRole("checkbox"))
    expect(nut).toBeDisabled() // có cam kết, chưa lý do
    await u.type(screen.getByLabelText(/Lý do \(bắt buộc khi cam kết\)/), "   ")
    expect(nut).toBeDisabled() // lý do chỉ khoảng trắng
    expect(than).toEqual([])
  })

  it("cam kết + lý do ⇒ thân mang unknown_submitter_ack = true + lý do đã cắt + document_id máy chủ trả", async () => {
    batDuyet()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: true }))
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    await u.type(screen.getByLabelText(/Lý do \(bắt buộc khi cam kết\)/), "  Đã đối chiếu bản gốc  ")
    const nut = screen.getByTestId("ut-verify-ack-submit-04")
    expect(nut).toBeDisabled() // có lý do, chưa cam kết
    await u.click(screen.getByRole("checkbox"))
    expect(nut).toBeEnabled()
    await u.click(nut)
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      version: 5,
      document_id: 99,
      unknown_submitter_ack: true,
      reason: "Đã đối chiếu bản gốc",
    })
  })

  it("requires_ack = false ⇒ Duyệt gửi thẳng, thân KHÔNG mang cờ cam kết", async () => {
    batDuyet()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: false }))
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ version: 5, document_id: 99 })
    expect(screen.queryByTestId("ut-verify-ack-dialog-04")).toBeNull()
  })

  it("thiếu cờ requires_ack (máy chủ cũ / null) ⇒ không tự bật cam kết", async () => {
    batDuyet()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: null }))
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).not.toHaveProperty("unknown_submitter_ack")
  })

  it("409 UNKNOWN_SUBMITTER trong hộp cam kết ⇒ câu tiếng Việt, giữ hộp, không lộ mã", async () => {
    batDuyet(409, { reason_code: "unknown_submitter", error_code: "UNKNOWN_SUBMITTER", detail: "x" })
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: true }))
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    await u.click(screen.getByRole("checkbox"))
    await u.type(screen.getByLabelText(/Lý do \(bắt buộc khi cam kết\)/), "Đã đối chiếu")
    await u.click(screen.getByTestId("ut-verify-ack-submit-04"))
    const loi = await screen.findByRole("alert")
    expect(loi).toHaveTextContent(/Không rõ ai đã tải tệp \/ nhận bản giấy/)
    expect(loi.textContent).not.toMatch(/unknown_submitter|UNKNOWN_SUBMITTER/)
    expect(screen.getByTestId("ut-verify-ack-dialog-04")).toBeInTheDocument()
  })

  it("chưa có dòng giấy (status missing) ⇒ hộp cam kết có câu gợi ý ghi nhận bản giấy", async () => {
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: true, status: "missing", document_id: null, document_file_path: null }))
    expect(screen.getByTestId("ut-evidence-verify-04")).toHaveTextContent("Duyệt (Hồ sơ giấy)")
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    expect(screen.getByTestId("ut-verify-ack-goi-y-04")).toHaveTextContent(/Đã nhận bản giấy/)
  })
})

describe("UtEvidenceCards GĐ2-F1 — lý do chặn từ máy chủ", () => {
  it("review_block_reason = own_submission ⇒ KHÔNG nút Duyệt / Từ chối, hiện câu", () => {
    ve(hoSo({ review_block_reason: "own_submission" }))
    expect(screen.queryByTestId("ut-evidence-verify-04")).toBeNull()
    expect(screen.queryByTestId("ut-evidence-reject-04")).toBeNull()
    expect(screen.getByTestId("ut-evidence-block-reason-04")).toHaveTextContent(/không tự duyệt hay từ chối/)
  })

  it("không có lý do chặn ⇒ có nút Duyệt + Từ chối", () => {
    ve(hoSo({ review_block_reason: null }))
    expect(screen.getByTestId("ut-evidence-verify-04")).toBeInTheDocument()
    expect(screen.getByTestId("ut-evidence-reject-04")).toBeInTheDocument()
    expect(screen.queryByTestId("ut-evidence-block-reason-04")).toBeNull()
  })

  it("409 OWN_SUBMISSION khi duyệt thẳng ⇒ câu tiếng Việt (toast), không lộ mã", async () => {
    const { toast } = await import("sonner")
    const loi = vi.spyOn(toast, "error")
    batDuyet(409, { reason_code: "own_submission", error_code: "OWN_SUBMISSION", detail: "x" })
    const u = userEvent.setup()
    ve(hoSo())
    await u.click(screen.getByTestId("ut-evidence-verify-04"))
    await waitFor(() => expect(loi).toHaveBeenCalledTimes(1))
    const cau = String(loi.mock.calls[0][0])
    expect(cau).toMatch(/không tự duyệt hay từ chối/)
    expect(cau).not.toMatch(/own_submission|OWN_SUBMISSION|status code/)
  })
})

describe("UtEvidenceCards GĐ2-F1 — từ chối có cam kết", () => {
  const LY_DO = "Minh chứng không rõ nét, cần nộp lại"

  it("requires_ack ⇒ hộp Từ chối có cam kết; khoá tới khi tích; thân mang unknown_submitter_ack = true", async () => {
    batTuChoi()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: true }))
    await u.click(screen.getByTestId("ut-evidence-reject-04"))
    await u.type(screen.getByTestId("ut-reject-reason-input"), LY_DO)
    const nut = screen.getByTestId("ut-reject-submit")
    expect(nut).toBeDisabled()
    await u.click(screen.getByRole("checkbox"))
    expect(nut).toBeEnabled()
    await u.click(nut)
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ version: 5, reject_reason: LY_DO, unknown_submitter_ack: true })
  })

  it("requires_ack = false ⇒ không hộp cam kết; thân mang unknown_submitter_ack = false", async () => {
    batTuChoi()
    const u = userEvent.setup()
    ve(hoSo({ requires_ack: false }))
    await u.click(screen.getByTestId("ut-evidence-reject-04"))
    expect(screen.queryByTestId("hop-cam-ket-khong-ro-nguoi-nhan")).toBeNull()
    await u.type(screen.getByTestId("ut-reject-reason-input"), LY_DO)
    await u.click(screen.getByTestId("ut-reject-submit"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ version: 5, reject_reason: LY_DO, unknown_submitter_ack: false })
  })

  it("409 OWN_SUBMISSION khi từ chối ⇒ câu tiếng Việt trong hộp, giữ hộp", async () => {
    batTuChoi(409, { reason_code: "own_submission", error_code: "OWN_SUBMISSION", detail: "x" })
    const u = userEvent.setup()
    ve(hoSo())
    await u.click(screen.getByTestId("ut-evidence-reject-04"))
    await u.type(screen.getByTestId("ut-reject-reason-input"), LY_DO)
    await u.click(screen.getByTestId("ut-reject-submit"))
    const loi = await screen.findByRole("alert")
    expect(loi).toHaveTextContent(/không tự duyệt hay từ chối/)
    // ResponsiveDialogContent không chuyển data-testid ⇒ kiểm hộp còn mở qua ô lý do.
    expect(screen.getByTestId("ut-reject-reason-input")).toHaveValue(LY_DO)
  })
})

describe("UtEvidenceCards GĐ2-F1 — nhãn theo dữ liệu máy chủ", () => {
  it("bản giấy đã ghi nhận (paper_submitted, không tệp) ⇒ nhãn 'Duyệt (bản giấy)'", () => {
    ve(hoSo({ status: "paper_submitted", document_file_path: null, document_id: 77 }))
    expect(screen.getByTestId("ut-evidence-verify-04")).toHaveTextContent("Duyệt (bản giấy)")
  })
})
