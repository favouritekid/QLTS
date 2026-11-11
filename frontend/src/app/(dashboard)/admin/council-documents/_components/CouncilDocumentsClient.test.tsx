/**
 * Văn bản Hội đồng — thẻ ẩn / hiện theo CỜ của máy chủ (lượt F), không theo vai.
 * API thật qua MSW (không mock hook): cờ tắt ⇒ thẻ / nút không có trong DOM.
 */
import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilDocumentPermissions } from "@/lib/zod/council-documents"

import { CouncilDocumentsClient } from "./CouncilDocumentsClient"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/council-documents",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
const TAT_CA: CouncilDocumentPermissions = Object.fromEntries(
  Object.keys(NO_COUNCIL_PERMISSIONS).map((k) => [k, true]),
) as CouncilDocumentPermissions

let nguoiTaoGoi = 0
const BO_MAU = {
  id: 5, nguoi_tao_id: 2, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z", unit_id: 3, trinh_do: "Cao đẳng",
  so_ho_so: 12, so_tep: 4, kich_thuoc_tong: 2048, nam_hoc: 2026, tham_so_quyet_dinh: null,
  nguoi_tao_ten: "Lê Thị Bảo", tinh_trang: "chua_ghi_nhan", quyet_dinh: null, luot_gui_cho: null,
}

function moc(co: CouncilDocumentPermissions | "403") {
  nguoiTaoGoi = 0
  server.use(
    http.get(`${API}${P}/quyen`, () =>
      co === "403"
        ? HttpResponse.json({ detail: "x", error_code: "PERMISSION_DENIED" }, { status: 403 })
        : HttpResponse.json({ permissions: co }),
    ),
    http.get(`${API}${P}/sets`, () => HttpResponse.json([BO_MAU])),
    http.get(`${API}/api/admissions/academic-years`, () => HttpResponse.json([2026])),
    http.get(`${API}${P}/nguoi-tao-bo`, () => {
      nguoiTaoGoi += 1
      return HttpResponse.json([{ id: 2, ten: "Lê Thị Bảo" }])
    }),
    http.get(`${API}${P}/templates`, () => HttpResponse.json([])),
    http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([])),
    http.get(`${API}${P}/nhat-ky-xoa`, () => HttpResponse.json([])),
  )
}

function ve() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilDocumentsClient />
    </QueryClientProvider>,
  )
}

const THE = ["bo", "tao", "mau", "nhat-ky-tai", "nhat-ky-xoa"] as const

describe("CouncilDocumentsClient — cờ quyết thẻ", () => {
  it("mọi cờ bật ⇒ đủ năm thẻ", async () => {
    moc(TAT_CA)
    ve()
    for (const t of THE) expect(await screen.findByTestId(`tab-${t}`)).toBeTruthy()
  })

  it("chỉ cờ đọc bộ (như quản lý) ⇒ chỉ thẻ Bộ văn bản; không Tạo bộ / Kho mẫu / nhật ký", async () => {
    moc({ ...NO_COUNCIL_PERMISSIONS, xem_danh_sach_bo: true, xem_chi_tiet_bo: true, tai_tep: true })
    ve()
    expect(await screen.findByTestId("tab-bo")).toBeTruthy()
    for (const t of THE.slice(1)) expect(screen.queryByTestId(`tab-${t}`)).toBeNull()
    expect(screen.queryByTestId("create-set-form")).toBeNull()
  })

  it("cờ tạo bộ tắt ⇒ không có form dựng bộ dù các cờ khác bật", async () => {
    moc({ ...TAT_CA, tao_bo: false })
    ve()
    expect(await screen.findByTestId("tab-bo")).toBeTruthy()
    expect(screen.queryByTestId("tab-tao")).toBeNull()
  })

  it("cờ tải mẫu tắt ⇒ thẻ Kho mẫu có danh sách nhưng không form tải", async () => {
    moc({ ...NO_COUNCIL_PERMISSIONS, xem_mau: true })
    ve()
    expect(await screen.findByTestId("tab-mau")).toBeTruthy()
    expect(await screen.findByTestId("template-list-empty")).toBeTruthy()
    expect(screen.queryByTestId("upload-template-form")).toBeNull()
  })

  // Nối dây cờ → danh sách (CLAUDE.md §10: gọi thẳng component con chỉ kiểm logic, không kiểm chỗ NỐI).
  it("cờ xem_nguoi_tao_bo bật ⇒ danh sách có bộ lọc 'Người tạo' và gọi GET /nguoi-tao-bo; tắt ⇒ không bộ lọc, KHÔNG gọi", async () => {
    moc({ ...NO_COUNCIL_PERMISSIONS, xem_danh_sach_bo: true, xem_chi_tiet_bo: true, xem_nguoi_tao_bo: true })
    const { unmount } = ve()
    expect(await screen.findByTestId("loc-nguoi-tao")).toBeTruthy()
    await screen.findByTestId("set-row-5")
    expect(nguoiTaoGoi).toBe(1)
    unmount()

    moc({ ...NO_COUNCIL_PERMISSIONS, xem_danh_sach_bo: true, xem_chi_tiet_bo: true, xem_nguoi_tao_bo: false })
    ve()
    await screen.findByTestId("set-row-5")
    expect(screen.queryByTestId("loc-nguoi-tao")).toBeNull()
    expect(nguoiTaoGoi).toBe(0)
  })

  it("cờ tai_ca_bo bật ⇒ mỗi dòng có nút 'Tải cả bộ'; tắt ⇒ không có", async () => {
    moc({ ...NO_COUNCIL_PERMISSIONS, xem_danh_sach_bo: true, xem_chi_tiet_bo: true, tai_ca_bo: true })
    const { unmount } = ve()
    expect(await screen.findByTestId("tai-ca-bo-5")).toBeTruthy()
    unmount()

    moc({ ...NO_COUNCIL_PERMISSIONS, xem_danh_sach_bo: true, xem_chi_tiet_bo: true, tai_ca_bo: false })
    ve()
    await screen.findByTestId("set-row-5")
    expect(screen.queryByTestId("tai-ca-bo-5")).toBeNull()
  })

  it("403 ở route cờ ⇒ báo không có quyền, không thẻ nào", async () => {
    moc("403")
    ve()
    expect(await screen.findByTestId("council-forbidden")).toBeTruthy()
    for (const t of THE) expect(screen.queryByTestId(`tab-${t}`)).toBeNull()
  })

  it("mọi cờ tắt (200) ⇒ báo không có quyền", async () => {
    moc(NO_COUNCIL_PERMISSIONS)
    ve()
    expect(await screen.findByTestId("council-forbidden")).toBeTruthy()
  })
})
