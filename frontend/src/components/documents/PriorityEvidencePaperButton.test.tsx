/**
 * GĐ2-F1 — nút "Đã nhận bản giấy" của minh chứng ưu tiên: CHỈ hiện khi máy chủ bật `can_mark_paper_submitted` (thiếu /
 * null / false ⇒ không nút — fail-closed); xác nhận rồi mới gọi route; dòng đã ghi nhận ⇒ hiện trạng thái; lỗi ⇒ câu
 * tiếng Việt. Dữ liệu giả.
 */
import { afterEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { PriorityEvidencePaperButton } from "./PriorityEvidencePaperButton"

const URL_GIAY = `${API}/api/v2/admissions/42/priority-evidence/04/paper-submitted`

function hoSo(muc: Record<string, unknown>): AdmissionProfileResponse {
  return {
    id: 42,
    version: 5,
    priority_object_codes: ["04"],
    priority_evidence_documents: [
      {
        sub_code: "04",
        bonus_points: 1.0,
        label: "Giấy chứng nhận diện thử",
        document_id: null,
        document_file_path: null,
        status: "missing",
        verification_status: null,
        ...muc,
      },
    ],
  } as unknown as AdmissionProfileResponse
}

afterEach(() => server.resetHandlers())

describe("PriorityEvidencePaperButton", () => {
  it.each([
    ["false", false],
    ["null", null],
    ["thiếu khoá", undefined],
  ])("cờ can_mark_paper_submitted = %s ⇒ KHÔNG nút", (_ten, co) => {
    renderWithClient(<PriorityEvidencePaperButton profile={hoSo({ can_mark_paper_submitted: co })} subCode="04" />)
    expect(screen.queryByTestId("priority-evidence-paper-04")).toBeNull()
  })

  it("cờ bật ⇒ có nút; bấm ⇒ hộp xác nhận (chưa gọi); xác nhận ⇒ gọi đúng route MỘT lần", async () => {
    let goi = 0
    server.use(
      http.post(URL_GIAY, () => {
        goi += 1
        return HttpResponse.json({ id: 42 })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<PriorityEvidencePaperButton profile={hoSo({ can_mark_paper_submitted: true })} subCode="04" />)
    await u.click(screen.getByTestId("priority-evidence-paper-04"))
    expect(screen.getByTestId("priority-evidence-paper-dialog-04")).toHaveTextContent(
      /không được tự duyệt hay từ chối/,
    )
    expect(goi).toBe(0)
    await u.click(screen.getByTestId("priority-evidence-paper-confirm-04"))
    await waitFor(() => expect(goi).toBe(1))
  })

  it("dòng đã ghi nhận bản giấy (paper_submitted) ⇒ hiện trạng thái, không nút", () => {
    renderWithClient(
      <PriorityEvidencePaperButton
        profile={hoSo({ status: "paper_submitted", document_id: 77, can_mark_paper_submitted: false })}
        subCode="04"
      />,
    )
    expect(screen.getByTestId("priority-evidence-paper-recorded-04")).toHaveTextContent(/Đã ghi nhận minh chứng bản giấy/)
    expect(screen.queryByTestId("priority-evidence-paper-04")).toBeNull()
  })

  it("máy chủ từ chối 400 ⇒ câu tiếng Việt trong hộp, giữ hộp", async () => {
    server.use(http.post(URL_GIAY, () => HttpResponse.json({ detail: "x", error_code: "BAD_REQUEST" }, { status: 400 })))
    const u = userEvent.setup()
    renderWithClient(<PriorityEvidencePaperButton profile={hoSo({ can_mark_paper_submitted: true })} subCode="04" />)
    await u.click(screen.getByTestId("priority-evidence-paper-04"))
    await u.click(screen.getByTestId("priority-evidence-paper-confirm-04"))
    const loi = await screen.findByRole("alert")
    expect(loi).toHaveTextContent(/Không ghi nhận được/)
    expect(screen.getByTestId("priority-evidence-paper-dialog-04")).toBeInTheDocument()
  })
})
