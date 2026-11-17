/**
 * GĐ1b §5.6 / §5.7 / §5.9 — bảng tra lô: "Chạy lô này" CHỈ theo `can_execute`, "Chốt lô" CHỈ theo `can_finalize`
 * (không suy từ trạng thái); chốt 422 ⇒ "Cần nhập lý do chốt lô"; 404 ⇒ "Bản xem trước không còn — xem trước lại".
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { API, B1, loGia, renderWithClient } from "../test-helpers"
import { BatchStatusPanel } from "./BatchStatusPanel"

const P = `${API}/api/admissions/documents/bulk-verify`
let soExecute = 0
let thanFinalize: unknown[] = []

function lo(view: Record<string, unknown>) {
  server.use(http.get(`${P}/${B1}`, () => HttpResponse.json(view)))
}

beforeEach(() => {
  soExecute = 0
  thanFinalize = []
  server.use(
    http.post(`${P}/${B1}/execute`, () => {
      soExecute++
      return HttpResponse.json(loGia({ status: "completed" }))
    }),
  )
})
afterEach(() => server.resetHandlers())

describe("BatchStatusPanel", () => {
  it("not_started nhưng can_execute = false (vd Admin xem lô người khác) ⇒ KHÔNG có nút Chạy", async () => {
    lo(loGia({ status: "not_started", can_execute: false, counts: { profiles: 1, recorded: 0, error: 0, not_processed: 0, pending: 2 } }))
    renderWithClient(<BatchStatusPanel endpoint={{ mode: "batch" }} batchId={B1} />)
    await screen.findByTestId("ket-qua-lo")
    expect(screen.queryByRole("button", { name: "Chạy lô này" })).toBeNull()
  })

  it("can_execute = true ⇒ có nút; phải tích xác nhận; bấm gửi execute đúng một lần", async () => {
    lo(loGia({ status: "not_started", can_execute: true }))
    const u = userEvent.setup()
    renderWithClient(<BatchStatusPanel endpoint={{ mode: "batch" }} batchId={B1} />)
    const nut = await screen.findByRole("button", { name: "Chạy lô này" })
    expect(nut).toBeDisabled()
    await u.click(screen.getByRole("checkbox"))
    await u.click(nut)
    await waitFor(() => expect(soExecute).toBe(1))
  })

  it("interrupted_unfinalized + can_finalize = false ⇒ không có nút Chốt lô", async () => {
    lo(loGia({ status: "interrupted_unfinalized", can_finalize: false }))
    renderWithClient(<BatchStatusPanel endpoint={{ mode: "batch" }} batchId={B1} />)
    await screen.findByTestId("ket-qua-lo")
    expect(screen.queryByRole("button", { name: "Chốt lô" })).toBeNull()
  })

  it("can_finalize = true ⇒ Chốt lô; 422 ⇒ 'Cần nhập lý do chốt lô'; có lý do ⇒ gửi {reason}", async () => {
    lo(loGia({ status: "interrupted_unfinalized", can_finalize: true }))
    server.use(
      http.post(`${P}/${B1}/finalize`, async ({ request }) => {
        const b = (await request.json()) as Record<string, unknown>
        thanFinalize.push(b)
        if (!b.reason) return HttpResponse.json({ error_code: "VALIDATION_ERROR", detail: "x" }, { status: 422 })
        return HttpResponse.json({ batch: loGia({ status: "interrupted" }), finalized_now: true })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<BatchStatusPanel endpoint={{ mode: "batch" }} batchId={B1} />)
    await u.click(await screen.findByRole("button", { name: "Chốt lô" }))
    const hopChot = await screen.findByRole("dialog")
    await u.click(screen.getAllByRole("button", { name: "Chốt lô" }).at(-1) as HTMLElement)
    expect(await screen.findByText("Cần nhập lý do chốt lô")).toBeInTheDocument()
    await u.type(screen.getByLabelText(/Lý do chốt/), "máy chủ khởi động lại giữa lô")
    await u.click(screen.getAllByRole("button", { name: "Chốt lô" }).at(-1) as HTMLElement)
    await waitFor(() => expect(hopChot).not.toBeInTheDocument())
    expect(thanFinalize).toEqual([{}, { reason: "máy chủ khởi động lại giữa lô" }])
  })

  it("404 ⇒ 'Bản xem trước không còn — xem trước lại'", async () => {
    server.use(http.get(`${P}/${B1}`, () => HttpResponse.json({ detail: "Not found" }, { status: 404 })))
    renderWithClient(<BatchStatusPanel endpoint={{ mode: "batch" }} batchId={B1} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Bản xem trước không còn — xem trước lại")
  })

  it("đang chạy ⇒ báo đang cập nhật (hỏi lại theo nhịp 3 s / 10 s — khoá ở messages.test)", async () => {
    lo(loGia({ status: "running", counts: { profiles: 2, recorded: 1, error: 0, not_processed: 0, pending: 1 } }))
    renderWithClient(<BatchStatusPanel endpoint={{ mode: "batch" }} batchId={B1} />)
    expect(await screen.findByTestId("dang-hoi-lai")).toBeInTheDocument()
    expect(soExecute).toBe(0)
  })
})
