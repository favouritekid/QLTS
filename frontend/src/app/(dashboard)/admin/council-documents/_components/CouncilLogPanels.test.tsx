/**
 * Nhật ký tải / xoá (đặc tả 5.7, máy chủ `083a428d`): hiện TÊN người máy chủ trả (`nguoi_tai_ten` / `nguoi_xoa_ten`, LUÔN có
 * khoá); `null` (tài khoản không còn) ⇒ giữ "Tài khoản #n" (không bịa tên).
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"

import { CouncilDeletionLogPanel, CouncilDownloadLogPanel } from "./CouncilLogPanels"

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))

const API = "http://localhost:8000"
function ve(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
}

beforeEach(() => vi.spyOn(console, "error").mockImplementation(() => undefined))

describe("nhật ký — tên người", () => {
  it("nhật ký tải: có tên ⇒ tên; chưa có ⇒ 'Tài khoản #n'", async () => {
    server.use(
      http.get(`${API}${P}/nhat-ky-tai`, () =>
        HttpResponse.json([
          { id: 1, set_id: 5, thu_tu: 1, path: "a.docx", sha256: "a".repeat(64), nguoi_tai_id: 2, tai_luc: "2026-11-05T01:00:00Z", nguoi_tai_ten: "Lê Thu Hạnh" },
          { id: 2, set_id: 5, thu_tu: 2, path: "b.docx", sha256: "b".repeat(64), nguoi_tai_id: 3, tai_luc: "2026-11-05T01:00:00Z", nguoi_tai_ten: null },
        ]),
      ),
    )
    ve(<CouncilDownloadLogPanel />)
    expect(await screen.findByText("Lê Thu Hạnh")).toBeTruthy()
    expect(screen.getByText("Tài khoản #3")).toBeTruthy()
    expect(screen.queryByText("Tài khoản #2")).toBeNull()
  })

  it("nhật ký xoá: có tên ⇒ tên; chưa có ⇒ 'Tài khoản #n'", async () => {
    server.use(
      http.get(`${API}${P}/nhat-ky-xoa`, () =>
        HttpResponse.json([
          { id: 1, set_id: 5, so_ho_so: 3, so_tep: 2, danh_sach_tep: [], nguoi_xoa_id: 2, xoa_luc: "2026-11-05T01:00:00Z", ly_do: "x", nguoi_xoa_ten: "Quản trị Thử" },
          { id: 2, set_id: 6, so_ho_so: 1, so_tep: 2, danh_sach_tep: [], nguoi_xoa_id: 4, xoa_luc: "2026-11-05T01:00:00Z", ly_do: "y", nguoi_xoa_ten: null },
        ]),
      ),
    )
    ve(<CouncilDeletionLogPanel />)
    expect(await screen.findByText("Quản trị Thử")).toBeTruthy()
    expect(screen.getByText("Tài khoản #4")).toBeTruthy()
  })
})
