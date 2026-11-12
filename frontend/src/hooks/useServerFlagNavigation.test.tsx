/**
 * F238 (Codex lần 8, lượt G) — mục "Văn bản Hội đồng" của thanh bên hiện THEO CỜ máy chủ, không theo
 * vai: quản lý chưa gán đơn vị (máy chủ trả mọi cờ tắt) KHÔNG thấy mục; 403 / lỗi / đang tải ⇒ ẩn;
 * không có mục mang cờ sau bộ lọc vai thô ⇒ KHÔNG hỏi `/quyen`. API thật qua MSW.
 */
import fs from "node:fs"
import path from "node:path"
import { beforeEach, describe, expect, it } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { navigationConfig } from "@/lib/config/navigation"
import type { NavGroup } from "@/types/navigation"

import { NO_COUNCIL_PERMISSIONS } from "./admin/useCouncilDocuments"
import { useServerFlagNavigation } from "./useServerFlagNavigation"

const API = "http://localhost:8000"
const HREF = "/admin/council-documents"

/** Mọi cờ tắt — dựng từ chính hằng của module (đủ khoá như hợp đồng máy chủ; thiếu khoá ⇒ Zod nổ ⇒ menu ẩn). */
const TAT = { ...NO_COUNCIL_PERMISSIONS }

let hoi = 0
function mocQuyen(tra: () => Response) {
  server.use(
    http.get(`${API}${P}/quyen`, () => {
      hoi += 1
      return tra()
    }),
  )
}

/** Nhóm thanh bên như `useAppNavigation` trả cho admin / quản lý (đã qua bộ lọc vai thô). */
function navTheoVai(): NavGroup[] {
  return navigationConfig.groups
    .map((g) => ({ ...g, items: g.items.filter((i) => !i.roles || i.roles.length === 0 || i.roles.includes("manager")) }))
    .filter((g) => g.items.length > 0)
}

function chay(nav: NavGroup[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return renderHook(() => useServerFlagNavigation(nav), { wrapper })
}

const coMuc = (nav: NavGroup[]) => nav.some((g) => g.items.some((i) => i.href === HREF))

beforeEach(() => {
  hoi = 0
})

describe("useServerFlagNavigation — mục văn bản Hội đồng theo cờ máy chủ", () => {
  it("cấu hình: mục mang serverFlag (không chỉ dựa vai)", () => {
    const muc = navigationConfig.groups.flatMap((g) => g.items).find((i) => i.href === HREF)
    expect(muc?.serverFlag).toBe("council-documents")
  })

  it("máy chủ trả ít nhất một cờ bật ⇒ hiện mục", async () => {
    mocQuyen(() => HttpResponse.json({ permissions: { ...TAT, xem_danh_sach_bo: true } }))
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(coMuc(result.current)).toBe(true))
  })

  it("quản lý chưa gán đơn vị — máy chủ trả MỌI cờ tắt ⇒ KHÔNG thấy mục", async () => {
    mocQuyen(() => HttpResponse.json({ permissions: TAT }))
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(hoi).toBe(1))
    await new Promise((r) => setTimeout(r, 20))
    expect(coMuc(result.current)).toBe(false)
    // các mục khác vẫn còn (chỉ mục mang cờ bị lọc)
    expect(result.current.length).toBeGreaterThan(0)
  })

  it("403 / đang tải ⇒ ẩn", async () => {
    mocQuyen(() => HttpResponse.json({ detail: "x" }, { status: 403 }))
    const { result } = chay(navTheoVai())
    expect(coMuc(result.current)).toBe(false) // đang tải
    await waitFor(() => expect(hoi).toBe(1))
    await new Promise((r) => setTimeout(r, 20))
    expect(coMuc(result.current)).toBe(false)
  })

  it("không còn mục mang cờ (vai bị lọc thô) ⇒ không hỏi /quyen", async () => {
    mocQuyen(() => HttpResponse.json({ permissions: { ...TAT, xem_mau: true } }))
    const khong = navTheoVai().map((g) => ({ ...g, items: g.items.filter((i) => i.href !== HREF) }))
    chay(khong)
    await new Promise((r) => setTimeout(r, 30))
    expect(hoi).toBe(0)
  })

  it("nối dây: thanh bên lọc qua useServerFlagNavigation", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../components/layouts/dashboard/AppSidebar.tsx"),
      "utf8",
    )
    expect(src).toMatch(/const navigation = useServerFlagNavigation\(navigationTheoVai\)/)
  })
})
