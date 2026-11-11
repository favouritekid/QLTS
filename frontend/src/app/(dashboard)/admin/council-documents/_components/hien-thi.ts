/**
 * Văn bản Hội đồng — định dạng HIỂN THỊ (không quyết định nghiệp vụ gì).
 */
import { getStatusConfig } from "@/lib/status-config"

/** Nhãn trạng thái hồ sơ (chỉ để đọc) + mã gốc của máy chủ — mức chặn / cảnh báo do MÁY CHỦ quyết. */
export function nhanTrangThai(s: string): string {
  const nhan = getStatusConfig(s).label
  return nhan && nhan !== s ? `${nhan} (${s})` : s
}

/** Nhãn loại mẫu — trùng `TEN_LOAI` của `council_document_template_service.py`. Loại lạ ⇒ in nguyên. */
const NHAN_LOAI_MAU: Record<string, string> = {
  bien_ban: "Biên bản",
  quyet_dinh: "Quyết định",
  danh_sach: "Danh sách xét tuyển",
}

export function nhanLoaiMau(loai: string): string {
  return NHAN_LOAI_MAU[loai] ?? loai
}

/** sha256 rút gọn để nhìn (12 ký tự đầu) — bản đầy đủ ở thuộc tính `title`. */
export function shaRutGon(sha: string): string {
  return sha.length > 12 ? `${sha.slice(0, 12)}…` : sha
}

export function kichThuoc(byte: number): string {
  if (byte < 1024) return `${byte} B`
  if (byte < 1024 * 1024) return `${(byte / 1024).toFixed(1)} KB`
  return `${(byte / (1024 * 1024)).toFixed(2)} MB`
}

/** Thời điểm ISO (UTC) ⇒ giờ Việt Nam, dạng dd/MM/yyyy HH:mm. Không đọc được ⇒ in nguyên. */
export function thoiDiem(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d)
}

/** Ngày YYYY-MM-DD ⇒ dd/MM/yyyy (không qua múi giờ). */
export function ngay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso
}

export function nguoi(id: number | null): string {
  return id === null ? "—" : `Tài khoản #${id}`
}

/** Tên người khi máy chủ đã trả (`nguoi_tao_ten`); chưa có ⇒ rơi về "Tài khoản #n" (đặc tả 3.4 ⏳ chờ máy chủ). */
export function nguoiHienThi(ten: string | null | undefined, id: number | null): string {
  return ten ? ten : nguoi(id)
}

// ── mức kiểm trước (bước 1–2) ────────────────────────────────────────────────
const NHAN_MUC_KIEM: Record<string, string> = {
  duoc_dung: "Được dựng",
  can_xac_nhan: "Cần xác nhận",
  bi_chan: "Bị chặn",
}
/** Nhãn mức do MÁY CHỦ quyết; mã lạ ⇒ in nguyên (không suy mức). */
export function nhanMucKiem(muc: string): string {
  return NHAN_MUC_KIEM[muc] ?? muc
}

// ── tình trạng bộ / văn bản (danh sách bộ, bước 6) ───────────────────────────
const NHAN_TINH_TRANG_BO: Record<string, string> = {
  chua_ghi_nhan: "Chưa ghi nhận",
  con_hieu_luc: "Còn hiệu lực",
  het_hieu_luc: "Hết hiệu lực",
  da_huy_ghi_nhan: "Đã huỷ ghi nhận",
  chua_xac_dinh: "Chưa xác định",
}
export function nhanTinhTrangBo(t: string): string {
  return NHAN_TINH_TRANG_BO[t] ?? t
}
/** Chú thích đi kèm nhãn "Chưa ghi nhận" (đặc tả 3.4): nói đúng nghĩa của nhãn. */
export const CHU_THICH_CHUA_GHI_NHAN = "phần mềm chưa có bản ghi Quyết định đã ký của bộ này; không có nghĩa là giấy chưa ký"

const NHAN_LOAI_QD: Record<string, string> = {
  trung_tuyen: "Quyết định trúng tuyển",
  bo_sung: "Quyết định bổ sung",
}
export function nhanLoaiQuyetDinh(loai: string): string {
  return NHAN_LOAI_QD[loai] ?? loai
}

const NHAN_TRANG_THAI_QD: Record<string, string> = {
  hieu_luc: "Còn hiệu lực",
  het_hieu_luc: "Hết hiệu lực",
  huy_ghi_nhan: "Đã huỷ ghi nhận",
}
export function nhanTrangThaiQuyetDinh(t: string): string {
  return NHAN_TRANG_THAI_QD[t] ?? t
}

/** Lý do một dòng dán mã không khớp (`POST /sets/doi-ma`) — máy chủ chỉ nêu SỐ DÒNG, không giá trị. */
const NHAN_LY_DO_DAN_MA: Record<string, string> = {
  rong: "dòng trống",
  trung: "mã trùng",
  ky_tu_la: "có ký tự lạ",
  khong_khop: "không khớp hồ sơ nào của năm học đã chọn",
}
export function nhanLyDoDanMa(ly_do: string): string {
  return NHAN_LY_DO_DAN_MA[ly_do] ?? ly_do
}

/**
 * Đọc MỘT dict `quyet_dinh` của máy chủ (hai hình chưa thống nhất — xem `councilSetSchema`): chỉ lấy khoá nào có và
 * ĐÚNG KIỂU; khoá vắng ⇒ không có trường ấy. Không suy, không điền mặc định.
 */
export interface TomTatQuyetDinh {
  so?: string
  ngay?: string
  loai?: string
  trangThai?: string
  soHoSo?: number
  goc?: { so: string; ngay: string }
}
export function tomTatQuyetDinh(raw: Record<string, unknown> | null | undefined): TomTatQuyetDinh | null {
  if (!raw) return null
  const chuoi = (v: unknown) => (typeof v === "string" && v !== "" ? v : undefined)
  const goc =
    raw.goc && typeof raw.goc === "object"
      ? { so: chuoi((raw.goc as Record<string, unknown>).so_quyet_dinh), ngay: chuoi((raw.goc as Record<string, unknown>).ngay_ky) }
      : undefined
  return {
    so: chuoi(raw.so_quyet_dinh),
    ngay: chuoi(raw.ngay_ky),
    loai: chuoi(raw.loai),
    trangThai: chuoi(raw.trang_thai),
    soHoSo: typeof raw.so_ho_so === "number" ? raw.so_ho_so : undefined,
    goc: goc && goc.so && goc.ngay ? { so: goc.so, ngay: goc.ngay } : undefined,
  }
}

/** "Ngành · trình độ" của một dòng kiểm trước. */
export function nganhTrinhDo(nganh: string, trinhDo: string): string {
  return trinhDo ? `${nganh} · ${trinhDo}` : nganh
}
