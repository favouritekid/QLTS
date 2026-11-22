/**
 * GĐ2-C C1 — màn hình Admin quyền "Thư ký Hội đồng": không phải Admin ⇒ máy chủ 403 ⇒ trang báo (không suy vai); chọn người qua
 * ô tìm theo tên / email (owner 22-11 câu 3) — gửi `q` lên máy chủ, chọn một ứng viên rồi gán ⇒ thân `{user_id, reason}` (không
 * trường hạn — owner C1); chưa chọn người / chưa có lý do ⇒ không gán được; thu hồi cần lý do; quyền đã thu hồi không có nút
 * Thu hồi; câu báo theo `reason_code` của máy chủ. Dữ liệu giả.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"

import ReviewSecretariesPage from "../page"
import { candidateLabel, grantPersonLabel, ReviewSecretariesClient } from "./ReviewSecretariesClient"

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
const UNG_VIEN = { id: 9, username: "canbo09", full_name: "Cán Bộ Chín", email: "canbo09@example.com", role: "officer" }
const NHAN_UNG_VIEN = "Cán Bộ Chín (canbo09) · canbo09@example.com · Cán bộ"

let thanGan: unknown[] = []
let thanThuHoi: unknown[] = []
let tuKhoa: string[] = []
beforeEach(() => {
  thanGan = []
  thanThuHoi = []
  tuKhoa = []
})
afterEach(() => server.resetHandlers())

function ungVienHandler() {
  return http.get(`${P}/candidates`, ({ request }) => {
    tuKhoa.push(new URL(request.url).searchParams.get("q") ?? "")
    return HttpResponse.json([UNG_VIEN])
  })
}

describe("ReviewSecretariesClient", () => {
  it("403 ⇒ 'Chỉ Admin quản lý quyền Thư ký Hội đồng.'", async () => {
    server.use(
      http.get(P, () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 })),
      http.get(`${P}/candidates`, () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 })),
    )
    renderWithClient(<ReviewSecretariesClient />)
    expect(await screen.findByTestId("thu-ky-loi")).toHaveTextContent("Chỉ Admin quản lý quyền Thư ký Hội đồng.")
  })

  it("gán: tìm theo tên gửi q, chọn ứng viên, thân đúng hợp đồng (KHÔNG trường hạn)", async () => {
    server.use(
      http.get(P, () => HttpResponse.json([])),
      ungVienHandler(),
      http.post(P, async ({ request }) => {
        thanGan.push(await request.json())
        return HttpResponse.json(QUYEN, { status: 201 })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<ReviewSecretariesClient />)
    const form = await screen.findByTestId("gan-thu-ky")
    const nut = within(form).getByRole("button", { name: "Gán quyền" })
    await u.type(within(form).getByLabelText(/Tìm Quản lý hoặc Cán bộ/), "chín")
    await waitFor(() => expect(tuKhoa).toContain("chín"))
    await u.type(within(form).getByLabelText(/Lý do gán/), "Ban thư ký đợt 1")
    expect(nut).toBeDisabled() // chưa chọn người
    await u.click(await within(form).findByRole("button", { name: NHAN_UNG_VIEN }))
    expect(within(form).getByTestId("nguoi-da-chon")).toHaveTextContent(`Đã chọn: ${NHAN_UNG_VIEN}`)
    await u.click(nut)
    await waitFor(() => expect(thanGan).toEqual([{ user_id: 9, reason: "Ban thư ký đợt 1" }]))
  })

  it("chọn người mà chưa có lý do ⇒ không gán được; Bỏ chọn ⇒ lại không gán được", async () => {
    server.use(http.get(P, () => HttpResponse.json([])), ungVienHandler())
    const u = userEvent.setup()
    renderWithClient(<ReviewSecretariesClient />)
    const form = await screen.findByTestId("gan-thu-ky")
    const nut = within(form).getByRole("button", { name: "Gán quyền" })
    await u.click(await within(form).findByRole("button", { name: NHAN_UNG_VIEN }))
    expect(nut).toBeDisabled()
    await u.type(within(form).getByLabelText(/Lý do gán/), "x")
    expect(nut).toBeEnabled()
    await u.click(within(form).getByRole("button", { name: "Bỏ chọn" }))
    expect(nut).toBeDisabled()
  })

  it("409 đang có quyền ⇒ câu theo reason_code", async () => {
    server.use(
      http.get(P, () => HttpResponse.json([])),
      ungVienHandler(),
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
    await u.click(await within(form).findByRole("button", { name: NHAN_UNG_VIEN }))
    await u.type(within(form).getByLabelText(/Lý do gán/), "lần hai")
    await u.click(within(form).getByRole("button", { name: "Gán quyền" }))
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Người này đang là Thư ký Hội đồng — thu hồi quyền cũ trước nếu muốn gán lại.",
    )
  })

  it("không ứng viên nào khớp ⇒ câu báo", async () => {
    server.use(http.get(P, () => HttpResponse.json([])), http.get(`${P}/candidates`, () => HttpResponse.json([])))
    renderWithClient(<ReviewSecretariesClient />)
    expect(
      await screen.findByText("Không tìm thấy Quản lý hoặc Cán bộ đang hoạt động nào khớp."),
    ).toBeInTheDocument()
  })

  it("thu hồi cần lý do; gửi {reason}", async () => {
    server.use(
      http.get(P, () => HttpResponse.json([QUYEN])),
      http.get(`${P}/candidates`, () => HttpResponse.json([])),
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
      http.get(`${P}/candidates`, () => HttpResponse.json([])),
    )
    renderWithClient(<ReviewSecretariesClient />)
    const ds = await screen.findByTestId("danh-sach-thu-ky")
    expect(ds).toHaveTextContent("Đã thu hồi")
    expect(ds).toHaveTextContent("lý do thu hồi: Tự thu hồi: tài khoản bị khoá")
    expect(screen.queryByRole("button", { name: "Thu hồi quyền #41" })).toBeNull()
  })

  it("trang hiện câu owner duyệt: 'Admin luôn có quyền Thư ký Hội đồng, không cần gán.'", async () => {
    server.use(http.get(P, () => HttpResponse.json([])), http.get(`${P}/candidates`, () => HttpResponse.json([])))
    renderWithClient(<ReviewSecretariesPage />)
    expect(screen.getByTestId("admin-luon-la-thu-ky")).toHaveTextContent(
      /^Admin luôn có quyền Thư ký Hội đồng, không cần gán\.$/,
    )
    expect(await screen.findByTestId("gan-thu-ky")).toBeInTheDocument()
  })

  it("nhãn người / ứng viên: họ tên (tên đăng nhập) · …; thiếu họ tên / tóm tắt ⇒ phần còn lại", () => {
    expect(grantPersonLabel(QUYEN)).toBe("Cán Bộ Chín (canbo09) · Cán bộ · #9")
    expect(grantPersonLabel({ ...QUYEN, user: { ...QUYEN.user, full_name: null, role: "manager" } })).toBe(
      "canbo09 · Quản lý · #9",
    )
    expect(grantPersonLabel({ ...QUYEN, user: null })).toBe("Người dùng #9")
    expect(candidateLabel(UNG_VIEN)).toBe(NHAN_UNG_VIEN)
    expect(candidateLabel({ ...UNG_VIEN, full_name: null, role: "manager" })).toBe("canbo09 · canbo09@example.com · Quản lý")
  })
})
