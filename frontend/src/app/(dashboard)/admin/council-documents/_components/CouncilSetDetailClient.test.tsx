/**
 * Văn bản Hội đồng — chi tiết bộ (lượt F): nút theo CỜ (tải tệp, xoá, xem mã, nhật
 * ký), hộp xác nhận xoá nêu số hồ sơ / số tệp + bắt buộc lý do, danh sách mã đầu
 * vào chỉ trong bộ nhớ (ẩn ⇒ gỡ khỏi cache), không console / storage / URL. "Tải cả bộ" (máy chủ `083a428d`): cờ `tai_ca_bo`,
 * bấm ⇒ ĐÚNG bộ đang xem, ĐÚNG MỘT lần, lưu `bo-<id>.zip`; lỗi ⇒ hộp `download-zip-error`, không lưu tệp.
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS, councilDocumentKeys } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilDocumentPermissions } from "@/lib/zod/council-documents"

import { CouncilSetDetailClient } from "./CouncilSetDetailClient"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/admin/council-documents/7",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { downloadBlob } = vi.hoisted(() => ({ downloadBlob: vi.fn() }))
// Chặn điều hướng thật của jsdom; đồng thời cho test thấy ĐÚNG Blob + tên tệp đưa cho trình duyệt.
vi.mock("@/lib/utils/download-blob", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/utils/download-blob")>()),
  downloadBlob,
}))

const API = "http://localhost:8000"
const maGia = (n: number) => "099" + "999" + String(n).padStart(6, "0")
const MA = [maGia(7), maGia(3), maGia(5)]
const TAT_CA = Object.fromEntries(
  Object.keys(NO_COUNCIL_PERMISSIONS).map((k) => [k, true]),
) as CouncilDocumentPermissions
const QUAN_LY: CouncilDocumentPermissions = {
  ...NO_COUNCIL_PERMISSIONS,
  xem_danh_sach_bo: true,
  xem_chi_tiet_bo: true,
  tai_tep: true,
}

const BO = {
  id: 7, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z",
  unit_id: 2, trinh_do: "Cao đẳng", so_ho_so: 3, so_tep: 2, kich_thuoc_tong: 20, nam_hoc: 2026,
  tham_so_quyet_dinh: { so_quyet_dinh: "99", ngay_quyet_dinh: "2026-09-08" },
  thong_tin_dung: { luat: "v1.1" },
  // `GET /sets/{id}` (máy chủ `083a428d`): cùng hình với danh sách — bốn trường LUÔN có khoá.
  nguoi_tao_ten: "Trần Minh Khoa", tinh_trang: "chua_ghi_nhan", quyet_dinh: null, luot_gui_cho: null,
  tep: [
    { thu_tu: 1, path: "HoiDong/BienBanXetTuyen-CD.docx", sha256: "a".repeat(64), kich_thuoc: 10 },
    { thu_tu: 2, path: "HoiDong/QuyetDinhTrungTuyen-CD.docx", sha256: "b".repeat(64), kich_thuoc: 10 },
  ],
}

let console_: ReturnType<typeof vi.spyOn>[] = []
let xoaBody: unknown = null
let urls: string[] = []
let zipGoi: number[] = []
let zipTra: (() => Response) | null = null

function moc(co: CouncilDocumentPermissions) {
  server.use(
    http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: co })),
    http.get(`${API}${P}/sets/7`, ({ request }) => {
      urls.push(request.url)
      return HttpResponse.json(BO)
    }),
    http.get(`${API}${P}/sets/7/ma-ho-so`, ({ request }) => {
      urls.push(request.url)
      return HttpResponse.json({ set_id: 7, so_ho_so: 3, ma_ho_so: MA })
    }),
    http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([])),
    // Đúng hợp đồng `083a428d`: application/zip + attachment; filename="bo-<id>.zip" + no-store.
    http.get(`${API}${P}/sets/:id/tai-ca-bo`, ({ params }) => {
      zipGoi.push(Number(params.id))
      if (zipTra) return zipTra()
      return new HttpResponse(new Blob(["PK"]), {
        headers: {
          "content-type": "application/zip",
          "content-disposition": `attachment; filename="bo-${String(params.id)}.zip"`,
          "cache-control": "no-store",
        },
      })
    }),
    http.delete(`${API}${P}/sets/7`, async ({ request }) => {
      xoaBody = await request.json()
      return HttpResponse.json({
        id: 3, set_id: 7, so_ho_so: 3, so_tep: 2, danh_sach_tep: [], nguoi_xoa_id: 1,
        xoa_luc: "2026-11-05T02:00:00Z", ly_do: "GIA ly do", nguoi_xoa_ten: null,
      })
    }),
  )
}

function ve() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000, gcTime: 5 * 60 * 1000 } },
  })
  render(
    <QueryClientProvider client={qc}>
      <CouncilSetDetailClient setId={7} />
    </QueryClientProvider>,
  )
  return qc
}

beforeEach(() => {
  xoaBody = null
  urls = []
  zipGoi = []
  zipTra = null
  downloadBlob.mockClear()
  push.mockReset()
  localStorage.clear()
  sessionStorage.clear()
  console_ = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  )
})

describe("CouncilSetDetailClient — nút theo cờ", () => {
  it("admin (mọi cờ): tải tệp, xem mã, nhật ký tải, xoá", async () => {
    moc(TAT_CA)
    ve()
    expect(await screen.findByTestId("set-detail")).toBeTruthy()
    expect(screen.getByTestId("download-file-1")).toBeTruthy()
    expect(screen.getByTestId("input-codes-section")).toBeTruthy()
    expect(screen.getByTestId("delete-set-open")).toBeTruthy()
    expect(await screen.findByTestId("download-log-empty")).toBeTruthy()
  })

  it("quản lý (cờ đọc bộ): tải tệp được; KHÔNG xoá, KHÔNG xem mã, KHÔNG nhật ký", async () => {
    moc(QUAN_LY)
    ve()
    expect(await screen.findByTestId("set-detail")).toBeTruthy()
    expect(screen.getByTestId("download-file-2")).toBeTruthy()
    expect(screen.queryByTestId("input-codes-section")).toBeNull()
    expect(screen.queryByTestId("delete-set-open")).toBeNull()
    expect(screen.queryByTestId("download-log")).toBeNull()
    expect(screen.queryByTestId("download-log-empty")).toBeNull()
  })

  it("cờ tải tệp tắt ⇒ không nút tải", async () => {
    moc({ ...QUAN_LY, tai_tep: false })
    ve()
    expect(await screen.findByTestId("set-detail")).toBeTruthy()
    expect(screen.queryByTestId("download-file-1")).toBeNull()
  })

  it("cờ xem chi tiết tắt ⇒ không gọi API chi tiết", async () => {
    moc({ ...QUAN_LY, xem_chi_tiet_bo: false })
    ve()
    expect(await screen.findByTestId("council-forbidden")).toBeTruthy()
    expect(urls).toEqual([])
  })
})

/** jsdom: `Blob` không có `.text()` — đọc nội dung bằng FileReader. */
const docBlob = (b: Blob) =>
  new Promise<string>((xong, loi) => {
    const r = new FileReader()
    r.onload = () => xong(String(r.result))
    r.onerror = () => loi(r.error)
    r.readAsText(b)
  })

describe("Tải cả bộ (cờ tai_ca_bo)", () => {
  it("cờ tắt ⇒ không có nút", async () => {
    moc({ ...QUAN_LY, tai_ca_bo: false })
    ve()
    expect(await screen.findByTestId("set-detail")).toBeTruthy()
    expect(screen.queryByTestId("tai-ca-bo")).toBeNull()
  })

  it("cờ bật: bấm ⇒ gọi ĐÚNG bộ đang xem (7) MỘT lần; hàm lưu tệp nhận Blob có byte máy chủ + tên bo-7.zip", async () => {
    moc({ ...QUAN_LY, tai_ca_bo: true })
    ve()
    const nut = await screen.findByTestId("tai-ca-bo")
    expect(nut.textContent).toContain("2 tệp")
    fireEvent.click(nut)
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1))
    expect(zipGoi).toEqual([7])
    const [blob, ten] = downloadBlob.mock.calls[0] as [Blob, string]
    expect(blob).toBeInstanceOf(Blob)
    expect(await docBlob(blob)).toBe("PK")
    expect(ten).toBe("bo-7.zip")
    expect(screen.queryByTestId("download-zip-error")).toBeNull()
  })

  it("máy chủ báo lỗi (tệp hỏng ⇒ 500) ⇒ hộp download-zip-error, KHÔNG lưu tệp nào, gọi đúng một lần", async () => {
    moc({ ...QUAN_LY, tai_ca_bo: true })
    zipTra = () => HttpResponse.json({ detail: "Tệp đã lưu hỏng" }, { status: 500 })
    ve()
    fireEvent.click(await screen.findByTestId("tai-ca-bo"))
    expect((await screen.findByTestId("download-zip-error")).textContent).toContain("Lỗi hệ thống")
    expect(downloadBlob).not.toHaveBeenCalled()
    expect(zipGoi).toEqual([7])
  })

  it("Quản lý ngoài đơn vị ⇒ 404 ⇒ câu 'Không tìm thấy' trong download-zip-error, KHÔNG lưu tệp nào", async () => {
    moc({ ...QUAN_LY, tai_ca_bo: true })
    zipTra = () => HttpResponse.json({ detail: "Not Found" }, { status: 404 })
    ve()
    fireEvent.click(await screen.findByTestId("tai-ca-bo"))
    expect((await screen.findByTestId("download-zip-error")).textContent).toContain("Không tìm thấy")
    expect(downloadBlob).not.toHaveBeenCalled()
  })
})

describe("xoá bộ — hộp xác nhận", () => {
  it("nêu số hồ sơ / số tệp; lý do bắt buộc; gửi lý do; xong ⇒ về danh sách", async () => {
    moc(TAT_CA)
    ve()
    fireEvent.click(await screen.findByTestId("delete-set-open"))
    expect((await screen.findByTestId("delete-set-summary")).textContent).toMatch(/3 hồ sơ, 2 tệp/)
    const nut = screen.getByTestId("delete-set-confirm") as HTMLButtonElement
    expect(nut.disabled).toBe(true)
    fireEvent.change(screen.getByTestId("delete-set-reason"), { target: { value: "   " } })
    expect(nut.disabled).toBe(true)
    fireEvent.change(screen.getByTestId("delete-set-reason"), { target: { value: "GIA dựng nhầm" } })
    expect(nut.disabled).toBe(false)
    fireEvent.click(nut)
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents"))
    expect(xoaBody).toEqual({ ly_do: "GIA dựng nhầm" })
  })
})

describe("danh sách mã đầu vào — chỉ trong bộ nhớ", () => {
  it("chỉ tải khi bấm Hiện; đúng thứ tự; Ẩn ⇒ gỡ khỏi cache; không console / storage / URL", async () => {
    moc(TAT_CA)
    const qc = ve()
    fireEvent.click(await screen.findByTestId("input-codes-toggle"))
    const ds = await screen.findByTestId("input-codes")
    expect(Array.from(ds.querySelectorAll("li")).map((li) => li.textContent)).toEqual(MA)
    expect(urls.filter((u) => u.endsWith("/ma-ho-so"))).toHaveLength(1)
    fireEvent.click(screen.getByTestId("input-codes-toggle")) // Ẩn
    await waitFor(() => expect(screen.queryByTestId("input-codes")).toBeNull())
    await waitFor(() =>
      expect(qc.getQueryCache().find({ queryKey: councilDocumentKeys.inputCodes(7) })).toBeUndefined(),
    )
    const toanBo = JSON.stringify({
      cache: qc.getQueryCache().getAll().map((q) => q.state.data),
      c: console_.map((s) => s.mock.calls),
      l: { ...localStorage },
      s: { ...sessionStorage },
      href: window.location.href,
      push: push.mock.calls,
      urls,
    })
    for (const m of MA) expect(toanBo.includes(m), "mã giả còn ngoài DOM sau khi ẩn").toBe(false)
  })
})
