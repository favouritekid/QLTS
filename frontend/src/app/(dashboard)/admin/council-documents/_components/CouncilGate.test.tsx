/**
 * Văn bản Hội đồng — cổng dựng bộ ở giao diện (lượt G, owner 05-11): danh sách bị chặn / cần cảnh
 * báo hiện rõ từng SỐ DÒNG theo phản hồi máy chủ (400 / 409); hộp xác nhận CHỈ mở khi máy chủ nói
 * người gọi được xác nhận (`nguoi_goi_duoc_xac_nhan`), gửi lại ĐÚNG số đếm máy chủ trả; quản lý
 * chỉ thấy câu "cần admin xác nhận". Không quyết theo vai; danh sách mã không ra console / storage
 * / URL. API thật qua MSW. Mã giả sinh lúc chạy (tỉnh 099 không tồn tại).
 */
import fs from "node:fs"
import path from "node:path"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AxiosError, AxiosHeaders } from "axios"

import { server } from "@/test/mocks/server"
import {
  COUNCIL_DOCUMENTS_PREFIX as P,
  councilSetGateFromError,
  describeCouncilDocumentError,
} from "@/lib/api/council-documents"

import mau422 from "@/test/fixtures/council-documents-422-dot-thieu-thang.json"

import { CreateCouncilSetForm } from "./CreateCouncilSetForm"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/admin/council-documents",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
const maGia = (n: number) => "099" + "999" + String(n).padStart(6, "0")
const MA = [maGia(41), maGia(42), maGia(43)]

const BO = {
  id: 31, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T01:00:00Z",
  unit_id: 2, trinh_do: "Cao đẳng", so_ho_so: 3, so_tep: 2, kich_thuoc_tong: 9, nam_hoc: 2026,
  tham_so_quyet_dinh: null, thong_tin_dung: {}, tep: [],
}

function cong(over: Record<string, unknown> = {}) {
  return {
    muc: "can_xac_nhan",
    so_dong: 3,
    chan: [],
    canh_bao: {
      so_ho_so_theo_trang_thai: { reviewing: 1, submitted: 2 },
      dong_theo_trang_thai: { reviewing: [2], submitted: [1, 3] },
    },
    can_admin_xac_nhan: true,
    nguoi_goi_duoc_xac_nhan: true,
    ...over,
  }
}

const CHAN = cong({
  muc: "chan",
  chan: [
    { ma: "trang_thai_chan", mo_ta: "trạng thái hồ sơ không được đưa vào Quyết định trúng tuyển", trang_thai: "draft", so_ho_so: 1, dong: [2] },
    { ma: "hoc_phi_khac_nganh_nv", mo_ta: "ngành của khoản học phí học kỳ 1 khác ngành của nguyện vọng dùng để in", trang_thai: null, so_ho_so: 2, dong: [1, 3] },
  ],
  canh_bao: { so_ho_so_theo_trang_thai: {}, dong_theo_trang_thai: {} },
  can_admin_xac_nhan: false,
})

let bodies: Record<string, unknown>[] = []
let urls: string[] = []
let console_: ReturnType<typeof vi.spyOn>[] = []

/** Mỗi POST trả phần tử kế tiếp của `tra` (phần tử cuối lặp lại). */
function mocPost(tra: (() => Response)[]) {
  let i = 0
  server.use(
    http.post(`${API}${P}/sets`, async ({ request }) => {
      urls.push(request.url)
      bodies.push((await request.clone().json()) as Record<string, unknown>)
      const f = tra[Math.min(i, tra.length - 1)]
      i += 1
      return f()
    }),
    http.get(`${API}${P}/sets`, ({ request }) => {
      urls.push(request.url)
      return HttpResponse.json([])
    }),
  )
}

const tra409 = (g: unknown, d = "Có 3 hồ sơ ở trạng thái cần cảnh báo — admin phải xác nhận.") => () =>
  HttpResponse.json({ detail: d, error_code: "CONFLICT", kiem_tra_dung_bo: g }, { status: 409 })
const tra400 = (g: unknown) => () =>
  HttpResponse.json(
    { detail: "Không dựng bộ văn bản: 3 hồ sơ không đưa được vào văn bản (2 lý do) — xem danh sách từng dòng.", error_code: "DATA_VALIDATION_ERROR", kiem_tra_dung_bo: g },
    { status: 400 },
  )
const tra201 = () => HttpResponse.json(BO, { status: 201 })

function ve() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 5 * 60 * 1000 }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={qc}>
      <CreateCouncilSetForm canOpenDetail />
    </QueryClientProvider>,
  )
  return qc
}

function nhapVaGui() {
  fireEvent.change(screen.getByTestId("ma-ho-so-input"), { target: { value: MA.join("\n") } })
  fireEvent.change(screen.getByTestId("nam-hoc-input"), { target: { value: "2026" } })
  fireEvent.click(screen.getByTestId("create-set-submit"))
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

describe("cổng dựng bộ — danh sách theo số dòng", () => {
  it("400 chặn: hiện TỪNG lý do + trạng thái + số dòng; không hộp xác nhận", async () => {
    mocPost([tra400(CHAN)])
    ve()
    nhapVaGui()
    const muc = await screen.findAllByTestId("gate-chan-item")
    expect(muc.map((x) => x.textContent)).toEqual([
      "trạng thái hồ sơ không được đưa vào Quyết định trúng tuyển — trạng thái Nháp (draft): 1 hồ sơ — dòng 2",
      "ngành của khoản học phí học kỳ 1 khác ngành của nguyện vọng dùng để in: 2 hồ sơ — dòng 1, 3",
    ])
    expect(screen.queryByTestId("xac-nhan-trang-thai-dialog")).toBeNull()
    expect(bodies).toHaveLength(1)
    khongMaRaNgoai()
  })

  it("409 cần xác nhận, máy chủ nói ĐƯỢC xác nhận: hộp xác nhận nêu số đếm; đồng ý ⇒ gửi lại đúng số đếm + giữ thứ tự mã", async () => {
    mocPost([tra409(cong()), tra201])
    ve()
    nhapVaGui()
    const hop = await screen.findByTestId("xac-nhan-trang-thai-dialog")
    expect(screen.getByTestId("xac-nhan-trang-thai-dem").textContent).toContain("Chờ duyệt (submitted): 2 hồ sơ — dòng 1, 3")
    expect(hop.textContent).toContain("reviewing")
    fireEvent.click(screen.getByTestId("xac-nhan-trang-thai-dong-y"))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents/31"))
    expect(bodies).toEqual([
      { ma_ho_so: MA, academic_year: 2026 },
      { ma_ho_so: MA, academic_year: 2026, xac_nhan_trang_thai: { reviewing: 1, submitted: 2 } },
    ])
    khongMaRaNgoai()
  })

  it("huỷ hộp xác nhận ⇒ không gửi lại", async () => {
    mocPost([tra409(cong())])
    ve()
    nhapVaGui()
    await screen.findByTestId("xac-nhan-trang-thai-dialog")
    fireEvent.click(screen.getByTestId("xac-nhan-trang-thai-huy"))
    await waitFor(() => expect(screen.queryByTestId("xac-nhan-trang-thai-dialog")).toBeNull())
    expect(bodies).toHaveLength(1)
  })

  it("409 cần xác nhận, máy chủ nói KHÔNG được (quản lý): chỉ câu 'cần admin xác nhận', không hộp, không nút xác nhận", async () => {
    mocPost([tra409(cong({ nguoi_goi_duoc_xac_nhan: false }), "Có 3 hồ sơ ở trạng thái cần cảnh báo — cần admin xác nhận.")])
    ve()
    nhapVaGui()
    expect((await screen.findByTestId("gate-can-admin")).textContent).toMatch(/Cần admin xác nhận/)
    expect(screen.getAllByTestId("gate-canh-bao-item").map((x) => x.textContent)).toEqual([
      "Đang xét (reviewing): 1 hồ sơ — dòng 2",
      "Chờ duyệt (submitted): 2 hồ sơ — dòng 1, 3",
    ])
    expect(screen.queryByTestId("xac-nhan-trang-thai-dialog")).toBeNull()
    expect(screen.queryByTestId("xac-nhan-trang-thai-dong-y")).toBeNull()
    expect(bodies).toHaveLength(1)
    khongMaRaNgoai()
  })

  it("xác nhận rồi máy chủ báo số đếm ĐÃ đổi: hộp mở lại với số MỚI, lần gửi sau mang số mới", async () => {
    const moi = cong({
      muc: "xac_nhan_lech",
      canh_bao: { so_ho_so_theo_trang_thai: { submitted: 3 }, dong_theo_trang_thai: { submitted: [1, 2, 3] } },
    })
    mocPost([tra409(cong()), tra409(moi, "Số hồ sơ theo trạng thái đã khác lúc xác nhận — xem lại rồi xác nhận lại."), tra201])
    ve()
    nhapVaGui()
    await screen.findByTestId("xac-nhan-trang-thai-dialog")
    fireEvent.click(screen.getByTestId("xac-nhan-trang-thai-dong-y"))
    await waitFor(() => expect(bodies).toHaveLength(2))
    await waitFor(() =>
      expect(screen.getByTestId("xac-nhan-trang-thai-dem").textContent).toContain("Chờ duyệt (submitted): 3 hồ sơ — dòng 1, 2, 3"),
    )
    fireEvent.click(screen.getByTestId("xac-nhan-trang-thai-dong-y"))
    await waitFor(() => expect(push).toHaveBeenCalled())
    expect(bodies[2].xac_nhan_trang_thai).toEqual({ submitted: 3 })
  })

  it("409 có chặn kèm cảnh báo (chặn thắng): không hộp xác nhận", async () => {
    mocPost([tra409(cong({ chan: CHAN.chan }))])
    ve()
    nhapVaGui()
    await screen.findAllByTestId("gate-chan-item")
    expect(screen.queryByTestId("xac-nhan-trang-thai-dialog")).toBeNull()
  })
})

function loi(status: number, data: unknown) {
  const e = new AxiosError("x", "ERR", undefined, undefined, {
    status,
    statusText: "",
    headers: {},
    config: { headers: new AxiosHeaders() },
    data,
  })
  return e
}

describe("describeCouncilDocumentError — cổng chỉ ở 400 / 409, sai dạng thì bỏ", () => {
  it("400 / 409 có cổng ⇒ trả cổng đã kiểm dạng", () => {
    expect(describeCouncilDocumentError(loi(400, { detail: "d", kiem_tra_dung_bo: CHAN })).gate?.chan).toHaveLength(2)
    expect(councilSetGateFromError(loi(409, { detail: "d", kiem_tra_dung_bo: cong() }))?.nguoi_goi_duoc_xac_nhan).toBe(true)
  })

  it.each([403, 404, 500, 503])("%s kèm cổng ⇒ KHÔNG trả cổng (không lộ chi tiết)", (st) => {
    expect(describeCouncilDocumentError(loi(st, { detail: "d", kiem_tra_dung_bo: CHAN })).gate).toBeUndefined()
  })

  it("cổng sai dạng ⇒ bỏ cổng, vẫn hiện câu máy chủ", () => {
    const m = describeCouncilDocumentError(loi(409, { detail: "d", kiem_tra_dung_bo: { muc: 1 } }))
    expect(m.gate).toBeUndefined()
    expect(m.detail).toBe("d")
  })
})

describe("F236 — 422 theo khuôn THẬT của handler (mẫu chung với test backend)", () => {
  // Nguồn: thân 422 THẬT của `POST /sets` chụp bởi
  // `Backend_FastAPI/tests/api/test_council_documents_hop_dong_api.py::test_than_422_that_bang_mau_chung_cua_giao_dien`
  // — test ấy so phản hồi thật với CHÍNH tệp này (đổi handler mà không đổi tệp ⇒ backend đỏ).
  it("đọc danh sách ở `errors` (không ở `detail`): hiện vị trí + câu, không `input`", () => {
    const m = describeCouncilDocumentError(loi(422, mau422))
    expect(typeof (mau422 as { detail: unknown }).detail).toBe("string")
    expect(m.detail).toBe(
      "tham_so_quyet_dinh: Value error, đợt xét tuyển cần đủ cả số đợt và tháng",
    )
    expect(JSON.stringify(m)).not.toContain("dot_so")
  })

  it("form: máy chủ trả 422 thật ⇒ câu lỗi hiện tại chỗ", async () => {
    mocPost([() => HttpResponse.json(mau422, { status: 422 })])
    ve()
    nhapVaGui()
    expect((await screen.findByTestId("council-error-detail")).textContent).toBe(
      "tham_so_quyet_dinh: Value error, đợt xét tuyển cần đủ cả số đợt và tháng",
    )
    khongMaRaNgoai()
  })
})

describe("không quyết theo vai ở giao diện", () => {
  it("module văn bản Hội đồng không đọc vai người dùng", () => {
    const goc = path.resolve(__dirname, "../../../../..")
    const tep = [
      "lib/api/council-documents.ts",
      "lib/zod/council-documents.ts",
      "hooks/admin/useCouncilDocuments.ts",
      ...fs
        .readdirSync(__dirname)
        .filter((t) => /\.(ts|tsx)$/.test(t) && !/\.test\.tsx?$/.test(t))
        .map((t) => path.relative(goc, path.join(__dirname, t))),
    ]
    expect(tep.length).toBeGreaterThanOrEqual(10)
    const lot = tep.filter((t) =>
      /\buseAuth\b|\buser\??\.role\b|\.role\s*===|UserRole/.test(fs.readFileSync(path.join(goc, t), "utf8")),
    )
    expect(lot).toEqual([])
  })
})
