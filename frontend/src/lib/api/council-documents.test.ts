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
import {
  COUNCIL_DOCUMENTS_PREFIX as P,
  createCouncilSet,
  describeCouncilDocumentError,
  downloadCouncilSetFile,
  filenameFromContentDisposition,
  getCouncilDocumentPermissions,
  getCouncilSetInputCodes,
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
    [422, { detail: [{ type: "extra_forbidden", loc: ["body", "x"], msg: "Extra inputs are not permitted", input: { ma_ho_so: "MA" } }] }],
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
  it("parse đủ mười cờ", async () => {
    const co = {
      xem_mau: true, tai_mau_len: false, xem_danh_sach_bo: true, tao_bo: false, xem_chi_tiet_bo: true,
      tai_tep: true, xoa_bo: false, xem_ma_ho_so: false, xem_nhat_ky_tai: false, xem_nhat_ky_xoa: false,
    }
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: co })))
    expect(await getCouncilDocumentPermissions()).toEqual(co)
  })

  it("thiếu cờ ⇒ NỔ (không tự coi là tắt / bật)", async () => {
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { xem_mau: true } })))
    await expect(getCouncilDocumentPermissions()).rejects.toBeTruthy()
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
    const m = await loiTu(422, {
      detail: [
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
