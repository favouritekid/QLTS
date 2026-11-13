/**
 * LUẬT MÁY CHỦ THẬT của các lệnh ghi giao diện Văn bản Hội đồng — chép lại cho MSW (Codex lần 20, câu 2: "OpenAPI kiểm hình
 * dạng không bắt được nhầm nghĩa này; MSW phải từ chối theo luật thật").
 *
 * Nguồn: bảng `HOP-DONG-THAN-YEU-CAU-LENH-GHI-GD1-2026-11-13.md` (phiên A) + mã máy chủ LXT1 `19424587`:
 *   council_decision_service.py (ghi_nhan_quyet_dinh :339, huy_ghi_nhan :807, _so_tham_so :203, _so_chua_dung :318, _bo_qd_hop_le :286),
 *   council_document_set_service.py (so_voi_kiem_truoc, kiem_danh_sach_id, kiem_ly_do), council_document_template_service.py (tai_mau_len),
 *   council_document_render_service.py (DecisionParams), council_candidate_service.py (loi_mot_ma), router council_documents.py (Form).
 *
 * Mỗi hàm trả `null` (máy chủ NHẬN) hoặc `LoiMayChu` {status, body} đúng khuôn handler lỗi thật:
 *   400 {detail, error_code:"DATA_VALIDATION_ERROR"} · 404 "RESOURCE_NOT_FOUND" · 409 "CONFLICT" / "DUPLICATE_RESOURCE" (+ `ma_loi` …) ·
 *   422 {detail:"Request validation failed", error_code:"VALIDATION_ERROR", errors:[{type, loc, msg}]}.
 *
 * ⚠️ Chỉ ÁP những luật mà MSW có đủ dữ liệu để áp. Luật cố ý KHÔNG áp (ghi lý do ở từng hàm + trong báo cáo): kiểm nội dung tệp mẫu
 * `.docx` (`bo_dung.kiem_mau`), kho mẫu theo ngày ký (`_kiem_mau_theo_ngay_ky`), dòng bộ / chỉ tiêu / khoá (`_bo_qd_hop_le` phần dòng,
 * `khoa_chi_tieu_cua_dong_bo`), đếm đổi trạng thái (`_kiem_xac_nhan_dem`), cổng kiểm trước (`cong.danh_gia`) — cần CSDL.
 */
import { HttpResponse } from "msw"

export interface LoiMayChu {
  status: number
  body: Record<string, unknown>
}

/** Biến lỗi luật thành phản hồi MSW; `null` ⇒ máy chủ nhận (handler tự trả thân thành công). */
export function dap(loi: LoiMayChu | null): Response | null {
  return loi === null ? null : HttpResponse.json(loi.body, { status: loi.status })
}

const mien = (status: number, detail: string, code: string, them: Record<string, unknown> = {}): LoiMayChu => ({
  status,
  body: { detail, error_code: code, ...them },
})
export const loi400 = (detail: string, them?: Record<string, unknown>) => mien(400, detail, "DATA_VALIDATION_ERROR", them)
export const loi404 = (detail: string) => mien(404, detail, "RESOURCE_NOT_FOUND")
export const loi409 = (detail: string, them?: Record<string, unknown>) => mien(409, detail, "CONFLICT", them)
export const loiTrung = (detail: string) => mien(409, detail, "DUPLICATE_RESOURCE")
export const loi422 = (loc: string[], msg: string, type = "value_error"): LoiMayChu => ({
  status: 422,
  body: { detail: "Request validation failed", error_code: "VALIDATION_ERROR", errors: [{ type, loc: ["body", ...loc], msg }] },
})

// ── hằng và hàm nhỏ chung ────────────────────────────────────────────────────────────────────────────────────────────────
export const LY_DO_TOI_DA = 1000 // LY_DO_XOA_TOI_DA (models/council_document.py:81)
export const CAU_DOI_TU_LUC_KIEM = "Dữ liệu đã đổi từ lúc kiểm — bấm Kiểm tra lại."
export const MA_LOI_DOI_TU_LUC_KIEM = "du_lieu_doi_tu_luc_kiem"
/** Mã trạng thái hồ sơ hợp lệ (CHECK 15 trạng thái ở `app/models/admission.py`). */
export const TRANG_THAI_HO_SO = [
  "draft", "submitted", "resubmitted", "approved", "overridden", "confirmed", "enrolled", "reviewing", "result_published",
  "admitted", "waitlisted", "rejected", "revision_requested", "withdrawal_pending", "withdrawn",
] as const
const RE_NGAY = /^\d{4}-\d{2}-\d{2}$/
const RE_SO_1_6 = /^[0-9]{1,6}$/
const RE_SO_1_2 = /^[0-9]{1,2}$/
const RE_UUID = /^[0-9a-fA-F-]{36}$/
const RE_MA_HO_SO = /^(?:[0-9]{12}|[0-9]{9})$/

/** Ngày `YYYY-MM-DD` hợp lệ (lịch thật) — như `date` của FastAPI. */
export function laNgay(v: unknown): v is string {
  if (typeof v !== "string" || !RE_NGAY.test(v)) return false
  const d = new Date(`${v}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v
}

/** Là tệp tải lên? (duck-typing: `File` của undici trong handler MSW KHÔNG là `instanceof Blob` của jsdom). */
function laTep(v: unknown): v is Blob {
  return typeof v === "object" && v !== null && typeof (v as Blob).slice === "function" && typeof (v as Blob).size === "number"
}

/** Đọc `n` ký tự đầu của tệp tải lên (jsdom có thể thiếu `Blob.text()` ⇒ rơi về `FileReader`; undici `File` của MSW có `text()`). */
async function docDauTep(b: Blob, n: number): Promise<string> {
  const phan = b.slice(0, n)
  if (typeof phan.text === "function") return phan.text()
  return await new Promise<string>((xong, hong) => {
    const r = new FileReader()
    r.onload = () => xong(String(r.result))
    r.onerror = () => hong(r.error)
    r.readAsText(phan)
  })
}

/** `kiem_ly_do` (MỘT nguồn): chuỗi; cắt khoảng trắng hai đầu; không rỗng; ≤ 1000; không ký tự nhóm C ngoài xuống dòng / tab. */
export function luatLyDo(ly: unknown, viec: string): LoiMayChu | null {
  if (typeof ly !== "string") return loi400(`Lý do ${viec} phải là chữ.`)
  const s = ly.trim()
  if (s === "") return loi400(`Phải nhập lý do ${viec}.`)
  if ([...s].length > LY_DO_TOI_DA) return loi400(`Lý do ${viec} dài quá giới hạn kỹ thuật ${LY_DO_TOI_DA} ký tự.`)
  if ([...s].some((c) => /\p{C}/u.test(c) && !"\n\r\t".includes(c))) return loi400(`Lý do ${viec} có ký tự điều khiển / vô hình — gõ lại.`)
  return null
}

// ── 7. DELETE /sets/{id} ─────────────────────────────────────────────────────────────────────────────────────────────────
/** `kiem_ly_do_xoa` + bộ đang có văn bản hiệu lực ⇒ 409. `ly_do` thiếu / không phải chuỗi ⇒ 422 (StrictStr). */
export function luatXoaBo(thanBody: unknown, bo: { coVanBanHieuLuc: boolean }): LoiMayChu | null {
  const ly = (thanBody as { ly_do?: unknown } | null)?.ly_do
  if (typeof ly !== "string") return loi422(["ly_do"], "Input should be a valid string", "string_type")
  const sai = luatLyDo(ly, "xoá bộ văn bản")
  if (sai) return sai
  if (bo.coVanBanHieuLuc) return loi409("Bộ này đang có văn bản hiệu lực — không xoá được.")
  return null
}

// ── 1. POST /templates ───────────────────────────────────────────────────────────────────────────────────────────────────
const TEN_LOAI_MAU: Record<string, string> = { bien_ban: "Biên bản", quyet_dinh: "Quyết định", danh_sach: "Danh sách" }
/**
 * `tai_mau_len`: loại ∈ 3 loại; `hieu_luc_tu` là NGÀY (áp cho văn bản KÝ từ ngày này — KHÔNG phải ngày tải); ghi chú ≤ 500 ký tự;
 * cùng (loại, ngày hiệu lực) đã có ⇒ 409 (không ghi đè; hai mẫu cùng loại KHÁC ngày ⇒ được).
 * KHÔNG áp: `bo_dung.kiem_mau` (nội dung .docx) — chỉ kiểm có tệp và chữ ký ZIP `PK`.
 */
export async function luatTaiMau(
  form: FormData,
  mauDaCo: ReadonlyArray<{ loai: string; hieu_luc_tu: string }>,
): Promise<LoiMayChu | null> {
  const loai = form.get("loai")
  const hieu = form.get("hieu_luc_tu")
  const ghiChu = form.get("ghi_chu")
  const tep = form.get("file")
  if (typeof loai !== "string") return loi422(["loai"], "Field required", "missing")
  if (typeof hieu !== "string" || !laNgay(hieu)) return loi422(["hieu_luc_tu"], "Input should be a valid date or datetime", "date_from_datetime_parsing")
  if (!laTep(tep)) return loi422(["file"], "Field required", "missing")
  if (!(loai in TEN_LOAI_MAU)) return loi400("Loại mẫu không thuộc bien_ban / quyet_dinh / danh_sach.")
  if (typeof ghiChu === "string" && [...ghiChu].length > 500) return loi400("Ghi chú của mẫu dài quá 500 ký tự.")
  if (tep.size === 0 || (await docDauTep(tep, 2)) !== "PK") return loi400("Tệp mẫu không phải .docx hợp lệ.")
  if (mauDaCo.some((m) => m.loai === loai && m.hieu_luc_tu === hieu)) {
    return loiTrung(`Đã có mẫu ${TEN_LOAI_MAU[loai]} hiệu lực từ ngày ${hieu}.`)
  }
  return null
}

// ── mã hồ sơ (dùng chung `POST /sets` dạng mã và `POST /sets/doi-ma`) ─────────────────────────────────────────────────
export type LyDoMa = "khong_phai_chuoi" | "rong" | "ky_tu_la" | "sai_dinh_dang"
/**
 * `loi_mot_ma` (candidate_service:273, theo thứ tự): không phải chuỗi ⇒ khong_phai_chuoi; rỗng (sau cắt) ⇒ rong; dài > 32 hoặc ký tự nhóm C ⇒
 * ky_tu_la; không đúng 12 hoặc 9 chữ số ASCII ⇒ sai_dinh_dang.
 * ⚠️ Đây là luật TẦNG SERVICE. Ở ranh giới HTTP schema (`List[str]` / `List[StrictStr]`) chặn phần tử không phải chuỗi bằng 422 TRƯỚC khi tới
 * đây — mô-đun này chưa áp lớp schema ấy cho `ma_ho_so`.
 */
export function loiMotMa(m: unknown): { ma: string | null; ly_do: LyDoMa | null } {
  if (typeof m !== "string") return { ma: null, ly_do: "khong_phai_chuoi" }
  const s = m.trim()
  if (s === "") return { ma: s, ly_do: "rong" }
  if ([...s].length > 32 || [...s].some((c) => /\p{C}/u.test(c))) return { ma: s, ly_do: "ky_tu_la" }
  if (!RE_MA_HO_SO.test(s)) return { ma: s, ly_do: "sai_dinh_dang" }
  return { ma: s, ly_do: null }
}

// ── 5. POST /sets/doi-ma ─────────────────────────────────────────────────────────────────────────────────────────────────
export interface DoiMaOut {
  profile_ids: number[]
  dong_loi: Array<{ dong: number; ly_do: string }>
}
/** Trả id theo thứ tự dòng + lỗi theo SỐ DÒNG (không nêu giá trị). Mã đúng nhưng NGOÀI phạm vi / sai năm ⇒ `khong_khop`; dòng trùng ⇒ dòng sau mang `trung`. */
export function luatDoiMa(codes: unknown, idTheoMa: ReadonlyMap<string, number>): DoiMaOut {
  const out: DoiMaOut = { profile_ids: [], dong_loi: [] }
  const gap = new Set<string>()
  ;(Array.isArray(codes) ? codes : []).forEach((c, i) => {
    const { ma, ly_do } = loiMotMa(c)
    if (ly_do) return void out.dong_loi.push({ dong: i + 1, ly_do })
    if (ma !== null && gap.has(ma)) return void out.dong_loi.push({ dong: i + 1, ly_do: "trung" })
    if (ma !== null) gap.add(ma)
    const id = ma === null ? undefined : idTheoMa.get(ma)
    if (id === undefined) return void out.dong_loi.push({ dong: i + 1, ly_do: "khong_khop" })
    out.profile_ids.push(id)
  })
  return out
}

// ── 6. POST /sets/tim-ho-so ──────────────────────────────────────────────────────────────────────────────────────────────
/** Schema (`extra=forbid`, page ≥ 1, page_size 1…100) + service: từ khoá cắt khoảng trắng ≤ 100 ký tự; trạng thái ∈ CHECK. */
export function luatTimHoSo(than: Record<string, unknown>): LoiMayChu | null {
  const khoa = new Set(["academic_year", "tu_khoa", "major_ids", "trang_thai", "page", "page_size"])
  const la = Object.keys(than).find((k) => !khoa.has(k))
  if (la) return loi422([la], "Extra inputs are not permitted", "extra_forbidden")
  if (!Number.isInteger(than.academic_year)) return loi422(["academic_year"], "Input should be a valid integer", "int_type")
  if (than.page !== undefined && (!Number.isInteger(than.page) || (than.page as number) < 1)) return loi422(["page"], "Input should be greater than or equal to 1", "greater_than_equal")
  if (than.page_size !== undefined && (!Number.isInteger(than.page_size) || (than.page_size as number) < 1 || (than.page_size as number) > 100)) {
    return loi422(["page_size"], "Input should be less than or equal to 100", "less_than_equal")
  }
  if (typeof than.tu_khoa === "string" && than.tu_khoa.length > 200) return loi422(["tu_khoa"], "String should have at most 200 characters", "string_too_long")
  if (typeof than.tu_khoa === "string" && [...than.tu_khoa.trim()].length > 100) return loi400("Từ khoá tìm kiếm dài quá 100 ký tự.")
  if (Array.isArray(than.trang_thai) && than.trang_thai.some((t) => !(TRANG_THAI_HO_SO as readonly unknown[]).includes(t))) {
    return loi400("Trạng thái hồ sơ không hợp lệ.")
  }
  return null
}

// ── 4. POST /sets/kiem-truoc  (và kiem_danh_sach_id dùng chung với POST /sets dạng id) ────────────────────────────────────
/** Trần số hồ sơ của MỘT bộ = mặc định của `COUNCIL_SET_MAX_PROFILES` (app/config.py:455 — `default=1000`; prod không đặt biến ⇒ 1000). */
export const TRAN_HO_SO_MAC_DINH = 1000
/** `kiem_danh_sach_id`: rỗng / vượt trần / id không phải số nguyên dương / TRÙNG (nêu số dòng, không nêu giá trị). */
export function luatDanhSachId(ids: unknown, toiDa = TRAN_HO_SO_MAC_DINH): LoiMayChu | null {
  if (!Array.isArray(ids) || ids.length === 0) return loi400("Danh sách hồ sơ rỗng.")
  if (ids.length > toiDa) return loi400(`Danh sách có ${ids.length} hồ sơ, vượt giới hạn kỹ thuật ${toiDa} hồ sơ cho một bộ văn bản.`)
  const gap = new Map<number, number>()
  for (let i = 0; i < ids.length; i++) {
    const p = ids[i]
    if (typeof p !== "number" || !Number.isInteger(p) || p < 1) return loi400(`Dòng ${i + 1}: id hồ sơ không hợp lệ.`)
    const truoc = gap.get(p)
    if (truoc !== undefined) return loi400(`Dòng ${i + 1} trùng hồ sơ với dòng ${truoc} — mỗi người một dòng.`)
    gap.set(p, i + 1)
  }
  return null
}
export function luatKiemTruoc(than: Record<string, unknown>, toiDa = TRAN_HO_SO_MAC_DINH): LoiMayChu | null {
  if (!Number.isInteger(than.academic_year)) return loi422(["academic_year"], "Input should be a valid integer", "int_type")
  if (!Array.isArray(than.profile_ids) || than.profile_ids.length === 0) return loi422(["profile_ids"], "List should have at least 1 item after validation, not 0", "too_short")
  return luatDanhSachId(than.profile_ids, toiDa)
}

// ── 9. tham_so_quyet_dinh (DecisionParams) ───────────────────────────────────────────────────────────────────────────────
/** `DecisionParams` (`extra=forbid`): số 1–6 chữ số; `dot_so` CHUỖI 1–2 chữ số; `dot_thang` SỐ 1–12; đợt PHẢI ĐỦ CẢ HAI hoặc không; ngày Biên bản không sau ngày Quyết định. */
export function luatThamSoQuyetDinh(ts: unknown): LoiMayChu | null {
  if (ts === null || ts === undefined) return null
  if (typeof ts !== "object" || Array.isArray(ts)) return loi422(["tham_so_quyet_dinh"], "Input should be a valid dictionary or object", "model_attributes_type")
  const t = ts as Record<string, unknown>
  const L = (k: string) => ["tham_so_quyet_dinh", k]
  const khoa = new Set(["so_quyet_dinh", "ngay_quyet_dinh", "dot_so", "dot_thang", "so_bien_ban", "ngay_bien_ban"])
  const la = Object.keys(t).find((k) => !khoa.has(k))
  if (la) return loi422(L(la), "Extra inputs are not permitted", "extra_forbidden")
  const chuoi = (k: string, re: RegExp) => t[k] !== undefined && t[k] !== null && (typeof t[k] !== "string" || !re.test(t[k] as string))
  if (chuoi("so_quyet_dinh", RE_SO_1_6)) return loi422(L("so_quyet_dinh"), "String should match pattern '^[0-9]{1,6}$'", "string_pattern_mismatch")
  if (chuoi("so_bien_ban", RE_SO_1_6)) return loi422(L("so_bien_ban"), "String should match pattern '^[0-9]{1,6}$'", "string_pattern_mismatch")
  if (chuoi("dot_so", RE_SO_1_2)) return loi422(L("dot_so"), "String should match pattern '^[0-9]{1,2}$'", "string_pattern_mismatch")
  for (const k of ["ngay_quyet_dinh", "ngay_bien_ban"]) {
    if (t[k] !== undefined && t[k] !== null && !laNgay(t[k])) return loi422(L(k), "Input should be a valid date or datetime", "date_from_datetime_parsing")
  }
  if (t.dot_thang !== undefined && t.dot_thang !== null && (typeof t.dot_thang !== "number" || !Number.isInteger(t.dot_thang) || t.dot_thang < 1 || t.dot_thang > 12)) {
    return loi422(L("dot_thang"), "Input should be less than or equal to 12", "less_than_equal")
  }
  const coSo = t.dot_so !== undefined && t.dot_so !== null
  const coThang = t.dot_thang !== undefined && t.dot_thang !== null
  if (coSo !== coThang) return loi422(["tham_so_quyet_dinh"], "Value error, đợt xét tuyển cần đủ cả số đợt và tháng")
  const bb = t.ngay_bien_ban
  const qd = t.ngay_quyet_dinh
  if (typeof bb === "string" && typeof qd === "string" && bb > qd) return loi422(["tham_so_quyet_dinh"], "Value error, ngày Biên bản sau ngày Quyết định căn cứ vào nó")
  return null
}

// ── 2, 3. POST /sets (dạng mã / dạng id) ─────────────────────────────────────────────────────────────────────────────────
/** Ảnh chụp kiểm trước của MÁY CHỦ GIẢ: thứ tự chuẩn + dấu tính lại từ dữ liệu HIỆN TẠI (đổi dữ liệu ⇒ dấu đổi). */
export interface AnhKiemTruoc {
  thuTuChuan: readonly number[]
  dau: string
}
export function luatTaoBo(than: Record<string, unknown>, o: { anh: AnhKiemTruoc | null; idTheoMa: ReadonlyMap<string, number>; toiDa?: number }): LoiMayChu | null {
  const khoa = new Set(["ma_ho_so", "profile_ids", "phien_ban_kiem", "academic_year", "tham_so_quyet_dinh", "xac_nhan_trang_thai"])
  const la = Object.keys(than).find((k) => !khoa.has(k))
  if (la) return loi422([la], "Extra inputs are not permitted", "extra_forbidden")
  if (!Number.isInteger(than.academic_year)) return loi422(["academic_year"], "Input should be a valid integer", "int_type")
  const theoMa = than.ma_ho_so !== undefined && than.ma_ho_so !== null
  const theoId = (than.profile_ids !== undefined && than.profile_ids !== null) || (than.phien_ban_kiem !== undefined && than.phien_ban_kiem !== null)
  if (theoMa === theoId) return loi422([], "Value error, Gửi đúng MỘT dạng: ma_ho_so, hoặc profile_ids kèm phien_ban_kiem.")
  if (theoId && (!Array.isArray(than.profile_ids) || typeof than.phien_ban_kiem !== "string" || than.phien_ban_kiem === "")) {
    return loi422([], "Value error, Dạng id cần cả profile_ids và phien_ban_kiem.")
  }
  const ts = luatThamSoQuyetDinh(than.tham_so_quyet_dinh)
  if (ts) return ts
  if (theoMa) {
    const ma = than.ma_ho_so as unknown[]
    if (!Array.isArray(ma) || ma.length === 0) return loi400("Danh sách mã hồ sơ rỗng.")
    const gap = new Map<string, number>()
    for (let i = 0; i < ma.length; i++) {
      const { ma: s, ly_do } = loiMotMa(ma[i])
      if (ly_do === "khong_phai_chuoi") return loi400(`Dòng ${i + 1}: mã hồ sơ không phải chuỗi.`)
      if (ly_do === "rong") return loi400(`Dòng ${i + 1}: mã hồ sơ rỗng.`)
      if (ly_do === "ky_tu_la") return loi400(`Dòng ${i + 1}: không phải mã hồ sơ (quá dài hoặc có ký tự điều khiển).`)
      if (ly_do === "sai_dinh_dang") return loi400(`Dòng ${i + 1}: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số (CMND), chỉ chữ số 0-9.`)
      const truoc = gap.get(s as string)
      if (truoc !== undefined) return loi400(`Dòng ${i + 1} trùng mã hồ sơ với dòng ${truoc} — mỗi người một dòng.`)
      gap.set(s as string, i + 1)
      if (!o.idTheoMa.has(s as string)) return loi400(`Dòng ${i + 1}: mã hồ sơ không khớp đúng một hồ sơ của năm học đã chọn.`)
    }
    return null
  }
  const ds = luatDanhSachId(than.profile_ids, o.toiDa)
  if (ds) return ds
  // so_voi_kiem_truoc: thứ tự gửi KHÁC thứ tự chuẩn, HOẶC dấu tính lại khác dấu đã kiểm ⇒ 409 du_lieu_doi_tu_luc_kiem (không tự sắp lại)
  const ids = than.profile_ids as number[]
  const dungThuTu = o.anh !== null && ids.length === o.anh.thuTuChuan.length && ids.every((id, i) => id === o.anh!.thuTuChuan[i])
  const khopDau = o.anh !== null && than.phien_ban_kiem === o.anh.dau
  if (!(dungThuTu && khopDau)) return loi409(CAU_DOI_TU_LUC_KIEM, { ma_loi: MA_LOI_DOI_TU_LUC_KIEM })
  return null
}

// ── 8. POST /decisions ───────────────────────────────────────────────────────────────────────────────────────────────────
export interface BoGhiNhan {
  so_ho_so: number
  /** tham số ĐÃ IN trên bộ (JSON thô như cột `tham_so_quyet_dinh`) hoặc null */
  tham_so: Record<string, unknown> | null
  /** ngày dựng theo giờ Việt Nam, `YYYY-MM-DD` */
  ngay_dung: string
  /** bộ đã có văn bản còn sống (chưa huỷ ghi nhận) */
  van_ban_song_id?: number
  /**
   * Bộ TÁI DỰNG theo bản ký = cột `ban_ky_so_quyet_dinh` + `ban_ky_ngay` (cùng NULL hoặc cùng có — CHECK_BO_BAN_KY_DU). Vắng / `null` = bộ thường.
   * Bộ tái dựng: số / ngày trên giấy PHẢI bằng bản ký đã khai (`_so_tham_so` :210) và KHÔNG áp "ngày ký trước ngày dựng" (:425 chỉ khi
   * `ban_ky_so_quyet_dinh is None`).
   */
  ban_ky?: { so_quyet_dinh: string; ngay: string } | null
}
export interface NguCanhGhiNhan {
  bo: BoGhiNhan
  /** Quyết định gốc theo id (để kiểm "trúng tuyển đang hiệu lực") */
  goc: (id: number) => { loai: string; trang_thai: string } | undefined
  /** số đã dùng trong năm ký ⇒ id văn bản đang dùng */
  soDaDung: (so: string, nam: number) => number | undefined
}
const TRUONG_THAM_SO_GIAY = ["so_bien_ban", "ngay_bien_ban", "dot_so", "dot_thang"] as const

/**
 * `ghi_nhan_quyet_dinh` + khuôn `Form` của router. Thứ tự: khuôn trường (422) → số / ngày / scan / ghi chú / cặp loại↔gốc / xác nhận khớp
 * bản in (400) → gốc (404 / 409) → bộ đã có văn bản sống (409) → `xac_nhan_so_ho_so == bo.so_ho_so` (400) → tham số giấy lệch bản in (400)
 * → ngày ký trước ngày dựng (400; CHỈ bộ thường — bộ tái dựng theo bản ký thì bỏ qua) → số đã dùng trong NĂM CỦA NGÀY KÝ (409).
 * KHÔNG áp: mẫu theo ngày ký, dòng bộ / chỉ tiêu / khoá, đếm đổi trạng thái (`xac_nhan_trang_thai` chỉ kiểm là JSON), lượt gửi (hook có test riêng).
 */
export async function luatGhiNhan(form: FormData, cx: NguCanhGhiNhan): Promise<LoiMayChu | null> {
  const s = (k: string) => {
    const v = form.get(k)
    return typeof v === "string" ? v : null
  }
  // --- khuôn trường của router ---
  const setId = s("set_id")
  if (setId === null || !/^[0-9]+$/.test(setId) || Number(setId) < 1) return loi422(["set_id"], "Input should be greater than or equal to 1", "greater_than_equal")
  const loai = s("loai")
  if (loai === null || !/^(trung_tuyen|bo_sung)$/.test(loai)) return loi422(["loai"], "String should match pattern '^(trung_tuyen|bo_sung)$'", "string_pattern_mismatch")
  const gocRaw = s("goc_id")
  if (gocRaw !== null && (!/^[0-9]+$/.test(gocRaw) || Number(gocRaw) < 1)) return loi422(["goc_id"], "Input should be greater than or equal to 1", "greater_than_equal")
  const so = s("so_quyet_dinh")
  if (so === null || !RE_SO_1_6.test(so)) return loi422(["so_quyet_dinh"], "String should match pattern '^[0-9]{1,6}$'", "string_pattern_mismatch")
  const ngayKy = s("ngay_ky")
  if (ngayKy === null || !laNgay(ngayKy)) return loi422(["ngay_ky"], "Input should be a valid date or datetime", "date_from_datetime_parsing")
  const soBb = s("so_bien_ban")
  if (soBb !== null && !RE_SO_1_6.test(soBb)) return loi422(["so_bien_ban"], "String should match pattern '^[0-9]{1,6}$'", "string_pattern_mismatch")
  const ngayBb = s("ngay_bien_ban")
  if (ngayBb !== null && !laNgay(ngayBb)) return loi422(["ngay_bien_ban"], "Input should be a valid date or datetime", "date_from_datetime_parsing")
  const dotSo = s("dot_so")
  if (dotSo !== null && !RE_SO_1_2.test(dotSo)) return loi422(["dot_so"], "String should match pattern '^[0-9]{1,2}$'", "string_pattern_mismatch")
  const dotThangRaw = s("dot_thang")
  if (dotThangRaw !== null && (!/^[0-9]+$/.test(dotThangRaw) || Number(dotThangRaw) < 1 || Number(dotThangRaw) > 12)) {
    return loi422(["dot_thang"], "Input should be less than or equal to 12", "less_than_equal")
  }
  const xnRaw = s("xac_nhan_so_ho_so")
  if (xnRaw === null || !/^[0-9]+$/.test(xnRaw) || Number(xnRaw) < 1) return loi422(["xac_nhan_so_ho_so"], "Input should be greater than or equal to 1", "greater_than_equal")
  const khop = s("xac_nhan_khop_ban_in")
  if (khop === null || !/^(true|false)$/i.test(khop)) return loi422(["xac_nhan_khop_ban_in"], "Input should be a valid boolean", "bool_parsing")
  const ma = s("ma_luot_gui")
  if (ma === null || !RE_UUID.test(ma)) return loi422(["ma_luot_gui"], "String should match pattern '^[0-9a-fA-F-]{36}$'", "string_pattern_mismatch")
  const scan = form.get("scan")
  // --- service ---
  if (!laTep(scan) || scan.size === 0) return loi400("Phải kèm bản scan (PDF) của văn bản đã ký.")
  if ((await docDauTep(scan, 5)) !== "%PDF-") return loi400("Bản scan phải là tệp PDF.")
  const xnTt = s("xac_nhan_trang_thai")
  if (xnTt !== null) {
    try {
      const j: unknown = JSON.parse(xnTt)
      if (j === null || typeof j !== "object" || Array.isArray(j)) return loi400("xac_nhan_trang_thai phải là đối tượng {mã trạng thái: số}.")
    } catch {
      return loi400("xac_nhan_trang_thai không phải JSON hợp lệ.")
    }
  }
  const ghiChu = s("ghi_chu_mau")
  if (ghiChu !== null && ghiChu !== "") {
    const sai = luatLyDo(ghiChu, "ghi chú mẫu")
    if (sai) return sai
  }
  // cặp loại ↔ gốc: `(loai == "bo_sung") != (goc_id is not None)` ⇒ 400
  if ((loai === "bo_sung") !== (gocRaw !== null)) return loi400("Quyết định bổ sung phải chọn Quyết định gốc; Quyết định trúng tuyển thì không.")
  if (khop.toLowerCase() !== "true") {
    return loi400("Admin phải xác nhận danh sách, ngành, điểm từng em trên bản ký khớp bản in của bộ (C2: bản ký sửa tay ⇒ dựng lại bộ cho khớp bản ký).")
  }
  if (gocRaw !== null) {
    const g = cx.goc(Number(gocRaw))
    if (g === undefined) return loi404("Không có Quyết định gốc này.")
    if (g.loai !== "trung_tuyen" || g.trang_thai !== "hieu_luc") return loi409("Quyết định gốc phải là Quyết định trúng tuyển đang hiệu lực.")
  }
  if (cx.bo.van_ban_song_id !== undefined) {
    return loi409(`Bộ này đã được ghi nhận là văn bản đã ký #${cx.bo.van_ban_song_id}.`, { quyet_dinh_id: cx.bo.van_ban_song_id })
  }
  if (Number(xnRaw) !== cx.bo.so_ho_so) return loi400("Số hồ sơ gõ lại không khớp số hồ sơ của bộ.")
  // _so_tham_so: mọi tham số bộ ĐÃ in phải BẰNG giá trị trên giấy (lệch ⇒ CHẶN); trường bộ để trống nhận giá trị Admin gõ
  const ts = cx.bo.tham_so ?? {}
  const lech: string[] = []
  const banKy = cx.bo.ban_ky ?? null
  if (banKy !== null && (banKy.so_quyet_dinh !== so || banKy.ngay !== ngayKy)) lech.push("số / ngày của bản ký đã khai khi tái dựng")
  if (ts.so_quyet_dinh != null && ts.so_quyet_dinh !== so) lech.push("số Quyết định")
  if (ts.ngay_quyet_dinh != null && ts.ngay_quyet_dinh !== ngayKy) lech.push("ngày Quyết định")
  const giay: Record<string, unknown> = { so_bien_ban: soBb, ngay_bien_ban: ngayBb, dot_so: dotSo, dot_thang: dotThangRaw === null ? null : Number(dotThangRaw) }
  for (const t of TRUONG_THAM_SO_GIAY) {
    if (ts[t] != null && giay[t] !== ts[t]) lech.push(t)
  }
  if (lech.length > 0) {
    return loi400(`Giấy đã ký khác bản in của bộ ở: ${lech.join(", ")} — dựng lại bộ đúng tham số trên giấy.`, { truong_lech: lech })
  }
  // :425 — CHỈ bộ THƯỜNG (`ban_ky_so_quyet_dinh is None`); bộ tái dựng đã bị ràng số / ngày bằng bản ký ở trên.
  if (banKy === null && ngayKy < cx.bo.ngay_dung) {
    return loi400("Ngày ký trước ngày dựng bộ (giờ Việt Nam) — tờ giấy không thể là bản in của bộ này.")
  }
  const nam = Number(ngayKy.slice(0, 4))
  const dung = cx.soDaDung(so, nam)
  if (dung !== undefined) return loi409(`Số Quyết định ${so} đã dùng trong năm ${nam} (văn bản #${dung}).`, { quyet_dinh_id: dung })
  return null
}

// ── 10. POST /decisions/{id}/huy-ghi-nhan ────────────────────────────────────────────────────────────────────────────────
/** `huy_ghi_nhan`: lý do (kiem_ly_do) → `so_go_lai` phải BẰNG NGUYÊN CHUỖI số QUYẾT ĐỊNH của văn bản (không phải số hồ sơ) → văn bản chưa huỷ. */
export function luatHuyGhiNhan(than: unknown, qd: { so_quyet_dinh: string; trang_thai: string }): LoiMayChu | null {
  const t = (than ?? {}) as Record<string, unknown>
  if (typeof t.so_go_lai !== "string") return loi422(["so_go_lai"], "Input should be a valid string", "string_type")
  const ly = luatLyDo(t.ly_do, "huỷ ghi nhận")
  if (ly) return ly
  if (t.so_go_lai !== qd.so_quyet_dinh) return loi400("Số văn bản gõ lại không khớp.")
  if (qd.trang_thai === "huy_ghi_nhan") return loi409("Văn bản đã được huỷ ghi nhận.")
  return null
}

// ── 11. lượt gửi ─────────────────────────────────────────────────────────────────────────────────────────────────────────
/** Mở lượt: đã có lượt `cho_gui` ⇒ 409 `luot_dang_cho` + mã + giờ tạo. */
export function luatMoLuot(luotCho: { ma: string; tao_luc: string } | null): LoiMayChu | null {
  return luotCho === null
    ? null
    : loi409("Bộ đang có lượt gửi chưa rõ.", { ma_loi: "luot_dang_cho", ma: luotCho.ma, tao_luc: luotCho.tao_luc })
}
/** Phân xử: `ma` trên URL phải đúng dạng uuid (giao diện chặn chuỗi lạ bằng `MA_LUOT_RE`). */
export function luatPhanXuMa(ma: string): LoiMayChu | null {
  return RE_UUID.test(ma) ? null : loi422(["ma"], "String should match pattern '^[0-9a-fA-F-]{36}$'", "string_pattern_mismatch")
}
