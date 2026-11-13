/**
 * Văn bản Hội đồng — form dựng bộ (lượt F): giữ thứ tự + số dòng, lỗi máy chủ
 * nguyên văn, 409 / 503, chống bấm đúp; danh sách mã KHÔNG ra console / storage /
 * URL. API thật qua MSW. Mã giả sinh lúc chạy (tỉnh 099 không tồn tại).
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse, delay } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { dap, luatTaoBo } from "@/test/mocks/council-luat-may-chu"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"

import { CreateCouncilSetForm, dongNhapThanhDanhSach } from "./CreateCouncilSetForm"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/admin/council-documents",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
const maGia = (n: number) => "099" + "999" + String(n).padStart(6, "0")
const MA = [maGia(30), maGia(10), maGia(20)]

let console_: ReturnType<typeof vi.spyOn>[] = []
let bodies: unknown[] = []
let urls: string[] = []

const BO = {
  id: 21, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T01:00:00Z",
  unit_id: 2, trinh_do: "Cao đẳng", so_ho_so: 3, so_tep: 2, kich_thuoc_tong: 9, nam_hoc: 2026,
  tham_so_quyet_dinh: null, thong_tin_dung: {}, tep: [],
  nguoi_tao_ten: null, tinh_trang: null, quyet_dinh: null, luot_gui_cho: null,
}

function mocPost(tra: () => Response | Promise<Response>) {
  server.use(
    http.post(`${API}${P}/sets`, async ({ request }) => {
      urls.push(request.url)
      bodies.push(await request.clone().json())
      return tra()
    }),
    http.get(`${API}${P}/sets`, ({ request }) => {
      urls.push(request.url)
      return HttpResponse.json([])
    }),
  )
}

function ve(canOpenDetail = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 5 * 60 * 1000 }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={qc}>
      <CreateCouncilSetForm canOpenDetail={canOpenDetail} />
    </QueryClientProvider>,
  )
  return qc
}

function nhap(vanBan: string, nam = "2026") {
  fireEvent.change(screen.getByTestId("ma-ho-so-input"), { target: { value: vanBan } })
  fireEvent.change(screen.getByTestId("nam-hoc-input"), { target: { value: nam } })
}

function khongMaRaNgoai() {
  const ngoai = JSON.stringify({
    c: console_.map((s) => s.mock.calls),
    l: { ...localStorage },
    s: { ...sessionStorage },
    href: window.location.href,
    push: push.mock.calls,
    urls,
  })
  for (const m of MA) expect(ngoai.includes(m), "mã giả lọt ra console / storage / URL").toBe(false)
}

beforeEach(() => {
  bodies = []
  urls = []
  push.mockReset()
  localStorage.clear()
  sessionStorage.clear()
  console_ = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  )
})

describe("dongNhapThanhDanhSach — giữ thứ tự VÀ số dòng", () => {
  it("giữ dòng trống ở giữa, bỏ dòng trống ở CUỐI, không tự sửa mã", () => {
    expect(dongNhapThanhDanhSach(`${MA[0]}\r\n\n ${MA[1]} \n${MA[2]}\n\n  \n`)).toEqual([
      MA[0],
      "",
      ` ${MA[1]} `,
      MA[2],
    ])
    expect(dongNhapThanhDanhSach("")).toEqual([])
  })
})

describe("CreateCouncilSetForm", () => {
  it("gửi đúng thứ tự + năm học số; không tham số khi không điền; thành công ⇒ sang trang bộ", async () => {
    mocPost(() => HttpResponse.json(BO, { status: 201 }))
    ve()
    nhap(MA.join("\n") + "\n")
    fireEvent.click(screen.getByTestId("create-set-submit"))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents/21"))
    expect(bodies).toEqual([{ ma_ho_so: MA, academic_year: 2026 }])
    expect((screen.getByTestId("ma-ho-so-input") as HTMLTextAreaElement).value).toBe("") // xoá sau khi xong
    khongMaRaNgoai()
  })

  it("tham số Quyết định: chỉ gửi ô đã điền", async () => {
    mocPost(() => HttpResponse.json(BO, { status: 201 }))
    ve()
    nhap(MA[0])
    fireEvent.click(screen.getByTestId("tham-so-toggle"))
    fireEvent.change(screen.getByLabelText("Số Quyết định"), { target: { value: "1844" } })
    fireEvent.change(screen.getByLabelText("Ngày Quyết định"), { target: { value: "2026-09-08" } })
    fireEvent.click(screen.getByTestId("create-set-submit"))
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      ma_ho_so: [MA[0]],
      academic_year: 2026,
      tham_so_quyet_dinh: { so_quyet_dinh: "1844", ngay_quyet_dinh: "2026-09-08" },
    })
  })

  it("chống bấm đúp: nút khoá khi đang gửi ⇒ đúng MỘT POST", async () => {
    mocPost(async () => {
      await delay(150)
      return HttpResponse.json(BO, { status: 201 })
    })
    ve()
    nhap(MA.join("\n"))
    const nut = screen.getByTestId("create-set-submit")
    fireEvent.click(nut)
    await waitFor(() => expect(bodies).toHaveLength(1)) // POST đầu đã tới máy chủ, còn treo 150 ms
    fireEvent.click(nut) // bấm lại trong lúc đang gửi
    fireEvent.submit(screen.getByTestId("create-set-form")) // Enter trong form
    await waitFor(() => expect(push).toHaveBeenCalled())
    expect(bodies).toHaveLength(1)
    expect((nut as HTMLButtonElement).disabled).toBe(true) // xong ⇒ ô nhập đã xoá ⇒ nút khoá
  })

  it("nút khoá khi chưa có mã hoặc năm học", () => {
    ve()
    expect((screen.getByTestId("create-set-submit") as HTMLButtonElement).disabled).toBe(true)
    nhap("\n\n", "2026")
    expect((screen.getByTestId("create-set-submit") as HTMLButtonElement).disabled).toBe(true)
    nhap(MA[0], "")
    expect((screen.getByTestId("create-set-submit") as HTMLButtonElement).disabled).toBe(true)
  })

  it("400 theo số dòng: hiện NGUYÊN VĂN câu máy chủ, giữ ô nhập", async () => {
    const d = "Dòng 2: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số (CMND), chỉ chữ số 0-9."
    mocPost(() => HttpResponse.json({ detail: d, error_code: "DATA_VALIDATION_ERROR" }, { status: 400 }))
    ve()
    nhap(MA.join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    expect((await screen.findByTestId("council-error-detail")).textContent).toBe(d)
    expect((screen.getByTestId("ma-ho-so-input") as HTMLTextAreaElement).value).toBe(MA.join("\n"))
    expect(push).not.toHaveBeenCalled()
    khongMaRaNgoai()
  })

  it("409 đang dựng bộ khác: hiện câu máy chủ", async () => {
    const d = "Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại."
    mocPost(() => HttpResponse.json({ detail: d, error_code: "CONFLICT" }, { status: 409 }))
    ve()
    nhap(MA.join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    expect((await screen.findByTestId("council-error-detail")).textContent).toBe(d)
    khongMaRaNgoai()
  })

  it("503 đóng băng: câu rõ, không lộ chi tiết", async () => {
    mocPost(() => HttpResponse.json({ detail: "x", code: "ADMISSION_FROZEN" }, { status: 503 }))
    ve()
    nhap(MA.join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    expect((await screen.findByTestId("create-set-error")).textContent).toMatch(/đóng băng/)
    expect(screen.queryByTestId("council-error-detail")).toBeNull()
    khongMaRaNgoai()
  })

  it("422 (FastAPI kèm `input` = thân có mã): không hiện mã", async () => {
    mocPost(() =>
      HttpResponse.json(
        // Lượt G (F236): khuôn THẬT của handler 422 — danh sách ở `errors`, `detail` là chuỗi.
        { detail: "Request validation failed", error_code: "VALIDATION_ERROR", errors: [{ type: "missing", loc: ["body", "academic_year"], msg: "Field required", input: { ma_ho_so: MA } }] },
        { status: 422 },
      ),
    )
    ve()
    nhap(MA.join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    const loi = await screen.findByTestId("create-set-error")
    for (const m of MA) expect(loi.textContent?.includes(m)).toBe(false)
    khongMaRaNgoai()
  })

  it("ô nhập không có `name`, tắt autocomplete (trình duyệt không lưu lịch sử form)", () => {
    ve()
    const o = screen.getByTestId("ma-ho-so-input")
    expect(o.getAttribute("name")).toBeNull()
    expect(o.getAttribute("autocomplete")).toBe("off")
    expect(screen.getByTestId("create-set-form").getAttribute("autocomplete")).toBe("off")
  })
})

// ── Hợp đồng thân yêu cầu mục 2 (`POST /sets` dạng MÃ): máy chủ giả ÁP LUẬT THẬT (`council-luat-may-chu.ts` → `luatTaoBo`) ─────────────────
// CCCD chỉ duy nhất trong MỘT năm học ⇒ mã đúng dạng nhưng sai năm ⇒ "không có hồ sơ"; mã 11 số / trùng dòng ⇒ 400 nêu SỐ DÒNG.
describe("hợp đồng thân yêu cầu — POST /sets dạng mã (luật thật)", () => {
  const KHO_2026 = new Map([[MA[0], 30], [MA[1], 10], [MA[2], 20]])
  function mocLuat() {
    server.use(
      http.post(`${API}${P}/sets`, async ({ request }) => {
        urls.push(request.url)
        const than = (await request.clone().json()) as Record<string, unknown>
        bodies.push(than)
        const sai = dap(luatTaoBo(than, { anh: null, idTheoMa: than.academic_year === 2026 ? KHO_2026 : new Map() }))
        return sai ?? HttpResponse.json(BO, { status: 201 })
      }),
      http.get(`${API}${P}/sets`, () => HttpResponse.json([])),
    )
  }

  it("ĐÚNG: ba mã 12 số của năm 2026 theo đúng thứ tự trên giấy ⇒ dựng được", async () => {
    mocLuat()
    ve()
    nhap(MA.join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents/21"))
  })

  it("SAI: mã 11 số ở dòng 2 ⇒ 400 nêu 'Dòng 2' (không nêu giá trị); không chuyển trang", async () => {
    mocLuat()
    ve()
    nhap([MA[0], "09999900000", MA[2]].join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    const loi = await screen.findByTestId("create-set-error")
    expect(loi.textContent).toContain("Dòng 2")
    expect(loi.textContent).not.toContain("09999900000")
    expect(push).not.toHaveBeenCalled()
  })

  it("SAI: cùng một mã ở hai dòng ⇒ 400 'Dòng 2 trùng' ", async () => {
    mocLuat()
    ve()
    nhap([MA[0], MA[0]].join("\n"))
    fireEvent.click(screen.getByTestId("create-set-submit"))
    expect((await screen.findByTestId("create-set-error")).textContent).toContain("Dòng 2 trùng")
  })

  it("SAI: mã ĐÚNG dạng nhưng sai NĂM HỌC (2027 — mã chỉ có ở 2026) ⇒ 400; sửa năm về 2026 ⇒ dựng được", async () => {
    mocLuat()
    ve()
    nhap(MA.join("\n"), "2027")
    fireEvent.click(screen.getByTestId("create-set-submit"))
    expect((await screen.findByTestId("create-set-error")).textContent).toContain("không khớp đúng một hồ sơ")
    expect(push).not.toHaveBeenCalled()
    fireEvent.change(screen.getByTestId("nam-hoc-input"), { target: { value: "2026" } })
    fireEvent.click(screen.getByTestId("create-set-submit"))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents/21"))
    expect(bodies.map((b) => (b as { academic_year: number }).academic_year)).toEqual([2027, 2026])
  })

  it("tham số đợt chỉ MỘT NỬA (Đợt số 1, không tháng) ⇒ máy chủ 422; ĐỦ (1, 9) ⇒ được, thân dot_so CHUỖI + dot_thang SỐ", async () => {
    mocLuat()
    ve()
    nhap(MA[0])
    fireEvent.click(screen.getByTestId("tham-so-toggle"))
    fireEvent.change(screen.getByLabelText("Đợt số"), { target: { value: "1" } })
    fireEvent.click(screen.getByTestId("create-set-submit"))
    expect((await screen.findByTestId("create-set-error")).textContent).toContain("đợt xét tuyển cần đủ cả số đợt và tháng")
    fireEvent.change(screen.getByLabelText("Tháng của đợt"), { target: { value: "9" } })
    fireEvent.click(screen.getByTestId("create-set-submit"))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents/21"))
    expect((bodies[1] as { tham_so_quyet_dinh: unknown }).tham_so_quyet_dinh).toEqual({ dot_so: "1", dot_thang: 9 })
  })
})
