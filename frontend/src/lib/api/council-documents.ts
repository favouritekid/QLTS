/**
 * Văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1) — API client.
 *
 * Tiền tố `/api/admission-config/council-documents` (router
 * `Backend_FastAPI/app/routers/council_documents.py`). Mọi phản hồi qua Zod.
 *
 * ⚠️ DỮ LIỆU CÁ NHÂN (danh sách mã hồ sơ = CCCD):
 *   - danh sách mã CHỈ đi trong THÂN POST (`createCouncilSet`) — không bao giờ
 *     vào URL / query string;
 *   - không `console.*` ở bất kỳ nhánh nào của tệp này (lỗi axios mang
 *     `config.data` = thân yêu cầu ⇒ in lỗi là in danh sách mã);
 *   - không lưu ở đâu ngoài bộ nhớ của React Query (xem hook).
 */
import axios from "axios"

import { api } from "@/lib/api/client"
import { readApiError } from "@/lib/error-handler"
import {
  councilBlockedRowsSchema,
  councilCodesInSchema,
  councilCodesOutSchema,
  councilCompareSchema,
  councilConfirmNeededSchema,
  councilDecisionCancelSchema,
  councilDecisionDetailSchema,
  councilDecisionListSchema,
  councilDecisionWriteSchema,
  councilDocumentPermissionsOutSchema,
  councilDownloadLogListSchema,
  councilProfileSearchInSchema,
  councilProfileSearchOutSchema,
  councilSetCreateByIdsSchema,
  councilSetCreateSchema,
  councilSetDeleteSchema,
  councilSetDeletionListSchema,
  councilSetDeletionSchema,
  councilSetDetailSchema,
  councilSetGateSchema,
  councilSetInputCodesSchema,
  councilSetListSchema,
  councilSetPreviewInSchema,
  councilSetPreviewSchema,
  councilSubmissionListSchema,
  councilSubmissionOpenSchema,
  councilSubmissionResolveSchema,
  councilTemplateListSchema,
  councilTemplateSchema,
  type CouncilBlockedRows,
  type CouncilCodesIn,
  type CouncilCodesOut,
  type CouncilCompare,
  type CouncilConfirmNeeded,
  type CouncilDecisionCancel,
  type CouncilDecision,
  type CouncilDecisionDetail,
  type CouncilDecisionWrite,
  type CouncilDocumentPermissions,
  type CouncilDownloadLog,
  type CouncilProfileSearchIn,
  type CouncilProfileSearchOut,
  type CouncilSet,
  type CouncilSetCreate,
  type CouncilSetCreateByIds,
  type CouncilSetDeletion,
  type CouncilSetDetail,
  type CouncilSetGate,
  type CouncilSetInputCodes,
  type CouncilSetPreview,
  type CouncilSetPreviewIn,
  type CouncilSubmission,
  type CouncilSubmissionOpen,
  type CouncilSubmissionResolve,
  type CouncilTemplate,
  type CouncilTemplateKind,
} from "@/lib/zod/council-documents"

export const COUNCIL_DOCUMENTS_PREFIX = "/api/admission-config/council-documents"
const P = COUNCIL_DOCUMENTS_PREFIX

/** Cờ quyền giao diện của người gọi. 403 (vai không có dòng Casbin) ném lỗi — hook quyết. */
export async function getCouncilDocumentPermissions(): Promise<CouncilDocumentPermissions> {
  const res = await api.get(`${P}/quyen`)
  return councilDocumentPermissionsOutSchema.parse(res.data).permissions
}

// ── kho mẫu ──────────────────────────────────────────────────────────────────
export async function listCouncilTemplates(): Promise<CouncilTemplate[]> {
  const res = await api.get(`${P}/templates`)
  return councilTemplateListSchema.parse(res.data)
}

export interface UploadCouncilTemplateInput {
  loai: CouncilTemplateKind
  /** YYYY-MM-DD */
  hieu_luc_tu: string
  ghi_chu?: string
  file: File
}

export async function uploadCouncilTemplate(
  input: UploadCouncilTemplateInput,
): Promise<CouncilTemplate> {
  const fd = new FormData()
  fd.append("loai", input.loai)
  fd.append("hieu_luc_tu", input.hieu_luc_tu)
  if (input.ghi_chu !== undefined && input.ghi_chu !== "") {
    fd.append("ghi_chu", input.ghi_chu)
  }
  fd.append("file", input.file)
  const res = await api.post(`${P}/templates`, fd)
  return councilTemplateSchema.parse(res.data)
}

// ── bộ văn bản ───────────────────────────────────────────────────────────────
export interface CouncilSetListParams {
  limit: number
  offset: number
  // ⏳ CHỜ MÁY CHỦ (đặc tả 3.4): bộ lọc của `GET /sets` CHƯA có ở `dd6c725d` — chỉ gửi khi người dùng đặt; máy chủ cũ
  // bỏ qua (danh sách không lọc). Số Quyết định chỉ gồm chữ số (không phải dữ liệu cá nhân).
  so_quyet_dinh?: string
  nam_hoc?: number
  tinh_trang?: string
  nguoi_tao_id?: number
}

export async function listCouncilSets(
  params: CouncilSetListParams,
): Promise<CouncilSet[]> {
  const q: Record<string, string | number> = { limit: params.limit, offset: params.offset }
  if (params.so_quyet_dinh) q.so_quyet_dinh = params.so_quyet_dinh
  if (params.nam_hoc !== undefined) q.nam_hoc = params.nam_hoc
  if (params.tinh_trang) q.tinh_trang = params.tinh_trang
  if (params.nguoi_tao_id !== undefined) q.nguoi_tao_id = params.nguoi_tao_id
  const res = await api.get(`${P}/sets`, { params: q })
  return councilSetListSchema.parse(res.data)
}

export async function getCouncilSet(setId: number): Promise<CouncilSetDetail> {
  const res = await api.get(`${P}/sets/${setId}`)
  return councilSetDetailSchema.parse(res.data)
}

/** Dựng + lưu một bộ. Danh sách mã CHỈ ở thân JSON, GIỮ nguyên thứ tự. */
export async function createCouncilSet(
  payload: CouncilSetCreate,
): Promise<CouncilSetDetail> {
  const body = councilSetCreateSchema.parse(payload)
  const res = await api.post(`${P}/sets`, body)
  return councilSetDetailSchema.parse(res.data)
}

export async function deleteCouncilSet(
  setId: number,
  lyDo: string,
): Promise<CouncilSetDeletion> {
  const body = councilSetDeleteSchema.parse({ ly_do: lyDo })
  const res = await api.delete(`${P}/sets/${setId}`, { data: body })
  return councilSetDeletionSchema.parse(res.data)
}

/** Danh sách mã đầu vào (CHỈ admin) — DỮ LIỆU CÁ NHÂN, chỉ giữ trong bộ nhớ. */
export async function getCouncilSetInputCodes(
  setId: number,
): Promise<CouncilSetInputCodes> {
  const res = await api.get(`${P}/sets/${setId}/ma-ho-so`)
  return councilSetInputCodesSchema.parse(res.data)
}

export interface CouncilFileBlob {
  blob: Blob
  filename: string
}

/**
 * Tên tệp từ `Content-Disposition`: ưu tiên `filename*=UTF-8''…` (RFC 6266 /
 * 5987 — tên có dấu), rồi `filename="…"` (bản ASCII máy chủ dựng sẵn), cuối
 * cùng `fallback`. Bỏ mọi thành phần thư mục / ký tự điều khiển.
 */
export function filenameFromContentDisposition(
  header: string | undefined,
  fallback: string,
): string {
  const sach = (ten: string) => {
    const cuoi = ten.split(/[\\/]/).pop() ?? ""
    const bo = cuoi.replace(/[\u0000-\u001f\u007f]/g, "").trim()
    return bo || fallback
  }
  if (!header) return fallback
  const sao = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)
  if (sao) {
    try {
      return sach(decodeURIComponent(sao[1].trim()))
    } catch {
      /* mã hoá hỏng ⇒ thử bản ASCII */
    }
  }
  const thuong = /filename\s*=\s*"([^"]*)"/i.exec(header) ?? /filename\s*=\s*([^;]+)/i.exec(header)
  if (thuong) return sach(thuong[1].trim())
  return fallback
}

/**
 * Tải MỘT tệp đã lưu (bytes máy chủ đã lưu — không dựng lại). Lỗi: thân lỗi
 * (Blob vì `responseType: "blob"`) được đọc lại thành JSON để hiện đúng câu
 * của máy chủ.
 */
export async function downloadCouncilSetFile(
  setId: number,
  thuTu: number,
): Promise<CouncilFileBlob> {
  return taiBlob(`${P}/sets/${setId}/files/${thuTu}`, `bo-${setId}-tep-${thuTu}`)
}

/** Tải một đường dẫn trả byte (tệp lẻ / zip cả bộ). Lỗi: thân lỗi (Blob) đọc lại thành JSON để hiện đúng câu máy chủ. */
async function taiBlob(url: string, tenDuPhong: string): Promise<CouncilFileBlob> {
  try {
    const res = await api.get<Blob>(url, { responseType: "blob" })
    return {
      blob: res.data,
      filename: filenameFromContentDisposition(
        res.headers["content-disposition"] as string | undefined,
        tenDuPhong,
      ),
    }
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.data instanceof Blob) {
      try {
        e.response.data = JSON.parse(await e.response.data.text())
      } catch {
        e.response.data = undefined
      }
    }
    throw e
  }
}

/**
 * Tải CẢ BỘ (.zip) — ⏳ CHỜ MÁY CHỦ (`GET /sets/{id}/tai-ca-bo`, đặc tả 3.6). Máy chủ kiểm sha từng tệp, ghi
 * nhật ký tải, commit rồi mới trả byte; giao diện chỉ nhận và lưu.
 */
export async function downloadCouncilSetZip(setId: number): Promise<CouncilFileBlob> {
  return taiBlob(`${P}/sets/${setId}/tai-ca-bo`, `bo-${setId}.zip`)
}

// ── nhật ký (CHỈ admin) ──────────────────────────────────────────────────────
export interface CouncilLogParams {
  limit: number
  offset: number
  /** chỉ nhật ký tải: lọc theo bộ (bộ đã xoá vẫn lọc được) */
  set_id?: number
}

export async function listCouncilDownloadLog(
  params: CouncilLogParams,
): Promise<CouncilDownloadLog[]> {
  const q: Record<string, number> = { limit: params.limit, offset: params.offset }
  if (params.set_id !== undefined) q.set_id = params.set_id
  const res = await api.get(`${P}/nhat-ky-tai`, { params: q })
  return councilDownloadLogListSchema.parse(res.data)
}

export async function listCouncilSetDeletions(
  params: Omit<CouncilLogParams, "set_id">,
): Promise<CouncilSetDeletion[]> {
  const res = await api.get(`${P}/nhat-ky-xoa`, {
    params: { limit: params.limit, offset: params.offset },
  })
  return councilSetDeletionListSchema.parse(res.data)
}

// ── vòng giao diện: chọn hồ sơ → kiểm trước → dựng (đặc tả 3.1 / 3.2 / 3.3 / 3.11) ─────────────────────────────────
// Máy chủ có các route này từ `5feb425d` (DTO đã đối chiếu từng trường với `schemas/council_document.py`); test vẫn dùng
// MSW. Cả ba POST chỉ đọc (kiểm trước, tìm hồ sơ, đổi mã) bị cần gạt đóng băng chặn (503) như mọi lần ghi.
// ⚠️ Thân yêu cầu / phản hồi có `ho_ten`, `cccd`: chỉ ở bộ nhớ, không `console.*`, không URL.

/** Kiểm trước + thứ tự (đặc tả 3.1): cùng cổng và cùng đường đọc với bộ dựng; KHÔNG ghi gì. */
export async function previewCouncilSet(input: CouncilSetPreviewIn): Promise<CouncilSetPreview> {
  const body = councilSetPreviewInSchema.parse(input)
  const res = await api.post(`${P}/sets/kiem-truoc`, body)
  return councilSetPreviewSchema.parse(res.data)
}

/** Dán danh sách mã ⇒ id hồ sơ (đặc tả 3.2). Danh sách mã CHỈ ở thân JSON. */
export async function resolveCouncilCodes(input: CouncilCodesIn): Promise<CouncilCodesOut> {
  const body = councilCodesInSchema.parse(input)
  const res = await api.post(`${P}/sets/doi-ma`, body)
  return councilCodesOutSchema.parse(res.data)
}

/** Tìm hồ sơ cho trang chọn (đặc tả 3.11): POST, thân JSON — từ khoá (tên / CCCD) không bao giờ vào URL. */
export async function searchCouncilProfiles(
  input: CouncilProfileSearchIn,
): Promise<CouncilProfileSearchOut> {
  const body = councilProfileSearchInSchema.parse(input)
  const res = await api.post(`${P}/sets/tim-ho-so`, body)
  return councilProfileSearchOutSchema.parse(res.data)
}

/** Dựng bộ theo id + dấu kiểm trước (đặc tả 3.3). 409 `du_lieu_doi_tu_luc_kiem` ⇒ giao diện đưa về bước kiểm tra. */
export async function createCouncilSetByIds(
  payload: CouncilSetCreateByIds,
): Promise<CouncilSetDetail> {
  const body = councilSetCreateByIdsSchema.parse(payload)
  const res = await api.post(`${P}/sets`, body)
  return councilSetDetailSchema.parse(res.data)
}

/** Đối chiếu ảnh chụp của bộ với dữ liệu hiện tại: số dòng + TÊN trường đổi (không giá trị). Chỉ admin. */
export async function compareCouncilSet(setId: number): Promise<CouncilCompare> {
  const res = await api.get(`${P}/sets/${setId}/so-voi-hien-tai`)
  return councilCompareSchema.parse(res.data)
}

// ── Quyết định đã ký + lượt gửi ghi nhận (máy chủ có từ `dd6c725d`) ───────────────────────────────────────────────
export interface CouncilDecisionListParams {
  limit: number
  offset: number
  set_id?: number
  // ⏳ CHỜ MÁY CHỦ (phiên A chốt 11-11): bộ lọc loại + trạng thái; máy chủ cũ bỏ qua ⇒ nơi dùng vẫn lọc phòng thủ.
  loai?: string
  trang_thai?: string
}

export async function listCouncilDecisions(
  params: CouncilDecisionListParams,
): Promise<CouncilDecision[]> {
  const q: Record<string, string | number> = { limit: params.limit, offset: params.offset }
  if (params.set_id !== undefined) q.set_id = params.set_id
  if (params.loai) q.loai = params.loai
  if (params.trang_thai) q.trang_thai = params.trang_thai
  const res = await api.get(`${P}/decisions`, { params: q })
  return councilDecisionListSchema.parse(res.data)
}

export async function getCouncilDecision(decisionId: number): Promise<CouncilDecisionDetail> {
  const res = await api.get(`${P}/decisions/${decisionId}`)
  return councilDecisionDetailSchema.parse(res.data)
}

export interface CreateCouncilDecisionInput {
  set_id: number
  /** mã lượt do máy chủ cấp (`openCouncilSubmission`) — BẮT BUỘC; KHÔNG lưu ở trình duyệt */
  ma_luot_gui: string
  loai: "trung_tuyen" | "bo_sung"
  goc_id?: number
  so_quyet_dinh: string
  /** YYYY-MM-DD */
  ngay_ky: string
  so_bien_ban?: string
  ngay_bien_ban?: string
  dot_so?: string
  dot_thang?: number
  xac_nhan_so_ho_so: number
  xac_nhan_khop_ban_in: boolean
  xac_nhan_trang_thai?: Record<string, number>
  ghi_chu_mau?: string
  scan: File
}

/**
 * Ghi nhận MỘT Quyết định đã ký (multipart). Trả văn bản + số đếm; `lap_lai: true` khi gửi lặp đúng nội dung
 * (văn bản cũ, không ghi lần hai). Mất mạng / 5xx / hết giờ: KHÔNG kết luận "chưa ghi" — xem
 * `phanLoaiLoiGui` (`council-submission.ts`) và nút phân xử.
 */
export async function createCouncilDecision(
  input: CreateCouncilDecisionInput,
): Promise<CouncilDecisionWrite> {
  const fd = new FormData()
  fd.append("set_id", String(input.set_id))
  fd.append("ma_luot_gui", input.ma_luot_gui)
  fd.append("loai", input.loai)
  if (input.goc_id !== undefined) fd.append("goc_id", String(input.goc_id))
  fd.append("so_quyet_dinh", input.so_quyet_dinh)
  fd.append("ngay_ky", input.ngay_ky)
  if (input.so_bien_ban) fd.append("so_bien_ban", input.so_bien_ban)
  if (input.ngay_bien_ban) fd.append("ngay_bien_ban", input.ngay_bien_ban)
  if (input.dot_so) fd.append("dot_so", input.dot_so)
  if (input.dot_thang !== undefined) fd.append("dot_thang", String(input.dot_thang))
  fd.append("xac_nhan_so_ho_so", String(input.xac_nhan_so_ho_so))
  fd.append("xac_nhan_khop_ban_in", input.xac_nhan_khop_ban_in ? "true" : "false")
  if (input.xac_nhan_trang_thai && Object.keys(input.xac_nhan_trang_thai).length > 0) {
    fd.append("xac_nhan_trang_thai", JSON.stringify(input.xac_nhan_trang_thai))
  }
  if (input.ghi_chu_mau) fd.append("ghi_chu_mau", input.ghi_chu_mau)
  fd.append("scan", input.scan)
  const res = await api.post(`${P}/decisions`, fd)
  return councilDecisionWriteSchema.parse(res.data)
}

/** Huỷ ghi nhận (nhập SAI): lý do + gõ lại số hồ sơ + xác nhận trạng thái theo `CouncilDecisionCancelIn`. */
export async function cancelCouncilDecisionRecord(
  decisionId: number,
  payload: CouncilDecisionCancel,
): Promise<CouncilDecisionWrite> {
  const body = councilDecisionCancelSchema.parse(payload)
  const res = await api.post(`${P}/decisions/${decisionId}/huy-ghi-nhan`, body)
  return councilDecisionWriteSchema.parse(res.data)
}

/** `xac_nhan_can` của `409` ghi nhận / huỷ ghi nhận (cần xác nhận số hồ sơ theo loại). Sai dạng / vắng ⇒ undefined. */
export function councilConfirmNeededFromError(error: unknown): CouncilConfirmNeeded | undefined {
  const r = councilConfirmNeededSchema.safeParse(readApiError(error).data?.xac_nhan_can)
  return r.success && Object.keys(r.data.so_ho_so_theo_loai).length > 0 ? r.data : undefined
}

/** `dong_bi_chan` của `409` ghi nhận. Sai dạng / vắng ⇒ undefined. */
export function councilBlockedRowsFromError(error: unknown): CouncilBlockedRows | undefined {
  const r = councilBlockedRowsSchema.safeParse(readApiError(error).data?.dong_bi_chan)
  return r.success && r.data.length > 0 ? r.data : undefined
}

/** Mã lượt gửi: uuid do máy chủ cấp (không phải dữ liệu cá nhân ⇒ được nằm trong URL). Chặn chuỗi lạ trước khi ghép URL. */
const MA_LUOT_RE = /^[0-9a-fA-F-]{36}$/

/** Mở MỘT lượt gửi ghi nhận cho bộ — gọi NGAY trước khi gửi, không gọi khi vào bước 6 (tránh lượt treo). */
export async function openCouncilSubmission(setId: number): Promise<CouncilSubmissionOpen> {
  const res = await api.post(`${P}/sets/${setId}/luot-ghi-nhan`)
  return councilSubmissionOpenSchema.parse(res.data)
}

/** Các lượt của bộ — khôi phục sau tải lại trang. Mã lượt KHÔNG được lưu ở trình duyệt. */
export async function listCouncilSubmissions(setId: number): Promise<CouncilSubmission[]> {
  const res = await api.get(`${P}/sets/${setId}/luot-ghi-nhan`)
  return councilSubmissionListSchema.parse(res.data)
}

/** Phân xử lượt chưa rõ. Chỉ kết luận theo `ket_qua` của phản hồi 2xx; lỗi ⇒ vẫn "chưa xác định". */
export async function resolveCouncilSubmission(ma: string): Promise<CouncilSubmissionResolve> {
  if (!MA_LUOT_RE.test(ma)) throw new Error("Mã lượt gửi không hợp lệ.")
  const res = await api.post(`${P}/luot-ghi-nhan/${ma}/chan`)
  return councilSubmissionResolveSchema.parse(res.data)
}

// ── thông báo lỗi ────────────────────────────────────────────────────────────
/** Mã lỗi riêng của máy chủ (`ma_loi` ở cấp cao nhất của thân lỗi, cùng `ma`, `tao_luc`) — giao diện rẽ nhánh theo ĐÂY. */
export interface CouncilApiErrorCode {
  maLoi?: string
  /** `ma` lượt gửi kèm lỗi (409 `luot_dang_cho`; có thể `null`) */
  ma?: string | null
  taoLuc?: string
}

export function councilErrorCode(error: unknown): CouncilApiErrorCode {
  const d = readApiError(error).data
  if (!d) return {}
  const chuoi = (v: unknown) => (typeof v === "string" && v.length > 0 ? v : undefined)
  const ma = d.ma === null ? null : chuoi(d.ma)
  return { maLoi: chuoi(d.ma_loi), ma, taoLuc: chuoi(d.tao_luc) }
}

export interface CouncilErrorMessage {
  /** câu chính, hiện cho người dùng */
  title: string
  /** câu của MÁY CHỦ (đã che dữ liệu) khi là lỗi miền — hiện nguyên văn */
  detail?: string
  status?: number
  /** cổng dựng bộ (lượt G): danh sách bị chặn / cần xác nhận theo SỐ DÒNG — chỉ ở 400 / 409 */
  gate?: CouncilSetGate
  /** mã lỗi riêng của máy chủ (`ma_loi`: `du_lieu_doi_tu_luc_kiem`, `luot_dang_cho`, …) — chỉ ở 409; giao diện rẽ nhánh theo đây */
  maLoi?: string
}

/** `kiem_tra_dung_bo` của thân lỗi 400 / 409 (máy chủ: chỉ số dòng, mã lý do, trạng thái, số
 * đếm). Sai dạng ⇒ undefined (giao diện chỉ hiện câu máy chủ). */
function docGate(data: Record<string, unknown> | undefined): CouncilSetGate | undefined {
  const r = councilSetGateSchema.safeParse(data?.kiem_tra_dung_bo)
  return r.success ? r.data : undefined
}

/** Cổng dựng bộ của một lỗi dựng bộ (400 / 409) — form dùng để mở hộp xác nhận THEO PHẢN HỒI
 * máy chủ (`nguoi_goi_duoc_xac_nhan`), không theo vai. */
export function councilSetGateFromError(error: unknown): CouncilSetGate | undefined {
  return describeCouncilDocumentError(error).gate
}

/**
 * Lỗi ⇒ câu HIỆN TẠI CHỖ cho người dùng (không toast). Thân lỗi đọc qua bộ đọc CHUNG
 * `readApiError` (`@/lib/error-handler` — cùng nguồn với `handleApiError`; F238): ở đây chỉ còn
 * CÁCH TRÌNH BÀY riêng của module — lỗi miền (400 / 409) hiện NGUYÊN VĂN `detail` của máy chủ (máy
 * chủ chỉ nêu số dòng / tên trường, không nêu giá trị) + danh sách cổng dựng bộ; 403 / 404 / 5xx:
 * câu cố định, không lộ chi tiết; 422: `loc` (bỏ phần tử đầu "body") + `msg` từ khoá `errors` của
 * handler THẬT (F236), KHÔNG `input` / `ctx`; 503 đóng băng: câu riêng.
 */
export function describeCouncilDocumentError(error: unknown): CouncilErrorMessage {
  const e = readApiError(error)
  if (!e.isAxios) {
    if (error && typeof error === "object" && (error as { name?: unknown }).name === "ZodError") {
      return { title: "Dữ liệu không đúng định dạng (máy chủ hoặc ô nhập)." }
    }
    return { title: "Đã có lỗi không xác định." }
  }
  if (!e.hasResponse || e.status === undefined) {
    return { title: "Không kết nối được máy chủ — kiểm tra mạng rồi thử lại." }
  }
  const status = e.status
  switch (status) {
    case 400:
      return { status, title: "Máy chủ từ chối dữ liệu.", detail: e.detail, gate: docGate(e.data) }
    case 403:
      return { status, title: "Bạn không có quyền thực hiện thao tác này." }
    case 404:
      return {
        status,
        title: "Không tìm thấy — bộ văn bản / tệp có thể đã bị xoá hoặc ngoài phạm vi của bạn.",
      }
    case 409:
      return {
        status,
        title: "Không thực hiện được lúc này.",
        detail: e.detail,
        gate: docGate(e.data),
        maLoi: councilErrorCode(error).maLoi,
      }
    case 422: {
      const dong = e.validation.map((x) => {
        const loc = x.loc.slice(1)
        return loc.length ? `${loc.join(".")}: ${x.msg}` : x.msg
      })
      return {
        status,
        title: "Dữ liệu gửi lên sai dạng.",
        detail: dong.length ? Array.from(new Set(dong)).join("\n") : undefined,
      }
    }
    case 429:
      return { status, title: "Đã vượt giới hạn số lần thao tác — vui lòng thử lại sau." }
    case 503:
      if (e.frozen) {
        return {
          status,
          // Ba route chỉ đọc của luồng dựng bộ (kiểm trước, tìm hồ sơ, đổi mã) cũng bị cần gạt chặn (máy chủ `5feb425d`).
          title:
            "Tuyển sinh đang tạm đóng băng — thao tác ghi bị chặn, cả chọn / kiểm trước hồ sơ để dựng bộ. Xem / tải vẫn được.",
        }
      }
      return { status, title: "Hệ thống tạm thời không phục vụ — thử lại sau." }
    default:
      if (status >= 500) {
        return { status, title: "Lỗi hệ thống — thử lại sau hoặc báo quản trị viên." }
      }
      return { status, title: `Đã có lỗi (mã ${status}).` }
  }
}
