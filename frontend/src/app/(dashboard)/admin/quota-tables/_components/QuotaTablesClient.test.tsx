/**
 * GĐ2-F1 — trang bảng chỉ tiêu năm: năm chưa có bảng (404) ⇒ cho tạo với `version` 0; máy chủ 403 ⇒ câu "Chỉ Admin" (không
 * kiểm vai ở giao diện); danh sách ngành để thêm chỉ lấy học vụ của ĐÚNG năm đang xem. Dữ liệu giả.
 */
import { afterEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"

import { buildMemberOptions, QuotaTablesClient } from "./QuotaTablesClient"

const P = `${API}/api/admission-config/quota-tables/2026`

function batDanhMuc() {
  server.use(
    http.get(`${API}/api/offerings/academic-info`, () =>
      HttpResponse.json([
        { id: 21, offering_id: 1, academic_year: 2026, annual_admission_quota: null, is_deleted: false },
        { id: 22, offering_id: 1, academic_year: 2025, annual_admission_quota: 10, is_deleted: false },
      ]),
    ),
    http.get(`${API}/api/program-offerings`, () =>
      HttpResponse.json([{ id: 1, offering_type: "Chính quy", program: { code: "M1", name: "Ngành Một" } }]),
    ),
  )
}

afterEach(() => server.resetHandlers())

describe("QuotaTablesClient", () => {
  it("năm chưa có bảng (404) ⇒ nút tạo; tạo ⇒ PUT version 0", async () => {
    const than: unknown[] = []
    batDanhMuc()
    server.use(
      http.get(P, () => HttpResponse.json({ detail: "Năm 2026 chưa có bảng chỉ tiêu." }, { status: 404 })),
      http.put(P, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json({
          academic_year: 2026, status: "draft", version: 1, locked_by_user_id: null, locked_at: null,
          available_actions: ["edit", "lock"], groups: [],
        })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    await u.click(await screen.findByTestId("nut-tao-bang"))
    await u.click(screen.getByRole("button", { name: /Thêm nhóm ngành/ }))
    await u.type(screen.getByLabelText("Mã nhóm"), "N1")
    await u.type(screen.getByLabelText("Tên nhóm"), "Nhóm thử")
    await u.type(screen.getByLabelText("Trần chỉ tiêu nhóm"), "10")
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ version: 0, groups: [{ code: "N1", name: "Nhóm thử", ceiling: 10, members: [] }] })
  })

  it("máy chủ 403 ⇒ câu 'Chỉ Admin', không nút tạo / sửa", async () => {
    batDanhMuc()
    server.use(http.get(P, () => HttpResponse.json({ detail: "x", error_code: "PERMISSION_DENIED" }, { status: 403 })))
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    expect(await screen.findByTestId("loi-tai-bang")).toHaveTextContent(/Chỉ Admin/)
    expect(screen.queryByTestId("nut-tao-bang")).toBeNull()
    expect(screen.queryByTestId("nut-sua-bang")).toBeNull()
  })
})

describe("buildMemberOptions", () => {
  it("chỉ học vụ của đúng năm, chưa xoá; giữ chỉ tiêu null là null", () => {
    const o = buildMemberOptions(
      [
        { id: 21, offering_id: 1, academic_year: 2026, annual_admission_quota: null, is_deleted: false },
        { id: 22, offering_id: 1, academic_year: 2025, annual_admission_quota: 10 },
        { id: 23, offering_id: 1, academic_year: 2026, annual_admission_quota: 5, is_deleted: true },
      ],
      [{ id: 1, offering_type: "Chính quy", program: { code: "M1", name: "Ngành Một" } }],
      2026,
    )
    expect(o).toEqual([
      { offering_academic_info_id: 21, label: "M1 — Ngành Một (Chính quy)", annual_admission_quota: null },
    ])
  })
})
