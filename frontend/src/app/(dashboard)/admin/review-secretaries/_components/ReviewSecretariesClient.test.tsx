/**
 * GĐ2-C C1 — màn hình Admin quyền "Thư ký Hội đồng": không phải Admin ⇒ máy chủ 403 ⇒ trang báo (không suy vai); gán gửi
 * đúng thân `{user_id, reason}` (không trường hạn — owner C1); thu hồi cần lý do; quyền đã thu hồi không có nút Thu hồi; câu báo
 * theo `reason_code` của máy chủ. Dữ liệu giả.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"

import { grantPersonLabel, ReviewSecretariesClient } from "./ReviewSecretariesClient"

const P = `${API}/api/admission-config/review-secretaries`
const QUYEN = {
  id: 41,
  user_id: 9,
  user: { id: 9, username: "canbo09", full_name: "Cán Bộ Chín", role: "officer", status: "active" },
  granted_by_user_id: 1,
  granted_at: "2026-11-22T01:00:00Z",
  reason: "Ban thư ký đợt 1",
  revoked_at: null,
  revoked_by_user_id: null,
  revoke_reason: null,
  is_active: true,
}

let thanGan: unknown[] = []
let thanThuHoi: unknown[] = []
beforeEach(() => {
  thanGan = []
  thanThuHoi = []
})
afterEach(() => server.resetHandlers())

describe("ReviewSecretariesClient", () => {
  it("403 ⇒ 'Chỉ Admin quản lý quyền Thư ký Hội đồng.'", async () => {
    server.use(http.get(P, () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 })))
    renderWithClient(<ReviewSecretariesClient />)
    expect(await screen.findByTestId("thu-ky-loi")).toHaveTextContent("Chỉ Admin quản lý quyền Thư ký Hội đồng.")
  })

  it("gán: thân đúng hợp đồng, KHÔNG có trường hạn", async () => {
    server.use(
      http.get(P, () => HttpResponse.json([])),
      http.post(P, async ({ request }) => {
        thanGan.push(await request.json())
        return HttpResponse.json(QUYEN, { status: 201 })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<ReviewSecretariesClient />)
    const form = await screen.findByTestId("gan-thu-ky")
    const nut = within(form).getByRole("button", { name: "Gán quyền" })
    expect(nut).toBeDisabled()
    await u.type(within(form).getByLabelText(/Mã người dùng/), "9")
    expect(nut).toBeDisabled()
    await u.type(within(form).getByLabelText(/Lý do gán/), "Ban thư ký đợt 1")
    await u.click(nut)
    await waitFor(() => expect(thanGan).toEqual([{ user_id: 9, reason: "Ban thư ký đợt 1" }]))
  })

  it("409 đang có quyền ⇒ câu theo reason_code", async () => {
    server.use(
      http.get(P, () => HttpResponse.json([])),
      http.post(P, () =>
        HttpResponse.json(
          {
            reason_code: "review_secretary_already_active",
            grant_id: 41,
            detail: "x",
            error_code: "REVIEW_SECRETARY_ALREADY_ACTIVE",
          },
          { status: 409 },
        ),
      ),
    )
    const u = userEvent.setup()
    renderWithClient(<ReviewSecretariesClient />)
    const form = await screen.findByTestId("gan-thu-ky")
    await u.type(within(form).getByLabelText(/Mã người dùng/), "9")
    await u.type(within(form).getByLabelText(/Lý do gán/), "lần hai")
    await u.click(within(form).getByRole("button", { name: "Gán quyền" }))
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Người này đang là Thư ký Hội đồng — thu hồi quyền cũ trước nếu muốn gán lại.",
    )
  })

  it("thu hồi cần lý do; gửi {reason}", async () => {
    server.use(
      http.get(P, () => HttpResponse.json([QUYEN])),
      http.post(`${P}/41/revoke`, async ({ request }) => {
        thanThuHoi.push(await request.json())
        return HttpResponse.json({
          ...QUYEN,
          revoked_at: "2026-11-23T01:00:00Z",
          revoked_by_user_id: 1,
          revoke_reason: "Hết nhiệm vụ",
          is_active: false,
        })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<ReviewSecretariesClient />)
    await u.click(await screen.findByRole("button", { name: "Thu hồi quyền #41" }))
    const hop = await screen.findByRole("dialog")
    const nut = within(hop).getByRole("button", { name: "Thu hồi" })
    expect(nut).toBeDisabled()
    await u.type(within(hop).getByLabelText(/Lý do thu hồi/), "Hết nhiệm vụ")
    await u.click(nut)
    await waitFor(() => expect(thanThuHoi).toEqual([{ reason: "Hết nhiệm vụ" }]))
  })

  it("quyền đã thu hồi ⇒ nhãn 'Đã thu hồi' + lý do thu hồi, KHÔNG nút Thu hồi", async () => {
    server.use(
      http.get(P, () =>
        HttpResponse.json([
          {
            ...QUYEN,
            revoked_at: "2026-11-23T01:00:00Z",
            revoked_by_user_id: 1,
            revoke_reason: "Tự thu hồi: tài khoản bị khoá",
            is_active: false,
          },
        ]),
      ),
    )
    renderWithClient(<ReviewSecretariesClient />)
    const ds = await screen.findByTestId("danh-sach-thu-ky")
    expect(ds).toHaveTextContent("Đã thu hồi")
    expect(ds).toHaveTextContent("lý do thu hồi: Tự thu hồi: tài khoản bị khoá")
    expect(screen.queryByRole("button", { name: "Thu hồi quyền #41" })).toBeNull()
  })

  it("nhãn người: họ tên (tên đăng nhập) · vai · mã; thiếu tóm tắt ⇒ chỉ mã", () => {
    expect(grantPersonLabel(QUYEN)).toBe("Cán Bộ Chín (canbo09) · Cán bộ · #9")
    expect(grantPersonLabel({ ...QUYEN, user: { ...QUYEN.user, full_name: null, role: "manager" } })).toBe(
      "canbo09 · Quản lý · #9",
    )
    expect(grantPersonLabel({ ...QUYEN, user: null })).toBe("Người dùng #9")
  })
})
