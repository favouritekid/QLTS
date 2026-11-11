/**
 * Văn bản Hội đồng — bước 6 "Ghi nhận": giao thức lượt gửi (đặc tả bản 2 mục 3.7.3 – 3.7.5, 5.6.1).
 *
 * Mỗi ca khoá MỘT bất biến. Phần quan trọng nhất: mọi kết cục không rõ (mất mạng, 5xx, 404, 2xx sai dạng, phân xử mất
 * phản hồi, `ket_qua` lạ) phải ra "Chưa xác định" — KHÔNG BAO GIỜ "chưa ghi". Trạng thái duy nhất mang nghĩa "chưa ghi"
 * là `chua_ghi_da_chan`, và chỉ khi máy chủ nói `ket_qua: "chua_ghi_da_chan"`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { useGhiNhanQuyetDinh, type DuLieuGuiGhiNhan } from "./useGhiNhanQuyetDinh"

const API = "http://localhost:8000"
const SET = 5
const MA = "11111111-2222-3333-4444-555555555555"
const MA_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
const GHI_CHU_NHAY_CAM = "GHI-CHU-NHAY-CAM-KHONG-DUOC-LO"

function qd(over: Record<string, unknown> = {}) {
  return {
    id: 7,
    loai: "trung_tuyen",
    trang_thai: "hieu_luc",
    can_bo: false,
    set_id: SET,
    so_quyet_dinh: "501",
    ngay_ky: "2026-09-08",
    pham_vi_so: 2026,
    so_ho_so: 3,
    ghi_nhan_boi_id: 1,
    ghi_nhan_luc: "2026-11-11T03:00:00Z",
    canh_bao_vuot_chi_tieu: [],
    ma_luot_gui: MA,
    lap_lai: false,
    ...over,
  }
}

function du_lieu(): DuLieuGuiGhiNhan {
  return {
    loai: "trung_tuyen",
    so_quyet_dinh: "501",
    ngay_ky: "2026-09-08",
    xac_nhan_so_ho_so: 3,
    xac_nhan_khop_ban_in: true,
    ghi_chu_mau: GHI_CHU_NHAY_CAM,
    scan: new File(["%PDF-1.4 gia"], "scan.pdf", { type: "application/pdf" }),
  }
}

function qcNhuApp() {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 5 * 60 * 1000, gcTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: false },
      mutations: { retry: false },
    },
  })
}
function boc(qc: QueryClient) {
  const W = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  W.displayName = "Boc"
  return W
}

let consoleSpies: ReturnType<typeof vi.spyOn>[] = []
beforeEach(() => {
  consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  )
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
})

interface Dem {
  mo: number
  gui: number
  chan: number
  maTrongForm: string[]
}

type Tra = () => Response | Promise<Response>
interface Cau {
  mo?: Tra
  gui?: Tra
  chan?: Tra
  ds?: Tra
}

/** Dựng 4 route lượt gửi; đếm số lần gọi và mã lượt thật sự nằm trong thân form. */
function dung(c: Cau): Dem {
  const dem: Dem = { mo: 0, gui: 0, chan: 0, maTrongForm: [] }
  server.use(
    http.post(`${API}${P}/sets/${SET}/luot-ghi-nhan`, () => {
      dem.mo++
      return c.mo ? c.mo() : HttpResponse.json({ ma: MA }, { status: 201 })
    }),
    http.post(`${API}${P}/decisions`, async ({ request }) => {
      dem.gui++
      try {
        const fd = await request.formData()
        dem.maTrongForm.push(String(fd.get("ma_luot_gui")))
      } catch {
        dem.maTrongForm.push("<khong-doc-duoc-form>")
      }
      return c.gui ? c.gui() : HttpResponse.json(qd(), { status: 201 })
    }),
    http.post(`${API}${P}/luot-ghi-nhan/:ma/chan`, () => {
      dem.chan++
      return c.chan ? c.chan() : HttpResponse.json({ ket_qua: "dang_xu_ly" })
    }),
    http.get(`${API}${P}/sets/${SET}/luot-ghi-nhan`, () =>
      c.ds ? c.ds() : HttpResponse.json([]),
    ),
  )
  return dem
}

function dung_hook() {
  const qc = qcNhuApp()
  const r = renderHook(() => useGhiNhanQuyetDinh(SET), { wrapper: boc(qc) })
  return { qc, ...r }
}

async function guiXong(h: ReturnType<typeof dung_hook>, dl = du_lieu()) {
  await act(async () => {
    await h.result.current.gui(dl)
  })
}

const luot = (ma: string, trang_thai: string, extra: Record<string, unknown> = {}) => ({
  ma,
  trang_thai,
  tao_luc: "2026-11-11T02:00:00Z",
  ket_thuc_luc: trang_thai === "cho_gui" ? null : "2026-11-11T02:05:00Z",
  decision_id: trang_thai === "da_ghi" ? 7 : null,
  ...extra,
})

describe("gửi ghi nhận — đường thành công", () => {
  it("mở lượt ĐÚNG MỘT lần rồi gửi kèm đúng mã; kết quả lấy từ DTO máy chủ", async () => {
    const dem = dung({})
    const h = dung_hook()
    await guiXong(h)
    expect(dem.mo).toBe(1)
    expect(dem.gui).toBe(1)
    expect(dem.maTrongForm).toEqual([MA])
    const t = h.result.current.trangThai
    expect(t.kieu).toBe("da_ghi")
    if (t.kieu === "da_ghi") {
      expect(t.quyetDinh?.id).toBe(7)
      expect(t.quyetDinh?.lap_lai).toBe(false)
    }
  })

  it("gửi LẶP (200, lap_lai) ⇒ vẫn là da_ghi với văn bản cũ", async () => {
    dung({ gui: () => HttpResponse.json(qd({ lap_lai: true }), { status: 200 }) })
    const h = dung_hook()
    await guiXong(h)
    const t = h.result.current.trangThai
    expect(t.kieu).toBe("da_ghi")
    if (t.kieu === "da_ghi") expect(t.quyetDinh?.lap_lai).toBe(true)
  })

  it("chống bấm đúp: hai lần gui đồng thời ⇒ chỉ MỘT lần mở lượt và MỘT lần gửi", async () => {
    const dem = dung({})
    const h = dung_hook()
    await act(async () => {
      const a = h.result.current.gui(du_lieu())
      const b = h.result.current.gui(du_lieu())
      await Promise.all([a, b])
    })
    expect(dem.mo).toBe(1)
    expect(dem.gui).toBe(1)
  })
})

describe("gửi ghi nhận — máy chủ TỪ CHỐI dứt khoát", () => {
  it("400 (từ chối nghiệp vụ) ⇒ bi_tu_choi/sua_va_gui_lai; gửi lại dùng CÙNG mã và KHÔNG mở lượt mới", async () => {
    let lan = 0
    const dem = dung({
      gui: () => {
        lan++
        return lan === 1
          ? HttpResponse.json({ detail: "Số hồ sơ gõ lại không khớp.", error_code: "BUSINESS_RULE_VIOLATION" }, { status: 400 })
          : HttpResponse.json(qd(), { status: 201 })
      },
    })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "bi_tu_choi", huong: "sua_va_gui_lai" })
    await guiXong(h)
    expect(dem.mo).toBe(1) // không mở lượt thứ hai
    expect(dem.maTrongForm).toEqual([MA, MA]) // cùng mã
    expect(h.result.current.trangThai.kieu).toBe("da_ghi")
  })

  it("409 luot_da_chan ⇒ mo_luot_moi; lần gửi sau mở lượt MỚI", async () => {
    let lan = 0
    let mo = 0
    const dem = dung({
      mo: () => HttpResponse.json({ ma: ++mo === 1 ? MA : MA_2 }, { status: 201 }),
      gui: () => {
        lan++
        return lan === 1
          ? HttpResponse.json({ detail: "Lượt gửi đã bị chặn.", error_code: "CONFLICT", ma_loi: "luot_da_chan" }, { status: 409 })
          : HttpResponse.json(qd({ ma_luot_gui: MA_2 }), { status: 201 })
      },
    })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "bi_tu_choi", huong: "mo_luot_moi" })
    await guiXong(h)
    expect(dem.mo).toBe(2)
    expect(dem.maTrongForm).toEqual([MA, MA_2])
  })

  it("409 luot_da_dung_noi_dung_khac ⇒ huong phan_xu; phân xử trả da_ghi kèm DTO", async () => {
    dung({
      gui: () =>
        HttpResponse.json(
          { detail: "Lượt này đã ghi với nội dung khác.", error_code: "CONFLICT", ma_loi: "luot_da_dung_noi_dung_khac", decision_id: 7 },
          { status: 409 },
        ),
      chan: () => HttpResponse.json({ ket_qua: "da_ghi", quyet_dinh: qd() }),
    })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "bi_tu_choi", huong: "phan_xu" })
    await act(async () => {
      await h.result.current.phanXu()
    })
    expect(h.result.current.trangThai.kieu).toBe("da_ghi")
  })
})

describe("gửi ghi nhận — KHÔNG RÕ ⇒ luôn 'chưa xác định', không bao giờ 'chưa ghi'", () => {
  it("mất mạng lúc gửi ⇒ chua_xac_dinh (mang đúng mã lượt), KHÔNG phải bi_tu_choi", async () => {
    dung({ gui: () => HttpResponse.error() })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", ma: MA, lyDo: "gui" })
  })

  it.each([
    ["500", () => HttpResponse.json({ detail: "x" }, { status: 500 })],
    ["502", () => new HttpResponse("bad gateway", { status: 502 })],
    ["503 (không phải đóng băng)", () => HttpResponse.json({ detail: "x" }, { status: 503 })],
    ["504 hết giờ", () => new HttpResponse(null, { status: 504 })],
    ["404", () => HttpResponse.json({ detail: "Không có." }, { status: 404 })],
    ["401", () => HttpResponse.json({ detail: "hết phiên" }, { status: 401 })],
  ])("%s ⇒ chua_xac_dinh (không suy chưa ghi)", async (_ten, tra) => {
    dung({ gui: tra })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", ma: MA })
  })

  it("2xx nhưng thân sai dạng (Zod nổ) ⇒ chua_xac_dinh: máy chủ ĐÃ trả 2xx nên có thể đã ghi", async () => {
    dung({ gui: () => HttpResponse.json({ khong: "dung dang" }, { status: 201 }) })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai.kieu).toBe("chua_xac_dinh")
  })

  it("không có đường 'gửi lại' sau chua_xac_dinh: phanXu dùng mã cũ, không mở lượt mới", async () => {
    const dem = dung({ gui: () => HttpResponse.error() })
    const h = dung_hook()
    await guiXong(h)
    await act(async () => {
      await h.result.current.phanXu()
    })
    expect(dem.mo).toBe(1)
    expect(dem.chan).toBe(1)
  })
})

describe("phân xử — bốn kết quả", () => {
  async function denChuaXacDinh(tra: Tra) {
    const dem = dung({ gui: () => HttpResponse.error(), chan: tra })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai.kieu).toBe("chua_xac_dinh")
    await act(async () => {
      await h.result.current.phanXu()
    })
    return { h, dem }
  }

  it("da_ghi + quyet_dinh ⇒ da_ghi kèm DTO", async () => {
    const { h } = await denChuaXacDinh(() => HttpResponse.json({ ket_qua: "da_ghi", quyet_dinh: qd() }))
    const t = h.result.current.trangThai
    expect(t.kieu).toBe("da_ghi")
    if (t.kieu === "da_ghi") expect(t.quyetDinh?.so_quyet_dinh).toBe("501")
  })

  it("da_ghi KHÔNG kèm quyet_dinh ⇒ vẫn da_ghi (chi tiết null), không rơi về 'chưa ghi'", async () => {
    const { h } = await denChuaXacDinh(() => HttpResponse.json({ ket_qua: "da_ghi" }))
    expect(h.result.current.trangThai).toEqual({ kieu: "da_ghi", quyetDinh: null })
  })

  it("chua_ghi_da_chan ⇒ chua_ghi_da_chan (trạng thái DUY NHẤT nói 'chưa ghi'); lần gửi sau mở lượt MỚI", async () => {
    const { h, dem } = await denChuaXacDinh(() => HttpResponse.json({ ket_qua: "chua_ghi_da_chan" }))
    expect(h.result.current.trangThai.kieu).toBe("chua_ghi_da_chan")
    server.use(http.post(`${API}${P}/decisions`, () => HttpResponse.json(qd(), { status: 201 })))
    await guiXong(h)
    expect(dem.mo).toBe(2)
  })

  it("dang_xu_ly ⇒ vẫn chua_xac_dinh (lyDo dang_xu_ly)", async () => {
    const { h } = await denChuaXacDinh(() => HttpResponse.json({ ket_qua: "dang_xu_ly" }))
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", lyDo: "dang_xu_ly" })
  })

  it("ket_qua LẠ ⇒ chua_xac_dinh (không suy)", async () => {
    const { h } = await denChuaXacDinh(() => HttpResponse.json({ ket_qua: "gia_tri_moi_cua_may_chu" }))
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", lyDo: "van_chua_ro" })
  })

  it.each([
    ["mất mạng", () => HttpResponse.error()],
    ["404 mã không có", () => HttpResponse.json({ detail: "x" }, { status: 404 })],
    ["500", () => HttpResponse.json({ detail: "x" }, { status: 500 })],
    ["200 sai dạng", () => HttpResponse.json({ linh_tinh: 1 })],
  ])("phân xử %s ⇒ chua_xac_dinh (phan_xu_loi), KHÔNG chưa ghi", async (_t, tra) => {
    const { h } = await denChuaXacDinh(tra)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", lyDo: "phan_xu_loi" })
  })

  it("phân xử lặp khi vẫn chưa rõ: gọi lại được (luỹ đẳng)", async () => {
    const { h, dem } = await denChuaXacDinh(() => HttpResponse.json({ ket_qua: "dang_xu_ly" }))
    await act(async () => {
      await h.result.current.phanXu()
    })
    expect(dem.chan).toBe(2)
  })
})

describe("mở lượt", () => {
  it("409 luot_dang_cho ⇒ chua_xac_dinh với mã CŨ của máy chủ; KHÔNG gửi POST /decisions", async () => {
    const dem = dung({
      mo: () =>
        HttpResponse.json(
          { detail: "Bộ đang có lượt gửi chưa rõ.", error_code: "CONFLICT", ma_loi: "luot_dang_cho", ma: MA_2, tao_luc: "2026-11-11T01:00:00Z" },
          { status: 409 },
        ),
    })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", ma: MA_2, lyDo: "mo_luot" })
    expect(dem.gui).toBe(0)
  })

  it("mất mạng lúc mở nhưng danh sách lượt thấy cho_gui ⇒ chua_xac_dinh với mã ấy; không gửi", async () => {
    const dem = dung({ mo: () => HttpResponse.error(), ds: () => HttpResponse.json([luot(MA_2, "cho_gui")]) })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai).toMatchObject({ kieu: "chua_xac_dinh", ma: MA_2 })
    expect(dem.gui).toBe(0)
  })

  it("mất mạng lúc mở và danh sách không có lượt chờ ⇒ loi_mo_luot (CHƯA gửi gì, thử lại an toàn)", async () => {
    const dem = dung({ mo: () => HttpResponse.error(), ds: () => HttpResponse.json([luot(MA_2, "da_chan")]) })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai.kieu).toBe("loi_mo_luot")
    expect(dem.gui).toBe(0)
  })

  it("409 luot_dang_thay_doi + danh sách rỗng ⇒ loi_mo_luot, không tự mở lại", async () => {
    const dem = dung({
      mo: () => HttpResponse.json({ detail: "x", error_code: "CONFLICT", ma_loi: "luot_dang_thay_doi", ma: null }, { status: 409 }),
    })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai.kieu).toBe("loi_mo_luot")
    expect(dem.mo).toBe(1)
    expect(dem.gui).toBe(0)
  })

  it("404 lúc mở ⇒ bo_khong_con", async () => {
    dung({ mo: () => HttpResponse.json({ detail: "Không có bộ." }, { status: 404 }) })
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai.kieu).toBe("bo_khong_con")
  })
})

describe("khôi phục sau tải lại trang", () => {
  it("có lượt cho_gui ⇒ vào thẳng chua_xac_dinh với giờ tạo của lượt, không lưu mã ở đâu ngoài bộ nhớ", async () => {
    const dem = dung({})
    const h = dung_hook()
    act(() => h.result.current.khoiPhuc([luot(MA, "cho_gui", { tao_luc: "2026-11-11T02:00:00Z" })]))
    expect(h.result.current.trangThai).toEqual({
      kieu: "chua_xac_dinh",
      ma: MA,
      luc: "2026-11-11T02:00:00Z",
      lyDo: "tai_lai_trang",
    })
    // nút phân xử dùng đúng mã vừa khôi phục
    server.use(http.post(`${API}${P}/luot-ghi-nhan/${MA}/chan`, () => HttpResponse.json({ ket_qua: "chua_ghi_da_chan" })))
    await act(async () => {
      await h.result.current.phanXu()
    })
    expect(h.result.current.trangThai.kieu).toBe("chua_ghi_da_chan")
    expect(dem.mo).toBe(0)
    expect(JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } }).includes(MA)).toBe(false)
  })

  it("không có lượt cho_gui (chỉ da_chan / da_ghi) ⇒ giữ nguyên nhap", () => {
    dung({})
    const h = dung_hook()
    act(() => h.result.current.khoiPhuc([luot(MA, "da_chan"), luot(MA_2, "da_ghi")]))
    expect(h.result.current.trangThai.kieu).toBe("nhap")
  })

  it("trạng thái lạ của lượt KHÔNG bị coi là đang chờ", () => {
    dung({})
    const h = dung_hook()
    act(() => h.result.current.khoiPhuc([luot(MA, "trang_thai_moi")]))
    expect(h.result.current.trangThai.kieu).toBe("nhap")
  })

  it("không ghi đè khi đang ở trạng thái khác nhap (đã da_ghi)", async () => {
    dung({})
    const h = dung_hook()
    await guiXong(h)
    expect(h.result.current.trangThai.kieu).toBe("da_ghi")
    act(() => h.result.current.khoiPhuc([luot(MA_2, "cho_gui")]))
    expect(h.result.current.trangThai.kieu).toBe("da_ghi")
  })
})

describe("không lộ dữ liệu", () => {
  it("sau gửi (thành công, bị từ chối, không rõ): MutationCache rỗng; không console / storage / URL mang mã lượt hay ghi chú", async () => {
    for (const tra of [
      () => HttpResponse.json(qd(), { status: 201 }),
      () => HttpResponse.json({ detail: "từ chối" }, { status: 400 }),
      () => HttpResponse.error(),
    ] as Tra[]) {
      dung({ gui: tra })
      const h = dung_hook()
      await guiXong(h)
      expect(h.qc.getMutationCache().getAll()).toHaveLength(0)
      const ngoai = JSON.stringify({
        c: consoleSpies.map((s) => s.mock.calls),
        l: { ...localStorage },
        s: { ...sessionStorage },
        u: window.location.href,
      })
      expect(ngoai.includes(MA), "mã lượt lọt ra ngoài bộ nhớ").toBe(false)
      expect(ngoai.includes(GHI_CHU_NHAY_CAM), "ghi chú lọt ra ngoài bộ nhớ").toBe(false)
      h.unmount()
    }
  })
})
