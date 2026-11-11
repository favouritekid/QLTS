/**
 * Văn bản Hội đồng — trang `/moi`: chọn hồ sơ → kiểm tra & chốt → tham số → dựng (đặc tả 5.1 – 5.4, bản 2 mục 5.1).
 * Máy chủ giả (MSW) đóng vai các route ⏳ CHỜ MÁY CHỦ: `tim-ho-so`, `kiem-truoc`, `doi-ma`, `POST /sets` dạng id.
 *
 * Khoá: (1) thứ tự hàng do MÁY CHỦ quyết (khác thứ tự người dùng chọn) và không có nút đổi thứ tự; (2) dựng gửi ĐÚNG
 * id theo thứ tự máy chủ + dấu `phien_ban_kiem`; (3) "Chốt" khoá khi còn dòng bị chặn / đang kiểm; (4) khối xác nhận số;
 * (5) 409 `du_lieu_doi_tu_luc_kiem` ⇒ về bước kiểm tra; (6) dữ liệu cá nhân (từ khoá, CCCD) không vào URL.
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS } from "@/hooks/admin/useCouncilDocuments"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"

import { CouncilNewSetClient } from "./CouncilNewSetClient"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/admin/council-documents/moi",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"
const CCCD_GIA = (n: number) => "099" + "999" + String(n).padStart(6, "0")
const QUYEN = { ...NO_COUNCIL_PERMISSIONS, tao_bo: true, kiem_truoc: true, tim_ho_so: true, doi_ma: true }

const HO_SO = [
  { profile_id: 11, ho_ten: "Nguyễn Văn A", cccd: CCCD_GIA(11), nganh_nhan: "CĐ Kế toán", trinh_do: "Cao đẳng", duong_xet_nhan: "Xét học bạ", trang_thai: "approved", trang_thai_nhan: "Đã duyệt" },
  { profile_id: 12, ho_ten: "Trần Thị B", cccd: CCCD_GIA(12), nganh_nhan: "CĐ Kế toán", trinh_do: "Cao đẳng", duong_xet_nhan: null, trang_thai: "resubmitted", trang_thai_nhan: "Nộp lại" },
  { profile_id: 13, ho_ten: "Lê Văn C", cccd: CCCD_GIA(13), nganh_nhan: "TC Điện", trinh_do: "Trung cấp", duong_xet_nhan: "Xét học bạ", trang_thai: "approved", trang_thai_nhan: "Đã duyệt" },
]

const BO_MOI = {
  id: 9, nguoi_tao_id: 1, tao_luc: "2026-11-11T01:00:00Z", moc_chup: "2026-11-11T00:59:00Z", unit_id: null,
  trinh_do: "Cao đẳng", so_ho_so: 2, so_tep: 6, kich_thuoc_tong: 100, nam_hoc: 2026, tham_so_quyet_dinh: null,
  thong_tin_dung: {}, tep: [],
}

interface Cau {
  /** mức kiểm trước theo id hồ sơ (mặc định duoc_dung) */
  muc?: Record<number, "duoc_dung" | "can_xac_nhan" | "bi_chan">
  tao?: () => Response
  /** máy chủ báo người gọi có xác nhận được hay không (⏳ `nguoi_goi_duoc_xac_nhan`); vắng ⇒ không gửi trường */
  xacNhanDuoc?: boolean
  /** sau lần kiểm trước thứ n (đếm từ 1), đổi mức (mô phỏng người dùng sửa hồ sơ ở thẻ khác) */
  doiMucTuLanKiem?: { lan: number; muc: Record<number, "duoc_dung" | "can_xac_nhan" | "bi_chan"> }
}

let kiemBodies: { academic_year: number; profile_ids: number[] }[] = []
let timBodies: Record<string, unknown>[] = []
let taoBodies: Record<string, unknown>[] = []
let doiMaBodies: Record<string, unknown>[] = []
let urls: string[] = []

function dung(cau: Cau = {}) {
  server.use(
    http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: QUYEN })),
    http.get(`${API}/api/admissions/academic-years`, () => HttpResponse.json([2026, 2025])),
    http.get(`${API}/api/admission-config/programs`, () =>
      HttpResponse.json([{ id: 1, name: "CĐ Kế toán", code: "K", degree_level: "Cao đẳng" }]),
    ),
    http.post(`${API}${P}/sets/tim-ho-so`, async ({ request }) => {
      urls.push(request.url)
      timBodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json({ tong: 3, page: 1, page_size: 25, dong: HO_SO })
    }),
    http.post(`${API}${P}/sets/kiem-truoc`, async ({ request }) => {
      urls.push(request.url)
      const b = (await request.json()) as { academic_year: number; profile_ids: number[] }
      kiemBodies.push(b)
      const muc = cau.doiMucTuLanKiem && kiemBodies.length >= cau.doiMucTuLanKiem.lan ? cau.doiMucTuLanKiem.muc : (cau.muc ?? {})
      // MÁY CHỦ sắp theo id tăng dần — KHÁC thứ tự người dùng chọn / gửi.
      const ids = [...b.profile_ids].sort((x, y) => x - y)
      const dong = ids.map((id, i) => {
        const h = HO_SO.find((x) => x.profile_id === id)!
        const m = muc[id] ?? "duoc_dung"
        return {
          stt: i + 1, stt_qd: i + 1, profile_id: id, ho_ten: h.ho_ten, trang_thai: h.trang_thai, trang_thai_nhan: h.trang_thai_nhan,
          nganh_nhan: h.nganh_nhan, trinh_do: h.trinh_do, duong_xet_nhan: h.duong_xet_nhan, diem_in: "20,5", muc: m,
          ly_do: m === "duoc_dung" ? [] : [{ ma: "ly_do_x", cau: m === "bi_chan" ? "Thiếu thông tin ngành." : "Hồ sơ nộp lại." }],
        }
      })
      const dem = (m: string) => dong.filter((d) => d.muc === m).length
      const xn: Record<string, number> = {}
      for (const d of dong) if (d.muc === "can_xac_nhan") xn[d.trang_thai] = (xn[d.trang_thai] ?? 0) + 1
      return HttpResponse.json({
        kiem_luc: "2026-11-11T02:00:00Z",
        phien_ban_kiem: "PBK-" + kiemBodies.length,
        dong,
        khong_tim_thay: [],
        tom_tat: {
          tong: dong.length, duoc_dung: dem("duoc_dung"), can_xac_nhan: dem("can_xac_nhan"), bi_chan: dem("bi_chan"),
          theo_nganh: [{ nganh_nhan: "CĐ Kế toán", trinh_do: "Cao đẳng", so: dong.length }],
          can_xac_nhan_theo_trang_thai: xn, so_nhom: 1, du_kien_so_tep: 4,
          ...(cau.xacNhanDuoc !== undefined ? { nguoi_goi_duoc_xac_nhan: cau.xacNhanDuoc } : {}),
        },
      })
    }),
    http.post(`${API}${P}/sets/doi-ma`, async ({ request }) => {
      urls.push(request.url)
      const b = (await request.json()) as Record<string, unknown>
      doiMaBodies.push(b)
      return HttpResponse.json({ profile_ids: [13], dong_loi: [{ dong: 2, ly_do: "khong_khop" }] })
    }),
    http.post(`${API}${P}/sets`, async ({ request }) => {
      urls.push(request.url)
      taoBodies.push((await request.json()) as Record<string, unknown>)
      return cau.tao ? cau.tao() : HttpResponse.json(BO_MOI, { status: 201 })
    }),
  )
}

function ve() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilNewSetClient />
    </QueryClientProvider>,
  )
}

/** Đã chọn năm học 2026 và tick hồ sơ theo thứ tự cho trước; đợi kiểm trước xong. */
async function chon(ids: number[]) {
  await screen.findByTestId("buoc-chon")
  fireEvent.change(await screen.findByTestId("loc-nam"), { target: { value: "2026" } })
  for (const id of ids) {
    fireEvent.click(await screen.findByTestId(`chon-${id}`))
  }
  await waitFor(() => expect(screen.getByTestId("tom-tat-tong")).toBeTruthy(), { timeout: 4000 })
}

beforeEach(() => {
  kiemBodies = []
  timBodies = []
  taoBodies = []
  doiMaBodies = []
  urls = []
  push.mockClear()
  useCouncilSelectionStore.getState().lamSach()
  vi.spyOn(console, "error").mockImplementation(() => undefined)
})

describe("trang /moi — luồng chính", () => {
  it("chọn → kiểm tra → tham số → dựng: thứ tự do MÁY CHỦ quyết, id gửi dựng đúng thứ tự máy chủ + dấu kiểm trước", async () => {
    dung()
    ve()
    await chon([12, 11]) // người dùng chọn 12 trước, 11 sau
    expect(screen.getByTestId("tom-tat-tong").textContent).toBe("2 hồ sơ đang chọn")
    // gửi kiểm trước: ĐÚNG năm + id theo thứ tự chọn (máy chủ sắp lại)
    expect(kiemBodies.at(-1)).toEqual({ academic_year: 2026, profile_ids: [12, 11] })

    fireEvent.click(screen.getByTestId("tiep-kiem-tra"))
    const bang = await screen.findByTestId("bang-kiem-tra")
    const thuTu = within(bang).getAllByTestId(/^dong-\d+$/).map((r) => r.getAttribute("data-testid"))
    expect(thuTu).toEqual(["dong-11", "dong-12"]) // thứ tự máy chủ, KHÔNG phải thứ tự chọn
    expect(screen.getByTestId("stt-11").textContent).toContain("1")
    expect(screen.queryByRole("button", { name: /đổi thứ tự|lên|xuống|kéo/i })).toBeNull()

    fireEvent.click(screen.getByTestId("chot-tiep"))
    const soQd = await screen.findByLabelText("Số Quyết định")
    fireEvent.change(soQd, { target: { value: "501" } })
    fireEvent.click(screen.getByTestId("tham-so-tiep"))

    expect((await screen.findByTestId("du-kien-tep")).textContent).toContain("Sẽ tạo 4 tệp")
    fireEvent.click(screen.getByTestId("dung-bo"))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/council-documents/9?buoc=tai"))

    expect(taoBodies).toHaveLength(1)
    expect(taoBodies[0]).toEqual({
      profile_ids: [11, 12], // thứ tự MÁY CHỦ trả, không phải [12, 11]
      phien_ban_kiem: "PBK-" + kiemBodies.length,
      academic_year: 2026,
      tham_so_quyet_dinh: { so_quyet_dinh: "501" },
    })
    // dựng xong ⇒ xoá lựa chọn + tham số khỏi bộ nhớ
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([])
    expect(useCouncilSelectionStore.getState().namHoc).toBeNull()
  })

  it("dữ liệu cá nhân: từ khoá tìm / CCCD chỉ ở thân JSON; không URL / storage mang chúng", async () => {
    dung()
    ve()
    await screen.findByTestId("buoc-chon")
    fireEvent.change(await screen.findByTestId("loc-nam"), { target: { value: "2026" } })
    fireEvent.change(screen.getByTestId("loc-tu-khoa"), { target: { value: CCCD_GIA(11) } })
    await waitFor(() => expect(timBodies.some((b) => b.tu_khoa === CCCD_GIA(11))).toBe(true), { timeout: 3000 })
    for (const u of urls) {
      expect(u).not.toContain(CCCD_GIA(11))
      expect(u).not.toContain("tu_khoa")
      expect(new URL(u).search).toBe("")
    }
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(CCCD_GIA(11))
  })

  it("bảng hiện cột Kiểm trước CHỈ cho hồ sơ đã chọn; chưa chọn ⇒ '—'", async () => {
    dung({ muc: { 11: "duoc_dung" } })
    ve()
    await chon([11])
    await waitFor(() => expect(screen.getByTestId("kiem-11").textContent).toBe("Được dựng"), { timeout: 4000 })
    expect(screen.getByTestId("kiem-12").textContent).toBe("—")
  })
})

describe("bước 2 — chốt danh sách", () => {
  it("còn dòng BỊ CHẶN ⇒ 'Chốt' bị khoá, hiện nguyên văn lý do của cổng; bỏ dòng ấy ⇒ kiểm lại ⇒ mở", async () => {
    dung({ muc: { 12: "bi_chan" } })
    ve()
    await chon([11, 12])
    fireEvent.click(screen.getByTestId("tiep-kiem-tra"))
    await screen.findByTestId("bang-kiem-tra")
    expect((screen.getByTestId("chot-tiep") as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId("ly-do-khoa-chot").textContent).toContain("1 dòng bị chặn")
    expect(screen.getByTestId("ly-do-12").textContent).toBe("Thiếu thông tin ngành.") // nguyên văn

    fireEvent.click(screen.getByTestId("bo-khoi-bo-12"))
    await waitFor(() => expect((screen.getByTestId("chot-tiep") as HTMLButtonElement).disabled).toBe(false), { timeout: 4000 })
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([11])
  })

  it("trong lúc kiểm lại: 'Chốt' bị khoá và KHÔNG hiện số cũ như còn đúng", async () => {
    dung()
    ve()
    await chon([11])
    fireEvent.click(screen.getByTestId("tiep-kiem-tra"))
    await screen.findByTestId("bang-kiem-tra")
    expect((screen.getByTestId("chot-tiep") as HTMLButtonElement).disabled).toBe(false)
    act(() => useCouncilSelectionStore.getState().them([12])) // danh sách đổi ⇒ đang chờ 600 ms
    expect((screen.getByTestId("chot-tiep") as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId("tom-tat-dang-kiem")).toBeTruthy()
    expect(screen.queryByTestId("tom-tat-tong")).toBeNull()
  })

  it("'Mở hồ sơ để sửa' là liên kết thẻ mới tới /admissions/{id} (id nội bộ, không dữ liệu cá nhân)", async () => {
    dung()
    ve()
    await chon([11])
    fireEvent.click(screen.getByTestId("tiep-kiem-tra"))
    const a = (await screen.findByTestId("mo-ho-so-11")) as HTMLAnchorElement
    expect(a.getAttribute("href")).toBe("/admissions/11")
    expect(a.getAttribute("target")).toBe("_blank")
    expect(a.getAttribute("rel")).toContain("noopener")
  })
})

describe("bước 4 — dựng", () => {
  async function denBuoc4(cau: Cau) {
    dung(cau)
    ve()
    await chon([11, 12])
    fireEvent.click(screen.getByTestId("tiep-kiem-tra"))
    await screen.findByTestId("bang-kiem-tra")
    fireEvent.click(screen.getByTestId("chot-tiep"))
    fireEvent.click(await screen.findByTestId("tham-so-tiep"))
    await screen.findByTestId("buoc-dung")
  }

  it("hồ sơ CẦN XÁC NHẬN ⇒ khối gõ số; nút Dựng khoá tới khi gõ khớp số máy chủ báo; thân mang xac_nhan_trang_thai", async () => {
    await denBuoc4({ muc: { 12: "can_xac_nhan" } })
    expect(screen.getByTestId("khoi-xac-nhan")).toBeTruthy()
    const dung_ = screen.getByTestId("dung-bo") as HTMLButtonElement
    expect(dung_.disabled).toBe(true)
    fireEvent.change(screen.getByTestId("xac-nhan-resubmitted"), { target: { value: "2" } }) // sai (máy chủ báo 1)
    expect(dung_.disabled).toBe(true)
    fireEvent.change(screen.getByTestId("xac-nhan-resubmitted"), { target: { value: "1" } })
    expect(dung_.disabled).toBe(false)
    fireEvent.click(dung_)
    await waitFor(() => expect(taoBodies).toHaveLength(1))
    expect(taoBodies[0].xac_nhan_trang_thai).toEqual({ resubmitted: 1 })
  })

  it("máy chủ nói người gọi KHÔNG xác nhận được ⇒ khối xác nhận khoá + câu giải thích; nút Dựng khoá", async () => {
    await denBuoc4({ muc: { 12: "can_xac_nhan" }, xacNhanDuoc: false })
    expect(screen.getByTestId("khong-xac-nhan-duoc").textContent).toContain("không xác nhận được")
    expect((screen.getByTestId("xac-nhan-resubmitted") as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByTestId("dung-bo") as HTMLButtonElement).disabled).toBe(true)
    expect(taoBodies).toHaveLength(0)
  })

  it("máy chủ nói người gọi xác nhận được (true) ⇒ không câu khoá; gõ khớp thì dựng được", async () => {
    await denBuoc4({ muc: { 12: "can_xac_nhan" }, xacNhanDuoc: true })
    expect(screen.queryByTestId("khong-xac-nhan-duoc")).toBeNull()
    fireEvent.change(screen.getByTestId("xac-nhan-resubmitted"), { target: { value: "1" } })
    expect((screen.getByTestId("dung-bo") as HTMLButtonElement).disabled).toBe(false)
  })

  it("không có hồ sơ cần xác nhận ⇒ không khối xác nhận và KHÔNG gửi xac_nhan_trang_thai", async () => {
    await denBuoc4({})
    expect(screen.queryByTestId("khoi-xac-nhan")).toBeNull()
    fireEvent.click(screen.getByTestId("dung-bo"))
    await waitFor(() => expect(taoBodies).toHaveLength(1))
    expect("xac_nhan_trang_thai" in taoBodies[0]).toBe(false)
    expect("tham_so_quyet_dinh" in taoBodies[0]).toBe(false) // không điền ô nào ⇒ không gửi tham số
  })

  it("409 du_lieu_doi_tu_luc_kiem ⇒ về bước 2 và kiểm lại; không chuyển trang", async () => {
    await denBuoc4({
      tao: () =>
        HttpResponse.json(
          { detail: "Dữ liệu đã đổi từ lúc kiểm — bấm Kiểm tra lại.", error_code: "CONFLICT", ma_loi: "du_lieu_doi_tu_luc_kiem" },
          { status: 409 },
        ),
    })
    const soLanKiem = kiemBodies.length
    fireEvent.click(screen.getByTestId("dung-bo"))
    expect(await screen.findByTestId("buoc-kiem-tra")).toBeTruthy()
    await waitFor(() => expect(kiemBodies.length).toBeGreaterThan(soLanKiem))
    expect(push).not.toHaveBeenCalled()
  })

  it("lỗi miền khác (422 / 400) ⇒ hiện nguyên văn câu của máy chủ, vẫn ở bước 4", async () => {
    await denBuoc4({ tao: () => HttpResponse.json({ detail: "Đợt số và tháng phải cùng điền.", error_code: "DATA_VALIDATION_ERROR" }, { status: 400 }) })
    fireEvent.click(screen.getByTestId("dung-bo"))
    expect((await screen.findByTestId("dung-bo-loi")).textContent).toContain("Đợt số và tháng phải cùng điền.")
    expect(screen.getByTestId("buoc-dung")).toBeTruthy()
  })
})

describe("điều kiện vào trang", () => {
  it("thiếu cờ kiem_truoc ⇒ báo chưa sẵn sàng, KHÔNG gọi tim-ho-so", async () => {
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...NO_COUNCIL_PERMISSIONS, tao_bo: true } })))
    server.use(http.post(`${API}${P}/sets/tim-ho-so`, async ({ request }) => { timBodies.push((await request.json()) as Record<string, unknown>); return HttpResponse.json({}) }))
    ve()
    expect(await screen.findByTestId("moi-chua-san-sang")).toBeTruthy()
    expect(timBodies).toHaveLength(0)
  })

  it("thiếu cờ tim_ho_so (route tìm hồ sơ chưa có) ⇒ báo chưa sẵn sàng, KHÔNG gọi tim-ho-so", async () => {
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...NO_COUNCIL_PERMISSIONS, tao_bo: true, kiem_truoc: true } })))
    server.use(http.post(`${API}${P}/sets/tim-ho-so`, async ({ request }) => { timBodies.push((await request.json()) as Record<string, unknown>); return HttpResponse.json({}) }))
    ve()
    expect(await screen.findByTestId("moi-chua-san-sang")).toBeTruthy()
    expect(timBodies).toHaveLength(0)
  })

  it("thiếu cờ doi_ma ⇒ vẫn chọn được từ danh sách nhưng KHÔNG có cách phụ dán mã", async () => {
    dung()
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...QUYEN, doi_ma: false } })))
    ve()
    await screen.findByTestId("buoc-chon")
    fireEvent.change(await screen.findByTestId("loc-nam"), { target: { value: "2026" } })
    await screen.findByTestId("chon-11")
    expect(screen.queryByTestId("dan-ma")).toBeNull()
  })

  it("không có quyền tao_bo ⇒ không vào được", async () => {
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: NO_COUNCIL_PERMISSIONS })))
    ve()
    expect(await screen.findByTestId("council-forbidden")).toBeTruthy()
  })
})

describe("danh sách chọn", () => {
  it("đổi năm khi đang có danh sách ⇒ hỏi; đồng ý ⇒ xoá danh sách; giữ nguyên ⇒ còn", async () => {
    dung()
    ve()
    await chon([11])
    fireEvent.change(screen.getByTestId("loc-nam"), { target: { value: "2025" } })
    expect(await screen.findByTestId("doi-nam-dialog")).toBeTruthy()
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([11]) // chưa xoá
    fireEvent.click(screen.getByText("Giữ nguyên"))
    await waitFor(() => expect(screen.queryByTestId("doi-nam-dialog")).toBeNull())
    expect(useCouncilSelectionStore.getState().namHoc).toBe(2026)

    fireEvent.change(screen.getByTestId("loc-nam"), { target: { value: "2025" } })
    fireEvent.click(await screen.findByTestId("doi-nam-dong-y"))
    await waitFor(() => expect(useCouncilSelectionStore.getState().idHoSo).toEqual([]))
    expect(useCouncilSelectionStore.getState().namHoc).toBe(2025)
  })

  it("dán mã: danh sách mã chỉ ở thân JSON; id thêm vào danh sách; dòng lỗi báo SỐ DÒNG, không giá trị", async () => {
    dung()
    ve()
    await screen.findByTestId("buoc-chon")
    fireEvent.change(await screen.findByTestId("loc-nam"), { target: { value: "2026" } })
    const o = await screen.findByTestId("dan-ma-input")
    fireEvent.change(o, { target: { value: `${CCCD_GIA(13)}\n${CCCD_GIA(99)}` } })
    fireEvent.click(screen.getByTestId("dan-ma-them"))
    await waitFor(() => expect(doiMaBodies).toHaveLength(1))
    expect(doiMaBodies[0]).toEqual({ academic_year: 2026, ma_ho_so: [CCCD_GIA(13), CCCD_GIA(99)] })
    expect(await screen.findByTestId("dan-ma-dong-loi")).toBeTruthy()
    expect(screen.getByTestId("dan-ma-dong-loi").textContent).toBe("Dòng 2: không khớp hồ sơ nào của năm học đã chọn")
    expect(screen.getByTestId("dan-ma-dong-loi").textContent).not.toContain(CCCD_GIA(99))
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([13])
    for (const u of urls) expect(u).not.toContain(CCCD_GIA(13))
  })

  it("xoá hết danh sách khi đang ở bước 2 ⇒ về bước 1; chọn lại từ đầu KHÔNG nhảy lại bước 2", async () => {
    dung()
    ve()
    await chon([11])
    fireEvent.click(screen.getByTestId("tiep-kiem-tra"))
    await screen.findByTestId("buoc-kiem-tra")
    act(() => useCouncilSelectionStore.getState().boTatCa())
    expect(await screen.findByTestId("buoc-chon")).toBeTruthy()
    act(() => useCouncilSelectionStore.getState().them([12]))
    expect(screen.getByTestId("buoc-chon")).toBeTruthy() // vẫn bước 1
    expect(screen.queryByTestId("buoc-kiem-tra")).toBeNull()
  })

  it("cảnh báo beforeunload CHỈ khi đang có danh sách; gỡ khi rỗng", async () => {
    const them = vi.spyOn(window, "addEventListener")
    const go = vi.spyOn(window, "removeEventListener")
    dung()
    ve()
    await chon([11])
    expect(them.mock.calls.some((c) => c[0] === "beforeunload")).toBe(true)
    act(() => useCouncilSelectionStore.getState().boTatCa())
    await waitFor(() => expect(go.mock.calls.some((c) => c[0] === "beforeunload")).toBe(true))
  })
})
