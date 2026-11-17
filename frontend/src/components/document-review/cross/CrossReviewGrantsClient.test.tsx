/**
 * GĐ1b §6 — Admin quản lý quyền duyệt chéo: không phải Admin ⇒ máy chủ 403 ⇒ trang báo (không suy vai); cấp quyền
 * gửi đúng thân (hạn giờ Việt Nam +07:00, lý do); thu hồi cần lý do.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { API, renderWithClient } from "../test-helpers"
import { CrossReviewGrantsClient, vnLocalToIso } from "./CrossReviewGrantsClient"

const C = `${API}/api/admissions/cross-review`
const QUYEN = {
  id: 31,
  grantee_user_id: 9,
  unit_id: 3,
  allow_verify: true,
  allow_reject: false,
  granted_by_user_id: 1,
  granted_at: "2026-11-17T01:00:00Z",
  expires_at: "2026-11-24T10:00:00Z",
  reason: "đơn vị 3 thiếu người",
  revoked_at: null,
  revoked_by_user_id: null,
}

let thanTao: unknown[] = []
let thanThuHoi: unknown[] = []
beforeEach(() => {
  thanTao = []
  thanThuHoi = []
})
afterEach(() => server.resetHandlers())

describe("CrossReviewGrantsClient", () => {
  it("403 ⇒ 'Chỉ Admin quản lý quyền duyệt chéo'", async () => {
    server.use(http.get(`${C}/grants`, () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 })))
    renderWithClient(<CrossReviewGrantsClient />)
    expect(await screen.findByTestId("quyen-cheo-loi")).toHaveTextContent("Chỉ Admin quản lý quyền duyệt chéo")
  })

  it("cấp quyền: thân đúng hợp đồng, hạn kèm +07:00", async () => {
    server.use(
      http.get(`${C}/grants`, () => HttpResponse.json({ items: [] })),
      http.post(`${C}/grants`, async ({ request }) => {
        thanTao.push(await request.json())
        return HttpResponse.json(QUYEN, { status: 201 })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<CrossReviewGrantsClient />)
    const form = await screen.findByTestId("cap-quyen-cheo")
    const nut = within(form).getByRole("button", { name: "Cấp quyền" })
    expect(nut).toBeDisabled()
    await u.type(within(form).getByLabelText(/Mã người dùng/), "9")
    await u.type(within(form).getByLabelText(/Mã đơn vị/), "3")
    fireEvent.change(within(form).getByLabelText(/Hết hạn/), { target: { value: "2026-11-24T17:00" } })
    await u.type(within(form).getByLabelText(/Lý do cấp/), "đơn vị 3 thiếu người")
    await u.click(nut)
    await waitFor(() => expect(thanTao).toHaveLength(1))
    expect(thanTao[0]).toEqual({
      grantee_user_id: 9,
      unit_id: 3,
      allow_verify: true,
      allow_reject: false,
      expires_at: "2026-11-24T17:00:00+07:00",
      reason: "đơn vị 3 thiếu người",
    })
  })

  it("thu hồi cần lý do; gửi {reason}", async () => {
    server.use(
      http.get(`${C}/grants`, () => HttpResponse.json({ items: [QUYEN] })),
      http.post(`${C}/grants/31/revoke`, async ({ request }) => {
        thanThuHoi.push(await request.json())
        return HttpResponse.json({ ...QUYEN, revoked_at: "2026-11-18T01:00:00Z", revoked_by_user_id: 1 })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<CrossReviewGrantsClient />)
    await u.click(await screen.findByRole("button", { name: "Thu hồi" }))
    const hop = await screen.findByRole("dialog")
    const nut = within(hop).getByRole("button", { name: "Thu hồi" })
    expect(nut).toBeDisabled()
    await u.type(within(hop).getByLabelText(/Lý do thu hồi/), "đủ người")
    await u.click(nut)
    await waitFor(() => expect(thanThuHoi).toEqual([{ reason: "đủ người" }]))
  })

  it("vnLocalToIso: chỉ nhận đúng dạng datetime-local", () => {
    expect(vnLocalToIso("2026-11-24T17:00")).toBe("2026-11-24T17:00:00+07:00")
    expect(vnLocalToIso("")).toBeNull()
    expect(vnLocalToIso("24/11/2026 17:00")).toBeNull()
  })
})
