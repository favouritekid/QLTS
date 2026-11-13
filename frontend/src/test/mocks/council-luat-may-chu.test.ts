/**
 * Luật máy chủ giả lập (MSW) của các lệnh ghi Văn bản Hội đồng — mỗi luật một cặp ca ĐÚNG / SAI, dùng "giá trị phân biệt" của bảng hợp đồng
 * (`HOP-DONG-THAN-YEU-CAU-LENH-GHI-GD1-2026-11-13.md`): bộ có số hồ sơ 4, số Quyết định "201", set_id 1; năm học 2026 ≠ năm ký 2027.
 * Ca SAI luôn dùng đúng giá trị DỄ NHẦM (số QĐ ↔ số hồ sơ ↔ set_id), không chỉ giá trị rác — vì OpenAPI / zod chỉ kiểm hình dạng.
 */
import { describe, expect, it } from "vitest"

import {
  LY_DO_TOI_DA,
  luatDanhSachId,
  luatDoiMa,
  luatGhiNhan,
  luatHuyGhiNhan,
  luatKiemTruoc,
  luatMoLuot,
  luatPhanXuMa,
  luatTaiMau,
  luatTaoBo,
  luatThamSoQuyetDinh,
  luatTimHoSo,
  luatXoaBo,
  loiMotMa,
  luatDoiMaTruoc,
  luatLopSchemaMa,
  neuDong,
  type NguCanhGhiNhan,
} from "./council-luat-may-chu"

const SET_ID = 1
const SO_QD = "201"
const SO_HO_SO = 4
const MA_LUOT = "11111111-2222-3333-4444-555555555555"
const CCCD = (n: number) => "099" + "999" + String(n).padStart(6, "0")

// ── 7. DELETE /sets/{id} ────────────────────────────────────────────────────────────────────────────────────────────────
describe("luatXoaBo — lý do xoá bộ (kiem_ly_do)", () => {
  const khongVanBan = { coVanBanHieuLuc: false }
  it("ĐÚNG: lý do có chữ (cắt khoảng trắng hai đầu)", () => {
    expect(luatXoaBo({ ly_do: "  Dựng nhầm năm học  " }, khongVanBan)).toBeNull()
  })
  it("SAI: chỉ khoảng trắng ⇒ 400 'Phải nhập lý do'", () => {
    expect(luatXoaBo({ ly_do: "   " }, khongVanBan)).toMatchObject({ status: 400, body: { error_code: "DATA_VALIDATION_ERROR", detail: expect.stringContaining("Phải nhập lý do") } })
  })
  it("SAI: ký tự vô hình (U+200B) ⇒ 400", () => {
    expect(luatXoaBo({ ly_do: "lý do\u200b" }, khongVanBan)).toMatchObject({ status: 400 })
  })
  it("SAI: vượt trần kỹ thuật; ĐÚNG ở đúng trần", () => {
    expect(luatXoaBo({ ly_do: "a".repeat(LY_DO_TOI_DA) }, khongVanBan)).toBeNull()
    expect(luatXoaBo({ ly_do: "a".repeat(LY_DO_TOI_DA + 1) }, khongVanBan)).toMatchObject({ status: 400 })
  })
  it("SAI: thiếu / không phải chuỗi ⇒ 422 (StrictStr)", () => {
    expect(luatXoaBo({}, khongVanBan)).toMatchObject({ status: 422 })
    expect(luatXoaBo({ ly_do: 5 }, khongVanBan)).toMatchObject({ status: 422 })
  })
  it("SAI: bộ đang có văn bản hiệu lực ⇒ 409", () => {
    expect(luatXoaBo({ ly_do: "lý do" }, { coVanBanHieuLuc: true })).toMatchObject({ status: 409, body: { error_code: "CONFLICT" } })
  })
})

// ── 1. POST /templates ──────────────────────────────────────────────────────────────────────────────────────────────────
describe("luatTaiMau — hieu_luc_tu là ngày KÝ áp mẫu (không phải ngày tải); trùng (loại, ngày) ⇒ 409", () => {
  const docx = () => new File(["PK\u0003\u0004 gia"], "mau.docx")
  const form = (o: Record<string, string | File>) => {
    const f = new FormData()
    for (const [k, v] of Object.entries(o)) f.append(k, v)
    return f
  }
  const co = [{ loai: "quyet_dinh", hieu_luc_tu: "2026-09-08" }]
  it("ĐÚNG: cùng loại KHÁC ngày ⇒ được; KHÁC loại cùng ngày ⇒ được", async () => {
    expect(await luatTaiMau(form({ loai: "quyet_dinh", hieu_luc_tu: "2027-01-01", file: docx() }), co)).toBeNull()
    expect(await luatTaiMau(form({ loai: "bien_ban", hieu_luc_tu: "2026-09-08", file: docx() }), co)).toBeNull()
  })
  it("SAI: cùng loại + cùng ngày hiệu lực ⇒ 409 DUPLICATE_RESOURCE (không ghi đè)", async () => {
    expect(await luatTaiMau(form({ loai: "quyet_dinh", hieu_luc_tu: "2026-09-08", file: docx() }), co)).toMatchObject({
      status: 409,
      body: { error_code: "DUPLICATE_RESOURCE", detail: expect.stringContaining("2026-09-08") },
    })
  })
  it("SAI: loại viết khác (quyet-dinh, danh_sach_xet_tuyen) ⇒ 400", async () => {
    for (const loai of ["quyet-dinh", "danh_sach_xet_tuyen"]) {
      expect(await luatTaiMau(form({ loai, hieu_luc_tu: "2027-01-01", file: docx() }), [])).toMatchObject({ status: 400 })
    }
  })
  it("SAI: ngày không đúng dạng YYYY-MM-DD / không có thật ⇒ 422", async () => {
    for (const hieu of ["08/09/2026", "2026-02-30"]) {
      expect(await luatTaiMau(form({ loai: "quyet_dinh", hieu_luc_tu: hieu, file: docx() }), [])).toMatchObject({ status: 422 })
    }
  })
  it("ghi chú: ĐÚNG 500 ký tự; SAI 501", async () => {
    expect(await luatTaiMau(form({ loai: "quyet_dinh", hieu_luc_tu: "2027-01-01", ghi_chu: "a".repeat(500), file: docx() }), [])).toBeNull()
    expect(await luatTaiMau(form({ loai: "quyet_dinh", hieu_luc_tu: "2027-01-01", ghi_chu: "a".repeat(501), file: docx() }), [])).toMatchObject({ status: 400 })
  })
  it("SAI: tệp không phải .docx (không có chữ ký ZIP) ⇒ 400", async () => {
    expect(await luatTaiMau(form({ loai: "quyet_dinh", hieu_luc_tu: "2027-01-01", file: new File(["%PDF-1.4"], "mau.pdf") }), [])).toMatchObject({ status: 400 })
  })
})

// ── 5. POST /sets/doi-ma ────────────────────────────────────────────────────────────────────────────────────────────────
describe("luatDoiMa — lỗi theo SỐ DÒNG, không nêu giá trị", () => {
  const kho = new Map([[CCCD(1), 11], [CCCD(4), 14], ["123456789", 19]])
  it("ĐÚNG: 12 số khớp ⇒ id theo thứ tự dòng; 9 số (CMND) cũng được", () => {
    expect(luatDoiMa([CCCD(4), "123456789", CCCD(1)], kho)).toEqual({ profile_ids: [14, 19, 11], dong_loi: [] })
  })
  it("SAI: 11 số / chữ / rỗng ⇒ sai_dinh_dang / rong; ngoài phạm vi ⇒ khong_khop; DÒNG SAU của mã trùng mang `trung`", () => {
    const kq = luatDoiMa([CCCD(1), "09999900000", "09999900000a", "", CCCD(1), CCCD(7)], kho)
    expect(kq.profile_ids).toEqual([11])
    expect(kq.dong_loi).toEqual([
      { dong: 2, ly_do: "sai_dinh_dang" },
      { dong: 3, ly_do: "sai_dinh_dang" },
      { dong: 4, ly_do: "rong" },
      { dong: 5, ly_do: "trung" },
      { dong: 6, ly_do: "khong_khop" },
    ])
    expect(JSON.stringify(kq)).not.toContain(CCCD(7)) // không nêu giá trị
  })
  it("Đ3-2: phần tử KHÔNG PHẢI CHUỖI (số / null) ⇒ `khong_phai_chuoi` (loi_mot_ma, candidate_service:273) — KHÁC `rong` của mã trống", () => {
    const kq = luatDoiMa([CCCD(1), 123456789012, null, "", "   "], kho)
    expect(kq.profile_ids).toEqual([11])
    expect(kq.dong_loi).toEqual([
      { dong: 2, ly_do: "khong_phai_chuoi" },
      { dong: 3, ly_do: "khong_phai_chuoi" },
      { dong: 4, ly_do: "rong" },
      { dong: 5, ly_do: "rong" },
    ])
  })
  it("ky_tu_la: dài > 32 ký tự HOẶC có ký tự điều khiển (nhóm C) — trước kiểm dạng 9 / 12 số", () => {
    const kq = luatDoiMa(["1".repeat(33), CCCD(1) + String.fromCharCode(7), "1".repeat(11)], kho)
    expect(kq.dong_loi).toEqual([
      { dong: 1, ly_do: "ky_tu_la" },
      { dong: 2, ly_do: "ky_tu_la" },
      { dong: 3, ly_do: "sai_dinh_dang" },
    ])
  })
})
describe("loiMotMa — thứ tự luật của loi_mot_ma", () => {
  it("không phải chuỗi ⇒ khong_phai_chuoi (mã null); chuỗi rỗng / toàn khoảng trắng ⇒ rong; đúng 12 và 9 số ⇒ không lỗi (đã cắt khoảng trắng)", () => {
    for (const x of [123, null, undefined, {}, [], true]) expect(loiMotMa(x)).toEqual({ ma: null, ly_do: "khong_phai_chuoi" })
    expect(loiMotMa("")).toEqual({ ma: "", ly_do: "rong" })
    expect(loiMotMa("  ")).toEqual({ ma: "", ly_do: "rong" })
    expect(loiMotMa(` ${CCCD(1)} `)).toEqual({ ma: CCCD(1), ly_do: null })
    expect(loiMotMa("123456789")).toEqual({ ma: "123456789", ly_do: null })
  })
})

// ── 6. POST /sets/tim-ho-so ─────────────────────────────────────────────────────────────────────────────────────────────
describe("luatTimHoSo", () => {
  const nam = { academic_year: 2026 }
  it("ĐÚNG: từ khoá 100 ký tự; trạng thái là MÃ (approved); page_size 100", () => {
    expect(luatTimHoSo({ ...nam, tu_khoa: "a".repeat(100), trang_thai: ["approved"], page_size: 100 })).toBeNull()
  })
  it("SAI: từ khoá 101 ký tự (sau cắt) ⇒ 400; 100 ký tự + khoảng trắng hai đầu vẫn ĐÚNG", () => {
    expect(luatTimHoSo({ ...nam, tu_khoa: "a".repeat(101) })).toMatchObject({ status: 400 })
    expect(luatTimHoSo({ ...nam, tu_khoa: ` ${"a".repeat(100)} ` })).toBeNull()
  })
  it("SAI: trạng thái là NHÃN ('Đã duyệt') thay vì mã ⇒ 400", () => {
    expect(luatTimHoSo({ ...nam, trang_thai: ["Đã duyệt"] })).toMatchObject({ status: 400 })
  })
  it("SAI: page_size 101 / khoá lạ ⇒ 422", () => {
    expect(luatTimHoSo({ ...nam, page_size: 101 })).toMatchObject({ status: 422 })
    expect(luatTimHoSo({ ...nam, major_id: 1 })).toMatchObject({ status: 422 })
  })
})

// ── 4. POST /sets/kiem-truoc ────────────────────────────────────────────────────────────────────────────────────────────
describe("luatKiemTruoc / luatDanhSachId", () => {
  it("ĐÚNG: [1, 4]", () => {
    expect(luatKiemTruoc({ academic_year: 2026, profile_ids: [1, 4] })).toBeNull()
  })
  it("SAI: [1, 1] (trùng) ⇒ 400 nêu SỐ DÒNG, không nêu giá trị", () => {
    const sai = luatKiemTruoc({ academic_year: 2026, profile_ids: [1, 1] })
    expect(sai).toMatchObject({ status: 400, body: { detail: "Dòng 2 trùng hồ sơ với dòng 1 — mỗi người một dòng." } })
  })
  it("SAI: rỗng ⇒ 422; vượt trần ⇒ 400; id không dương ⇒ 400", () => {
    expect(luatKiemTruoc({ academic_year: 2026, profile_ids: [] })).toMatchObject({ status: 422 })
    expect(luatDanhSachId([1, 2, 3], 2)).toMatchObject({ status: 400 })
    expect(luatDanhSachId([1, 0])).toMatchObject({ status: 400 })
  })
  it("Đ3-1: trần MẶC ĐỊNH 1000 (COUNCIL_SET_MAX_PROFILES, config.py:455): 501 và 1000 hồ sơ ĐÚNG; 1001 ⇒ 400 đúng câu máy chủ; trần truyền vào vẫn ưu tiên", () => {
    const tu = (n: number) => Array.from({ length: n }, (_, i) => i + 1)
    expect(luatDanhSachId(tu(501))).toBeNull() // trần cũ (500) từng chặn nhầm ca này
    expect(luatDanhSachId(tu(1000))).toBeNull()
    expect(luatKiemTruoc({ academic_year: 2026, profile_ids: tu(501) })).toBeNull()
    expect(luatKiemTruoc({ academic_year: 2026, profile_ids: tu(1000) })).toBeNull()
    const cau = "Danh sách có 1001 hồ sơ, vượt giới hạn kỹ thuật 1000 hồ sơ cho một bộ văn bản."
    expect(luatDanhSachId(tu(1001))).toMatchObject({ status: 400, body: { detail: cau, error_code: "DATA_VALIDATION_ERROR" } })
    expect(luatKiemTruoc({ academic_year: 2026, profile_ids: tu(1001) })).toMatchObject({ status: 400, body: { detail: cau } })
    expect(luatDanhSachId(tu(3), 2)).toMatchObject({
      status: 400,
      body: { detail: "Danh sách có 3 hồ sơ, vượt giới hạn kỹ thuật 2 hồ sơ cho một bộ văn bản." },
    })
  })
})

// ── 9. tham_so_quyet_dinh ───────────────────────────────────────────────────────────────────────────────────────────────
describe("luatThamSoQuyetDinh — đợt PHẢI ĐỦ CẢ HAI (dot_so CHUỖI + dot_thang SỐ) hoặc không", () => {
  it("ĐÚNG: (dot_so '1', dot_thang 9); cả hai vắng; BB 08-09 + QĐ 08-09", () => {
    expect(luatThamSoQuyetDinh({ dot_so: "1", dot_thang: 9 })).toBeNull()
    expect(luatThamSoQuyetDinh({ so_quyet_dinh: SO_QD })).toBeNull()
    expect(luatThamSoQuyetDinh({ ngay_bien_ban: "2026-09-08", ngay_quyet_dinh: "2026-09-08" })).toBeNull()
  })
  it("SAI: (1, vắng) và (vắng, 9) ⇒ 422 'cần đủ cả số đợt và tháng'", () => {
    for (const ts of [{ dot_so: "1" }, { dot_thang: 9 }]) {
      expect(luatThamSoQuyetDinh(ts)).toMatchObject({ status: 422, body: { error_code: "VALIDATION_ERROR" } })
      expect(JSON.stringify(luatThamSoQuyetDinh(ts))).toContain("đợt xét tuyển cần đủ cả số đợt và tháng")
    }
  })
  it("SAI: nhầm KIỂU — dot_so là SỐ (1) hoặc dot_thang là CHUỖI ('9') ⇒ 422", () => {
    expect(luatThamSoQuyetDinh({ dot_so: 1, dot_thang: 9 })).toMatchObject({ status: 422 })
    expect(luatThamSoQuyetDinh({ dot_so: "1", dot_thang: "9" })).toMatchObject({ status: 422 })
  })
  it("SAI: nhầm NGHĨA — tháng 13 / dot_so 3 chữ số ⇒ 422", () => {
    expect(luatThamSoQuyetDinh({ dot_so: "1", dot_thang: 13 })).toMatchObject({ status: 422 })
    expect(luatThamSoQuyetDinh({ dot_so: "100", dot_thang: 1 })).toMatchObject({ status: 422 })
  })
  it("SAI: BB 09-09 sau QĐ 08-09 ⇒ 422", () => {
    expect(luatThamSoQuyetDinh({ ngay_bien_ban: "2026-09-09", ngay_quyet_dinh: "2026-09-08" })).toMatchObject({ status: 422 })
  })
})

// ── 2, 3. POST /sets ────────────────────────────────────────────────────────────────────────────────────────────────────
describe("luatTaoBo dạng ID — profile_ids ĐÚNG thứ tự kiểm trước + phien_ban_kiem nguyên văn", () => {
  const anh = { thuTuChuan: [1, 4, 9], dau: "DAU-LAN-KIEM-2" }
  const idTheoMa = new Map<string, number>()
  const goi = (profile_ids: number[], phien_ban_kiem: string, them: Record<string, unknown> = {}) =>
    luatTaoBo({ profile_ids, phien_ban_kiem, academic_year: 2026, ...them }, { anh, idTheoMa })
  it("ĐÚNG: thứ tự chuẩn + dấu thật", () => {
    expect(goi([1, 4, 9], "DAU-LAN-KIEM-2")).toBeNull()
  })
  it("SAI: CÙNG TẬP nhưng ĐẢO hai dòng ⇒ 409 du_lieu_doi_tu_luc_kiem (không tự sắp lại)", () => {
    expect(goi([4, 1, 9], "DAU-LAN-KIEM-2")).toMatchObject({ status: 409, body: { ma_loi: "du_lieu_doi_tu_luc_kiem", error_code: "CONFLICT" } })
  })
  it("SAI: dấu của LẦN KIỂM KHÁC (hồ sơ đổi sau kiểm) ⇒ 409 du_lieu_doi_tu_luc_kiem", () => {
    expect(goi([1, 4, 9], "DAU-LAN-KIEM-1")).toMatchObject({ status: 409, body: { ma_loi: "du_lieu_doi_tu_luc_kiem" } })
  })
  it("SAI: thiếu một hồ sơ / thừa một hồ sơ so với lần kiểm ⇒ 409", () => {
    expect(goi([1, 4], "DAU-LAN-KIEM-2")).toMatchObject({ status: 409 })
    expect(goi([1, 4, 9, 12], "DAU-LAN-KIEM-2")).toMatchObject({ status: 409 })
  })
  it("SAI: trộn HAI dạng (ma_ho_so + profile_ids) / thiếu dấu ⇒ 422; id trùng ⇒ 400", () => {
    expect(luatTaoBo({ ma_ho_so: [CCCD(1)], profile_ids: [1], phien_ban_kiem: "x", academic_year: 2026 }, { anh, idTheoMa })).toMatchObject({ status: 422 })
    expect(luatTaoBo({ profile_ids: [1, 4, 9], academic_year: 2026 }, { anh, idTheoMa })).toMatchObject({ status: 422 })
    expect(goi([1, 1, 9], "DAU-LAN-KIEM-2")).toMatchObject({ status: 400 })
  })
  it("tham_so_quyet_dinh đi qua DecisionParams: đợt chỉ một nửa ⇒ 422", () => {
    expect(goi([1, 4, 9], "DAU-LAN-KIEM-2", { tham_so_quyet_dinh: { dot_so: "1" } })).toMatchObject({ status: 422 })
  })
  it("Đ3-1: dạng id dùng trần mặc định 1000 — 1000 hồ sơ đúng thứ tự + dấu ⇒ ĐÚNG; 1001 ⇒ 400 (chặn TRƯỚC khi so dấu)", () => {
    const tu = (n: number) => Array.from({ length: n }, (_, i) => i + 1)
    const lon = { thuTuChuan: tu(1000), dau: "DAU-1000" }
    expect(luatTaoBo({ profile_ids: tu(1000), phien_ban_kiem: "DAU-1000", academic_year: 2026 }, { anh: lon, idTheoMa })).toBeNull()
    expect(luatTaoBo({ profile_ids: tu(1001), phien_ban_kiem: "DAU-1000", academic_year: 2026 }, { anh: lon, idTheoMa })).toMatchObject({
      status: 400,
      body: { detail: "Danh sách có 1001 hồ sơ, vượt giới hạn kỹ thuật 1000 hồ sơ cho một bộ văn bản." },
    })
  })
})
describe("luatTaoBo dạng MÃ — 12 / 9 số; trùng dòng; sai năm (mã đúng nhưng không có hồ sơ năm đó)", () => {
  const kho = new Map([[CCCD(1), 11], [CCCD(4), 14]])
  const goi = (ma: string[]) => luatTaoBo({ ma_ho_so: ma, academic_year: 2026 }, { anh: null, idTheoMa: kho })
  it("ĐÚNG: hai mã đúng", () => expect(goi([CCCD(4), CCCD(1)])).toBeNull())
  it("SAI: 11 số ⇒ 400 nêu số dòng; trùng ⇒ 400; mã đúng dạng nhưng KHÔNG có hồ sơ (sai năm) ⇒ 400", () => {
    expect(goi([CCCD(1), "09999900000"])).toMatchObject({ status: 400, body: { detail: expect.stringContaining("Dòng 2") } })
    expect(goi([CCCD(1), CCCD(1)])).toMatchObject({ status: 400, body: { detail: expect.stringContaining("Dòng 2 trùng") } })
    expect(goi([CCCD(9)])).toMatchObject({ status: 400 })
  })
  it("câu lỗi từng dòng = câu máy chủ (`_CAU_LOI_MA` + `chuan_hoa_ma`): rỗng · ký tự điều khiển · sai dạng · trùng — chỉ nêu SỐ DÒNG", () => {
    const loi = (ma: unknown[]) => (luatTaoBo({ ma_ho_so: ma, academic_year: 2026 }, { anh: null, idTheoMa: kho })?.body as { detail: string }).detail
    expect(loi([CCCD(1), ""])).toBe("Dòng 2: mã hồ sơ rỗng.")
    expect(loi([CCCD(1), CCCD(4) + String.fromCharCode(7)])).toBe("Dòng 2: không phải mã hồ sơ (quá dài hoặc có ký tự điều khiển).")
    expect(loi([CCCD(1), "09999900000"])).toBe("Dòng 2: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số (CMND), chỉ chữ số 0-9.")
    expect(loi([CCCD(1), CCCD(4), CCCD(1)])).toBe("Dòng 3 trùng mã hồ sơ với dòng 1 — mỗi người một dòng.")
  })

  // ── Đ3-5: ba pha của máy chủ (cú pháp xong → trần → khớp CSDL) + câu "không khớp" GỘP ────────────────────────────────────────
  const goiMa = (ma: unknown, them: { toiDa?: number; maNhieuHoSo?: ReadonlySet<string> } = {}, khoMa: ReadonlyMap<string, number> = kho) =>
    luatTaoBo({ ma_ho_so: ma, academic_year: 2026 }, { anh: null, idTheoMa: khoMa, ...them })
  const chiTiet = (r: ReturnType<typeof goiMa>) => (r?.body as { detail: string }).detail
  const KHONG_CO = (n: number) => CCCD(500 + n) // mã đúng dạng, KHÔNG có trong kho
  const CAU_GOP = "không có hồ sơ nào mang mã này trong năm học đã chọn"
  it("Đ3-5: 'không khớp' là MỘT câu GỘP nêu MỌI dòng không khớp (đếm từ 1), không nêu giá trị — không dừng ở dòng đầu", () => {
    const r = goiMa([CCCD(1), KHONG_CO(1), CCCD(4), KHONG_CO(2)])
    expect(r).toMatchObject({ status: 400, body: { error_code: "DATA_VALIDATION_ERROR" } })
    expect(chiTiet(r)).toBe(`Mã hồ sơ phải khớp đúng một hồ sơ: dòng 2, 4 ${CAU_GOP}.`)
    expect(JSON.stringify(r)).not.toContain(KHONG_CO(1))
    expect(JSON.stringify(r)).not.toContain(KHONG_CO(2))
    expect(goiMa([CCCD(4), CCCD(1)])).toBeNull() // mọi mã khớp ⇒ nhận
  })
  it("Đ3-5: mã khớp NHIỀU hồ sơ (so > 1) ⇒ phần riêng nối bằng '; ' SAU phần 'không có hồ sơ' (đúng thứ tự của máy chủ)", () => {
    const r = goiMa([CCCD(1), CCCD(4), KHONG_CO(3)], { maNhieuHoSo: new Set([CCCD(4)]) })
    expect(chiTiet(r)).toBe(`Mã hồ sơ phải khớp đúng một hồ sơ: dòng 3 ${CAU_GOP}; dòng 2 khớp NHIỀU hồ sơ cùng mã.`)
    expect(chiTiet(goiMa([CCCD(1), CCCD(4)], { maNhieuHoSo: new Set([CCCD(4)]) }))).toBe("Mã hồ sơ phải khớp đúng một hồ sơ: dòng 2 khớp NHIỀU hồ sơ cùng mã.")
  })
  it("Đ3-5: câu gộp chỉ nêu tối đa 20 dòng rồi '… (tổng N dòng)' (`_neu_dong`)", () => {
    const dong = (n: number) => Array.from({ length: n }, (_, i) => i + 1)
    expect(neuDong(dong(20))).toBe(dong(20).join(", "))
    expect(neuDong(dong(21))).toBe(`${dong(20).join(", ")} … (tổng 21 dòng)`)
    const khongCo = Array.from({ length: 25 }, (_, i) => KHONG_CO(i))
    expect(chiTiet(goiMa(khongCo))).toBe(`Mã hồ sơ phải khớp đúng một hồ sơ: dòng ${dong(20).join(", ")} … (tổng 25 dòng) ${CAU_GOP}.`)
  })
  it("Đ3-5: THỨ TỰ ba pha — cú pháp / trùng ĐỨNG TRƯỚC khớp CSDL: dòng 1 không khớp + dòng 2 sai dạng ⇒ báo dòng 2 (không phải câu gộp)", () => {
    expect(chiTiet(goiMa([KHONG_CO(1), "09999900000"]))).toBe("Dòng 2: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số (CMND), chỉ chữ số 0-9.")
    expect(chiTiet(goiMa([KHONG_CO(1), KHONG_CO(1)]))).toBe("Dòng 2 trùng mã hồ sơ với dòng 1 — mỗi người một dòng.")
  })
  it("Đ3-5: TRẦN ở nhánh mã — 1001 mã ⇒ 400 'Danh sách có 1001 mã, vượt giới hạn…' (chữ 'mã'); đúng 1000 mã khớp hết ⇒ nhận; trần truyền vào ưu tiên", () => {
    const tu = (n: number) => Array.from({ length: n }, (_, i) => CCCD(i + 1))
    const khoLon = new Map(tu(1001).map((m, i) => [m, i + 1] as [string, number]))
    expect(goiMa(tu(1000), {}, khoLon)).toBeNull()
    expect(chiTiet(goiMa(tu(1001), {}, khoLon))).toBe("Danh sách có 1001 mã, vượt giới hạn kỹ thuật 1000 hồ sơ cho một bộ văn bản.")
    expect(chiTiet(goiMa(tu(3), { toiDa: 2 }, khoLon))).toBe("Danh sách có 3 mã, vượt giới hạn kỹ thuật 2 hồ sơ cho một bộ văn bản.")
  })
  it("Đ3-5: trần đứng SAU cú pháp và TRƯỚC khớp CSDL — 1001 mã có dòng 5 sai dạng ⇒ báo dòng 5; 1001 mã không có trong kho ⇒ báo TRẦN (không phải câu gộp)", () => {
    const tu = (n: number) => Array.from({ length: n }, (_, i) => CCCD(i + 1))
    const coSai = tu(1001)
    coSai[4] = "09999900000"
    expect(chiTiet(goiMa(coSai, {}, new Map()))).toMatch(/^Dòng 5: mã hồ sơ phải gồm đúng 12 chữ số/)
    expect(chiTiet(goiMa(tu(1001), {}, new Map()))).toBe("Danh sách có 1001 mã, vượt giới hạn kỹ thuật 1000 hồ sơ cho một bộ văn bản.")
  })

  // ── Đ3-5b: lớp SCHEMA (pydantic) chạy TRƯỚC service ─────────────────────────────────────────────────────────────────────────
  it("Đ3-5b: phần tử KHÔNG PHẢI CHUỖI ⇒ 422 ở lớp schema (string_type, loc kèm CHỈ SỐ phần tử) — không còn 400 'không phải chuỗi' của service", () => {
    const r = goiMa([CCCD(1), 123456789012])
    expect(r).toEqual({
      status: 422,
      body: {
        detail: "Request validation failed",
        error_code: "VALIDATION_ERROR",
        errors: [{ type: "string_type", loc: ["body", "ma_ho_so", 1], msg: "Input should be a valid string" }],
      },
    })
    expect(goiMa([CCCD(1), null])).toMatchObject({ status: 422, body: { errors: [{ loc: ["body", "ma_ho_so", 1] }] } })
  })
  it("Đ3-5b: pydantic báo MỌI phần tử sai (không dừng ở phần tử đầu); mã chuỗi không bị tính", () => {
    const r = goiMa([CCCD(1), 5, null, CCCD(4), true, {}])
    expect((r?.body as { errors: Array<{ loc: unknown[] }> }).errors.map((e) => e.loc)).toEqual([
      ["body", "ma_ho_so", 1],
      ["body", "ma_ho_so", 2],
      ["body", "ma_ho_so", 4],
      ["body", "ma_ho_so", 5],
    ])
  })
  it("Đ3-5b: ma_ho_so rỗng ⇒ 422 too_short; không phải danh sách ('abc' / số / đối tượng) ⇒ 422 list_type — KHÔNG phải 400 'Danh sách mã hồ sơ rỗng.'", () => {
    expect(goiMa([])).toEqual({
      status: 422,
      body: {
        detail: "Request validation failed",
        error_code: "VALIDATION_ERROR",
        errors: [{ type: "too_short", loc: ["body", "ma_ho_so"], msg: "List should have at least 1 item after validation, not 0" }],
      },
    })
    for (const sai of ["abc", 5, {}]) {
      expect(goiMa(sai)).toMatchObject({ status: 422, body: { errors: [{ type: "list_type", loc: ["body", "ma_ho_so"], msg: "Input should be a valid list" }] } })
    }
  })
  it("Đ3-5b: lỗi TRƯỜNG (schema) đứng trước lỗi 'đúng MỘT dạng' của validator mô hình: ma_ho_so sai kiểu + profile_ids ⇒ lỗi phần tử, không phải câu 'Gửi đúng MỘT dạng'", () => {
    const r = luatTaoBo({ ma_ho_so: [CCCD(1), 7], profile_ids: [1], phien_ban_kiem: "x", academic_year: 2026 }, { anh: null, idTheoMa: kho })
    expect(r).toMatchObject({ status: 422, body: { errors: [{ type: "string_type", loc: ["body", "ma_ho_so", 1] }] } })
    // đối chứng: ma_ho_so ĐÚNG kiểu + profile_ids ⇒ câu 'đúng MỘT dạng' như cũ
    expect(luatTaoBo({ ma_ho_so: [CCCD(1)], profile_ids: [1], phien_ban_kiem: "x", academic_year: 2026 }, { anh: null, idTheoMa: kho })).toMatchObject({ status: 422 })
  })
})
describe("luatLopSchemaMa / luatDoiMaTruoc — doi-ma dùng List[StrictStr] (cùng luật) + trần theo 'dòng'", () => {
  it("luatLopSchemaMa: danh sách chuỗi ⇒ qua", () => {
    expect(luatLopSchemaMa([CCCD(1), ""])).toBeNull() // chuỗi rỗng vẫn là CHUỖI (rỗng là việc của service, không phải schema)
  })
  it("luatDoiMaTruoc ĐÚNG: thân đủ + 1000 dòng ⇒ qua (null)", () => {
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: [CCCD(1)] })).toBeNull()
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: Array.from({ length: 1000 }, (_, i) => CCCD(i + 1)) })).toBeNull()
  })
  it("luatDoiMaTruoc: 1001 dòng ⇒ 400 'Danh sách có 1001 dòng, vượt…' (chữ 'dòng'); trần đếm TRƯỚC kiểm từng mã (dòng sai không đổi câu)", () => {
    const nhieu = Array.from({ length: 1001 }, (_, i) => (i === 3 ? "abc" : CCCD(i + 1)))
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: nhieu })).toEqual({
      status: 400,
      body: { detail: "Danh sách có 1001 dòng, vượt giới hạn kỹ thuật 1000 hồ sơ cho một bộ văn bản.", error_code: "DATA_VALIDATION_ERROR" },
    })
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: [1, 2, 3] }, 2)).toMatchObject({ status: 422 }) // schema TRƯỚC trần
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: [CCCD(1), CCCD(2), CCCD(3)] }, 2)).toMatchObject({
      status: 400,
      body: { detail: "Danh sách có 3 dòng, vượt giới hạn kỹ thuật 2 hồ sơ cho một bộ văn bản." },
    })
  })
  it("luatDoiMaTruoc: phần tử không phải chuỗi / rỗng / thiếu trường / khoá lạ / năm học là chuỗi ⇒ 422 đúng loại", () => {
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: [CCCD(1), 12] })).toMatchObject({ status: 422, body: { errors: [{ type: "string_type", loc: ["body", "ma_ho_so", 1] }] } })
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: [] })).toMatchObject({ status: 422, body: { errors: [{ type: "too_short" }] } })
    expect(luatDoiMaTruoc({ academic_year: 2026 })).toMatchObject({ status: 422, body: { errors: [{ type: "missing", loc: ["body", "ma_ho_so"] }] } })
    expect(luatDoiMaTruoc({ ma_ho_so: [CCCD(1)] })).toMatchObject({ status: 422, body: { errors: [{ type: "missing", loc: ["body", "academic_year"] }] } })
    expect(luatDoiMaTruoc({ academic_year: 2026, ma_ho_so: [CCCD(1)], trang_thai: [] })).toMatchObject({ status: 422, body: { errors: [{ type: "extra_forbidden" }] } })
    expect(luatDoiMaTruoc({ academic_year: "2026", ma_ho_so: [CCCD(1)] })).toMatchObject({ status: 422, body: { errors: [{ type: "int_type", loc: ["body", "academic_year"] }] } })
  })
})

// ── 8. POST /decisions ──────────────────────────────────────────────────────────────────────────────────────────────────
describe("luatGhiNhan — xac_nhan_so_ho_so, goc_id ↔ loai, tham số đã in, số theo NĂM KÝ", () => {
  // bộ: set_id 1, so_ho_so 4, đã in số "201" + ngày QĐ 2027-03-10 + đợt (1, 9); dựng 2027-03-01. Năm học 2026 ≠ năm ký 2027.
  const cx = (over: Partial<NguCanhGhiNhan["bo"]> = {}, cho: Partial<NguCanhGhiNhan> = {}): NguCanhGhiNhan => ({
    bo: {
      so_ho_so: SO_HO_SO,
      tham_so: { so_quyet_dinh: SO_QD, ngay_quyet_dinh: "2027-03-10", dot_so: "1", dot_thang: 9 },
      ngay_dung: "2027-03-01",
      ...over,
    },
    goc: (id) => ({ 30: { loai: "trung_tuyen", trang_thai: "hieu_luc" }, 31: { loai: "trung_tuyen", trang_thai: "huy_ghi_nhan" }, 32: { loai: "bo_sung", trang_thai: "hieu_luc" } } as const)[id as 30 | 31 | 32],
    soDaDung: (so, nam) => (so === "300" && nam === 2027 ? 77 : undefined),
    ...cho,
  })
  const form = (o: Record<string, string | undefined> = {}, scan: File | null = new File(["%PDF-1.4 gia"], "scan.pdf")) => {
    const goc: Record<string, string | undefined> = {
      set_id: String(SET_ID), ma_luot_gui: MA_LUOT, loai: "trung_tuyen", so_quyet_dinh: SO_QD, ngay_ky: "2027-03-10",
      dot_so: "1", dot_thang: "9", xac_nhan_so_ho_so: String(SO_HO_SO), xac_nhan_khop_ban_in: "true", ...o,
    }
    const f = new FormData()
    for (const [k, v] of Object.entries(goc)) if (v !== undefined) f.append(k, v)
    if (scan) f.append("scan", scan)
    return f
  }

  it("ĐÚNG: đủ trường, khớp bản in", async () => {
    expect(await luatGhiNhan(form(), cx())).toBeNull()
  })
  it("xac_nhan_so_ho_so: ĐÚNG 4 (số hồ sơ của bộ); SAI 201 (số QĐ), 1 (set_id), 5 ⇒ 400 'không khớp số hồ sơ của bộ'", async () => {
    expect(await luatGhiNhan(form({ xac_nhan_so_ho_so: "4" }), cx())).toBeNull()
    for (const sai of ["201", "1", "5"]) {
      expect(await luatGhiNhan(form({ xac_nhan_so_ho_so: sai }), cx())).toMatchObject({
        status: 400,
        body: { error_code: "DATA_VALIDATION_ERROR", detail: "Số hồ sơ gõ lại không khớp số hồ sơ của bộ." },
      })
    }
  })
  it("goc_id ↔ loai: ĐÚNG bo_sung + gốc là trúng tuyển ĐANG hiệu lực; SAI trung_tuyen + goc_id ⇒ 400; SAI bo_sung không goc_id ⇒ 400", async () => {
    expect(await luatGhiNhan(form({ loai: "bo_sung", goc_id: "30" }), cx())).toBeNull()
    expect(await luatGhiNhan(form({ loai: "trung_tuyen", goc_id: "30" }), cx())).toMatchObject({
      status: 400,
      body: { detail: "Quyết định bổ sung phải chọn Quyết định gốc; Quyết định trúng tuyển thì không." },
    })
    expect(await luatGhiNhan(form({ loai: "bo_sung" }), cx())).toMatchObject({ status: 400 })
  })
  it("goc_id: gốc đã huỷ / gốc là Quyết định bổ sung ⇒ 409; không có gốc ⇒ 404", async () => {
    expect(await luatGhiNhan(form({ loai: "bo_sung", goc_id: "31" }), cx())).toMatchObject({ status: 409 })
    expect(await luatGhiNhan(form({ loai: "bo_sung", goc_id: "32" }), cx())).toMatchObject({ status: 409 })
    expect(await luatGhiNhan(form({ loai: "bo_sung", goc_id: "99" }), cx())).toMatchObject({ status: 404 })
  })
  it("tham số đã in: ĐÚNG gửi 201; SAI 202 ⇒ 400 nêu 'số Quyết định'; ngày ký lệch ngày QĐ đã in ⇒ 400", async () => {
    expect(await luatGhiNhan(form({ so_quyet_dinh: "202" }), cx())).toMatchObject({ status: 400, body: { truong_lech: ["số Quyết định"] } })
    expect(await luatGhiNhan(form({ ngay_ky: "2027-03-11" }), cx())).toMatchObject({ status: 400, body: { truong_lech: ["ngày Quyết định"] } })
  })
  it("dot_so ↔ dot_thang: bộ in (1, 9): ĐÚNG gửi (1, 9); SAI hoán (9, 1) ⇒ 400 lệch cả hai; thiếu dot_thang ⇒ 400", async () => {
    expect(await luatGhiNhan(form({ dot_so: "1", dot_thang: "9" }), cx())).toBeNull()
    expect(await luatGhiNhan(form({ dot_so: "9", dot_thang: "1" }), cx())).toMatchObject({ status: 400, body: { truong_lech: ["dot_so", "dot_thang"] } })
    expect(await luatGhiNhan(form({ dot_thang: undefined }), cx())).toMatchObject({ status: 400, body: { truong_lech: ["dot_thang"] } })
  })
  it("bộ để TRỐNG tham số ⇒ nhận giá trị Admin gõ (kể cả đợt (2, 3)); bộ ĐÃ in thì không", async () => {
    const trong = cx({ tham_so: null })
    expect(await luatGhiNhan(form({ so_quyet_dinh: "202", dot_so: "2", dot_thang: "3" }), trong)).toBeNull()
  })
  it("dot_thang 13 / dot_so 3 chữ số ⇒ 422 (khuôn trường của router)", async () => {
    expect(await luatGhiNhan(form({ dot_thang: "13" }), cx({ tham_so: null }))).toMatchObject({ status: 422 })
    expect(await luatGhiNhan(form({ dot_so: "100" }), cx({ tham_so: null }))).toMatchObject({ status: 422 })
  })
  it("số trùng tính theo NĂM CỦA NGÀY KÝ (2027), không phải năm học (2026): 300 đã dùng 2027 ⇒ 409; ngày ký 2028 ⇒ ĐÚNG", async () => {
    const trong = cx({ tham_so: null, ngay_dung: "2027-03-01" })
    expect(await luatGhiNhan(form({ so_quyet_dinh: "300", ngay_ky: "2027-04-01" }), trong)).toMatchObject({ status: 409, body: { quyet_dinh_id: 77 } })
    expect(await luatGhiNhan(form({ so_quyet_dinh: "300", ngay_ky: "2028-04-01" }), trong)).toBeNull()
  })
  it("ngày ký TRƯỚC ngày dựng bộ ⇒ 400; đúng ngày dựng ⇒ ĐÚNG", async () => {
    const trong = cx({ tham_so: null, ngay_dung: "2027-03-01" })
    expect(await luatGhiNhan(form({ ngay_ky: "2027-02-28" }), trong)).toMatchObject({ status: 400 })
    expect(await luatGhiNhan(form({ ngay_ky: "2027-03-01" }), trong)).toBeNull()
  })
  it("Đ3-4: bộ TÁI DỰNG theo bản ký (`ban_ky`) KHÔNG bị chặn 'ngày ký trước ngày dựng' (:425 chỉ áp khi ban_ky_so_quyet_dinh is None); bộ thường (vắng / null) vẫn bị chặn", async () => {
    const banKy = { so_quyet_dinh: SO_QD, ngay: "2027-02-20" } // ký 20-02, bộ tái dựng ngày 01-03 (SAU ngày ký)
    const f = () => form({ ngay_ky: "2027-02-20" })
    expect(await luatGhiNhan(f(), cx({ tham_so: null, ban_ky: banKy }))).toBeNull()
    expect(await luatGhiNhan(f(), cx({ tham_so: null, ban_ky: null }))).toMatchObject({ status: 400, body: { detail: expect.stringContaining("Ngày ký trước ngày dựng bộ") } })
    expect(await luatGhiNhan(f(), cx({ tham_so: null }))).toMatchObject({ status: 400, body: { detail: expect.stringContaining("Ngày ký trước ngày dựng bộ") } })
  })
  it("bộ tái dựng: số / ngày trên giấy PHẢI bằng bản ký đã khai (`_so_tham_so` :210) — lệch ⇒ 400 truong_lech nêu đúng một mục, đứng ĐẦU danh sách", async () => {
    const banKy = { so_quyet_dinh: SO_QD, ngay: "2027-02-20" }
    const muc = "số / ngày của bản ký đã khai khi tái dựng"
    // lệch SỐ (202 ≠ 201), cùng ngày
    expect(await luatGhiNhan(form({ so_quyet_dinh: "202", ngay_ky: "2027-02-20" }), cx({ tham_so: null, ban_ky: banKy }))).toMatchObject({ status: 400, body: { truong_lech: [muc] } })
    // lệch NGÀY (2027-02-21 ≠ 2027-02-20), cùng số
    expect(await luatGhiNhan(form({ ngay_ky: "2027-02-21" }), cx({ tham_so: null, ban_ky: banKy }))).toMatchObject({ status: 400, body: { truong_lech: [muc] } })
    // bộ tái dựng ĐỒNG THỜI có số QĐ đã in lệch ⇒ mục bản ký đứng TRƯỚC (thứ tự của `_so_tham_so`)
    expect(
      await luatGhiNhan(form({ so_quyet_dinh: "202", ngay_ky: "2027-02-20" }), cx({ ban_ky: banKy, tham_so: { so_quyet_dinh: SO_QD } })),
    ).toMatchObject({ status: 400, body: { truong_lech: [muc, "số Quyết định"] } })
  })
  it("xác nhận khớp bản in: 'false' ⇒ 400; bộ đã có văn bản sống ⇒ 409", async () => {
    expect(await luatGhiNhan(form({ xac_nhan_khop_ban_in: "false" }), cx())).toMatchObject({ status: 400 })
    expect(await luatGhiNhan(form(), cx({ van_ban_song_id: 5 }))).toMatchObject({ status: 409, body: { quyet_dinh_id: 5 } })
  })
  it("scan: thiếu / rỗng / không phải PDF (.docx) ⇒ 400", async () => {
    expect(await luatGhiNhan(form({}, null), cx())).toMatchObject({ status: 400 })
    expect(await luatGhiNhan(form({}, new File([], "scan.pdf")), cx())).toMatchObject({ status: 400 })
    expect(await luatGhiNhan(form({}, new File(["PK\u0003\u0004"], "scan.docx")), cx())).toMatchObject({ status: 400 })
  })
  it("Đ3-3: scan không phải PDF ⇒ 400 ĐÚNG câu máy chủ 'Bản scan phải là tệp PDF.' (decision_service:111) — không kèm '(%PDF-)'; phần mở rộng .pdf không cứu được nội dung", async () => {
    for (const sai of [new File(["hello world"], "scan.pdf"), new File(["%PDF"], "scan.pdf")]) {
      // `%PDF` thiếu dấu '-' ⇒ chữ ký sai
      expect(await luatGhiNhan(form({}, sai), cx())).toEqual({
        status: 400,
        body: { detail: "Bản scan phải là tệp PDF.", error_code: "DATA_VALIDATION_ERROR" },
      })
    }
    expect(await luatGhiNhan(form({}, new File(["%PDF-1.7"], "scan.pdf")), cx())).toBeNull() // đúng chữ ký ⇒ nhận
  })
  // tệp `n` byte, bắt đầu bằng chữ ký `%PDF-`
  const pdf = (n: number) => {
    const u = new Uint8Array(n)
    u.set([0x25, 0x50, 0x44, 0x46, 0x2d])
    return new File([u], "scan.pdf")
  }
  const CAU_TRAN = (n: number) => ({ status: 400, body: { detail: `Bản scan vượt giới hạn kỹ thuật ${n} byte.`, error_code: "DATA_VALIDATION_ERROR" } })
  it("Đ3-6: trần byte của scan (kiem_scan) — ĐÚNG trần ⇒ nhận; trần + 1 ⇒ 400 nêu TRẦN (không nêu kích thước); kiểm TRƯỚC chữ ký PDF; tệp rỗng ⇒ câu 'Phải kèm' đứng trước", async () => {
    const tran = { scanToiDa: 100 }
    expect(await luatGhiNhan(form({}, pdf(100)), cx({}, tran))).toBeNull()
    expect(await luatGhiNhan(form({}, pdf(101)), cx({}, tran))).toEqual(CAU_TRAN(100))
    expect(await luatGhiNhan(form({}, pdf(5000)), cx({}, tran))).toEqual(CAU_TRAN(100)) // nêu TRẦN, không nêu 5000
    // quá trần mà KHÔNG phải PDF ⇒ vẫn câu TRẦN (trần kiểm trước chữ ký)
    expect(await luatGhiNhan(form({}, new File([new Uint8Array(101)], "scan.pdf")), cx({}, tran))).toEqual(CAU_TRAN(100))
    // dưới trần mà không phải PDF ⇒ câu chữ ký (đối chứng: trần không nuốt câu PDF)
    expect(await luatGhiNhan(form({}, new File([new Uint8Array(50)], "scan.pdf")), cx({}, tran))).toMatchObject({ body: { detail: "Bản scan phải là tệp PDF." } })
    expect(await luatGhiNhan(form({}, new File([], "scan.pdf")), cx({}, tran))).toMatchObject({ body: { detail: "Phải kèm bản scan (PDF) của văn bản đã ký." } })
  })
  it("Đ3-6: trần MẶC ĐỊNH 20 MiB (20.971.520 byte, cấu hình mặc định của máy chủ): đúng 20 MiB ⇒ nhận; 20 MiB + 1 byte ⇒ 400 nêu 20971520", async () => {
    expect(await luatGhiNhan(form({}, pdf(20 * 1024 * 1024)), cx())).toBeNull()
    expect(await luatGhiNhan(form({}, pdf(20 * 1024 * 1024 + 1)), cx())).toEqual(CAU_TRAN(20971520))
  })
})

// ── 10. huỷ ghi nhận ────────────────────────────────────────────────────────────────────────────────────────────────────
describe("luatHuyGhiNhan — so_go_lai = SỐ QUYẾT ĐỊNH, nguyên chuỗi (Đ2-1)", () => {
  const qd = { so_quyet_dinh: SO_QD, trang_thai: "hieu_luc" }
  it("ĐÚNG: '201'", () => {
    expect(luatHuyGhiNhan({ ly_do: "Nhập sai", so_go_lai: "201" }, qd)).toBeNull()
  })
  it("SAI: '4' (số hồ sơ), '1' (set_id), ' 201' (khoảng trắng; máy chủ so NGUYÊN chuỗi) ⇒ 400 'Số văn bản gõ lại không khớp.'", () => {
    for (const sai of ["4", "1", " 201"]) {
      expect(luatHuyGhiNhan({ ly_do: "Nhập sai", so_go_lai: sai }, qd)).toMatchObject({
        status: 400,
        body: { detail: "Số văn bản gõ lại không khớp.", error_code: "DATA_VALIDATION_ERROR" },
      })
    }
  })
  it("SAI: lý do trống ⇒ 400; so_go_lai là SỐ (không phải chuỗi) ⇒ 422; văn bản đã huỷ ⇒ 409", () => {
    expect(luatHuyGhiNhan({ ly_do: "  ", so_go_lai: "201" }, qd)).toMatchObject({ status: 400 })
    expect(luatHuyGhiNhan({ ly_do: "x", so_go_lai: 201 }, qd)).toMatchObject({ status: 422 })
    expect(luatHuyGhiNhan({ ly_do: "x", so_go_lai: "201" }, { ...qd, trang_thai: "huy_ghi_nhan" })).toMatchObject({ status: 409 })
  })
})

// ── 11. lượt gửi ────────────────────────────────────────────────────────────────────────────────────────────────────────
describe("lượt gửi", () => {
  it("mở lượt: chưa có lượt chờ ⇒ ĐÚNG; đã có cho_gui ⇒ 409 luot_dang_cho kèm mã + giờ", () => {
    expect(luatMoLuot(null)).toBeNull()
    expect(luatMoLuot({ ma: MA_LUOT, tao_luc: "2026-11-11T02:00:00Z" })).toMatchObject({
      status: 409,
      body: { ma_loi: "luot_dang_cho", ma: MA_LUOT, tao_luc: "2026-11-11T02:00:00Z" },
    })
  })
  it("phân xử: mã uuid ⇒ ĐÚNG; chuỗi lạ ⇒ 422", () => {
    expect(luatPhanXuMa(MA_LUOT)).toBeNull()
    expect(luatPhanXuMa("../../etc/passwd")).toMatchObject({ status: 422 })
  })
})
