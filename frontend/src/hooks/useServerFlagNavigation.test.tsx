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
    expect(src).toMatch(/const navigation = useServerFlagNavigation\(navigationByRole\)/)
  })
})

/**
 * GĐ1b (đặc tả §7, bản 6 C2.1) — "Duyệt chéo" ⇐ `cross-review/eligibility`, "Lô duyệt giấy" ⇐ `bulk-verify/eligibility`.
 * Hiện CHỈ khi máy chủ trả `eligible = true`; `false` / đang tải / lỗi mạng / 4xx / 5xx ⇒ ẩn. Không theo vai (`roles: []`).
 */
describe("useServerFlagNavigation — mục GĐ1b theo cờ máy chủ (bản 6 C2.1)", () => {
  const CO = [
    { flag: "cross-review", href: "/cross-review", url: `${API}/api/admissions/cross-review/eligibility` },
    { flag: "document-batches", href: "/document-batches", url: `${API}/api/admissions/documents/bulk-verify/eligibility` },
  ] as const

  const co = (nav: NavGroup[], href: string) => nav.some((g) => g.items.some((i) => i.href === href))

  /** Thân ĐÚNG hình dạng từng endpoint (cross-review/eligibility có thêm `grants`) — sai hình dạng sẽ ẩn mục vì lỗi
   * parse, làm ca "false ⇒ ẩn" xanh nhầm lý do. */
  const than = (flag: (typeof CO)[number]["flag"], eligible: boolean) =>
    HttpResponse.json(flag === "cross-review" ? { eligible, grants: [] } : { eligible })

  /** Cờ Hội đồng tắt hết (để các ca này chỉ đo cờ GĐ1b); hai endpoint GĐ1b theo `tra`. */
  function mocGd1b(tra: Partial<Record<(typeof CO)[number]["flag"], () => Response>>) {
    const dem: Record<string, number> = { "cross-review": 0, "document-batches": 0 }
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: TAT })))
    for (const c of CO) {
      server.use(
        http.get(c.url, () => {
          dem[c.flag] += 1
          const f = tra[c.flag]
          return f ? f() : than(c.flag, false)
        }),
      )
    }
    return dem
  }

  it("cấu hình: hai mục mang serverFlag và KHÔNG giới hạn vai (roles rỗng)", () => {
    const tat = navigationConfig.groups.flatMap((g) => g.items)
    for (const c of CO) {
      const muc = tat.find((i) => i.href === c.href)
      expect(muc?.serverFlag).toBe(c.flag)
      expect(muc?.roles ?? []).toEqual([])
    }
  })

  it.each(CO)("$flag: eligible = true ⇒ hiện mục", async (c) => {
    mocGd1b({ [c.flag]: () => than(c.flag, true) })
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(co(result.current, c.href)).toBe(true))
  })

  it.each(CO)("$flag: eligible = false ⇒ ẩn mục", async (c) => {
    const dem = mocGd1b({ [c.flag]: () => than(c.flag, false) })
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(dem[c.flag]).toBeGreaterThanOrEqual(1))
    await new Promise((r) => setTimeout(r, 30))
    expect(co(result.current, c.href)).toBe(false)
  })

  it.each(CO)("$flag: 403 ⇒ ẩn mục", async (c) => {
    const dem = mocGd1b({ [c.flag]: () => HttpResponse.json({ detail: "x" }, { status: 403 }) })
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(dem[c.flag]).toBeGreaterThanOrEqual(1))
    await new Promise((r) => setTimeout(r, 30))
    expect(co(result.current, c.href)).toBe(false)
  })

  it.each(CO)("$flag: 500 ⇒ ẩn mục (kể cả lúc đang thử lại)", async (c) => {
    const dem = mocGd1b({ [c.flag]: () => HttpResponse.json({ detail: "x" }, { status: 500 }) })
    const { result } = chay(navTheoVai())
    expect(co(result.current, c.href)).toBe(false)
    await waitFor(() => expect(dem[c.flag]).toBeGreaterThanOrEqual(1))
    await new Promise((r) => setTimeout(r, 30))
    expect(co(result.current, c.href)).toBe(false)
  })

  it.each(CO)("$flag: lỗi mạng ⇒ ẩn mục", async (c) => {
    const dem = mocGd1b({ [c.flag]: () => HttpResponse.error() })
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(dem[c.flag]).toBeGreaterThanOrEqual(1))
    await new Promise((r) => setTimeout(r, 30))
    expect(co(result.current, c.href)).toBe(false)
  })

  it("hai cờ độc lập: chỉ cross-review bật ⇒ chỉ hiện Duyệt chéo", async () => {
    mocGd1b({ "cross-review": () => than("cross-review", true) })
    const { result } = chay(navTheoVai())
    await waitFor(() => expect(co(result.current, "/cross-review")).toBe(true))
    expect(co(result.current, "/document-batches")).toBe(false)
  })

  it("không còn mục mang cờ GĐ1b ⇒ không hỏi hai endpoint eligibility", async () => {
    const dem = mocGd1b({})
    const khong = navTheoVai().map((g) => ({
      ...g,
      items: g.items.filter((i) => i.href !== "/cross-review" && i.href !== "/document-batches"),
    }))
    chay(khong)
    await new Promise((r) => setTimeout(r, 30))
    expect(dem).toEqual({ "cross-review": 0, "document-batches": 0 })
  })
})
