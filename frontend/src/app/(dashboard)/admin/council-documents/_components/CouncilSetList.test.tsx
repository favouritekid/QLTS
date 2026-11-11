/**
 * Danh sách bộ văn bản (đặc tả 5.7, 3.4): cột, tình trạng do MÁY CHỦ trả, bộ lọc gửi lên máy chủ, "Mở" bộ chưa rõ ⇒ thẳng
 * bước 6, "Tải cả bộ" theo cờ. Trường máy chủ chưa trả (⏳) ⇒ "—", không suy.
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"

import { CouncilSetList } from "./CouncilSetList"

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
const goc = (id: number, extra: Record<string, unknown> = {}) => ({
  id, nguoi_tao_id: 2, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z", unit_id: null,
  trinh_do: "Cao đẳng", so_ho_so: 12, so_tep: 4, kich_thuoc_tong: 2048, nam_hoc: 2026, tham_so_quyet_dinh: null, ...extra,
})

let queries: URLSearchParams[] = []
let zipGoi: number[] = []

function dung(ds: unknown[]) {
  queries = []
  zipGoi = []
  server.use(
    http.get(`${API}/api/admissions/academic-years`, () => HttpResponse.json([2026, 2025])),
    http.get(`${API}${P}/sets`, ({ request }) => {
      queries.push(new URL(request.url).searchParams)
      return HttpResponse.json(ds)
    }),
    http.get(`${API}${P}/sets/:id/tai-ca-bo`, ({ params }) => {
      zipGoi.push(Number(params.id))
      return new HttpResponse(new Blob(["PK"]), { headers: { "content-type": "application/zip", "content-disposition": 'attachment; filename="bo-5.zip"' } })
    }),
  )
}

function ve(props: { canOpenDetail?: boolean; canZip?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilSetList canOpenDetail={props.canOpenDetail ?? true} canZip={props.canZip} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined)
  URL.createObjectURL = vi.fn(() => "blob:x")
  URL.revokeObjectURL = vi.fn()
})

describe("CouncilSetList", () => {
  it("máy chủ chưa trả tình trạng / Quyết định / tên người tạo (⏳) ⇒ '—' và 'Tài khoản #n', không suy", async () => {
    dung([goc(5)])
    ve()
    const dong = await screen.findByTestId("set-row-5")
    expect(within(dong).getByTestId("tt-5").textContent).toBe("—")
    expect(within(dong).getByTestId("qd-5").textContent).toBe("—")
    expect(dong.textContent).toContain("Tài khoản #2")
  })

  it("tình trạng + Quyết định + tên người tạo do máy chủ trả ⇒ hiện đúng; 'Chưa ghi nhận' kèm chú thích nghĩa của nó", async () => {
    dung([
      goc(5, { tinh_trang: "con_hieu_luc", nguoi_tao_ten: "Trần Minh Khoa", quyet_dinh: { so_quyet_dinh: "90", ngay_ky: "2026-10-20", goc: { so_quyet_dinh: "50", ngay_ky: "2026-09-08" } } }),
      goc(6, { tinh_trang: "chua_ghi_nhan" }),
    ])
    ve()
    const d5 = await screen.findByTestId("set-row-5")
    expect(within(d5).getByTestId("tt-5").textContent).toBe("Còn hiệu lực")
    expect(within(d5).getByTestId("qd-5").textContent).toContain("Số 90 · 20/10/2026")
    expect(within(d5).getByTestId("qd-5").textContent).toContain("bổ sung cho số 50")
    expect(d5.textContent).toContain("Trần Minh Khoa")
    const t6 = within(screen.getByTestId("set-row-6")).getByTestId("tt-6").textContent ?? ""
    expect(t6).toContain("Chưa ghi nhận")
    expect(t6).toContain("không có nghĩa là giấy chưa ký")
  })

  it("bộ có lượt gửi chờ / tình trạng chua_xac_dinh ⇒ chỉ 'Chưa xác định' (không 'chưa ghi nhận'); 'Mở' vào thẳng bước 6", async () => {
    dung([
      goc(5, { tinh_trang: "chua_ghi_nhan", luot_gui_cho: { ma: "11111111-2222-3333-4444-555555555555", tao_luc: "2026-11-11T01:00:00Z" } }),
      goc(6, { tinh_trang: "chua_xac_dinh" }),
      goc(7, { tinh_trang: "con_hieu_luc" }),
    ])
    ve()
    await screen.findByTestId("set-row-5")
    for (const id of [5, 6]) {
      const t = screen.getByTestId(`tt-${id}`).textContent ?? ""
      expect(t).toBe("Chưa xác định")
      expect(t).not.toMatch(/chưa ghi nhận/i)
      expect(screen.getByTestId(`mo-bo-${id}`).getAttribute("href")).toBe(`/admin/council-documents/${id}?buoc=ghi-nhan`)
    }
    expect(screen.getByTestId("mo-bo-7").getAttribute("href")).toBe("/admin/council-documents/7")
  })

  it("không có quyền xem chi tiết ⇒ không nút Mở", async () => {
    dung([goc(5)])
    ve({ canOpenDetail: false })
    await screen.findByTestId("set-row-5")
    expect(screen.queryByTestId("mo-bo-5")).toBeNull()
  })

  it("bộ lọc: chỉ gửi tham số khi người dùng đặt; số Quyết định chỉ nhận chữ số", async () => {
    dung([goc(5)])
    ve()
    await screen.findByTestId("set-row-5")
    expect(queries[0].get("limit")).toBe("50")
    expect(queries[0].has("so_quyet_dinh")).toBe(false)
    expect(queries[0].has("nam_hoc")).toBe(false)
    expect(queries[0].has("tinh_trang")).toBe(false)

    fireEvent.change(screen.getByTestId("loc-so-qd"), { target: { value: "9a0" } })
    expect((screen.getByTestId("loc-so-qd") as HTMLInputElement).value).toBe("90")
    fireEvent.change(await screen.findByTestId("loc-nam-bo"), { target: { value: "2026" } })
    fireEvent.change(screen.getByTestId("loc-tinh-trang"), { target: { value: "chua_xac_dinh" } })
    await waitFor(() => {
      const q = queries.at(-1)!
      expect(q.get("so_quyet_dinh")).toBe("90")
      expect(q.get("nam_hoc")).toBe("2026")
      expect(q.get("tinh_trang")).toBe("chua_xac_dinh")
    }, { timeout: 3000 })
  })

  it("danh sách rỗng khi đang lọc ⇒ nói không có bộ khớp bộ lọc", async () => {
    dung([])
    ve()
    expect((await screen.findByTestId("set-list-empty")).textContent).toContain("Chưa có bộ văn bản nào")
    fireEvent.change(screen.getByTestId("loc-tinh-trang"), { target: { value: "con_hieu_luc" } })
    await waitFor(() => expect(screen.getByTestId("set-list-empty").textContent).toContain("Không có bộ nào khớp bộ lọc"))
  })

  it("'Tải cả bộ' CHỈ khi có cờ tai_ca_bo; bấm gọi đúng bộ", async () => {
    dung([goc(5)])
    const { unmount } = ve({ canZip: false })
    await screen.findByTestId("set-row-5")
    expect(screen.queryByTestId("tai-ca-bo-5")).toBeNull()
    unmount()
    ve({ canZip: true })
    fireEvent.click(await screen.findByTestId("tai-ca-bo-5"))
    await waitFor(() => expect(zipGoi).toEqual([5]))
  })
})
