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

function moc(co: CouncilDocumentPermissions | "403") {
  server.use(
    http.get(`${API}${P}/quyen`, () =>
      co === "403"
        ? HttpResponse.json({ detail: "x", error_code: "PERMISSION_DENIED" }, { status: 403 })
        : HttpResponse.json({ permissions: co }),
    ),
    http.get(`${API}${P}/sets`, () => HttpResponse.json([])),
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
