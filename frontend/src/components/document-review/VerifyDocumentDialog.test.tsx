/**
 * GĐ1b §4.6 / §5.9 — duyệt một giấy: mặc định hình thức lúc nhận; KHÔNG dự phòng "photo" (thiếu ⇒ phải chọn);
 * `requires_ack` ⇒ cam kết + lý do; gửi `expected_row_version`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { VerifyDocumentDialog } from "./VerifyDocumentDialog"
import { API, giayThaoTac, renderWithClient } from "./test-helpers"

const URL_VERIFY = `${API}/api/admissions/5/documents/hoc_ba_thpt/verify-format`
let than: unknown[] = []

function hop(over: Record<string, unknown> = {}) {
  // Mặc định: giấy bản giấy ⇒ máy chủ bật can_change_format cùng can_verify (owner 18-11).
  const doc = giayThaoTac({ can_verify: true, can_change_format: true, ...over })
  const onOpenChange = vi.fn()
  renderWithClient(<VerifyDocumentDialog profileId={5} document={doc} open onOpenChange={onOpenChange} />)
  return { onOpenChange }
}

beforeEach(() => {
  than = []
  server.use(
    http.patch(URL_VERIFY, async ({ request }) => {
      than.push(await request.json())
      return HttpResponse.json({ id: 5 })
    }),
  )
})
afterEach(() => server.resetHandlers())

describe("VerifyDocumentDialog", () => {
  it("thiếu hình thức lúc nhận ⇒ không chọn sẵn gì, nút Duyệt khoá (không dự phòng photo)", () => {
    hop({ actual_submission_format: null })
    expect(screen.getByRole("button", { name: "Duyệt" })).toBeDisabled()
    expect(screen.getByTestId("chua-chon-hinh-thuc")).toBeInTheDocument()
    for (const r of screen.getAllByRole("radio")) expect(r).not.toBeChecked()
  })

  it("thiếu hình thức ⇒ người duyệt chọn 'Bản photo' thì gửi đúng photo", async () => {
    const u = userEvent.setup()
    const { onOpenChange } = hop({ actual_submission_format: null, row_version: 4 })
    await u.click(screen.getByLabelText("Bản photo"))
    await u.click(screen.getByRole("button", { name: "Duyệt" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(than).toEqual([{ format: "photo", expected_row_version: 4, unknown_submitter_ack: false }])
  })

  it("có hình thức lúc nhận ⇒ chọn sẵn đúng hình thức đó, không gửi reason", async () => {
    const u = userEvent.setup()
    const { onOpenChange } = hop({ actual_submission_format: "certified_copy" })
    expect(screen.getByLabelText("Bản sao chứng thực")).toBeChecked()
    await u.click(screen.getByRole("button", { name: "Duyệt" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(than).toEqual([{ format: "certified_copy", expected_row_version: 3, unknown_submitter_ack: false }])
  })

  it("giấy scan (can_change_format = false) ⇒ không có lựa chọn hình thức, gửi đúng hình thức đã khai", async () => {
    const u = userEvent.setup()
    const { onOpenChange } = hop({
      status: "uploaded", document_id: 77, actual_submission_format: "photo", can_change_format: false,
    })
    expect(screen.getByTestId("hinh-thuc-khoa")).toHaveTextContent("Bản photo")
    expect(screen.queryAllByRole("radio")).toHaveLength(0)
    await u.click(screen.getByRole("button", { name: "Duyệt" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(than).toEqual([{ format: "photo", expected_row_version: 3, unknown_submitter_ack: false }])
  })

  it("thiếu khoá can_change_format ⇒ coi như khoá (fail-closed)", () => {
    hop({ actual_submission_format: "original", can_change_format: undefined })
    expect(screen.getByTestId("hinh-thuc-khoa")).toBeInTheDocument()
    expect(screen.queryAllByRole("radio")).toHaveLength(0)
  })

  it("requires_ack ⇒ cần cả cam kết LẪN lý do; thân có reason + ack", async () => {
    const u = userEvent.setup()
    hop({ requires_ack: true })
    const nut = screen.getByRole("button", { name: "Duyệt" })
    expect(nut).toBeDisabled()
    await u.click(screen.getByRole("checkbox"))
    expect(nut).toBeDisabled()
    await u.type(screen.getByLabelText(/Lý do \(bắt buộc khi cam kết\)/), "đã gọi điện xác minh")
    expect(nut).toBeEnabled()
    await u.click(nut)
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      format: "original",
      expected_row_version: 3,
      unknown_submitter_ack: true,
      reason: "đã gọi điện xác minh",
    })
  })
})
