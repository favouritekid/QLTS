/**
 * KT-6 (owner 24-11: Thư ký Hội đồng CÓ THỂ là cán bộ thường) — trang "Bảng chỉ tiêu năm" ở `/quota-tables` (ngoài `/admin/*`).
 * Dựng qua ĐÚNG `page.tsx` của đường mới (nối dây), máy chủ giả qua MSW:
 *  - Thư ký là cán bộ: máy chủ trả 200 với `available_actions` rỗng ⇒ thấy bảng, KHÔNG nút sửa / khoá / mở khoá;
 *  - cán bộ chưa được gán: 404 thân chung của cổng ⇒ đúng câu owner duyệt nguyên văn 23-11, không bảng, không nút tạo;
 *  - vai bị Casbin chặn (403) ⇒ câu 403 sẵn có (không thêm câu mới);
 *  - đường cũ `/admin/quota-tables` chỉ chuyển hướng sang `/quota-tables`, không dựng trang thứ hai.
 * Proxy cho cán bộ vào đường mới: `src/proxy.thu-ky-ngoai-admin.test.ts`. Dữ liệu giả.
 */
import fs from "node:fs"
import path from "node:path"

import { afterEach, describe, expect, it, vi } from "vitest"
import { screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { QUOTA_TABLE_NO_ACCESS_MESSAGE } from "@/lib/quota-tables/messages"
import { server } from "@/test/mocks/server"

import AdminQuotaTablesRedirect from "../../admin/quota-tables/page"
import QuotaTablesPage from "../page"

const redirectMock = vi.hoisted(() =>
  vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`)
  }),
)

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  redirect: redirectMock,
}))

const NAM = new Date().getFullYear()
const P = `${API}/api/admission-config/quota-tables/${NAM}`

/** Bảng như máy chủ trả cho người XEM được mà không ghi được (Thư ký): `available_actions` rỗng. */
function bangChoThuKy() {
  return {
    academic_year: NAM,
    status: "locked",
    version: 3,
    locked_by_user_id: 1,
    locked_at: `${NAM}-06-01T08:00:00Z`,
    available_actions: [],
    quota_fingerprint: "3".repeat(64),
    groups: [
      {
        id: 7,
        code: "N1",
        name: "Nhóm thử",
        ceiling: 120,
        usage: { publish_count: 0, approved_count: 0, used: 0 },
        members: [],
      },
    ],
    academic_infos: [],
  }
}

afterEach(() => server.resetHandlers())

describe("KT-6 — trang /quota-tables (ngoài /admin)", () => {
  it("Thư ký là cán bộ (máy chủ 200, cờ rỗng) ⇒ thấy bảng, KHÔNG nút sửa / khoá / mở khoá", async () => {
    server.use(http.get(P, () => HttpResponse.json(bangChoThuKy())))
    renderWithClient(<QuotaTablesPage />)
    expect(await screen.findByTestId("bang-chi-tieu-xem")).toBeInTheDocument()
    expect(screen.getByTestId("nhom-N1")).toBeInTheDocument()
    expect(screen.queryByTestId("nut-sua-bang")).toBeNull()
    expect(screen.queryByTestId("nut-khoa-bang")).toBeNull()
    expect(screen.queryByTestId("nut-mo-khoa-bang")).toBeNull()
    expect(screen.queryByTestId("loi-tai-bang")).toBeNull()
  })

  it("cán bộ CHƯA được gán Thư ký (404 thân chung của cổng) ⇒ câu owner duyệt, không bảng, không nút tạo", async () => {
    server.use(
      http.get(P, () => HttpResponse.json({ detail: "Không tìm thấy", error_code: "RESOURCE_NOT_FOUND" }, { status: 404 })),
    )
    renderWithClient(<QuotaTablesPage />)
    expect(await screen.findByTestId("loi-tai-bang")).toHaveTextContent(QUOTA_TABLE_NO_ACCESS_MESSAGE)
    expect(screen.queryByTestId("bang-chi-tieu-xem")).toBeNull()
    expect(screen.queryByTestId("chua-co-bang")).toBeNull()
    expect(screen.queryByTestId("nut-tao-bang")).toBeNull()
  })

  it("vai bị Casbin chặn (403) ⇒ câu 403 sẵn có, không bảng", async () => {
    server.use(http.get(P, () => HttpResponse.json({ detail: "x" }, { status: 403 })))
    renderWithClient(<QuotaTablesPage />)
    expect(await screen.findByTestId("loi-tai-bang")).toHaveTextContent("Chỉ Admin được xem / sửa / khoá bảng chỉ tiêu năm.")
    expect(screen.queryByTestId("bang-chi-tieu-xem")).toBeNull()
  })

  it("đường cũ /admin/quota-tables ⇒ chuyển hướng sang /quota-tables, không dựng trang", () => {
    expect(() => AdminQuotaTablesRedirect()).toThrow("NEXT_REDIRECT:/quota-tables")
    expect(redirectMock).toHaveBeenCalledWith("/quota-tables")
  })

  it("MỘT chỗ dựng trang: thành phần chỉ nằm ở /quota-tables; /admin/quota-tables không còn thành phần / không import trang", () => {
    const app = path.resolve(__dirname, "../..")
    expect(fs.existsSync(path.join(app, "quota-tables/_components/QuotaTablesClient.tsx"))).toBe(true)
    expect(fs.existsSync(path.join(app, "admin/quota-tables/_components"))).toBe(false)
    const cu = fs.readFileSync(path.join(app, "admin/quota-tables/page.tsx"), "utf8")
    expect(cu).not.toMatch(/QuotaTablesClient/)
  })
})
