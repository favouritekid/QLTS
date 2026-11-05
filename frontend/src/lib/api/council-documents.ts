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
import axios, { AxiosError } from "axios"

import { api } from "@/lib/api/client"
import {
  councilDocumentPermissionsOutSchema,
  councilDownloadLogListSchema,
  councilSetCreateSchema,
  councilSetDeleteSchema,
  councilSetDeletionListSchema,
  councilSetDeletionSchema,
  councilSetDetailSchema,
  councilSetInputCodesSchema,
  councilSetListSchema,
  councilTemplateListSchema,
  councilTemplateSchema,
  type CouncilDocumentPermissions,
  type CouncilDownloadLog,
  type CouncilSet,
  type CouncilSetCreate,
  type CouncilSetDeletion,
  type CouncilSetDetail,
  type CouncilSetInputCodes,
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
}

export async function listCouncilSets(
  params: CouncilSetListParams,
): Promise<CouncilSet[]> {
  const res = await api.get(`${P}/sets`, {
    params: { limit: params.limit, offset: params.offset },
  })
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
    // eslint-disable-next-line no-control-regex
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
  try {
    const res = await api.get<Blob>(`${P}/sets/${setId}/files/${thuTu}`, {
      responseType: "blob",
    })
    return {
      blob: res.data,
      filename: filenameFromContentDisposition(
        res.headers["content-disposition"] as string | undefined,
        `bo-${setId}-tep-${thuTu}`,
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

// ── thông báo lỗi ────────────────────────────────────────────────────────────
export interface CouncilErrorMessage {
  /** câu chính, hiện cho người dùng */
  title: string
  /** câu của MÁY CHỦ (đã che dữ liệu) khi là lỗi miền — hiện nguyên văn */
  detail?: string
  status?: number
}

interface LoiMayChu {
  detail?: unknown
  error_code?: unknown
  code?: unknown
}

function chuoi(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined
}

/**
 * Lỗi ⇒ câu cho người dùng. KHÔNG đọc `config.data` / `input` / `ctx` của lỗi
 * (có thể mang danh sách mã). Lỗi miền (400 / 409) hiện NGUYÊN VĂN `detail` của
 * máy chủ — máy chủ chỉ nêu số dòng / tên trường, không nêu giá trị. 403 / 404 /
 * 5xx: câu cố định, không lộ chi tiết.
 */
export function describeCouncilDocumentError(error: unknown): CouncilErrorMessage {
  if (!axios.isAxiosError(error)) {
    if (error && typeof error === "object" && (error as { name?: unknown }).name === "ZodError") {
      return { title: "Dữ liệu không đúng định dạng (máy chủ hoặc ô nhập)." }
    }
    return { title: "Đã có lỗi không xác định." }
  }
  const e = error as AxiosError<LoiMayChu>
  if (!e.response) {
    return { title: "Không kết nối được máy chủ — kiểm tra mạng rồi thử lại." }
  }
  const status = e.response.status
  const data: LoiMayChu =
    e.response.data && typeof e.response.data === "object" ? e.response.data : {}
  switch (status) {
    case 400:
      return { status, title: "Máy chủ từ chối dữ liệu.", detail: chuoi(data.detail) }
    case 403:
      return { status, title: "Bạn không có quyền thực hiện thao tác này." }
    case 404:
      return {
        status,
        title: "Không tìm thấy — bộ văn bản / tệp có thể đã bị xoá hoặc ngoài phạm vi của bạn.",
      }
    case 409:
      return { status, title: "Không thực hiện được lúc này.", detail: chuoi(data.detail) }
    case 422: {
      // Chỉ `loc` (bỏ phần tử đầu "body") + `msg` — KHÔNG `input` / `ctx`.
      const ds = Array.isArray(data.detail) ? data.detail : []
      const dong = ds
        .map((x) => {
          const loc = Array.isArray((x as { loc?: unknown }).loc)
            ? ((x as { loc: unknown[] }).loc.slice(1).filter((p) => typeof p === "string") as string[])
            : []
          const msg = chuoi((x as { msg?: unknown }).msg)
          return msg ? (loc.length ? `${loc.join(".")}: ${msg}` : msg) : undefined
        })
        .filter((s): s is string => s !== undefined)
      return {
        status,
        title: "Dữ liệu gửi lên sai dạng.",
        detail: dong.length ? Array.from(new Set(dong)).join("\n") : undefined,
      }
    }
    case 429:
      return { status, title: "Đã vượt giới hạn số lần thao tác — vui lòng thử lại sau." }
    case 503:
      if (data.code === "ADMISSION_FROZEN") {
        return {
          status,
          title: "Tuyển sinh đang tạm đóng băng — thao tác ghi bị chặn. Xem / tải vẫn được.",
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
