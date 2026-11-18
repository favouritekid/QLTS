/**
 * GĐ1b §7 — hộp Đặt lại: lý do BẮT BUỘC; "Tệp scan được giữ lại" khi `reset_keeps_evidence`; không câu "xoá tệp" khi
 * giữ bằng chứng; cam kết khi `requires_ack`; gửi `expected_row_version`; lý do KHÔNG vào localStorage; 409
 * VERSION_CHANGED ⇒ làm mới chi tiết hồ sơ + đóng hộp.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"

import { ResetDocumentDialog } from "./ResetDocumentDialog"
import { API, giayThaoTac, renderWithClient } from "./test-helpers"

const URL_RESET = `${API}/api/admissions/5/documents/hoc_ba_thpt/reset`

function hop(over: Record<string, unknown> = {}, onOpenChange = vi.fn()) {
  const doc = giayThaoTac({ can_reset: true, reset_requires_reason: true, ...over })
  const r = renderWithClient(<ResetDocumentDialog profileId={5} document={doc} open onOpenChange={onOpenChange} />)
  return { ...r, onOpenChange }
}

let than: unknown[] = []
beforeEach(() => {
  than = []
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  server.resetHandlers()
  vi.restoreAllMocks()
})

describe("ResetDocumentDialog", () => {
  it("nút Đặt lại khoá cho tới khi có lý do (chỉ khoảng trắng vẫn khoá)", async () => {
    const u = userEvent.setup()
    hop()
    const nut = screen.getByRole("button", { name: "Đặt lại" })
    expect(nut).toBeDisabled()
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "   ")
    expect(nut).toBeDisabled()
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "nhận nhầm giấy")
    expect(nut).toBeEnabled()
  })

  it("gửi lý do đã cắt khoảng trắng + expected_row_version = row_version đang xem", async () => {
    server.use(
      http.post(URL_RESET, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json({ id: 5 })
      }),
    )
    const u = userEvent.setup()
    const { onOpenChange } = hop({ row_version: 9 })
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "  nhận nhầm giấy  ")
    await u.click(screen.getByRole("button", { name: "Đặt lại" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(than).toEqual([{ reason: "nhận nhầm giấy", expected_row_version: 9, unknown_submitter_ack: false }])
  })

  it("giấy đã duyệt giữ bằng chứng ⇒ 'Tệp scan được giữ lại', KHÔNG câu gỡ / xoá tệp", () => {
    hop({ status: "verified", document_id: 11, reset_keeps_evidence: true })
    expect(screen.getByTestId("dat-lai-giu-tep")).toHaveTextContent("Tệp scan được giữ lại")
    expect(screen.queryByTestId("dat-lai-go-tep")).toBeNull()
    expect(document.body.textContent ?? "").not.toMatch(/sẽ bị x[oó]a|file sẽ/i)
  })

  it("giấy có tệp, không giữ bằng chứng ⇒ câu gỡ tệp; không câu 'giữ lại'", () => {
    hop({ status: "uploaded", document_id: 11, reset_keeps_evidence: false })
    expect(screen.getByTestId("dat-lai-go-tep")).toBeInTheDocument()
    expect(screen.queryByTestId("dat-lai-giu-tep")).toBeNull()
  })

  it("requires_ack ⇒ phải tích cam kết mới gửi được; thân mang unknown_submitter_ack = true", async () => {
    server.use(
      http.post(URL_RESET, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json({ id: 5 })
      }),
    )
    const u = userEvent.setup()
    hop({ requires_ack: true })
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "không rõ ai nhận")
    const nut = screen.getByRole("button", { name: "Đặt lại" })
    expect(nut).toBeDisabled()
    await u.click(screen.getByRole("checkbox"))
    expect(nut).toBeEnabled()
    await u.click(nut)
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toMatchObject({ unknown_submitter_ack: true })
  })

  it("lý do KHÔNG ghi vào localStorage (không 'lý do gần đây')", async () => {
    server.use(http.post(URL_RESET, () => HttpResponse.json({ id: 5 })))
    const ghi = vi.spyOn(Storage.prototype, "setItem")
    const u = userEvent.setup()
    const { onOpenChange } = hop()
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "Nguyễn Văn A nộp nhầm")
    await u.click(screen.getByRole("button", { name: "Đặt lại" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(ghi).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it("409 VERSION_CHANGED ⇒ làm mới chi tiết hồ sơ + đóng hộp", async () => {
    server.use(
      http.post(URL_RESET, () =>
        HttpResponse.json({ reason_code: "version_changed", error_code: "VERSION_CHANGED", detail: "x" }, { status: 409 }),
      ),
    )
    const u = userEvent.setup()
    const { queryClient, onOpenChange } = hop()
    queryClient.setQueryData(admissionsKeys.detail(5), { id: 5 })
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "nhầm")
    await u.click(screen.getByRole("button", { name: "Đặt lại" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(queryClient.getQueryState(admissionsKeys.detail(5))?.isInvalidated).toBe(true)
  })

  it("409 OWN_SUBMISSION ⇒ giữ hộp, hiện câu tiếng Việt", async () => {
    server.use(
      http.post(URL_RESET, () =>
        HttpResponse.json({ reason_code: "own_submission", error_code: "OWN_SUBMISSION", detail: "x" }, { status: 409 }),
      ),
    )
    const u = userEvent.setup()
    const { onOpenChange } = hop()
    await u.type(screen.getByLabelText(/Lý do đặt lại/), "nhầm")
    await u.click(screen.getByRole("button", { name: "Đặt lại" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("không tự duyệt")
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })

  it("giấy ngoài cấu hình (X1) ⇒ tiêu đề riêng", () => {
    hop({ is_extra: true })
    expect(screen.getByRole("heading", { name: "Đặt lại giấy ngoài cấu hình" })).toBeInTheDocument()
  })
})
