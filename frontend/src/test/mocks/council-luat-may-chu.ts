/**
 * LUẬT MÁY CHỦ THẬT của các lệnh ghi giao diện Văn bản Hội đồng — chép lại cho MSW (Codex lần 20, câu 2: "OpenAPI kiểm hình
 * dạng không bắt được nhầm nghĩa này; MSW phải từ chối theo luật thật").
 *
 * Nguồn: bảng `HOP-DONG-THAN-YEU-CAU-LENH-GHI-GD1-2026-11-13.md` (phiên A) + mã máy chủ LXT1 `19424587`:
 *   council_decision_service.py (ghi_nhan_quyet_dinh :339, huy_ghi_nhan :807, _so_tham_so :203, _so_chua_dung :318, _bo_qd_hop_le :286),
 *   council_document_set_service.py (so_voi_kiem_truoc, kiem_danh_sach_id, kiem_ly_do), council_document_template_service.py (tai_mau_len),
 *   council_document_render_service.py (DecisionParams), council_candidate_service.py (loi_mot_ma), router council_documents.py (Form).
 * CÂU LỖI (Codex lần 22, mục 4): mỗi câu tiếng Việt trong `loi400/404/409(…)` phải có NGUYÊN VĂN ở mã máy chủ (đối chiếu LXT1 `452298b6`; các chỗ đã sửa: xoa_bo_van_ban :960 / :972,
 * kiem_goi_mau :73 / :81, tim_ho_so :470 / :474, kiem_xac_nhan_trang_thai :120 / :124 qua `_json_xac_nhan` :604, mo_luot :137). Viết câu CÙNG dòng với `loiNNN(` — công cụ so câu
 * (`so_cau_loi_msw.py`) chỉ đọc phần còn lại của dòng ấy, câu nằm sang dòng sau sẽ không được so.
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
/** `error_code` của lỗi TỆP (`FileValidationError`, `app/utils/exceptions.py:341`): CÙNG mã HTTP 400 với `DataValidationError` nhưng KHÁC `error_code`. */
export const MA_LOI_TEP = "FILE_VALIDATION_ERROR"
/** 400 miền. Viết câu lỗi ở CÙNG dòng với tên hàm (công cụ so câu `so_cau_loi_msw.py` chỉ đọc phần còn lại của dòng ấy) và KHÔNG viết tên hàm kèm dấu mở ngoặc trong chú thích. */
export const loi400 = (detail: string, them?: Record<string, unknown>, maLoi = "DATA_VALIDATION_ERROR") => mien(400, detail, maLoi, them)
export const loi404 = (detail: string) => mien(404, detail, "RESOURCE_NOT_FOUND")
export const loi409 = (detail: string, them?: Record<string, unknown>) => mien(409, detail, "CONFLICT", them)
export const loiTrung = (detail: string) => mien(409, detail, "DUPLICATE_RESOURCE")
/** 422 của pydantic: MỘT mục lỗi mỗi chỗ sai (`loc` có thể mang CHỈ SỐ phần tử — số, không phải chuỗi). */
export interface Muc422 {
  type: string
  loc: ReadonlyArray<string | number>
  msg: string
}
export const loi422Nhieu = (errors: Muc422[]): LoiMayChu => ({
  status: 422,
  body: {
    detail: "Request validation failed",
    error_code: "VALIDATION_ERROR",
    errors: errors.map((e) => ({ type: e.type, loc: ["body", ...e.loc], msg: e.msg })),
  },
})
export const loi422 = (loc: ReadonlyArray<string | number>, msg: string, type = "value_error"): LoiMayChu => loi422Nhieu([{ type, loc, msg }])

// ── hằng và hàm nhỏ chung ────────────────────────────────────────────────────────────────────────────────────────────────
export const LY_DO_TOI_DA = 1000 // LY_DO_XOA_TOI_DA (models/council_document.py:81)
export const CAU_DOI_TU_LUC_KIEM = "Dữ liệu đã đổi từ lúc kiểm — bấm Kiểm tra lại."
export const MA_LOI_DOI_TU_LUC_KIEM = "du_lieu_doi_tu_luc_kiem"
/** Mã trạng thái hồ sơ hợp lệ (CHECK 15 trạng thái ở `app/models/admission.py`). */
export const TRANG_THAI_HO_SO = [
  "draft", "submitted", "resubmitted", "approved", "overridden", "confirmed", "enrolled", "reviewing", "result_published",
  "admitted", "waitlisted", "rejected", "revision_requested", "withdrawal_pending", "withdrawn",
] as const
/** Trần KỸ THUẬT của bản scan PDF = mặc định của `COUNCIL_DECISION_SCAN_MAX_BYTES` (app/config.py:465 — `default=20 * 1024 * 1024`). */
export const TRAN_BYTE_SCAN_MAC_DINH = 20 * 1024 * 1024
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

/**
 * Trường `StrictStr` BẮT BUỘC của thân JSON — pydantic chạy TRƯỚC service: vắng ⇒ 422 `missing` "Field required"; không phải chuỗi (null, số, bool, mảng, đối tượng …) ⇒ 422 `string_type`
 * "Input should be a valid string". Dùng cho `CouncilSetDelete.ly_do` (schemas/council_document.py:279) và `CouncilDecisionCancelIn.ly_do` / `.so_go_lai` (:474 – :475).
 * (Trường Tuỳ CHỌN `Optional[StrictStr]` — `tu_khoa`, `phien_ban_kiem` — coi `null` / vắng là hợp lệ: xem `luatTimHoSo`, `luatLopSchemaPhienBan`.)
 */
export function luatStrictStrBatBuoc(than: unknown, truong: string): LoiMayChu | null {
  const v = than !== null && typeof than === "object" ? (than as Record<string, unknown>)[truong] : undefined
  if (v === undefined) return loi422([truong], "Field required", "missing")
  if (typeof v !== "string") return loi422([truong], "Input should be a valid string", "string_type")
  return null
}

// ── 7. DELETE /sets/{id} ─────────────────────────────────────────────────────────────────────────────────────────────────
/**
 * Điều CSDL nói về bộ lúc xoá (`xoa_bo_van_ban`, council_document_set_service.py:936): văn bản SỐNG của bộ (`van_ban_song_cua_bo`: mọi văn bản trỏ bộ có
 * trạng thái ≠ `huy_ghi_nhan`, xếp theo id) và lượt gửi `cho_gui` của bộ (`co_luot_cho_gui`).
 */
export interface NguCanhXoaBo {
  /** id các văn bản SỐNG của bộ, đúng thứ tự máy chủ (theo id); rỗng / vắng ⇒ không có (Python `if song:`) */
  vanBanSongIds?: readonly number[]
  /** mã lượt gửi `cho_gui` của bộ; `null` / vắng ⇒ không có */
  luotChoMa?: string | null
}

/**
 * `xoa_bo_van_ban`, theo thứ tự của máy chủ: `ly_do` thiếu / không phải chuỗi ⇒ 422 (StrictStr) → `kiem_ly_do_xoa` (400) → văn bản ĐÃ KÝ còn sống ⇒ 409 (:960, kèm
 * `quyet_dinh_id` = DANH SÁCH id) → lượt gửi chưa rõ ⇒ 409 `bo_co_luot_gui_chua_ro` kèm `ma` (:972) — văn bản đã ký kiểm TRƯỚC, lượt chưa rõ SAU.
 * KHÔNG áp: 404 khi bộ biến mất giữa chừng (`khoa_bo`, :954) — router đã trả 404 từ lúc nạp bộ.
 */
export function luatXoaBo(thanBody: unknown, bo: NguCanhXoaBo): LoiMayChu | null {
  const lopLy = luatStrictStrBatBuoc(thanBody, "ly_do")
  if (lopLy) return lopLy
  const sai = luatLyDo((thanBody as { ly_do: string }).ly_do, "xoá bộ văn bản")
  if (sai) return sai
  const song = bo.vanBanSongIds ?? []
  if (song.length > 0) return loi409(`Bộ văn bản là bản in của Quyết định đã ký (văn bản #${song.join(", #")}) — lưu theo hạn lưu trữ, không xoá. Chỉ xoá được khi mọi ghi nhận của bộ đã huỷ ghi nhận.`, { quyet_dinh_id: [...song] })
  if (bo.luotChoMa != null) return loi409("Bộ đang có lượt gửi ghi nhận chưa rõ kết quả — phân xử (Kiểm tra trên máy chủ) trước khi xoá.", { ma_loi: "bo_co_luot_gui_chua_ro", ma: bo.luotChoMa })
  return null
}

// ── 1. POST /templates ───────────────────────────────────────────────────────────────────────────────────────────────────
/** `TEN_LOAI` của council_document_template_service.py:41 — tên đi vào câu lỗi (`%s`); loại `danh_sach` là "Danh sách xét tuyển", KHÔNG phải "Danh sách". */
const TEN_LOAI_MAU: Record<string, string> = { bien_ban: "Biên bản", quyet_dinh: "Quyết định", danh_sach: "Danh sách xét tuyển" }
/**
 * `tai_mau_len` (council_document_template_service.py:141), theo thứ tự: loại ∈ 3 loại (400) → ghi chú ≤ 500 ký tự (400) → `kiem_goi_mau`: tệp rỗng ⇒ 400
 * `FILE_VALIDATION_ERROR` "Mẫu <tên loại>: tệp rỗng hoặc không phải bytes." (:73); tệp không mở được như gói zip ⇒ 400 `FILE_VALIDATION_ERROR` "Mẫu <tên loại> không đọc
 * được như tệp Word (.docx)." (:81) — `FileValidationError` mang HTTP 400 nhưng `error_code` RIÊNG → cùng (loại, ngày hiệu lực) đã có ⇒ 409 (không ghi đè;
 * hai mẫu cùng loại KHÁC ngày ⇒ được). `hieu_luc_tu` là NGÀY (áp cho văn bản KÝ từ ngày này — KHÔNG phải ngày tải).
 * KHÔNG áp: trần kích thước tệp (`FileSizeError`, :74, mặc định 5 MiB), giới hạn gói zip (:86 – :99), `bo_dung.kiem_mau` (nội dung .docx) — chỉ kiểm có tệp và chữ ký ZIP `PK`
 * (tệp bắt đầu bằng `PK` nhưng không phải zip thật MSW vẫn nhận; máy chủ từ chối ở `zipfile.ZipFile`).
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
  // `loai not in TEN_LOAI` của máy chủ là phép thử KHOÁ của dict — KHÔNG dùng `in` của JS (nó thấy cả "constructor", "toString" … của prototype)
  if (!Object.prototype.hasOwnProperty.call(TEN_LOAI_MAU, loai)) return loi400("Loại mẫu không thuộc bien_ban / quyet_dinh / danh_sach.")
  if (typeof ghiChu === "string" && [...ghiChu].length > 500) return loi400("Ghi chú của mẫu dài quá 500 ký tự.")
  const ten = TEN_LOAI_MAU[loai]
  if (tep.size === 0) return loi400(`Mẫu ${ten}: tệp rỗng hoặc không phải bytes.`, undefined, MA_LOI_TEP)
  if ((await docDauTep(tep, 2)) !== "PK") return loi400(`Mẫu ${ten} không đọc được như tệp Word (.docx).`, undefined, MA_LOI_TEP)
  if (mauDaCo.some((m) => m.loai === loai && m.hieu_luc_tu === hieu)) {
    return loiTrung(`Đã có mẫu ${ten} hiệu lực từ ngày ${hieu}.`)
  }
  return null
}

// ── mã hồ sơ (dùng chung `POST /sets` dạng mã và `POST /sets/doi-ma`) ─────────────────────────────────────────────────
export type LyDoMa = "khong_phai_chuoi" | "rong" | "ky_tu_la" | "sai_dinh_dang"
/**
 * `loi_mot_ma` (candidate_service:273, theo thứ tự): không phải chuỗi ⇒ khong_phai_chuoi; rỗng (sau cắt) ⇒ rong; dài > 32 hoặc ký tự nhóm C ⇒
 * ky_tu_la; không đúng 12 hoặc 9 chữ số ASCII ⇒ sai_dinh_dang.
 * ⚠️ Đây là luật TẦNG SERVICE. Ở ranh giới HTTP schema (`List[str]` / `List[StrictStr]`) chặn phần tử không phải chuỗi bằng 422 TRƯỚC khi tới
 * đây — lớp ấy là :func:`luatLopSchemaMa` (`luatTaoBo` và `luatDoiMaTruoc` gọi nó trước).
 */
export function loiMotMa(m: unknown): { ma: string | null; ly_do: LyDoMa | null } {
  if (typeof m !== "string") return { ma: null, ly_do: "khong_phai_chuoi" }
  const s = m.trim()
  if (s === "") return { ma: s, ly_do: "rong" }
  if ([...s].length > 32 || [...s].some((c) => /\p{C}/u.test(c))) return { ma: s, ly_do: "ky_tu_la" }
  if (!RE_MA_HO_SO.test(s)) return { ma: s, ly_do: "sai_dinh_dang" }
  return { ma: s, ly_do: null }
}

/**
 * LỚP SCHEMA của `ma_ho_so` — pydantic chạy TRƯỚC service: `CouncilSetCreate.ma_ho_so: Optional[List[str]] = Field(None, min_length=1)`
 * (schemas/council_document.py:53) và `CouncilCodesIn.ma_ho_so: List[StrictStr] = Field(..., min_length=1)` (:175) cho CÙNG luật quan sát được:
 * không phải danh sách ⇒ 422 `list_type`; danh sách rỗng ⇒ 422 `too_short`; MỖI phần tử không phải chuỗi (số / null / đối tượng …) ⇒ MỘT lỗi
 * 422 `string_type` mang CHỈ SỐ phần tử (pydantic báo hết, không dừng ở phần tử đầu). Vì vậy `khong_phai_chuoi` và "danh sách rỗng" của
 * service KHÔNG BAO GIỜ tới được qua HTTP. Chỉ gọi khi `ma_ho_so` có mặt và khác null (trường tuỳ chọn của `POST /sets`).
 */
export function luatLopSchemaMa(ma: unknown): LoiMayChu | null {
  if (!Array.isArray(ma)) return loi422(["ma_ho_so"], "Input should be a valid list", "list_type")
  if (ma.length === 0) return loi422(["ma_ho_so"], "List should have at least 1 item after validation, not 0", "too_short")
  const sai: Muc422[] = []
  ma.forEach((p, i) => {
    if (typeof p !== "string") sai.push({ type: "string_type", loc: ["ma_ho_so", i], msg: "Input should be a valid string" })
  })
  return sai.length > 0 ? loi422Nhieu(sai) : null
}

/** `_neu_dong` (council_candidate_service.py:253): tối đa 20 số dòng, quá thì thêm " … (tổng N dòng)". */
const NEU_DONG_TOI_DA = 20
export function neuDong(dong: readonly number[]): string {
  const s = dong.slice(0, NEU_DONG_TOI_DA).join(", ")
  return s + (dong.length > NEU_DONG_TOI_DA ? ` … (tổng ${dong.length} dòng)` : "")
}

// ── 5. POST /sets/doi-ma ─────────────────────────────────────────────────────────────────────────────────────────────────
export interface DoiMaOut {
  profile_ids: number[]
  dong_loi: Array<{ dong: number; ly_do: string }>
}
/**
 * Phần máy chủ chạy TRƯỚC khi đổi mã (`CouncilCodesIn` + `doi_ma_thanh_id`): thân là đối tượng, khoá lạ cấm (`extra="forbid"`), `academic_year`
 * (StrictInt) và `ma_ho_so` BẮT BUỘC, lớp schema của `ma_ho_so` (:func:`luatLopSchemaMa`) ⇒ 422; rồi trần số dòng ⇒ 400 "Danh sách có N dòng,
 * vượt giới hạn kỹ thuật M hồ sơ cho một bộ văn bản." (đếm TRƯỚC khi kiểm từng mã). `null` ⇒ qua, gọi tiếp :func:`luatDoiMa`.
 */
export function luatDoiMaTruoc(than: unknown, toiDa = TRAN_HO_SO_MAC_DINH): LoiMayChu | null {
  if (than === null || typeof than !== "object" || Array.isArray(than)) {
    return loi422([], "Input should be a valid dictionary or object to extract fields from", "model_attributes_type")
  }
  const t = than as Record<string, unknown>
  const la = Object.keys(t).find((k) => k !== "academic_year" && k !== "ma_ho_so")
  if (la) return loi422([la], "Extra inputs are not permitted", "extra_forbidden")
  if (t.academic_year === undefined) return loi422(["academic_year"], "Field required", "missing")
  if (!Number.isInteger(t.academic_year)) return loi422(["academic_year"], "Input should be a valid integer", "int_type")
  if (t.ma_ho_so === undefined) return loi422(["ma_ho_so"], "Field required", "missing")
  const lop = luatLopSchemaMa(t.ma_ho_so)
  if (lop) return lop
  const n = (t.ma_ho_so as unknown[]).length
  if (n > toiDa) return loi400(`Danh sách có ${n} dòng, vượt giới hạn kỹ thuật ${toiDa} hồ sơ cho một bộ văn bản.`)
  return null
}
/**
 * Trả id theo thứ tự dòng + lỗi theo SỐ DÒNG (không nêu giá trị). Mã đúng nhưng NGOÀI phạm vi / sai năm ⇒ `khong_khop`; dòng trùng ⇒ dòng sau mang `trung`.
 * ⚠️ Đây là luật TẦNG SERVICE (`doi_ma_thanh_id`): qua HTTP, phần tử không phải chuỗi đã bị 422 ở :func:`luatDoiMaTruoc` — handler gọi hàm kia TRƯỚC.
 */
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
/** Trần từ khoá tìm (sau cắt khoảng trắng) = `TU_KHOA_TOI_DA` của council_candidate_service.py:435; vào cả phép kiểm lẫn câu lỗi (`%d`). */
export const TU_KHOA_TOI_DA = 100
/**
 * Schema (`extra=forbid`, page ≥ 1, page_size 1…100, `tu_khoa` / `trang_thai` đúng KIỂU chuỗi — 422) + service: từ khoá cắt khoảng trắng ≤ 100 ký tự (400 "Từ khoá tìm quá dài …");
 * trạng thái ∈ CHECK (400 "Bộ lọc trạng thái …"). KHÔNG áp: `trang_thai` tối đa 20 phần tử, `major_ids` (`StrictInt`, tối đa 200).
 */
export function luatTimHoSo(than: Record<string, unknown>): LoiMayChu | null {
  const khoa = new Set(["academic_year", "tu_khoa", "major_ids", "trang_thai", "page", "page_size"])
  const la = Object.keys(than).find((k) => !khoa.has(k))
  if (la) return loi422([la], "Extra inputs are not permitted", "extra_forbidden")
  if (!Number.isInteger(than.academic_year)) return loi422(["academic_year"], "Input should be a valid integer", "int_type")
  if (than.page !== undefined && (!Number.isInteger(than.page) || (than.page as number) < 1)) return loi422(["page"], "Input should be greater than or equal to 1", "greater_than_equal")
  if (than.page_size !== undefined && (!Number.isInteger(than.page_size) || (than.page_size as number) < 1 || (than.page_size as number) > 100)) {
    return loi422(["page_size"], "Input should be less than or equal to 100", "less_than_equal")
  }
  // `tu_khoa: Optional[StrictStr]` và `trang_thai: Optional[List[StrictStr]]` (schemas/council_document.py:142 / :144): null / vắng hợp lệ; kiểu sai ⇒ 422 TRƯỚC service
  if (than.tu_khoa !== undefined && than.tu_khoa !== null && typeof than.tu_khoa !== "string") return loi422(["tu_khoa"], "Input should be a valid string", "string_type")
  if (than.trang_thai !== undefined && than.trang_thai !== null) {
    if (!Array.isArray(than.trang_thai)) return loi422(["trang_thai"], "Input should be a valid list", "list_type")
    const sai: Muc422[] = []
    than.trang_thai.forEach((p, i) => {
      if (typeof p !== "string") sai.push({ type: "string_type", loc: ["trang_thai", i], msg: "Input should be a valid string" })
    })
    if (sai.length > 0) return loi422Nhieu(sai)
  }
  if (typeof than.tu_khoa === "string" && than.tu_khoa.length > 200) return loi422(["tu_khoa"], "String should have at most 200 characters", "string_too_long")
  if (typeof than.tu_khoa === "string" && [...than.tu_khoa.trim()].length > TU_KHOA_TOI_DA) return loi400(`Từ khoá tìm quá dài (tối đa ${TU_KHOA_TOI_DA} ký tự).`)
  if (Array.isArray(than.trang_thai) && than.trang_thai.some((t) => !(TRANG_THAI_HO_SO as readonly unknown[]).includes(t))) {
    return loi400("Bộ lọc trạng thái có giá trị không hợp lệ.")
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
/**
 * LỚP SCHEMA của `phien_ban_kiem` (`CouncilSetCreate`, schemas/council_document.py:55 — `Optional[StrictStr]`, 1…128 KÝ TỰ): không phải chuỗi ⇒ 422 `string_type`; rỗng ⇒ 422 `string_too_short`;
 * dài hơn 128 ký tự (đếm điểm mã, không đếm đơn vị UTF-16) ⇒ 422 `string_too_long`. Chỉ gọi khi có mặt và khác null (`null` ≡ vắng ⇒ rơi xuống validator mô hình "Dạng id cần cả …").
 */
export function luatLopSchemaPhienBan(v: unknown): LoiMayChu | null {
  if (typeof v !== "string") return loi422(["phien_ban_kiem"], "Input should be a valid string", "string_type")
  const n = [...v].length
  if (n < 1) return loi422(["phien_ban_kiem"], "String should have at least 1 character", "string_too_short")
  if (n > 128) return loi422(["phien_ban_kiem"], "String should have at most 128 characters", "string_too_long")
  return null
}

/**
 * `POST /sets`. Thứ tự = máy chủ: SCHEMA (khoá lạ · `academic_year` · lớp schema của `ma_ho_so` · lớp schema của `phien_ban_kiem` — pydantic báo lỗi TRƯỜNG trước validator mô hình
 * "đúng MỘT dạng") → dạng mã: `chuan_hoa_ma` (từng dòng: không phải chuỗi / rỗng / ký tự lạ / sai dạng / TRÙNG — DỪNG ở dòng sai ĐẦU TIÊN)
 * → TRẦN (`doc_ho_so_theo_ma`: đếm danh sách đã chuẩn hoá) → KHỚP CSDL (câu GỘP nêu mọi dòng không khớp / khớp nhiều, `_neu_dong` ≤ 20 dòng).
 * `o.maNhieuHoSo`: mã khớp NHIỀU hồ sơ (`phan_giai_ma` trả so > 1); mặc định không có.
 */
export function luatTaoBo(
  than: Record<string, unknown>,
  o: { anh: AnhKiemTruoc | null; idTheoMa: ReadonlyMap<string, number>; toiDa?: number; maNhieuHoSo?: ReadonlySet<string> },
): LoiMayChu | null {
  const khoa = new Set(["ma_ho_so", "profile_ids", "phien_ban_kiem", "academic_year", "tham_so_quyet_dinh", "xac_nhan_trang_thai"])
  const la = Object.keys(than).find((k) => !khoa.has(k))
  if (la) return loi422([la], "Extra inputs are not permitted", "extra_forbidden")
  if (!Number.isInteger(than.academic_year)) return loi422(["academic_year"], "Input should be a valid integer", "int_type")
  if (than.ma_ho_so !== undefined && than.ma_ho_so !== null) {
    const lop = luatLopSchemaMa(than.ma_ho_so)
    if (lop) return lop
  }
  // `phien_ban_kiem: Optional[StrictStr] = Field(None, min_length=1, max_length=128)` — lỗi TRƯỜNG (kiểu / độ dài) báo TRƯỚC validator mô hình "đúng MỘT dạng"
  if (than.phien_ban_kiem !== undefined && than.phien_ban_kiem !== null) {
    const pb = luatLopSchemaPhienBan(than.phien_ban_kiem)
    if (pb) return pb
  }
  const theoMa = than.ma_ho_so !== undefined && than.ma_ho_so !== null
  const theoId = (than.profile_ids !== undefined && than.profile_ids !== null) || (than.phien_ban_kiem !== undefined && than.phien_ban_kiem !== null)
  if (theoMa === theoId) return loi422([], "Value error, Gửi đúng MỘT dạng: ma_ho_so, hoặc profile_ids kèm phien_ban_kiem.")
  if (theoId && (!Array.isArray(than.profile_ids) || typeof than.phien_ban_kiem !== "string" || than.phien_ban_kiem === "")) {
    return loi422([], "Value error, Dạng id cần cả profile_ids và phien_ban_kiem.")
  }
  const ts = luatThamSoQuyetDinh(than.tham_so_quyet_dinh)
  if (ts) return ts
  if (theoMa) {
    // lớp schema ở trên đã bảo đảm `ma_ho_so` là danh sách ≥ 1 CHUỖI ⇒ nhánh "không phải danh sách / rỗng" của service không tới được qua HTTP
    const ma = than.ma_ho_so as string[]
    // pha 1 — `chuan_hoa_ma`: cú pháp + trùng, từng dòng, DỪNG ở dòng sai đầu tiên (chưa đụng CSDL)
    const gap = new Map<string, number>()
    const chuan: string[] = []
    for (let i = 0; i < ma.length; i++) {
      const { ma: s, ly_do } = loiMotMa(ma[i]) // phần tử luôn là chuỗi (lớp schema) ⇒ `khong_phai_chuoi` không xảy ra ở đây
      if (ly_do === "rong") return loi400(`Dòng ${i + 1}: mã hồ sơ rỗng.`)
      if (ly_do === "ky_tu_la") return loi400(`Dòng ${i + 1}: không phải mã hồ sơ (quá dài hoặc có ký tự điều khiển).`)
      if (ly_do === "sai_dinh_dang") return loi400(`Dòng ${i + 1}: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số (CMND), chỉ chữ số 0-9.`)
      const truoc = gap.get(s as string)
      if (truoc !== undefined) return loi400(`Dòng ${i + 1} trùng mã hồ sơ với dòng ${truoc} — mỗi người một dòng.`)
      gap.set(s as string, i + 1)
      chuan.push(s as string)
    }
    // pha 2 — trần (đếm danh sách đã chuẩn hoá; câu nói "mã", khác câu "hồ sơ" của dạng id và câu "dòng" của doi-ma)
    const toiDa = o.toiDa ?? TRAN_HO_SO_MAC_DINH
    if (chuan.length > toiDa) return loi400(`Danh sách có ${chuan.length} mã, vượt giới hạn kỹ thuật ${toiDa} hồ sơ cho một bộ văn bản.`)
    // pha 3 — khớp CSDL: MỘT câu GỘP cho mọi dòng không khớp (so == 0) / khớp nhiều (so > 1)
    const khong: number[] = []
    const nhieu: number[] = []
    chuan.forEach((s, i) => {
      if (o.maNhieuHoSo?.has(s)) nhieu.push(i + 1)
      else if (!o.idTheoMa.has(s)) khong.push(i + 1)
    })
    if (khong.length > 0 || nhieu.length > 0) {
      const phan: string[] = []
      if (khong.length > 0) phan.push(`dòng ${neuDong(khong)} không có hồ sơ nào mang mã này trong năm học đã chọn`)
      if (nhieu.length > 0) phan.push(`dòng ${neuDong(nhieu)} khớp NHIỀU hồ sơ cùng mã`)
      return loi400(`Mã hồ sơ phải khớp đúng một hồ sơ: ${phan.join("; ")}.`)
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
  /** trần byte của bản scan; mặc định = cấu hình mặc định của máy chủ (`TRAN_BYTE_SCAN_MAC_DINH`, 20 MiB). Cho test hạ thấp để khỏi tạo tệp 20 MiB. */
  scanToiDa?: number
}
const TRUONG_THAM_SO_GIAY = ["so_bien_ban", "ngay_bien_ban", "dot_so", "dot_thang"] as const

/**
 * `kiem_xac_nhan_trang_thai` (council_decision_service.py:115) — nhận cái `_json_xac_nhan` của router đã đọc ra: `null` (không gửi, "" hoặc JSON `null`) ⇒ nhận;
 * còn lại PHẢI là đối tượng KHÔNG rỗng ({} ⇒ từ chối, mảng / chuỗi / số cũng vậy — kể cả chuỗi "<khong-doc-duoc>" mà router đưa vào khi JSON hỏng) ⇒ 400 "Xác nhận phải là danh
 * sách {loại: số hồ sơ} không rỗng."; MỖI giá trị phải là SỐ NGUYÊN ≥ 1 (bool, chuỗi, null, 0, âm, số lẻ đều sai) ⇒ 400 "Số hồ sơ trong xác nhận phải là số nguyên ≥ 1.".
 * Giới hạn đã biết: JS không phân biệt `1.0` với `1` sau `JSON.parse` (Python: `1.0` là float ⇒ bị từ chối); `NaN` / `Infinity` Python đọc được còn JS thì không.
 */
export function luatXacNhanTrangThai(xn: unknown): LoiMayChu | null {
  if (xn === null || xn === undefined) return null
  if (typeof xn !== "object" || Array.isArray(xn) || Object.keys(xn).length === 0) return loi400("Xác nhận phải là danh sách {loại: số hồ sơ} không rỗng.")
  for (const v of Object.values(xn)) {
    if (typeof v !== "number" || !Number.isInteger(v) || v < 1) return loi400("Số hồ sơ trong xác nhận phải là số nguyên ≥ 1.")
  }
  return null
}

/**
 * `ghi_nhan_quyet_dinh` + khuôn `Form` của router. Thứ tự: khuôn trường (422) → số / ngày / scan (400) → xác nhận đổi trạng thái (400, :366) → ghi chú / cặp loại↔gốc /
 * xác nhận khớp bản in (400) → gốc (404 / 409) → bộ đã có văn bản sống (409) → `xac_nhan_so_ho_so == bo.so_ho_so` (400) → tham số giấy lệch bản in (400)
 * → ngày ký trước ngày dựng (400; CHỈ bộ thường — bộ tái dựng theo bản ký thì bỏ qua) → số đã dùng trong NĂM CỦA NGÀY KÝ (409).
 * KHÔNG áp: mẫu theo ngày ký, dòng bộ / chỉ tiêu / khoá, ĐẾM đổi trạng thái (`_kiem_xac_nhan_dem` — chỉ kiểm DẠNG của `xac_nhan_trang_thai`, không kiểm số đếm), lượt gửi (hook có test riêng).
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
  // `kiem_scan` (decision_service:101): rỗng → vượt trần kỹ thuật → chữ ký `%PDF-`. Router chỉ đọc tối đa TRẦN + 1 byte (`_doc_scan`) ⇒ đúng TRẦN byte vẫn nhận,
  // TRẦN + 1 trở lên bị chặn và câu luôn nêu TRẦN (không nêu kích thước thật). Tệp quá trần mà không phải PDF ⇒ câu trần (kiểm TRƯỚC chữ ký).
  if (!laTep(scan) || scan.size === 0) return loi400("Phải kèm bản scan (PDF) của văn bản đã ký.")
  const tranScan = cx.scanToiDa ?? TRAN_BYTE_SCAN_MAC_DINH
  if (scan.size > tranScan) return loi400(`Bản scan vượt giới hạn kỹ thuật ${tranScan} byte.`)
  if ((await docDauTep(scan, 5)) !== "%PDF-") return loi400("Bản scan phải là tệp PDF.")
  // `_json_xac_nhan` (router council_documents.py:604): vắng / "" ⇒ không có; JSON hỏng ⇒ MỘT CHUỖI (không phải 400 riêng) → `kiem_xac_nhan_trang_thai` (:366) — ĐỨNG SAU scan, TRƯỚC ghi chú mẫu.
  const xnTt = s("xac_nhan_trang_thai")
  if (xnTt !== null && xnTt !== "") {
    let j: unknown
    try {
      j = JSON.parse(xnTt)
    } catch {
      j = "<khong-doc-duoc>"
    }
    const saiXn = luatXacNhanTrangThai(j)
    if (saiXn) return saiXn
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
/**
 * LỚP SCHEMA của `xac_nhan` ở `CouncilDecisionCancelIn` (schemas/council_document.py:476 — `Optional[Dict[str, StrictInt]]`): vắng / null ⇒ nhận; không phải đối tượng ⇒ 422 `dict_type`;
 * MỖI giá trị không phải SỐ NGUYÊN (chuỗi / số lẻ / bool / null …) ⇒ 422 `int_type` mang KHOÁ của mục sai (`StrictInt`: bool KHÔNG phải số nguyên). `{}` và số < 1 KHÔNG bị chặn ở đây —
 * schema cho qua, tầng service (`kiem_xac_nhan_trang_thai`) mới chặn (400). Cùng giới hạn đã biết với :func:`luatXacNhanTrangThai` (`1.0` ≡ `1` sau `JSON.parse`).
 */
export function luatLopSchemaXacNhan(xn: unknown): LoiMayChu | null {
  if (xn === undefined || xn === null) return null
  if (typeof xn !== "object" || Array.isArray(xn)) return loi422(["xac_nhan"], "Input should be a valid dictionary", "dict_type")
  const sai: Muc422[] = []
  for (const [k, v] of Object.entries(xn)) {
    if (typeof v !== "number" || !Number.isInteger(v)) sai.push({ type: "int_type", loc: ["xac_nhan", k], msg: "Input should be a valid integer" })
  }
  return sai.length > 0 ? loi422Nhieu(sai) : null
}

/**
 * `huy_ghi_nhan` (council_decision_service.py:807), theo thứ tự: schema (422, theo thứ tự trường: `ly_do` và `so_go_lai` là `StrictStr` BẮT BUỘC ⇒ :func:`luatStrictStrBatBuoc`; `xac_nhan` ⇒ :func:`luatLopSchemaXacNhan`) → lý do (kiem_ly_do, :819) →
 * `xac_nhan` qua `kiem_xac_nhan_trang_thai` (:820 — `{}` / số < 1 ⇒ 400, CÙNG hai câu với ghi nhận) → `so_go_lai` phải BẰNG NGUYÊN CHUỖI số QUYẾT ĐỊNH của văn bản
 * (không phải số hồ sơ, :828) → văn bản chưa huỷ (:830). KHÔNG áp: các 409 `van_ban_sau` / `dong_xung_dot` và đếm đổi trạng thái (`_kiem_xac_nhan_dem`).
 */
export function luatHuyGhiNhan(than: unknown, qd: { so_quyet_dinh: string; trang_thai: string }): LoiMayChu | null {
  const t = (than ?? {}) as Record<string, unknown>
  // schema `CouncilDecisionCancelIn` báo lỗi theo THỨ TỰ TRƯỜNG: ly_do → so_go_lai → xac_nhan (MSW trả lỗi đầu tiên theo thứ tự ấy)
  const lopLy = luatStrictStrBatBuoc(t, "ly_do")
  if (lopLy) return lopLy
  const lopSo = luatStrictStrBatBuoc(t, "so_go_lai")
  if (lopSo) return lopSo
  const lopXn = luatLopSchemaXacNhan(t.xac_nhan)
  if (lopXn) return lopXn
  const ly = luatLyDo(t.ly_do, "huỷ ghi nhận")
  if (ly) return ly
  const xn = luatXacNhanTrangThai(t.xac_nhan ?? null)
  if (xn) return xn
  if (t.so_go_lai !== qd.so_quyet_dinh) return loi400("Số văn bản gõ lại không khớp.")
  if (qd.trang_thai === "huy_ghi_nhan") return loi409("Văn bản đã được huỷ ghi nhận.")
  return null
}

// ── 11. lượt gửi ─────────────────────────────────────────────────────────────────────────────────────────────────────────
/** Mở lượt (`mo_luot`, council_decision_submission_service.py:137): đã có lượt `cho_gui` ⇒ 409 `luot_dang_cho` + mã CŨ + giờ tạo. */
export function luatMoLuot(luotCho: { ma: string; tao_luc: string } | null): LoiMayChu | null {
  return luotCho === null
    ? null
    : loi409("Bộ đang có lượt gửi ghi nhận chưa rõ kết quả — bấm \"Kiểm tra trên máy chủ\" trước.", { ma_loi: "luot_dang_cho", ma: luotCho.ma, tao_luc: luotCho.tao_luc })
}
/** Phân xử: `ma` trên URL phải đúng dạng uuid (giao diện chặn chuỗi lạ bằng `MA_LUOT_RE`). */
export function luatPhanXuMa(ma: string): LoiMayChu | null {
  return RE_UUID.test(ma) ? null : loi422(["ma"], "String should match pattern '^[0-9a-fA-F-]{36}$'", "string_pattern_mismatch")
}
