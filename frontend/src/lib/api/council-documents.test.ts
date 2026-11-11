/**
 * Văn bản Hội đồng — API client (lượt F) qua axios THẬT + MSW (không mạng thật).
 *
 * Khoá: (1) danh sách mã chỉ ở THÂN POST, đúng thứ tự, không vào URL / query,
 * không tới host nào khác; (2) không `console.*` mang mã ở mọi nhánh lỗi; (3) lỗi
 * máy chủ ⇒ câu cho người dùng: lỗi miền nguyên văn, 403 / 404 / 5xx câu cố định,
 * 422 chỉ `loc` + `msg` (không `input` / `ctx`); (4) tên tệp từ Content-Disposition.
 *
 * Mã giả SINH LÚC CHẠY (tỉnh 099 không tồn tại) — không có chuỗi 12 chữ số viết sẵn.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"
import { NO_COUNCIL_PERMISSIONS } from "@/hooks/admin/useCouncilDocuments"
import { CO_CHO_MAY_CHU, councilDocumentPermissionsSchema, councilQuotaWarningSchema } from "@/lib/zod/council-documents"
import {
  COUNCIL_DOCUMENTS_PREFIX as P,
  createCouncilSet,
  describeCouncilDocumentError,
  downloadCouncilSetFile,
  filenameFromContentDisposition,
  createCouncilSetByIds,
  downloadCouncilSetZip,
  getCouncilDocumentPermissions,
  getCouncilSet,
  getCouncilSetInputCodes,
  listCouncilDecisions,
  listCouncilDownloadLog,
  listCouncilSetCreators,
  listCouncilSetDeletions,
  listCouncilSets,
  previewCouncilSet,
  resolveCouncilCodes,
  searchCouncilProfiles,
} from "./council-documents"

const API = "http://localhost:8000"
const maGia = (n: number) => "099" + "999" + String(n).padStart(6, "0")
const MA = [maGia(3), maGia(1), maGia(2)] // CỐ Ý không theo thứ tự số

type Spy = ReturnType<typeof vi.spyOn>
let consoleSpies: Spy[] = []
let urls: string[] = []
const nghe = ({ request }: { request: Request }) => {
  urls.push(request.url)
}

beforeEach(() => {
  urls = []
  server.events.on("request:start", nghe)
  consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  )
  localStorage.clear()
  sessionStorage.clear()
})

afterEach(() => {
  server.events.removeListener("request:start", nghe)
})

function khongCoMaO(noi: string, chuoi: string) {
  for (const m of MA) {
    expect(chuoi.includes(m), `mã giả lọt vào ${noi}`).toBe(false)
  }
}

function khongCoMaOConsoleStorageUrl() {
  for (const s of consoleSpies) khongCoMaO("console", JSON.stringify(s.mock.calls, (_k, v) => (v instanceof Error ? `${v.name}: ${v.message} ${JSON.stringify((v as { config?: unknown }).config ?? null)}` : v)))
  khongCoMaO("localStorage", JSON.stringify({ ...localStorage }))
  khongCoMaO("sessionStorage", JSON.stringify({ ...sessionStorage }))
  khongCoMaO("URL request", urls.join("\n"))
  khongCoMaO("window.location", window.location.href)
  for (const u of urls) expect(u.startsWith(`${API}${P}/`), u).toBe(true)
}

describe("createCouncilSet — danh sách mã chỉ ở thân POST", () => {
  it("gửi đúng thứ tự, không đụng URL / console / storage", async () => {
    let than: unknown = null
    server.use(
      http.post(`${API}${P}/sets`, async ({ request }) => {
        than = await request.json()
        return HttpResponse.json(
          {
            id: 7, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T01:00:00Z",
            unit_id: 3, trinh_do: "Cao đẳng", so_ho_so: 3, so_tep: 2, kich_thuoc_tong: 10, nam_hoc: 2026,
            tham_so_quyet_dinh: null, thong_tin_dung: {}, tep: [],
            nguoi_tao_ten: null, tinh_trang: null, quyet_dinh: null, luot_gui_cho: null,
          },
          { status: 201 },
        )
      }),
    )
    const bo = await createCouncilSet({ ma_ho_so: MA, academic_year: 2026 })
    expect(bo.id).toBe(7)
    expect(than).toEqual({ ma_ho_so: MA, academic_year: 2026 })
    expect(urls).toEqual([`${API}${P}/sets`])
    khongCoMaOConsoleStorageUrl()
  })

  it.each([
    [400, { detail: "Dòng 2: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số (CMND), chỉ chữ số 0-9.", error_code: "DATA_VALIDATION_ERROR" }],
    [409, { detail: "Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại.", error_code: "CONFLICT" }],
    // Lượt G (F236): khuôn THẬT của handler 422 — danh sách ở `errors`, `detail` là chuỗi.
    [422, { detail: "Request validation failed", error_code: "VALIDATION_ERROR", errors: [{ type: "extra_forbidden", loc: ["body", "x"], msg: "Extra inputs are not permitted", input: { ma_ho_so: "MA" } }] }],
    [503, { detail: "Tuyển sinh đang đóng băng", code: "ADMISSION_FROZEN" }],
    [500, { detail: "Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.", error_code: "SERVICE_ERROR" }],
  ])("lỗi %s: không console / storage / URL mang mã", async (status, body) => {
    // 422 thật của FastAPI phản hồi kèm `input` = thân (có mã) — đặt mã giả vào đó.
    const than = JSON.parse(JSON.stringify(body).replace('"MA"', JSON.stringify(MA)))
    server.use(http.post(`${API}${P}/sets`, () => HttpResponse.json(than, { status })))
    await expect(createCouncilSet({ ma_ho_so: MA, academic_year: 2026 })).rejects.toBeTruthy()
    khongCoMaOConsoleStorageUrl()
  })
})

describe("getCouncilSetInputCodes — dữ liệu cá nhân chỉ trả về người gọi", () => {
  it("GET không tham số mã, không console / storage", async () => {
    server.use(
      http.get(`${API}${P}/sets/5/ma-ho-so`, () =>
        HttpResponse.json({ set_id: 5, so_ho_so: 3, ma_ho_so: MA }),
      ),
    )
    const kq = await getCouncilSetInputCodes(5)
    expect(kq.ma_ho_so).toEqual(MA) // đúng thứ tự đã lưu
    expect(urls).toEqual([`${API}${P}/sets/5/ma-ho-so`])
    khongCoMaOConsoleStorageUrl()
  })
})

describe("getCouncilDocumentPermissions", () => {
  it("parse đủ cờ (mười cờ lượt F + mười ba cờ Quyết định + ba cờ lượt gửi + ba cờ đường chọn hồ sơ + hai cờ đợt 2: tai_ca_bo, xem_nguoi_tao_bo)", async () => {
    const co = {
      ...NO_COUNCIL_PERMISSIONS,
      xem_mau: true, xem_danh_sach_bo: true, xem_chi_tiet_bo: true, tai_tep: true,
      ghi_nhan_qd: true, mo_luot_gui: true, xem_luot_gui: true, phan_xu_luot_gui: true,
      kiem_truoc: true, tim_ho_so: true, doi_ma: true, tai_ca_bo: true, xem_nguoi_tao_bo: true,
    }
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: co })))
    expect(await getCouncilDocumentPermissions()).toEqual(co)
  })

  // Máy chủ đã trả các cờ này (đường chọn hồ sơ từ `5feb425d`; tải cả bộ + người tạo bộ từ `083a428d`) ⇒ vắng là hợp đồng
  // vỡ (máy chủ cũ / sai bản), KHÔNG được coi là "tắt" lặng lẽ.
  it.each([["kiem_truoc"], ["tim_ho_so"], ["doi_ma"], ["tai_ca_bo"], ["xem_nguoi_tao_bo"]] as const)("cờ %s vắng ⇒ NỔ (đã là cờ bắt buộc)", async (k) => {
    const co: Record<string, boolean> = { ...NO_COUNCIL_PERMISSIONS, xem_mau: true }
    delete co[k]
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: co })))
    await expect(getCouncilDocumentPermissions()).rejects.toBeTruthy()
  })

  it("CO_CHO_MAY_CHU khớp CHÍNH XÁC tập cờ đang `.default(false)` trong Zod — và RỖNG từ đợt 2 (máy chủ đã trả đủ)", () => {
    // Đỏ khi ai đó thêm cờ `.default(false)` mà quên danh sách (hoặc ngược lại): hai vế phải luôn khớp nhau.
    const macDinh = Object.entries(councilDocumentPermissionsSchema.shape)
      .filter(([, v]) => v.safeParse(undefined).success)
      .map(([ten]) => ten)
    expect([...macDinh].sort()).toEqual([...CO_CHO_MAY_CHU].sort())
    expect([...CO_CHO_MAY_CHU]).toEqual([])
  })

  it("thiếu cờ ⇒ NỔ (không tự coi là tắt / bật)", async () => {
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { xem_mau: true } })))
    await expect(getCouncilDocumentPermissions()).rejects.toBeTruthy()
  })
})

/**
 * Đường chọn hồ sơ — fixture dựng ĐÚNG hình Pydantic của máy chủ `5feb425d` (`CouncilPreviewRowOut`, `CouncilProfileSearchRowOut`,
 * `CouncilCodesOut`): dòng KHÔNG có `trang_thai_nhan`; `nguoi_goi_duoc_xac_nhan` và `academic_year` LUÔN có.
 */
describe("đường chọn hồ sơ — DTO khớp máy chủ 5feb425d", () => {
  const TOM_TAT = {
    tong: 1, duoc_dung: 1, can_xac_nhan: 0, bi_chan: 0,
    theo_nganh: [{ nganh_nhan: "CĐ Kế toán", trinh_do: "Cao đẳng", so: 1 }],
    can_xac_nhan_theo_trang_thai: {}, so_nhom: 1, du_kien_so_tep: 4, nguoi_goi_duoc_xac_nhan: false,
  }
  const KIEM = {
    kiem_luc: "2026-11-11T02:00:00Z", phien_ban_kiem: "dau-kiem-1",
    dong: [{
      stt: 1, stt_qd: 1, profile_id: 11, ho_ten: "Nguyễn Văn A", trang_thai: "approved", nganh_nhan: "CĐ Kế toán",
      trinh_do: "Cao đẳng", duong_xet_nhan: "Xét học bạ", diem_in: "20,5", muc: "duoc_dung", ly_do: [],
    }],
    khong_tim_thay: [], tom_tat: TOM_TAT,
  }
  const DONG_TIM = {
    profile_id: 11, ho_ten: "Nguyễn Văn A", cccd: maGia(11), nganh_nhan: "CĐ Kế toán", trinh_do: "Cao đẳng",
    duong_xet_nhan: null, trang_thai: "approved", academic_year: 2026,
  }
  const TIM = { tong: 1, page: 1, page_size: 25, dong: [DONG_TIM] }
  const VAO_TIM = { academic_year: 2026, tu_khoa: null, page: 1, page_size: 25 }

  it("kiem-truoc: parse hình máy chủ — dòng không có trang_thai_nhan; nguoi_goi_duoc_xac_nhan=false được GIỮ", async () => {
    server.use(http.post(`${API}${P}/sets/kiem-truoc`, () => HttpResponse.json(KIEM)))
    const kq = await previewCouncilSet({ academic_year: 2026, profile_ids: [11] })
    expect(kq.dong[0].trang_thai).toBe("approved")
    expect("trang_thai_nhan" in kq.dong[0]).toBe(false)
    expect(kq.tom_tat.nguoi_goi_duoc_xac_nhan).toBe(false)
  })

  it("kiem-truoc: tom_tat THIẾU nguoi_goi_duoc_xac_nhan ⇒ bị từ chối (máy chủ luôn trả; không đoán 'xác nhận được')", async () => {
    const { nguoi_goi_duoc_xac_nhan: _bo, ...thieu } = TOM_TAT
    server.use(http.post(`${API}${P}/sets/kiem-truoc`, () => HttpResponse.json({ ...KIEM, tom_tat: thieu })))
    await expect(previewCouncilSet({ academic_year: 2026, profile_ids: [11] })).rejects.toBeTruthy()
  })

  it("tim-ho-so: parse hình máy chủ (academic_year có, duong_xet_nhan null); thân gửi đúng và URL không query", async () => {
    let than: unknown
    server.use(http.post(`${API}${P}/sets/tim-ho-so`, async ({ request }) => {
      than = await request.json()
      return HttpResponse.json(TIM)
    }))
    const kq = await searchCouncilProfiles(VAO_TIM)
    expect(kq.dong[0].academic_year).toBe(2026)
    expect(kq.dong[0].duong_xet_nhan).toBeNull()
    expect("trang_thai_nhan" in kq.dong[0]).toBe(false)
    expect(than).toEqual(VAO_TIM)
    expect(urls).toEqual([`${API}${P}/sets/tim-ho-so`])
  })

  it("tim-ho-so: dòng THIẾU academic_year ⇒ bị từ chối (máy chủ luôn trả)", async () => {
    const { academic_year: _bo, ...thieu } = DONG_TIM
    server.use(http.post(`${API}${P}/sets/tim-ho-so`, () => HttpResponse.json({ ...TIM, dong: [thieu] })))
    await expect(searchCouncilProfiles(VAO_TIM)).rejects.toBeTruthy()
  })

  it("doi-ma: nhận đủ sáu mã lý do (kể cả sai_dinh_dang, nhieu_ho_so); mã chỉ ở thân, không URL / console / storage", async () => {
    const dongLoi = ["rong", "trung", "ky_tu_la", "sai_dinh_dang", "khong_khop", "nhieu_ho_so"].map((ly_do, i) => ({ dong: i + 1, ly_do }))
    let than: unknown
    server.use(http.post(`${API}${P}/sets/doi-ma`, async ({ request }) => {
      than = await request.json()
      return HttpResponse.json({ profile_ids: [11], dong_loi: dongLoi })
    }))
    const kq = await resolveCouncilCodes({ academic_year: 2026, ma_ho_so: MA })
    expect(kq.dong_loi.map((d) => d.ly_do)).toEqual(["rong", "trung", "ky_tu_la", "sai_dinh_dang", "khong_khop", "nhieu_ho_so"])
    expect(than).toEqual({ academic_year: 2026, ma_ho_so: MA })
    expect(urls).toEqual([`${API}${P}/sets/doi-ma`])
    khongCoMaOConsoleStorageUrl()
  })

  it("POST /sets dạng id: thân CHỈ có profile_ids + phien_ban_kiem + academic_year (+ tham số), KHÔNG kèm ma_ho_so (máy chủ trả 422 nếu gửi cả hai dạng)", async () => {
    let than: Record<string, unknown> = {}
    server.use(http.post(`${API}${P}/sets`, async ({ request }) => {
      than = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({
        id: 9, nguoi_tao_id: 1, tao_luc: "2026-11-11T01:00:00Z", moc_chup: "2026-11-11T00:59:00Z", unit_id: null,
        trinh_do: "Cao đẳng", so_ho_so: 1, so_tep: 4, kich_thuoc_tong: 100, nam_hoc: 2026, tham_so_quyet_dinh: null,
        thong_tin_dung: {}, tep: [],
        nguoi_tao_ten: null, tinh_trang: null, quyet_dinh: null, luot_gui_cho: null,
      }, { status: 201 })
    }))
    await createCouncilSetByIds({ profile_ids: [11], phien_ban_kiem: "dau-kiem-1", academic_year: 2026 })
    expect(Object.keys(than).sort()).toEqual(["academic_year", "phien_ban_kiem", "profile_ids"])
  })

  // Ba POST chỉ đọc vẫn bị cần gạt đóng băng chặn (503 ADMISSION_FROZEN): câu lỗi phải nói rõ cả việc chọn / kiểm trước dừng,
  // không để người dùng tưởng chỉ "ghi" mới bị chặn.
  it.each([
    ["kiem-truoc", () => previewCouncilSet({ academic_year: 2026, profile_ids: [11] })],
    ["tim-ho-so", () => searchCouncilProfiles(VAO_TIM)],
    ["doi-ma", () => resolveCouncilCodes({ academic_year: 2026, ma_ho_so: MA })],
  ] as const)("%s bị đóng băng chặn (503) ⇒ câu đóng băng nói rõ cả chọn / kiểm trước", async (route, goi) => {
    server.use(http.post(`${API}${P}/sets/${route}`, () => HttpResponse.json({ detail: "x", code: "ADMISSION_FROZEN" }, { status: 503 })))
    try {
      await goi()
    } catch (e) {
      const m = describeCouncilDocumentError(e)
      expect(m.status).toBe(503)
      expect(m.title).toMatch(/đóng băng/)
      expect(m.title).toMatch(/chọn \/ kiểm trước/)
      return
    }
    throw new Error("không lỗi")
  })
})

/** Byte của một zip giả — CỐ Ý có 0xFF 0xFE (không hợp lệ UTF-8): đọc nhầm thành chữ sẽ làm hỏng byte. */
const ZIP_BYTE = [0x50, 0x4b, 0x03, 0x04, 0xff, 0xfe]
/** jsdom: `Blob` không có `.text()` / `.arrayBuffer()` — đọc byte bằng FileReader. */
const docByte = (b: Blob) =>
  new Promise<number[]>((xong, loi) => {
    const r = new FileReader()
    r.onload = () => xong(Array.from(new Uint8Array(r.result as ArrayBuffer)))
    r.onerror = () => loi(r.error)
    r.readAsArrayBuffer(b)
  })

describe("đợt 2 — DTO khớp máy chủ 083a428d (danh sách / chi tiết bộ, người tạo, tải cả bộ, nhật ký, lọc văn bản)", () => {
  const QD = {
    id: 21, loai: "bo_sung", trang_thai: "hieu_luc", so_quyet_dinh: "90", ngay_ky: "2026-10-20", so_ho_so: 12,
    goc: { id: 3, so_quyet_dinh: "50", ngay_ky: "2026-09-08" },
  }
  const BO = {
    id: 5, nguoi_tao_id: 2, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z", unit_id: 3,
    trinh_do: "Cao đẳng", so_ho_so: 12, so_tep: 4, kich_thuoc_tong: 2048, nam_hoc: 2026, tham_so_quyet_dinh: null,
    nguoi_tao_ten: "Trần Minh Khoa", tinh_trang: "con_hieu_luc", quyet_dinh: QD,
    luot_gui_cho: { ma: "11111111-2222-3333-4444-555555555555", tao_luc: "2026-11-11T01:00:00Z" },
  }
  const BO_VUA_DUNG = { ...BO, nguoi_tao_ten: null, tinh_trang: null, quyet_dinh: null, luot_gui_cho: null }

  it("GET /sets: parse hình đầy đủ (quyet_dinh có id + goc, luot_gui_cho {ma, tao_luc})", async () => {
    server.use(http.get(`${API}${P}/sets`, () => HttpResponse.json([BO])))
    const [b] = await listCouncilSets({ limit: 50, offset: 0 })
    expect(b.tinh_trang).toBe("con_hieu_luc")
    expect(b.quyet_dinh).toEqual(QD)
    expect(b.luot_gui_cho?.ma).toBe("11111111-2222-3333-4444-555555555555")
    expect(b.nguoi_tao_ten).toBe("Trần Minh Khoa")
  })

  it("GET /sets: gửi bộ lọc ĐÚNG tên tham số khi đặt, KHÔNG gửi khi không đặt", async () => {
    const qs: URLSearchParams[] = []
    server.use(http.get(`${API}${P}/sets`, ({ request }) => {
      qs.push(new URL(request.url).searchParams)
      return HttpResponse.json([])
    }))
    await listCouncilSets({ limit: 50, offset: 0 })
    await listCouncilSets({ limit: 20, offset: 40, so_quyet_dinh: "90", nam_hoc: 2026, tinh_trang: "con_hieu_luc", nguoi_tao_id: 9 })
    expect([...qs[0].keys()].sort()).toEqual(["limit", "offset"])
    expect(Object.fromEntries(qs[1])).toEqual({
      limit: "20", offset: "40", so_quyet_dinh: "90", nam_hoc: "2026", tinh_trang: "con_hieu_luc", nguoi_tao_id: "9",
    })
  })

  // Bốn trường LUÔN có khoá ⇒ thiếu khoá là hợp đồng gãy: phải NỔ, không được coi như "chưa có tình trạng / Quyết định".
  it.each([["nguoi_tao_ten"], ["tinh_trang"], ["quyet_dinh"], ["luot_gui_cho"]] as const)("GET /sets: dòng THIẾU khoá %s ⇒ bị từ chối", async (k) => {
    const { [k]: _bo, ...thieu } = BO
    server.use(http.get(`${API}${P}/sets`, () => HttpResponse.json([thieu])))
    await expect(listCouncilSets({ limit: 50, offset: 0 })).rejects.toBeTruthy()
  })

  it("quyet_dinh THIẾU khoá goc (kể cả null) ⇒ bị từ chối; goc null ⇒ nhận", async () => {
    const { goc: _g, ...khongGoc } = QD
    server.use(http.get(`${API}${P}/sets`, () => HttpResponse.json([{ ...BO, quyet_dinh: khongGoc }])))
    await expect(listCouncilSets({ limit: 50, offset: 0 })).rejects.toBeTruthy()
    server.use(http.get(`${API}${P}/sets`, () => HttpResponse.json([{ ...BO, quyet_dinh: { ...QD, goc: null } }])))
    expect((await listCouncilSets({ limit: 50, offset: 0 }))[0].quyet_dinh?.goc).toBeNull()
  })

  it("GET /sets/{id}: CÙNG hình với danh sách (bốn trường + thong_tin_dung + tep)", async () => {
    server.use(http.get(`${API}${P}/sets/5`, () => HttpResponse.json({ ...BO, thong_tin_dung: {}, tep: [] })))
    const b = await getCouncilSet(5)
    expect(b.quyet_dinh?.id).toBe(21)
    expect(b.tinh_trang).toBe("con_hieu_luc")
  })

  it("bộ VỪA DỰNG (POST /sets): bốn trường = null ⇒ parse được và null được GIỮ nguyên (không ép thành chuỗi / undefined)", async () => {
    server.use(http.post(`${API}${P}/sets`, () => HttpResponse.json({ ...BO_VUA_DUNG, thong_tin_dung: {}, tep: [] }, { status: 201 })))
    const b = await createCouncilSet({ ma_ho_so: MA, academic_year: 2026 })
    expect([b.nguoi_tao_ten, b.tinh_trang, b.quyet_dinh, b.luot_gui_cho]).toEqual([null, null, null, null])
  })

  it("GET /nguoi-tao-bo: parse [{id, ten}]; URL không query; thiếu ten ⇒ bị từ chối", async () => {
    server.use(http.get(`${API}${P}/nguoi-tao-bo`, () => HttpResponse.json([{ id: 7, ten: "Lê Thị Bảo" }, { id: 9, ten: "Trần Minh Khoa" }])))
    expect(await listCouncilSetCreators()).toEqual([{ id: 7, ten: "Lê Thị Bảo" }, { id: 9, ten: "Trần Minh Khoa" }])
    expect(urls).toEqual([`${API}${P}/nguoi-tao-bo`])
    server.use(http.get(`${API}${P}/nguoi-tao-bo`, () => HttpResponse.json([{ id: 7 }])))
    await expect(listCouncilSetCreators()).rejects.toBeTruthy()
  })

  it("GET /decisions: gửi loai + trang_thai (và set_id) khi đặt; KHÔNG gửi khi không đặt", async () => {
    const qs: URLSearchParams[] = []
    server.use(http.get(`${API}${P}/decisions`, ({ request }) => {
      qs.push(new URL(request.url).searchParams)
      return HttpResponse.json([])
    }))
    await listCouncilDecisions({ limit: 50, offset: 0 })
    await listCouncilDecisions({ limit: 200, offset: 0, loai: "trung_tuyen", trang_thai: "hieu_luc", set_id: 7 })
    expect([...qs[0].keys()].sort()).toEqual(["limit", "offset"])
    expect(Object.fromEntries(qs[1])).toEqual({ limit: "200", offset: "0", loai: "trung_tuyen", trang_thai: "hieu_luc", set_id: "7" })
  })

  it("nhật ký tải / vết xoá: tên người (hoặc null) nhận được; THIẾU khoá nguoi_tai_ten / nguoi_xoa_ten ⇒ bị từ chối", async () => {
    const TAI = { id: 1, set_id: 5, thu_tu: 1, path: "a.docx", sha256: "a".repeat(64), nguoi_tai_id: 2, tai_luc: "2026-11-11T01:00:00Z", nguoi_tai_ten: "Lê Thị Bảo" }
    const XOA = { id: 3, set_id: 7, so_ho_so: 3, so_tep: 2, danh_sach_tep: [], nguoi_xoa_id: 1, xoa_luc: "2026-11-05T02:00:00Z", ly_do: "dựng nhầm", nguoi_xoa_ten: null }
    server.use(
      http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([TAI])),
      http.get(`${API}${P}/nhat-ky-xoa`, () => HttpResponse.json([XOA])),
    )
    expect((await listCouncilDownloadLog({ limit: 50, offset: 0 }))[0].nguoi_tai_ten).toBe("Lê Thị Bảo")
    expect((await listCouncilSetDeletions({ limit: 50, offset: 0 }))[0].nguoi_xoa_ten).toBeNull()
    const { nguoi_tai_ten: _t, ...taiThieu } = TAI
    const { nguoi_xoa_ten: _x, ...xoaThieu } = XOA
    server.use(
      http.get(`${API}${P}/nhat-ky-tai`, () => HttpResponse.json([taiThieu])),
      http.get(`${API}${P}/nhat-ky-xoa`, () => HttpResponse.json([xoaThieu])),
    )
    await expect(listCouncilDownloadLog({ limit: 50, offset: 0 })).rejects.toBeTruthy()
    await expect(listCouncilSetDeletions({ limit: 50, offset: 0 })).rejects.toBeTruthy()
  })

  it("cảnh báo vượt chỉ tiêu: nhan là chuỗi / null / VẮNG (cảnh báo lưu trước đợt 2) đều nhận được", () => {
    expect(councilQuotaWarningSchema.parse({ loai: "nganh", chi_tieu: 10, nhan: "CĐ Kế toán" }).nhan).toBe("CĐ Kế toán")
    expect(councilQuotaWarningSchema.parse({ loai: "duong_xet", chi_tieu: 10, nhan: null }).nhan).toBeNull()
    expect(councilQuotaWarningSchema.parse({ loai: "nganh", chi_tieu: 10 }).nhan).toBeUndefined()
  })

  it("tải cả bộ: GET /sets/{id}/tai-ca-bo; Blob + tên bo-5.zip từ Content-Disposition của máy chủ", async () => {
    server.use(http.get(`${API}${P}/sets/5/tai-ca-bo`, () =>
      new HttpResponse(new Uint8Array(ZIP_BYTE), {
        headers: { "content-type": "application/zip", "content-disposition": 'attachment; filename="bo-5.zip"', "cache-control": "no-store" },
      })))
    const kq = await downloadCouncilSetZip(5)
    expect(kq.filename).toBe("bo-5.zip")
    expect(await docByte(kq.blob)).toEqual(ZIP_BYTE)
    expect(urls).toEqual([`${API}${P}/sets/5/tai-ca-bo`])
  })

  it("tải cả bộ: máy chủ không gửi Content-Disposition ⇒ tên dự phòng bo-<id>.zip (id đúng bộ yêu cầu)", async () => {
    server.use(http.get(`${API}${P}/sets/8/tai-ca-bo`, () => new HttpResponse(new Uint8Array(ZIP_BYTE), { headers: { "content-type": "application/zip" } })))
    expect((await downloadCouncilSetZip(8)).filename).toBe("bo-8.zip")
  })
})

describe("describeCouncilDocumentError — câu cho người dùng", () => {
  async function loiTu(status: number, body: unknown) {
    server.use(http.post(`${API}${P}/sets`, () => HttpResponse.json(body as object, { status })))
    try {
      await createCouncilSet({ ma_ho_so: MA, academic_year: 2026 })
    } catch (e) {
      return describeCouncilDocumentError(e)
    }
    throw new Error("không lỗi")
  }

  it("400: câu miền của máy chủ NGUYÊN VĂN (số dòng)", async () => {
    const d = "Mã hồ sơ phải khớp đúng một hồ sơ: dòng 2, 3 không có hồ sơ nào mang mã này trong năm học đã chọn."
    const m = await loiTu(400, { detail: d, error_code: "DATA_VALIDATION_ERROR" })
    expect(m.detail).toBe(d)
  })

  it("409 đang dựng bộ khác: nguyên văn", async () => {
    const d = "Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại."
    expect((await loiTu(409, { detail: d, error_code: "CONFLICT" })).detail).toBe(d)
  })

  it("403 / 404: câu cố định, không lộ chi tiết máy chủ", async () => {
    const a = await loiTu(403, { detail: "Chỉ admin được làm thao tác này với bộ văn bản Hội đồng.", error_code: "PERMISSION_DENIED" })
    expect(a.detail).toBeUndefined()
    expect(a.title).toMatch(/không có quyền/)
    const b = await loiTu(404, { detail: "Không có bộ văn bản này.", error_code: "RESOURCE_NOT_FOUND" })
    expect(b.detail).toBeUndefined()
  })

  it("422: chỉ loc + msg, KHÔNG input / ctx (FastAPI phản hồi kèm thân có mã)", async () => {
    // Lượt G (F236): khuôn THẬT của handler 422 (`exception_handlers.py` —
    // `pydantic_validation_error_handler`): `detail` là CHUỖI, danh sách ở `errors`.
    const m = await loiTu(422, {
      detail: "Request validation failed",
      error_code: "VALIDATION_ERROR",
      errors: [
        { type: "string_pattern_mismatch", loc: ["body", "tham_so_quyet_dinh", "so_quyet_dinh"], msg: "String should match pattern", input: MA[0], ctx: { pattern: MA[1] } },
        { type: "missing", loc: ["body", "academic_year"], msg: "Field required", input: { ma_ho_so: MA } },
      ],
    })
    expect(m.detail).toBe("tham_so_quyet_dinh.so_quyet_dinh: String should match pattern\nacademic_year: Field required")
    khongCoMaO("thông báo 422", JSON.stringify(m))
  })

  it("429 / 503 đóng băng / 503 khác / 500: câu cố định", async () => {
    expect((await loiTu(429, { detail: "x", error_code: "HTTP_429" })).title).toMatch(/giới hạn/)
    expect((await loiTu(503, { detail: "x", code: "ADMISSION_FROZEN" })).title).toMatch(/đóng băng/)
    expect((await loiTu(503, { detail: "x", error_code: "SERVICE_UNAVAILABLE" })).title).not.toMatch(/đóng băng/)
    const m = await loiTu(500, { detail: "Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.", error_code: "SERVICE_ERROR" })
    expect(m.detail).toBeUndefined()
  })

  it("mất mạng: câu kết nối", async () => {
    server.use(http.post(`${API}${P}/sets`, () => HttpResponse.error()))
    try {
      await createCouncilSet({ ma_ho_so: MA, academic_year: 2026 })
    } catch (e) {
      expect(describeCouncilDocumentError(e).title).toMatch(/kết nối/)
      khongCoMaOConsoleStorageUrl()
      return
    }
    throw new Error("không lỗi")
  })
})

describe("tải tệp", () => {
  it("tên từ filename* (có dấu) được ưu tiên hơn bản ASCII", () => {
    const h = `attachment; filename="Bien_ban.docx"; filename*=UTF-8''${encodeURIComponent("Biên bản.docx")}`
    expect(filenameFromContentDisposition(h, "x")).toBe("Biên bản.docx")
  })

  it("không filename* ⇒ bản ASCII; bỏ thư mục; không header ⇒ dự phòng", () => {
    expect(filenameFromContentDisposition('attachment; filename="a.xlsx"', "x")).toBe("a.xlsx")
    expect(filenameFromContentDisposition(`attachment; filename*=UTF-8''${encodeURIComponent("../../a/b.docx")}`, "x")).toBe("b.docx")
    expect(filenameFromContentDisposition(undefined, "du-phong")).toBe("du-phong")
  })

  it("trả bytes + tên; lỗi Blob ⇒ đọc ra câu máy chủ", async () => {
    const h = `attachment; filename="Bien_ban.docx"; filename*=UTF-8''${encodeURIComponent("Biên bản.docx")}`
    server.use(
      http.get(`${API}${P}/sets/9/files/1`, () =>
        new HttpResponse(new Uint8Array([80, 75, 3, 4]), {
          headers: { "Content-Type": "application/octet-stream", "Content-Disposition": h },
        }),
      ),
      http.get(`${API}${P}/sets/9/files/2`, () =>
        HttpResponse.json({ detail: "Không có tệp này trong bộ văn bản.", error_code: "RESOURCE_NOT_FOUND" }, { status: 404 }),
      ),
    )
    const tep = await downloadCouncilSetFile(9, 1)
    expect(tep.filename).toBe("Biên bản.docx")
    expect(tep.blob.size).toBe(4)
    try {
      await downloadCouncilSetFile(9, 2)
    } catch (e) {
      expect(describeCouncilDocumentError(e).status).toBe(404)
      return
    }
    throw new Error("không lỗi")
  })
})
