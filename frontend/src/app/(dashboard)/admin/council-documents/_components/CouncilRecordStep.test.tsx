/**
 * Văn bản Hội đồng — bước 6 "Ghi nhận" ở mức GIAO DIỆN (đặc tả 5.6, 5.6.1, 3.8). Giao thức lượt gửi đã có test riêng ở
 * `hooks/admin/useGhiNhanQuyetDinh.test.tsx`; ở đây khoá điều NGƯỜI DÙNG THẤY:
 *   • ô đã in trên bộ khoá đúng giá trị in; nút Ghi nhận chỉ mở khi đủ điều kiện;
 *   • khung kết quả vẽ CHỈ từ DTO máy chủ (không từ ô nhập); cảnh báo vượt chỉ tiêu theo K-4;
 *   • lượt chưa rõ ⇒ MỌI chỗ nói "Chưa xác định", KHÔNG có "chưa ghi nhận", KHÔNG có nút gửi lại; kể cả khi máy chủ đang
 *     trả `tinh_trang: chua_ghi_nhan` cũ;
 *   • bốn kết quả phân xử; tải lại trang khôi phục lượt chờ; hộp thoại Huỷ ghi nhận.
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilDocumentPermissions } from "@/lib/zod/council-documents"

import { CouncilSetDetailClient } from "./CouncilSetDetailClient"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/admin/council-documents/7",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
const MA = "11111111-2222-3333-4444-555555555555"
/** Số Quyết định của văn bản giả (id 21). Hộp Huỷ ghi nhận đòi gõ lại ĐÚNG số này — không phải số hồ sơ (7). */
const SO_QD = "99"
const TAT_CA = Object.fromEntries(Object.keys(NO_COUNCIL_PERMISSIONS).map((k) => [k, true])) as CouncilDocumentPermissions

const BO = {
  id: 7, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z", unit_id: 2,
  trinh_do: "Cao đẳng", so_ho_so: 3, so_tep: 2, kich_thuoc_tong: 20, nam_hoc: 2026,
  tham_so_quyet_dinh: { so_quyet_dinh: "99", ngay_quyet_dinh: "2026-09-08" },
  thong_tin_dung: { luat: "v1.1" }, tep: [],
  // `GET /sets/{id}` (máy chủ `083a428d`): bốn trường LUÔN có khoá. `quyet_dinh` do `dung()` suy từ danh sách văn bản như máy chủ.
  nguoi_tao_ten: null, tinh_trang: "chua_ghi_nhan", quyet_dinh: null, luot_gui_cho: null,
}

function qd(over: Record<string, unknown> = {}) {
  return {
    id: 21, loai: "trung_tuyen", trang_thai: "hieu_luc", can_bo: false, set_id: 7,
    so_quyet_dinh: SO_QD, ngay_ky: "2026-09-08", pham_vi_so: 2026,
    so_ho_so: 7, // KHÁC số người dùng gõ (3) — để chứng minh khung kết quả lấy từ DTO; cũng KHÁC SỐ QUYẾT ĐỊNH (99) của hộp Huỷ
    ghi_nhan_boi_id: 1, ghi_nhan_luc: "2026-11-11T03:00:00Z", canh_bao_vuot_chi_tieu: [], ma_luot_gui: MA, lap_lai: false,
    ...over,
  }
}

interface Cau {
  gui?: () => Response
  chan?: () => Response
  ds?: unknown[]
  decisions?: unknown[]
  mo?: () => Response
  huy?: () => Response
  chiTiet?: () => Response
  bo?: Record<string, unknown>
}
let formGui: FormData[] = []
let huyBodies: Record<string, unknown>[] = []
let soLanMo = 0
let urlsDecisions: URL[] = []

/** Như `SQL_BO_MO_RONG` của máy chủ: văn bản CHƯA huỷ ghi nhận, id lớn nhất, của bộ 7 — hoặc null. */
function quyetDinhCuaBo7(ds: unknown[]) {
  type D = { id: number; set_id: number; loai: string; trang_thai: string; so_quyet_dinh: string; ngay_ky: string; so_ho_so: number }
  const song = (ds as D[]).filter((d) => d.set_id === 7 && d.trang_thai !== "huy_ghi_nhan").sort((a, b) => b.id - a.id)[0]
  return song
    ? { id: song.id, loai: song.loai, trang_thai: song.trang_thai, so_quyet_dinh: song.so_quyet_dinh, ngay_ky: song.ngay_ky, so_ho_so: song.so_ho_so, goc: null }
    : null
}

function dung(c: Cau = {}) {
  server.use(
    http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: TAT_CA })),
    http.get(`${API}${P}/sets/7`, () => HttpResponse.json({ ...BO, quyet_dinh: quyetDinhCuaBo7(c.decisions ?? []), ...(c.bo ?? {}) })),
    http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([])),
    http.get(`${API}${P}/sets/7/luot-ghi-nhan`, () => HttpResponse.json(c.ds ?? [])),
    // Như máy chủ thật (`083a428d`): LỌC theo `set_id`, `loai`, `trang_thai` khi có — giao diện không lọc lại.
    http.get(`${API}${P}/decisions`, ({ request }) => {
      const u = new URL(request.url)
      urlsDecisions.push(u)
      const khop = (d: unknown, khoa: string, tham: string) => {
        const v = u.searchParams.get(tham)
        return v === null || String((d as Record<string, unknown>)[khoa]) === v
      }
      return HttpResponse.json(
        (c.decisions ?? []).filter((d) => khop(d, "set_id", "set_id") && khop(d, "loai", "loai") && khop(d, "trang_thai", "trang_thai")),
      )
    }),
    http.get(`${API}${P}/decisions/21`, () => (c.chiTiet ? c.chiTiet() : HttpResponse.json({ ...qd(), dong: [], scan: null, su_kien: [] }))),
    http.post(`${API}${P}/sets/7/luot-ghi-nhan`, () => {
      soLanMo++
      return c.mo ? c.mo() : HttpResponse.json({ ma: MA }, { status: 201 })
    }),
    http.post(`${API}${P}/decisions`, async ({ request }) => {
      try {
        formGui.push(await request.formData())
      } catch {
        /* không đọc được form */
      }
      return c.gui ? c.gui() : HttpResponse.json(qd(), { status: 201 })
    }),
    http.post(`${API}${P}/luot-ghi-nhan/:ma/chan`, () => (c.chan ? c.chan() : HttpResponse.json({ ket_qua: "dang_xu_ly" }))),
    http.post(`${API}${P}/decisions/21/huy-ghi-nhan`, async ({ request }) => {
      const than = (await request.json()) as Record<string, unknown>
      huyBodies.push(than)
      // Như máy chủ thật (`council_decision_service.huy_ghi_nhan`, `if so_go_lai != x.so_quyet_dinh`): so NGUYÊN CHUỖI với SỐ QUYẾT
      // ĐỊNH của văn bản, KHÔNG phải số hồ sơ. Lệch ⇒ 400 DATA_VALIDATION_ERROR, văn bản không đổi. (Máy chủ giả cũ nhận mọi giá
      // trị nên không bắt được lỗi Đ2-1: hộp thoại bảo gõ số hồ sơ.)
      if (than.so_go_lai !== SO_QD) {
        return HttpResponse.json({ detail: "Số văn bản gõ lại không khớp.", error_code: "DATA_VALIDATION_ERROR" }, { status: 400 })
      }
      return c.huy ? c.huy() : HttpResponse.json(qd({ trang_thai: "huy_ghi_nhan" }))
    }),
  )
}

function ve(buoc: "ghi-nhan" | null = "ghi-nhan") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilSetDetailClient setId={7} buocBanDau={buoc} />
    </QueryClientProvider>,
  )
}

/** Điền đủ biểu mẫu (số QĐ + ngày ký đã khoá theo bộ). */
async function dien() {
  await screen.findByTestId("bieu-mau-ghi-nhan")
  const scan = new File(["%PDF-1.4 gia"], "scan.pdf", { type: "application/pdf" })
  fireEvent.change(screen.getByTestId("scan"), { target: { files: [scan] } })
  fireEvent.change(screen.getByTestId("xac-nhan-so-ho-so"), { target: { value: "3" } })
  fireEvent.click(screen.getByTestId("xac-nhan-khop"))
}
const nutGhi = () => screen.getByTestId("ghi-nhan") as HTMLButtonElement
const vanBan = () => document.body.textContent ?? ""

beforeEach(() => {
  formGui = []
  huyBodies = []
  soLanMo = 0
  urlsDecisions = []
  push.mockClear()
  vi.spyOn(console, "error").mockImplementation(() => undefined)
})

describe("biểu mẫu", () => {
  it("ô đã in trên bộ KHOÁ đúng giá trị in; ô chưa in nhập được", async () => {
    dung()
    ve()
    await screen.findByTestId("bieu-mau-ghi-nhan")
    const soQd = screen.getByTestId("so-quyet-dinh") as HTMLInputElement
    const ngayKy = screen.getByTestId("ngay-ky") as HTMLInputElement
    expect(soQd.value).toBe("99")
    expect(soQd.readOnly).toBe(true)
    expect(ngayKy.value).toBe("2026-09-08")
    expect(ngayKy.readOnly).toBe(true)
    expect((screen.getByTestId("so-bien-ban") as HTMLInputElement).readOnly).toBe(false) // chưa in ⇒ nhập
  })

  it("nút Ghi nhận chỉ mở khi đủ: scan + số hồ sơ gõ lại + xác nhận khớp bản in", async () => {
    dung()
    ve()
    await screen.findByTestId("bieu-mau-ghi-nhan")
    expect(nutGhi().disabled).toBe(true)
    const scan = new File(["%PDF"], "scan.pdf", { type: "application/pdf" })
    fireEvent.change(screen.getByTestId("scan"), { target: { files: [scan] } })
    expect(nutGhi().disabled).toBe(true)
    fireEvent.change(screen.getByTestId("xac-nhan-so-ho-so"), { target: { value: "3" } })
    expect(nutGhi().disabled).toBe(true)
    fireEvent.click(screen.getByTestId("xac-nhan-khop"))
    expect(nutGhi().disabled).toBe(false)
    fireEvent.change(screen.getByTestId("xac-nhan-so-ho-so"), { target: { value: "ba" } })
    expect(nutGhi().disabled).toBe(true)
  })

  it("Quyết định BỔ SUNG đòi chọn gốc; danh sách gốc chỉ gồm Quyết định trúng tuyển còn hiệu lực", async () => {
    dung({
      // Quyết định của CÁC BỘ KHÁC (set_id ≠ 7): bộ 7 chưa có văn bản nên biểu mẫu mở.
      decisions: [
        qd({ id: 30, set_id: 3, so_quyet_dinh: "10", trang_thai: "hieu_luc" }),
        qd({ id: 31, set_id: 4, so_quyet_dinh: "11", trang_thai: "huy_ghi_nhan" }),
        qd({ id: 32, set_id: 5, so_quyet_dinh: "12", loai: "bo_sung", trang_thai: "hieu_luc" }),
      ],
    })
    ve()
    await dien()
    fireEvent.click(screen.getByTestId("loai-bo-sung"))
    expect(nutGhi().disabled).toBe(true) // chưa chọn gốc
    const goc = (await screen.findByTestId("goc")) as HTMLSelectElement
    await waitFor(() => expect(goc.options.length).toBe(2)) // "Chưa chọn…" + 1 Quyết định gốc hợp lệ
    expect(goc.textContent).toContain("số 10")
    expect(goc.textContent).not.toContain("số 11")
    expect(goc.textContent).not.toContain("số 12")
    fireEvent.change(goc, { target: { value: "30" } })
    expect(nutGhi().disabled).toBe(false)
  })

  it("danh sách gốc: hỏi máy chủ với loai=trung_tuyen & trang_thai=hieu_luc (máy chủ lọc; giao diện không lọc lại)", async () => {
    dung({ decisions: [qd({ id: 30, set_id: 3, so_quyet_dinh: "10" })] })
    ve()
    await dien()
    fireEvent.click(screen.getByTestId("loai-bo-sung"))
    await waitFor(() => expect(urlsDecisions.some((u) => u.searchParams.get("loai") === "trung_tuyen")).toBe(true))
    const u = urlsDecisions.find((x) => x.searchParams.get("loai") === "trung_tuyen")!
    expect(u.searchParams.get("trang_thai")).toBe("hieu_luc")
    expect(u.searchParams.get("limit")).toBe("200")
    expect(u.searchParams.has("set_id")).toBe(false) // danh sách gốc là của MỌI bộ
  })
})

describe("gửi thành công", () => {
  it("khung kết quả lấy từ DTO MÁY CHỦ (không từ ô nhập); biểu mẫu khoá; cảnh báo vượt chỉ tiêu theo K-4", async () => {
    dung({
      gui: () =>
        HttpResponse.json(
          qd({
            canh_bao_vuot_chi_tieu: [
              { loai: "nganh", chi_tieu: 40, academic_info_id: 5, da_dung_cong_bo: 41, da_dung_phe_duyet_cu: 45, nhan: "CĐ Kế toán" },
              { loai: "duong_xet", chi_tieu: 10, admission_path_id: 9, da_dung: 12 },
            ],
          }),
          { status: 201 },
        ),
    })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    const kq = await screen.findByTestId("ket-qua-ghi-nhan")
    // DTO nói 7 hồ sơ (người dùng gõ 3) ⇒ khung hiện 7
    expect(within(kq).getByTestId("ket-qua-dong").textContent).toContain("7 hồ sơ")
    expect(within(kq).getByTestId("ket-qua-dong").textContent).toContain("số 99")
    expect(screen.queryByTestId("bieu-mau-ghi-nhan")).toBeNull() // biểu mẫu không còn
    // K-4: số chính = MỨC LỚN NHẤT trong hai cách đếm, ghi đúng chữ ấy, không gọi là "tổng"
    expect(screen.getByTestId("canh-bao-so-chinh-0").textContent).toBe("45")
    expect(screen.getByTestId("canh-bao-chi-tiet-0").textContent).toContain("công bố: 41")
    expect(screen.getByTestId("canh-bao-chi-tiet-0").textContent).toContain("Phê duyệt cũ: 45")
    expect(screen.getByTestId("canh-bao-0").textContent).toContain("mức lớn nhất trong hai cách đếm")
    expect(screen.getByTestId("canh-bao-0").textContent).not.toMatch(/tổng/i)
    expect(screen.getByTestId("canh-bao-0").textContent).toContain("CĐ Kế toán") // nhãn máy chủ trả
    expect(screen.getByTestId("canh-bao-1").textContent).toContain("đường xét (#9)") // thiếu nhãn ⇒ mã + id
    expect(screen.getByTestId("canh-bao-chi-tieu").textContent).toContain("đã ghi nhận, không chặn")
    // mở lượt đúng một lần, ngay lúc gửi; mã lượt nằm trong thân form
    expect(soLanMo).toBe(1)
    expect(formGui[0]?.get("ma_luot_gui")).toBe(MA)
  })

  it("gửi LẶP (lap_lai) ⇒ nói rõ 'văn bản cũ, không ghi lần hai'", async () => {
    dung({ gui: () => HttpResponse.json(qd({ lap_lai: true }), { status: 200 }) })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    expect((await screen.findByTestId("ket-qua-lap-lai")).textContent).toContain("không ghi lần hai")
  })
})

describe("lượt CHƯA RÕ — mọi chỗ chỉ nói 'Chưa xác định'", () => {
  async function denChuaRo(c: Cau = {}) {
    dung({ gui: () => HttpResponse.error(), ...c })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    return screen.findByTestId("chua-xac-dinh")
  }

  it("mất mạng sau khi gửi ⇒ thẻ Chưa xác định (kèm giờ + mã lượt), biểu mẫu khoá, KHÔNG có nút gửi lại", async () => {
    const the = await denChuaRo()
    expect(within(the).getByTestId("nhan-chua-xac-dinh").textContent).toContain("Chưa xác định")
    expect(within(the).getByTestId("ma-luot").textContent).toBe(MA)
    expect(the.textContent).toContain("đừng gửi lại")
    expect((screen.getByTestId("bieu-mau-ghi-nhan") as HTMLFieldSetElement).disabled).toBe(true)
    expect(screen.queryByTestId("ghi-nhan")).toBeNull() // không có nút Ghi nhận / Gửi lại
    expect(screen.queryByRole("button", { name: /gửi lại|ghi nhận lại|thử gửi/i })).toBeNull()
    expect(screen.getByTestId("kiem-tra-may-chu")).toBeTruthy()
  })

  it("toàn bộ chữ trên màn KHÔNG chứa 'chưa ghi nhận' — kể cả khi máy chủ đang trả tinh_trang cũ chua_ghi_nhan", async () => {
    expect(BO.tinh_trang).toBe("chua_ghi_nhan") // máy chủ giả đang nói nhãn cũ
    await denChuaRo()
    expect(vanBan()).not.toMatch(/chưa ghi nhận/i)
    expect(screen.getByTestId("tinh-trang").textContent).toContain("Chưa xác định")
    expect(screen.queryByTestId("chu-thich-chua-ghi-nhan")).toBeNull()
  })

  it.each([
    ["đã ghi + DTO", () => HttpResponse.json({ ket_qua: "da_ghi", quyet_dinh: qd() }), "ket-qua-ghi-nhan"],
    ["chưa ghi, đã chặn", () => HttpResponse.json({ ket_qua: "chua_ghi_da_chan" }), "da-chan"],
    ["đang xử lý", () => HttpResponse.json({ ket_qua: "dang_xu_ly" }), "tb-dang-xu-ly"],
    ["không kết nối", () => HttpResponse.error(), "tb-phan-xu-loi"],
  ] as const)("phân xử: %s", async (_ten, tra, thay) => {
    await denChuaRo({ chan: tra })
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    expect(await screen.findByTestId(thay)).toBeTruthy()
    if (thay === "tb-dang-xu-ly" || thay === "tb-phan-xu-loi") {
      // vẫn chưa rõ: thẻ còn, vẫn không có nhãn "chưa ghi nhận"
      expect(screen.getByTestId("chua-xac-dinh")).toBeTruthy()
      expect(vanBan()).not.toMatch(/chưa ghi nhận/i)
      expect(screen.queryByTestId("ghi-nhan")).toBeNull()
    }
    if (thay === "da-chan") {
      expect(screen.getByTestId("da-chan").textContent).toContain("chưa tạo Quyết định nào")
      fireEvent.click(screen.getByTestId("nhap-lai"))
      expect(await screen.findByTestId("ghi-nhan")).toBeTruthy() // chỉ lúc này mới gửi lại được (mở lượt MỚI)
    }
  })

  it("tải lại trang: lượt cho_gui ⇒ vào THẲNG bước 6 ở trạng thái Chưa xác định (không cần ?buoc=)", async () => {
    dung({ ds: [{ ma: MA, trang_thai: "cho_gui", tao_luc: "2026-11-11T02:00:00Z", ket_thuc_luc: null, decision_id: null }] })
    ve(null)
    const the = await screen.findByTestId("chua-xac-dinh")
    expect(within(the).getByTestId("ma-luot").textContent).toBe(MA)
    expect(screen.getByTestId("buoc-ghi-nhan")).toBeTruthy()
    expect(vanBan()).not.toMatch(/chưa ghi nhận/i)
    expect(soLanMo).toBe(0) // vào bước KHÔNG mở lượt
  })

  // Đ2-2 (chạy thử trình duyệt đợt 2): phân xử trả "đã chặn" nhưng dòng "Tình trạng" đầu trang vẫn "Chưa xác định" dù máy chủ đã
  // đổi sang `chua_ghi_nhan`. Máy chủ giả CÓ TRẠNG THÁI: bộ + danh sách lượt chỉ đổi sau khi gọi `chan`.
  it("Đ2-2: phân xử 'đã chặn' ⇒ dòng 'Tình trạng' đầu trang được LÀM MỚI theo máy chủ (không còn kẹt 'Chưa xác định')", async () => {
    let daChan = false
    const luotCho = { ma: MA, trang_thai: "cho_gui", tao_luc: "2026-11-11T02:00:00Z", ket_thuc_luc: null, decision_id: null }
    dung({
      ds: [luotCho],
      chan: () => {
        daChan = true
        return HttpResponse.json({ ket_qua: "chua_ghi_da_chan" })
      },
    })
    server.use(
      http.get(`${API}${P}/sets/7`, () =>
        HttpResponse.json({
          ...BO,
          tinh_trang: daChan ? "chua_ghi_nhan" : "chua_xac_dinh",
          luot_gui_cho: daChan ? null : { ma: MA, tao_luc: "2026-11-11T02:00:00Z" },
        }),
      ),
      http.get(`${API}${P}/sets/7/luot-ghi-nhan`, () =>
        HttpResponse.json([daChan ? { ...luotCho, trang_thai: "da_chan", ket_thuc_luc: "2026-11-11T02:05:00Z" } : luotCho]),
      ),
    )
    ve(null)
    await screen.findByTestId("chua-xac-dinh")
    expect(screen.getByTestId("tinh-trang").textContent).toContain("Chưa xác định") // trước phân xử: đúng
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    await screen.findByTestId("da-chan")
    await waitFor(() => expect(screen.getByTestId("tinh-trang").textContent).toContain("Chưa ghi nhận"))
    expect(screen.getByTestId("tinh-trang").textContent).not.toContain("Chưa xác định")
    // làm mới bộ KHÔNG được đẩy trang khỏi bước 6: khung "đã chặn" + nút "Nhập lại" còn đó để người dùng đọc
    expect(screen.getByTestId("da-chan")).toBeTruthy()
    expect(screen.getByTestId("nhap-lai")).toBeTruthy()
  })

  // Đ2-3: "Lượt gửi lúc …" là giờ của LƯỢT, không phải giờ bấm kiểm. Giờ lượt cố ý ở quá khứ xa (11:07 05/01/2026 giờ VN — `thoiDiem` in giờ trước ngày) để lệch
  // hẳn giờ hiện tại; mọi lần phân xử không kết luận (đóng băng / đang xử lý / mất mạng) phải giữ NGUYÊN giờ đó.
  it.each([
    ["đóng băng tuyển sinh (503)", () => HttpResponse.json({ detail: "Tuyển sinh đang đóng băng", code: "ADMISSION_FROZEN" }, { status: 503 }), "tb-dong-bang"],
    ["đang xử lý", () => HttpResponse.json({ ket_qua: "dang_xu_ly" }), "tb-dang-xu-ly"],
    ["không kết nối", () => HttpResponse.error(), "tb-phan-xu-loi"],
  ] as const)("Đ2-3: phân xử không kết luận (%s) ⇒ 'Lượt gửi lúc' GIỮ giờ của lượt, không thành giờ bấm kiểm", async (_ten, tra, thay) => {
    dung({
      ds: [{ ma: MA, trang_thai: "cho_gui", tao_luc: "2026-01-05T04:07:00Z", ket_thuc_luc: null, decision_id: null }],
      chan: tra,
    })
    ve(null)
    const the = await screen.findByTestId("chua-xac-dinh")
    expect(the.textContent).toContain("Lượt gửi lúc 11:07 05/01/2026,") // khôi phục sau tải lại: giờ tạo của lượt
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    await screen.findByTestId(thay)
    expect(screen.getByTestId("chua-xac-dinh").textContent).toContain("Lượt gửi lúc 11:07 05/01/2026,")
    // bấm kiểm lần nữa vẫn thế
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    await screen.findByTestId(thay)
    expect(screen.getByTestId("chua-xac-dinh").textContent).toContain("Lượt gửi lúc 11:07 05/01/2026,")
  })
})

describe("bị từ chối nghiệp vụ", () => {
  it("400 ⇒ hiện câu máy chủ, mở khoá biểu mẫu; gửi lại cùng mã (không mở lượt thứ hai)", async () => {
    let lan = 0
    dung({
      gui: () => {
        lan++
        return lan === 1
          ? HttpResponse.json({ detail: "Số hồ sơ gõ lại không khớp.", error_code: "BUSINESS_RULE_VIOLATION" }, { status: 400 })
          : HttpResponse.json(qd(), { status: 201 })
      },
    })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    expect((await screen.findByTestId("ghi-nhan-loi")).textContent).toContain("Số hồ sơ gõ lại không khớp.")
    expect((screen.getByTestId("bieu-mau-ghi-nhan") as HTMLFieldSetElement).disabled).toBe(false)
    expect(screen.queryByTestId("chua-xac-dinh")).toBeNull()
    fireEvent.click(nutGhi())
    await screen.findByTestId("ket-qua-ghi-nhan")
    expect(soLanMo).toBe(1)
    expect(formGui.map((f) => f.get("ma_luot_gui"))).toEqual([MA, MA])
  })

  it("409 cần xác nhận số hồ sơ đổi trạng thái ⇒ khối gõ số (số do máy chủ báo); gửi lại kèm xac_nhan_trang_thai", async () => {
    let lan = 0
    dung({
      gui: () => {
        lan++
        return lan === 1
          ? HttpResponse.json(
              {
                detail: "Có hồ sơ cần xác nhận.", error_code: "CONFLICT",
                xac_nhan_can: { so_ho_so_theo_loai: { resubmitted: 1 }, dong_theo_loai: { resubmitted: [2] } },
              },
              { status: 409 },
            )
          : HttpResponse.json(qd(), { status: 201 })
      },
    })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    const khoi = await screen.findByTestId("khoi-xac-nhan-trang-thai")
    expect(khoi.textContent).toContain("1 hồ sơ (dòng 2)")
    expect(nutGhi().disabled).toBe(true) // chưa gõ xác nhận
    fireEvent.change(screen.getByTestId("xac-nhan-tt-resubmitted"), { target: { value: "1" } })
    expect(nutGhi().disabled).toBe(false)
    fireEvent.click(nutGhi())
    await screen.findByTestId("ket-qua-ghi-nhan")
    expect(formGui[1]?.get("xac_nhan_trang_thai")).toBe(JSON.stringify({ resubmitted: 1 }))
  })

  it("409 có dòng bị chặn ⇒ liệt kê số dòng + lý do máy chủ trả", async () => {
    dung({
      gui: () =>
        HttpResponse.json(
          { detail: "2 hồ sơ đã có Quyết định hiệu lực.", error_code: "CONFLICT", dong_bi_chan: [{ dong: 1, ly_do: "co_qd_hieu_luc" }, { dong: 3, ly_do: "dau_appsheet" }] },
          { status: 409 },
        ),
    })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    const ds = await screen.findByTestId("dong-bi-chan")
    expect(ds.textContent).toContain("Dòng 1: co_qd_hieu_luc")
    expect(ds.textContent).toContain("Dòng 3: dau_appsheet")
  })

  it("không mở được lượt ⇒ báo 'chưa gửi gì', thử lại an toàn", async () => {
    dung({ mo: () => HttpResponse.error() })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    expect((await screen.findByTestId("loi-mo-luot")).textContent).toContain("Chưa gửi gì")
    expect(formGui).toHaveLength(0)
  })
})

describe("thanh bước trên trang bộ", () => {
  it("bước mở được theo CỜ: thiếu so_bo_voi_hien_tai ⇒ không có bước 5; thiếu mo_luot_gui ⇒ không có bước 6", async () => {
    server.use(
      http.get(`${API}${P}/quyen`, () =>
        HttpResponse.json({ permissions: { ...TAT_CA, so_bo_voi_hien_tai: false, mo_luot_gui: false } }),
      ),
      http.get(`${API}${P}/sets/7`, () => HttpResponse.json(BO)),
      http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([])),
      http.get(`${API}${P}/sets/7/luot-ghi-nhan`, () => HttpResponse.json([])),
    )
    ve(null)
    await screen.findByTestId("council-stepper")
    expect((screen.getByTestId("buoc-5") as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId("buoc-6") as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByTestId("buoc-ghi-nhan")).toBeNull()
    expect(screen.queryByTestId("tiep-sau-tai")).toBeNull()
  })

  it("?buoc=ghi-nhan nhưng người dùng KHÔNG có quyền ⇒ rơi về bước 4 (không mở bước không có cờ)", async () => {
    server.use(
      http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...TAT_CA, ghi_nhan_qd: false } })),
      http.get(`${API}${P}/sets/7`, () => HttpResponse.json(BO)),
      http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([])),
      http.get(`${API}${P}/sets/7/luot-ghi-nhan`, () => HttpResponse.json([])),
    )
    ve("ghi-nhan")
    await screen.findByTestId("set-files")
    expect(screen.queryByTestId("buoc-ghi-nhan")).toBeNull()
  })

  it("bấm bước ⇒ thay URL chỉ bằng ?buoc=<tên> (không dữ liệu cá nhân)", async () => {
    dung()
    ve(null)
    await screen.findByTestId("council-stepper")
    fireEvent.click(screen.getByTestId("buoc-5"))
    expect(push).toHaveBeenCalledWith("/admin/council-documents/7?buoc=doi-chieu", { scroll: false })
    fireEvent.click(screen.getByTestId("buoc-6"))
    expect(push).toHaveBeenCalledWith("/admin/council-documents/7?buoc=ghi-nhan", { scroll: false })
  })

  it("'+ Dựng bộ mới' CHỈ khi có cờ tao_bo + kiem_truoc", async () => {
    server.use(
      http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...TAT_CA, kiem_truoc: false } })),
      http.get(`${API}${P}/sets/7`, () => HttpResponse.json(BO)),
      http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([])),
      http.get(`${API}${P}/sets/7/luot-ghi-nhan`, () => HttpResponse.json([])),
    )
    ve(null)
    await screen.findByTestId("council-stepper")
    expect(screen.queryByTestId("dung-bo-moi-tu-bo")).toBeNull()
  })
})

describe("bộ đã có Quyết định + Huỷ ghi nhận", () => {
  it("bộ đã có văn bản còn tính ⇒ hiện kết quả (không hiện biểu mẫu)", async () => {
    dung({ decisions: [qd()] })
    ve()
    expect(await screen.findByTestId("ket-qua-ghi-nhan")).toBeTruthy()
    expect(screen.queryByTestId("bieu-mau-ghi-nhan")).toBeNull()
  })

  it("máy chủ đã trả quyet_dinh.id ⇒ chọn ĐÚNG văn bản đó (không đoán theo mới nhất)", async () => {
    dung({
      bo: { quyet_dinh: { id: 21, loai: "trung_tuyen", trang_thai: "hieu_luc", so_quyet_dinh: "99", ngay_ky: "2026-09-08", so_ho_so: 7, goc: null } },
      decisions: [
        qd({ id: 20, so_ho_so: 9, ghi_nhan_luc: "2026-11-12T03:00:00Z" }), // mới hơn nhưng KHÔNG phải văn bản của bộ theo máy chủ
        qd({ id: 21, so_ho_so: 7, ghi_nhan_luc: "2026-11-11T03:00:00Z" }),
      ],
    })
    ve()
    const kq = await screen.findByTestId("ket-qua-ghi-nhan")
    expect(within(kq).getByTestId("ket-qua-dong").textContent).toContain("7 hồ sơ")
    expect(within(kq).getByTestId("ket-qua-dong").textContent).not.toContain("9 hồ sơ")
  })

  it("máy chủ nói bộ KHÔNG có văn bản còn tính (quyet_dinh null) ⇒ biểu mẫu mở, dù danh sách có văn bản của bộ — không tự chọn 'mới nhất'", async () => {
    dung({ decisions: [qd()], bo: { quyet_dinh: null } })
    ve()
    // Biểu mẫu hiện NGAY khi danh sách văn bản còn đang tải ⇒ phải đợi yêu cầu danh sách của bộ 7 xong và được vẽ rồi mới
    // khẳng định "không hiện kết quả" — nếu không, khẳng định đúng một cách RỖNG (đột biến M40 sống sót ở lần đo đầu).
    expect(await screen.findByTestId("bieu-mau-ghi-nhan")).toBeTruthy()
    await waitFor(() => expect(urlsDecisions.some((u) => u.searchParams.get("set_id") === "7")).toBe(true))
    await new Promise((r) => setTimeout(r, 300))
    expect(screen.queryByTestId("ket-qua-ghi-nhan")).toBeNull()
    expect(screen.getByTestId("bieu-mau-ghi-nhan")).toBeTruthy()
  })

  it("văn bản đã huỷ ghi nhận ⇒ biểu mẫu mở lại để ghi nhận lại", async () => {
    dung({ decisions: [qd({ trang_thai: "huy_ghi_nhan" })] })
    ve()
    expect(await screen.findByTestId("bieu-mau-ghi-nhan")).toBeTruthy()
  })

  async function moHuy() {
    dung({ decisions: [qd()] })
    ve()
    fireEvent.click(await screen.findByTestId("huy-ghi-nhan-mo"))
    return screen.findByTestId("huy-ghi-nhan-dialog")
  }

  it("Huỷ ghi nhận: lý do + gõ lại SỐ QUYẾT ĐỊNH BẮT BUỘC; thân gửi đúng; xong ⇒ biểu mẫu mở lại", async () => {
    const hop = await moHuy()
    const nut = within(hop).getByTestId("huy-xac-nhan-nut") as HTMLButtonElement
    expect(nut.disabled).toBe(true)
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "Nhập sai số" } })
    expect(nut.disabled).toBe(true)
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: SO_QD } })
    expect(nut.disabled).toBe(false)
    dung({ decisions: [] }) // sau khi huỷ, máy chủ không còn văn bản còn tính
    fireEvent.click(nut)
    await waitFor(() => expect(huyBodies).toHaveLength(1))
    expect(huyBodies[0]).toEqual({ ly_do: "Nhập sai số", so_go_lai: SO_QD })
  })

  // Đ2-1 (CHẶN, chạy thử trình duyệt đợt 2): hộp thoại bảo gõ lại SỐ HỒ SƠ nhưng máy chủ so với SỐ QUYẾT ĐỊNH ⇒ làm đúng chữ trên
  // màn thì luôn 400, Admin không huỷ được. Ca này làm ĐÚNG như người dùng: đọc con số ngay trên nhãn rồi gõ đúng con số ấy.
  it("Đ2-1: nhãn ô gõ lại nói 'số Quyết định' (không phải 'số hồ sơ') và hiện số Quyết định của văn bản", async () => {
    const hop = await moHuy()
    const nhan = hop.querySelector('label[for="huy-so-quyet-dinh"]')?.textContent ?? ""
    expect(nhan).toMatch(/số Quyết định/)
    expect(nhan).not.toMatch(/số hồ sơ/)
    expect(/\((\d+)\)/.exec(nhan)?.[1]).toBe(SO_QD) // số trên nhãn là số Quyết định (99), KHÔNG phải số hồ sơ của văn bản (7)
  })

  it("Đ2-1: làm ĐÚNG chữ trên màn — đọc con số trên nhãn rồi gõ đúng con số ấy ⇒ huỷ được (văn bản đã huỷ, biểu mẫu mở lại)", async () => {
    const hop = await moHuy()
    const nhan = hop.querySelector('label[for="huy-so-quyet-dinh"]')?.textContent ?? ""
    const soTrenNhan = /\((\d+)\)/.exec(nhan)?.[1] ?? "" // đúng việc người dùng làm: chép con số in trên nhãn
    expect(soTrenNhan).not.toBe("") // không vacuous: nhãn có con số để chép
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "Nhập sai số" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: soTrenNhan } })
    dung({ decisions: [] }) // sau khi huỷ, máy chủ không còn văn bản còn tính
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    expect(await screen.findByTestId("bieu-mau-ghi-nhan")).toBeTruthy() // máy chủ nhận ⇒ văn bản đã huỷ ⇒ biểu mẫu mở lại
    expect(huyBodies).toEqual([{ ly_do: "Nhập sai số", so_go_lai: soTrenNhan }])
    await waitFor(() => expect(screen.queryByTestId("huy-ghi-nhan-dialog")).toBeNull())
  })

  it("Đ2-1: gõ SỐ HỒ SƠ thay vì số Quyết định ⇒ máy chủ 400; hộp thoại vẫn mở + hiện câu máy chủ, văn bản KHÔNG đổi; gõ lại đúng số ⇒ huỷ được", async () => {
    const hop = await moHuy()
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "Nhập sai số" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: "7" } }) // số hồ sơ của văn bản
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    expect((await within(hop).findByTestId("huy-loi")).textContent).toContain("Số văn bản gõ lại không khớp.")
    expect(huyBodies).toEqual([{ ly_do: "Nhập sai số", so_go_lai: "7" }])
    // văn bản không đổi: hộp thoại còn, khung kết quả còn (văn bản còn hiệu lực), biểu mẫu KHÔNG mở lại
    expect(screen.getByTestId("huy-ghi-nhan-dialog")).toBeTruthy()
    expect(screen.getByTestId("ket-qua-ghi-nhan")).toBeTruthy()
    expect(screen.queryByTestId("bieu-mau-ghi-nhan")).toBeNull()
    // 400 là từ chối dứt khoát (không phải "chưa rõ"): không đi đường đọc lại, nút bấm lại được ngay
    expect(within(hop).queryByTestId("huy-doc-lai")).toBeNull()
    expect((within(hop).getByTestId("huy-xac-nhan-nut") as HTMLButtonElement).disabled).toBe(false)
    // sửa lại đúng số Quyết định ⇒ huỷ được
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: SO_QD } })
    dung({ decisions: [] })
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    expect(await screen.findByTestId("bieu-mau-ghi-nhan")).toBeTruthy()
    expect(huyBodies.map((b) => b.so_go_lai)).toEqual(["7", SO_QD])
  })

  it("Đ2-1: dán thừa dấu cách đầu/cuối quanh số Quyết định ⇒ vẫn huỷ được (gửi đã cắt; máy chủ so nguyên chuỗi, số QĐ không có khoảng trắng)", async () => {
    const hop = await moHuy()
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "Nhập sai số" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: `  ${SO_QD} ` } })
    dung({ decisions: [] })
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    expect(await screen.findByTestId("bieu-mau-ghi-nhan")).toBeTruthy()
    expect(huyBodies).toEqual([{ ly_do: "Nhập sai số", so_go_lai: SO_QD }])
  })

  it("409 cần xác nhận ⇒ khối gõ số; gửi lại kèm xac_nhan đúng số máy chủ báo", async () => {
    let lan = 0
    dung({
      decisions: [qd()],
      huy: () => {
        lan++
        return lan === 1
          ? HttpResponse.json(
              { detail: "Cần xác nhận.", error_code: "CONFLICT", xac_nhan_can: { so_ho_so_theo_loai: { admitted: 2 }, dong_theo_loai: { admitted: [1, 4] } } },
              { status: 409 },
            )
          : HttpResponse.json(qd({ trang_thai: "huy_ghi_nhan" }))
      },
    })
    ve()
    fireEvent.click(await screen.findByTestId("huy-ghi-nhan-mo"))
    const hop = await screen.findByTestId("huy-ghi-nhan-dialog")
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "lý do" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: SO_QD } })
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    const khoi = await within(hop).findByTestId("huy-xac-nhan")
    expect(khoi.textContent).toContain("2 hồ sơ (dòng 1, 4)")
    const nut = within(hop).getByTestId("huy-xac-nhan-nut") as HTMLButtonElement
    expect(nut.disabled).toBe(true)
    fireEvent.change(within(hop).getByTestId("huy-xac-nhan-admitted"), { target: { value: "2" } })
    fireEvent.click(nut)
    await waitFor(() => expect(huyBodies).toHaveLength(2))
    expect(huyBodies[1]).toEqual({ ly_do: "lý do", so_go_lai: SO_QD, xac_nhan: { admitted: 2 } })
  })

  it("mất mạng lúc huỷ ⇒ ĐỌC LẠI văn bản trước; thấy vẫn còn hiệu lực ⇒ mới cho bấm lại", async () => {
    dung({ decisions: [qd()], huy: () => HttpResponse.error() })
    ve()
    fireEvent.click(await screen.findByTestId("huy-ghi-nhan-mo"))
    const hop = await screen.findByTestId("huy-ghi-nhan-dialog")
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "lý do" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: SO_QD } })
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    expect(await within(hop).findByTestId("huy-con-hieu-luc")).toBeTruthy() // đã đọc lại: còn hiệu lực
    expect((within(hop).getByTestId("huy-xac-nhan-nut") as HTMLButtonElement).disabled).toBe(false)
  })

  it("mất mạng lúc huỷ và đọc lại cũng lỗi ⇒ KHOÁ nút (không cho bấm lại mù)", async () => {
    dung({ decisions: [qd()], huy: () => HttpResponse.error(), chiTiet: () => HttpResponse.error() })
    ve()
    fireEvent.click(await screen.findByTestId("huy-ghi-nhan-mo"))
    const hop = await screen.findByTestId("huy-ghi-nhan-dialog")
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "lý do" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: SO_QD } })
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    expect(await within(hop).findByTestId("huy-doc-lai-loi")).toBeTruthy()
    expect((within(hop).getByTestId("huy-xac-nhan-nut") as HTMLButtonElement).disabled).toBe(true)
  })
})

/** Mã lượt gửi đã mang trong thân các lần POST /decisions, theo thứ tự. */
const maGui = () => formGui.map((f) => f.get("ma_luot_gui"))

// ── F276 (Codex lần 18): ghi nhận → huỷ ghi nhận → ghi nhận LẠI, KHÔNG tải lại trang ─────────────────────────────────────
// Bộ điều khiển là hook THẬT (`useGhiNhanQuyetDinh`) nối qua `CouncilSetDetailClient` → `CouncilRecordStep` →
// `CouncilRecordResult` → `CouncilCancelDialog`; máy chủ là MSW CÓ TRẠNG THÁI (không mock hook). Lỗi cũ: sau khi huỷ, giao diện
// chỉ đổi trạng thái về biểu mẫu mà GIỮ mã của lượt đã `da_ghi` ⇒ gửi lại cùng mã ⇒ máy chủ (luỹ đẳng) trả lại đúng văn bản ĐÃ
// HUỶ; khác nội dung thì 409.
describe("F276 — ghi nhận → huỷ → ghi nhận lại (không tải lại trang)", () => {
  const MA_MOI = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

  /**
   * Máy chủ giả có trạng thái: mỗi mã lượt chỉ ghi MỘT văn bản; gửi lại CÙNG mã trả đúng văn bản ấy (luỹ đẳng) — kể cả khi
   * văn bản đã bị huỷ ghi nhận. Lượt mở thứ nhất cấp `MA`, thứ hai cấp `MA_MOI`.
   */
  function mayChuGhiHuyGhiLai(opt: { matPhanHoiLanGuiDau?: boolean; loiNghiepVuLanGuiThu?: number } = {}) {
    const daGhi = new Map<string, Record<string, unknown>>()
    let lanGui = 0
    const cau: Cau = {
      decisions: [],
      mo: () => HttpResponse.json({ ma: soLanMo === 1 ? MA : MA_MOI }, { status: 201 }),
      gui: () => {
        lanGui++
        const ma = String(formGui[formGui.length - 1]?.get("ma_luot_gui"))
        if (opt.loiNghiepVuLanGuiThu === lanGui) {
          return HttpResponse.json({ detail: "Số hồ sơ gõ lại không khớp.", error_code: "BUSINESS_RULE_VIOLATION" }, { status: 400 })
        }
        const cu = daGhi.get(ma)
        if (cu) return HttpResponse.json({ ...cu, lap_lai: true }, { status: 200 })
        const moi = qd({ id: 21 + daGhi.size, ma_luot_gui: ma })
        daGhi.set(ma, moi)
        cau.decisions = [moi]
        return opt.matPhanHoiLanGuiDau && lanGui === 1 ? HttpResponse.error() : HttpResponse.json(moi, { status: 201 })
      },
      chan: () => HttpResponse.json({ ket_qua: "da_ghi", quyet_dinh: daGhi.get(MA) }),
      huy: () => {
        const huy = { ...daGhi.get(MA), trang_thai: "huy_ghi_nhan" }
        daGhi.set(MA, huy)
        cau.decisions = []
        return HttpResponse.json(huy)
      },
    }
    return cau
  }

  /** Huỷ văn bản đang hiện ở khung kết quả (lý do + gõ lại SỐ QUYẾT ĐỊNH của văn bản = 99) rồi đợi biểu mẫu mở lại. */
  async function huyRoiDoiBieuMau() {
    fireEvent.click(await screen.findByTestId("huy-ghi-nhan-mo"))
    const hop = await screen.findByTestId("huy-ghi-nhan-dialog")
    fireEvent.change(within(hop).getByTestId("huy-ly-do"), { target: { value: "Nhập sai số" } })
    fireEvent.change(within(hop).getByTestId("huy-so-quyet-dinh"), { target: { value: SO_QD } })
    fireEvent.click(within(hop).getByTestId("huy-xac-nhan-nut"))
    await waitFor(() => expect(huyBodies).toHaveLength(1))
    await screen.findByTestId("bieu-mau-ghi-nhan")
  }

  /** Các ô người dùng đã điền vẫn còn sau khi ghi (cùng một màn); bảo đảm đủ điều kiện mà không bật tắt nhầm ô xác nhận. */
  function bamGhiNhanLai() {
    const khop = screen.getByTestId("xac-nhan-khop")
    if (khop.getAttribute("aria-checked") !== "true") fireEvent.click(khop)
    fireEvent.change(screen.getByTestId("xac-nhan-so-ho-so"), { target: { value: "3" } })
    fireEvent.click(nutGhi())
  }

  it("ghi thành công → huỷ → ghi lại: lượt gửi THỨ HAI mang mã MỚI (mở lượt mới), không dùng lại mã lượt đã ghi", async () => {
    dung(mayChuGhiHuyGhiLai())
    ve()
    await dien()
    fireEvent.click(nutGhi())
    await screen.findByTestId("ket-qua-ghi-nhan") // lượt 1 đã ghi
    await huyRoiDoiBieuMau()
    bamGhiNhanLai()
    await screen.findByTestId("ket-qua-ghi-nhan")
    expect(maGui()).toEqual([MA, MA_MOI])
    expect(soLanMo).toBe(2)
    // hệ quả người dùng thấy: khung kết quả là văn bản MỚI còn hiệu lực, không phải văn bản cũ đã huỷ
    expect(screen.getByTestId("ket-qua-dong").textContent).not.toContain("Đã huỷ ghi nhận")
    expect(screen.queryByTestId("ket-qua-lap-lai")).toBeNull()
  })

  it("lượt chưa rõ → phân xử 'đã ghi' → huỷ → ghi lại: cũng mở lượt MỚI (nhánh anh em: mã lượt đến từ phân xử)", async () => {
    dung(mayChuGhiHuyGhiLai({ matPhanHoiLanGuiDau: true }))
    ve()
    await dien()
    fireEvent.click(nutGhi())
    await screen.findByTestId("chua-xac-dinh")
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    await screen.findByTestId("ket-qua-ghi-nhan") // phân xử: đã ghi
    await huyRoiDoiBieuMau()
    bamGhiNhanLai()
    await screen.findByTestId("ket-qua-ghi-nhan")
    expect(maGui()).toEqual([MA, MA_MOI])
    expect(soLanMo).toBe(2)
  })

  it("đối chứng: lỗi NGHIỆP VỤ khi ghi lại ⇒ gửi tiếp vẫn cùng mã lượt đang chờ (không mở lượt thứ ba)", async () => {
    dung(mayChuGhiHuyGhiLai({ loiNghiepVuLanGuiThu: 2 })) // lần gửi thứ hai (lượt MỚI sau huỷ) bị từ chối 400
    ve()
    await dien()
    fireEvent.click(nutGhi())
    await screen.findByTestId("ket-qua-ghi-nhan")
    await huyRoiDoiBieuMau()
    bamGhiNhanLai()
    expect((await screen.findByTestId("ghi-nhan-loi")).textContent).toContain("Số hồ sơ gõ lại không khớp.")
    fireEvent.click(nutGhi())
    await screen.findByTestId("ket-qua-ghi-nhan")
    expect(maGui()).toEqual([MA, MA_MOI, MA_MOI])
    expect(soLanMo).toBe(2)
  })
})

// ── Codex lần 18, §5.13 + câu 2: đóng băng tuyển sinh (503 ADMISSION_FROZEN) ──────────────────────────────────────────────
// Máy chủ cũng chặn việc PHÂN XỬ lượt cũ khi đóng băng. Lượt chưa rõ phải GIỮ NGUYÊN "Chưa xác định" (không bao giờ thành "chưa
// ghi nhận"), nói bằng lời thường vì sao chưa kiểm được, và biểu mẫu vẫn khoá.
describe("đóng băng tuyển sinh — bước ghi nhận", () => {
  const dongBang = () => HttpResponse.json({ detail: "Tuyển sinh đang đóng băng", code: "ADMISSION_FROZEN" }, { status: 503 })

  it("phân xử bị đóng băng chặn ⇒ VẪN 'Chưa xác định' + nói rõ lý do đóng băng; không 'chưa ghi nhận'; không mở khoá biểu mẫu", async () => {
    dung({ gui: () => HttpResponse.error(), chan: dongBang })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    await screen.findByTestId("chua-xac-dinh")
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    const tb = await screen.findByTestId("tb-dong-bang")
    expect(tb.textContent).toMatch(/đóng băng/)
    expect(tb.textContent).toMatch(/chưa xác định/i)
    expect(tb.textContent).not.toMatch(/không kết nối/i) // máy chủ vẫn trả lời; đây không phải mất mạng
    expect(screen.queryByTestId("tb-phan-xu-loi")).toBeNull()
    expect(screen.getByTestId("chua-xac-dinh")).toBeTruthy()
    expect(vanBan()).not.toMatch(/chưa ghi nhận/i)
    expect((screen.getByTestId("bieu-mau-ghi-nhan") as HTMLFieldSetElement).disabled).toBe(true)
    expect(screen.queryByTestId("ghi-nhan")).toBeNull()
    expect(screen.queryByTestId("da-chan")).toBeNull()
  })

  it("phân xử đóng băng rồi hết đóng băng ⇒ bấm lại được và phân xử ra kết quả thật", async () => {
    let dong = true
    dung({ gui: () => HttpResponse.error(), chan: () => (dong ? dongBang() : HttpResponse.json({ ket_qua: "chua_ghi_da_chan" })) })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    await screen.findByTestId("chua-xac-dinh")
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    await screen.findByTestId("tb-dong-bang")
    dong = false
    fireEvent.click(screen.getByTestId("kiem-tra-may-chu"))
    expect(await screen.findByTestId("da-chan")).toBeTruthy()
    expect(screen.queryByTestId("tb-dong-bang")).toBeNull()
  })

  it("mở lượt bị đóng băng chặn ⇒ nói rõ đóng băng + 'chưa gửi gì'; chưa gửi văn bản nào", async () => {
    dung({ mo: dongBang })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    const the = await screen.findByTestId("loi-mo-luot")
    expect(the.textContent).toMatch(/đóng băng/)
    expect(the.textContent).toContain("Chưa gửi gì")
    expect(formGui).toHaveLength(0)
    expect(screen.queryByTestId("chua-xac-dinh")).toBeNull()
  })

  it("gửi bị đóng băng chặn ⇒ nói rõ đóng băng; lượt còn chờ, gửi lại sau khi hết đóng băng vẫn CÙNG mã", async () => {
    let dong = true
    dung({ gui: () => (dong ? dongBang() : HttpResponse.json(qd(), { status: 201 })) })
    ve()
    await dien()
    fireEvent.click(nutGhi())
    expect((await screen.findByTestId("ghi-nhan-loi")).textContent).toMatch(/đóng băng/)
    dong = false
    fireEvent.click(nutGhi())
    await screen.findByTestId("ket-qua-ghi-nhan")
    expect(maGui()).toEqual([MA, MA])
    expect(soLanMo).toBe(1)
  })
})
