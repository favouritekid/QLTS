/**
 * KT-6 (owner 24-11: Thư ký Hội đồng CÓ THỂ là cán bộ thường) — trang "Bảng chỉ tiêu năm" ở `/quota-tables` (ngoài `/admin/*`).
 * Dựng qua ĐÚNG `page.tsx` của đường mới (nối dây), máy chủ giả qua MSW:
 *  - Thư ký là cán bộ: máy chủ trả 200 với `available_actions` rỗng ⇒ thấy bảng, KHÔNG nút sửa / khoá / mở khoá;
 *  - cán bộ chưa được gán: 404 thân chung của cổng ⇒ đúng câu owner duyệt nguyên văn 23-11, không bảng, không nút tạo;
 *  - vai bị Casbin chặn (403) ⇒ câu 403 sẵn có (không thêm câu mới);
 *  - đường cũ `/admin/quota-tables` chỉ chuyển hướng sang `/quota-tables`, không dựng trang thứ hai.
 * Proxy cho cán bộ vào đường mới: `src/proxy.thu-ky-ngoai-admin.test.ts`. Dữ liệu giả.
 *
 * GĐ2-B F1 (đính chính §2 + đính chính 2 §3): trang nhận năm qua `?year=` — test đi qua TRANG (`page.tsx` chờ `searchParams` bên
 * trong `<Suspense>`; `resolveServerTree` dựng như máy chủ), không chỉ qua thành phần:
 *  - `?year=<năm CHƯA có bảng>` ⇒ gọi đúng năm ấy + câu "Năm … chưa có bảng chỉ tiêu." — biến thể phá "trang bỏ `searchParams`"
 *    (vd `return <QuotaTablesClient />`) ⇒ gọi năm mặc định ⇒ ĐỎ;
 *  - `?year=abc` / khoá lặp (`string[]`) ⇒ năm mặc định — biến thể phá "nhận `Number(...)` không kiểm dạng" ⇒ ĐỎ.
 */
import fs from "node:fs"
import path from "node:path"

import { afterEach, describe, expect, it, vi } from "vitest"
import { screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { QUOTA_TABLE_NO_ACCESS_MESSAGE } from "@/lib/quota-tables/messages"
import type { PageSearchParams } from "@/lib/utils/search-params"
import { server } from "@/test/mocks/server"
import { resolveServerTree } from "@/test/server-component"

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

/** Dựng TRANG như máy chủ: `page.tsx` + `searchParams` (Promise), chờ thành phần async trong `<Suspense>` rồi vẽ. */
async function moTrang(sp: PageSearchParams = {}) {
  return renderWithClient(<>{await resolveServerTree(QuotaTablesPage({ searchParams: Promise.resolve(sp) }))}</>)
}

describe("KT-6 — trang /quota-tables (ngoài /admin)", () => {
  it("Thư ký là cán bộ (máy chủ 200, cờ rỗng) ⇒ thấy bảng, KHÔNG nút sửa / khoá / mở khoá", async () => {
    server.use(http.get(P, () => HttpResponse.json(bangChoThuKy())))
    await moTrang()
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
    await moTrang()
    expect(await screen.findByTestId("loi-tai-bang")).toHaveTextContent(QUOTA_TABLE_NO_ACCESS_MESSAGE)
    expect(screen.queryByTestId("bang-chi-tieu-xem")).toBeNull()
    expect(screen.queryByTestId("chua-co-bang")).toBeNull()
    expect(screen.queryByTestId("nut-tao-bang")).toBeNull()
  })

  it("vai bị Casbin chặn (403) ⇒ câu 403 sẵn có, không bảng", async () => {
    server.use(http.get(P, () => HttpResponse.json({ detail: "x" }, { status: 403 })))
    await moTrang()
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

describe("GĐ2-B F1 — trang /quota-tables nhận năm qua ?year= (liên kết từ 409 thiếu bảng của màn lần xét)", () => {
  const NAM_CHUA_CO = NAM + 1

  /** Máy chủ giả: năm mặc định CÓ bảng; năm `NAM_CHUA_CO` chưa có (404 mã riêng). Ghi lại năm được hỏi. */
  function mayChu(): number[] {
    const hoi: number[] = []
    server.use(
      http.get(`${API}/api/admission-config/quota-tables/:year`, ({ params }) => {
        const y = Number(params.year)
        hoi.push(y)
        if (y === NAM_CHUA_CO) {
          return HttpResponse.json(
            {
              detail: "Không tìm thấy",
              error_code: "RESOURCE_NOT_FOUND",
              reason_code: "quota_table_not_found",
              available_actions: [],
              quota_fingerprint: "c".repeat(64),
              academic_infos: [],
            },
            { status: 404 },
          )
        }
        return HttpResponse.json(bangChoThuKy())
      }),
    )
    return hoi
  }

  it("?year=<năm CHƯA có bảng> ⇒ hỏi đúng năm ấy, hiện 'Năm … chưa có bảng chỉ tiêu.', không lùi về năm mặc định", async () => {
    const hoi = mayChu()
    await moTrang({ year: String(NAM_CHUA_CO) })
    expect(await screen.findByTestId("chua-co-bang")).toHaveTextContent(`Năm ${NAM_CHUA_CO} chưa có bảng chỉ tiêu.`)
    expect(screen.queryByTestId("bang-chi-tieu-xem")).toBeNull()
    expect(hoi).toContain(NAM_CHUA_CO)
    expect(hoi).not.toContain(NAM)
  })

  it("?year=abc (sai dạng) ⇒ năm mặc định", async () => {
    const hoi = mayChu()
    await moTrang({ year: "abc" })
    expect(await screen.findByTestId("bang-chi-tieu-xem")).toBeInTheDocument()
    expect(hoi).toEqual([NAM])
  })

  it("?year lặp (string[]) ⇒ không đoán, năm mặc định", async () => {
    const hoi = mayChu()
    await moTrang({ year: [String(NAM_CHUA_CO), String(NAM_CHUA_CO + 1)] })
    expect(await screen.findByTestId("bang-chi-tieu-xem")).toBeInTheDocument()
    expect(hoi).toEqual([NAM])
  })
})
