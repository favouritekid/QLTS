/**
 * Danh sách bộ văn bản (đặc tả 5.7, 3.4 — máy chủ `083a428d`): cột, tình trạng do MÁY CHỦ trả, bốn bộ lọc LỌC Ở MÁY CHỦ
 * (số Quyết định / năm học / tình trạng / người tạo), "Mở" bộ chưa rõ ⇒ thẳng bước 6, "Tải cả bộ" theo cờ.
 * Bốn trường mới (`nguoi_tao_ten`, `tinh_trang`, `quyet_dinh`, `luot_gui_cho`) LUÔN có khoá; `null` ⇒ "—", không suy.
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"

import { CouncilSetList } from "./CouncilSetList"

const { downloadBlob } = vi.hoisted(() => ({ downloadBlob: vi.fn() }))
// Chặn điều hướng thật của jsdom (`link.click()` trên thẻ <a download> ⇒ "Not implemented: navigation"): hàm lưu tệp bị
// thay bằng spy, nên test khẳng định được ĐÚNG Blob + tên tệp mà giao diện đưa cho trình duyệt.
vi.mock("@/lib/utils/download-blob", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/utils/download-blob")>()),
  downloadBlob,
}))
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
/** Một bộ đúng hình `GET /sets` của máy chủ `083a428d` (mặc định: chưa ghi nhận, không Quyết định, không lượt chờ). */
const goc = (id: number, extra: Record<string, unknown> = {}) => ({
  id, nguoi_tao_id: 2, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z", unit_id: null,
  trinh_do: "Cao đẳng", so_ho_so: 12, so_tep: 4, kich_thuoc_tong: 2048, nam_hoc: 2026, tham_so_quyet_dinh: null,
  nguoi_tao_ten: null, tinh_trang: "chua_ghi_nhan", quyet_dinh: null, luot_gui_cho: null, ...extra,
})
const QD = (so: string, goc_: unknown = null) => ({
  id: 21, loai: "trung_tuyen", trang_thai: "hieu_luc", so_quyet_dinh: so, ngay_ky: "2026-10-20", so_ho_so: 12, goc: goc_,
})

let queries: URLSearchParams[] = []
let zipGoi: number[] = []
let nguoiTaoGoi = 0

interface Cau {
  nguoiTao?: () => Response
  zip?: () => Response
}
function dung(ds: unknown[], cau: Cau = {}) {
  queries = []
  zipGoi = []
  nguoiTaoGoi = 0
  server.use(
    http.get(`${API}/api/admissions/academic-years`, () => HttpResponse.json([2026, 2025])),
    http.get(`${API}${P}/sets`, ({ request }) => {
      queries.push(new URL(request.url).searchParams)
      return HttpResponse.json(ds)
    }),
    http.get(`${API}${P}/nguoi-tao-bo`, () => {
      nguoiTaoGoi += 1
      return cau.nguoiTao ? cau.nguoiTao() : HttpResponse.json([{ id: 7, ten: "Lê Thị Bảo" }, { id: 9, ten: "Trần Minh Khoa" }])
    }),
    // Đúng hợp đồng `083a428d`: application/zip + attachment; filename="bo-<id>.zip" + no-store.
    http.get(`${API}${P}/sets/:id/tai-ca-bo`, ({ params }) => {
      zipGoi.push(Number(params.id))
      if (cau.zip) return cau.zip()
      return new HttpResponse(new Blob(["PK"]), {
        headers: {
          "content-type": "application/zip",
          "content-disposition": `attachment; filename="bo-${String(params.id)}.zip"`,
          "cache-control": "no-store",
        },
      })
    }),
  )
}

function ve(props: { canOpenDetail?: boolean; canZip?: boolean; canFilterCreator?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilSetList canOpenDetail={props.canOpenDetail ?? true} canZip={props.canZip} canFilterCreator={props.canFilterCreator} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  downloadBlob.mockClear()
  vi.spyOn(console, "error").mockImplementation(() => undefined)
})

/** jsdom: `Blob` không có `.text()` — đọc nội dung bằng FileReader. */
const docBlob = (b: Blob) =>
  new Promise<string>((xong, loi) => {
    const r = new FileReader()
    r.onload = () => xong(String(r.result))
    r.onerror = () => loi(r.error)
    r.readAsText(b)
  })

describe("CouncilSetList", () => {
  it("bộ vừa dựng (tình trạng / Quyết định / tên người tạo đều null) ⇒ '—' và 'Tài khoản #n', không suy", async () => {
    dung([goc(5, { tinh_trang: null })])
    ve()
    const dong = await screen.findByTestId("set-row-5")
    expect(within(dong).getByTestId("tt-5").textContent).toBe("—")
    expect(within(dong).getByTestId("qd-5").textContent).toBe("—")
    expect(dong.textContent).toContain("Tài khoản #2")
  })

  it("tình trạng + Quyết định + tên người tạo do máy chủ trả ⇒ hiện đúng; 'Chưa ghi nhận' kèm chú thích nghĩa của nó", async () => {
    dung([
      goc(5, { tinh_trang: "con_hieu_luc", nguoi_tao_ten: "Trần Minh Khoa", quyet_dinh: QD("90", { id: 3, so_quyet_dinh: "50", ngay_ky: "2026-09-08" }) }),
      goc(6, { tinh_trang: "chua_ghi_nhan" }),
    ])
    ve()
    const d5 = await screen.findByTestId("set-row-5")
    expect(within(d5).getByTestId("tt-5").textContent).toBe("Còn hiệu lực")
    expect(within(d5).getByTestId("qd-5").textContent).toContain("Số 90 · 20/10/2026")
    expect(within(d5).getByTestId("qd-5").textContent).toContain("bổ sung cho số 50 (08/09/2026)")
    expect(d5.textContent).toContain("Trần Minh Khoa")
    const t6 = within(screen.getByTestId("set-row-6")).getByTestId("tt-6").textContent ?? ""
    expect(t6).toContain("Chưa ghi nhận")
    expect(t6).toContain("không có nghĩa là giấy chưa ký")
  })

  it("bộ có lượt gửi chờ / tình trạng chua_xac_dinh ⇒ chỉ 'Chưa xác định' (không 'chưa ghi nhận'); 'Mở' vào thẳng bước 6", async () => {
    dung([
      goc(5, { tinh_trang: "chua_ghi_nhan", luot_gui_cho: { ma: "11111111-2222-3333-4444-555555555555", tao_luc: "2026-11-11T01:00:00Z" } }),
      // Quản lý: `luot_gui_cho` luôn null kể cả khi tình trạng là chua_xac_dinh — nhãn vẫn phải là "Chưa xác định".
      goc(6, { tinh_trang: "chua_xac_dinh", luot_gui_cho: null }),
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

  it("máy chủ bỏ khoá luot_gui_cho (hợp đồng gãy) ⇒ hộp lỗi, KHÔNG hiện danh sách như thể không có lượt chờ", async () => {
    const { luot_gui_cho: _bo, ...thieu } = goc(5)
    dung([thieu])
    ve()
    expect(await screen.findByTestId("set-list-error")).toBeTruthy()
    expect(screen.queryByTestId("set-row-5")).toBeNull()
  })

  it("bộ lọc: chỉ gửi tham số khi người dùng đặt; số Quyết định chỉ nhận chữ số", async () => {
    dung([goc(5)])
    ve()
    await screen.findByTestId("set-row-5")
    expect(queries[0].get("limit")).toBe("50")
    expect(queries[0].has("so_quyet_dinh")).toBe(false)
    expect(queries[0].has("nam_hoc")).toBe(false)
    expect(queries[0].has("tinh_trang")).toBe(false)
    expect(queries[0].has("nguoi_tao_id")).toBe(false)

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

  describe("bộ lọc 'Người tạo' (cờ xem_nguoi_tao_bo)", () => {
    it("không có cờ ⇒ không hiện bộ lọc và KHÔNG gọi GET /nguoi-tao-bo (Casbin sẽ 403)", async () => {
      dung([goc(5)])
      ve({ canFilterCreator: false })
      await screen.findByTestId("set-row-5")
      await new Promise((r) => setTimeout(r, 80))
      expect(screen.queryByTestId("loc-nguoi-tao")).toBeNull()
      expect(nguoiTaoGoi).toBe(0)
    })

    it("có cờ ⇒ chọn từ danh sách máy chủ trả (tên người) ⇒ gửi nguoi_tao_id ĐÚNG id đã chọn (đổi người ⇒ id mới); lần đầu (Tất cả) KHÔNG có tham số", async () => {
      dung([goc(5)])
      ve({ canFilterCreator: true })
      await screen.findByTestId("set-row-5")
      expect(queries[0].has("nguoi_tao_id")).toBe(false)
      const chon = (await screen.findByTestId("loc-nguoi-tao")) as HTMLSelectElement
      await waitFor(() => expect(chon.options.length).toBe(3))
      expect([...chon.options].map((o) => o.textContent)).toEqual(["Tất cả", "Lê Thị Bảo", "Trần Minh Khoa"])
      expect(nguoiTaoGoi).toBe(1)

      fireEvent.change(chon, { target: { value: "9" } })
      await waitFor(() => expect(queries.at(-1)!.get("nguoi_tao_id")).toBe("9"))
      fireEvent.change(chon, { target: { value: "7" } })
      await waitFor(() => expect(queries.at(-1)!.get("nguoi_tao_id")).toBe("7"))
    })

    it("danh sách người tạo lỗi ⇒ bộ lọc tắt kèm lời nói rõ, DANH SÁCH BỘ vẫn hiện", async () => {
      dung([goc(5)], { nguoiTao: () => HttpResponse.json({ detail: "lỗi" }, { status: 500 }) })
      ve({ canFilterCreator: true })
      expect(await screen.findByTestId("loc-nguoi-tao-loi")).toBeTruthy()
      expect((screen.getByTestId("loc-nguoi-tao") as HTMLSelectElement).disabled).toBe(true)
      expect(screen.getByTestId("set-row-5")).toBeTruthy()
    })
  })

  describe("'Tải cả bộ'", () => {
    it("CHỈ khi có cờ tai_ca_bo", async () => {
      dung([goc(5)])
      ve({ canZip: false })
      await screen.findByTestId("set-row-5")
      expect(screen.queryByTestId("tai-ca-bo-5")).toBeNull()
    })

    it("bấm ⇒ gọi đúng bộ MỘT lần; hàm lưu tệp nhận một Blob có byte của máy chủ + tên bo-5.zip (không còn điều hướng thật của jsdom)", async () => {
      dung([goc(5), goc(6)])
      ve({ canZip: true })
      fireEvent.click(await screen.findByTestId("tai-ca-bo-6"))
      await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1))
      expect(zipGoi).toEqual([6])
      const [blob, ten] = downloadBlob.mock.calls[0] as [Blob, string]
      expect(blob).toBeInstanceOf(Blob)
      expect(await docBlob(blob)).toBe("PK")
      expect(ten).toBe("bo-6.zip")
    })

    it("máy chủ báo lỗi (tệp hỏng ⇒ 500, không zip) ⇒ hiện câu lỗi hệ thống cố định, KHÔNG lưu tệp nào", async () => {
      dung([goc(5)], { zip: () => HttpResponse.json({ detail: "Tệp đã lưu hỏng — không trả bộ." }, { status: 500 }) })
      ve({ canZip: true })
      fireEvent.click(await screen.findByTestId("tai-ca-bo-5"))
      const loi = await screen.findByTestId("set-list-zip-error")
      expect(loi.textContent).toContain("Lỗi hệ thống")
      expect(downloadBlob).not.toHaveBeenCalled()
      expect(zipGoi).toEqual([5])
    })

    it("Quản lý ngoài đơn vị ⇒ 404 ⇒ câu 'Không tìm thấy', KHÔNG lưu tệp nào", async () => {
      dung([goc(5)], { zip: () => HttpResponse.json({ detail: "Not Found" }, { status: 404 }) })
      ve({ canZip: true })
      fireEvent.click(await screen.findByTestId("tai-ca-bo-5"))
      expect((await screen.findByTestId("set-list-zip-error")).textContent).toContain("Không tìm thấy")
      expect(downloadBlob).not.toHaveBeenCalled()
    })
  })
})
