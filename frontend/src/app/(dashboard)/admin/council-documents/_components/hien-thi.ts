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

/** Tên người máy chủ trả (`nguoi_tao_ten` / `nguoi_tai_ten` / `nguoi_xoa_ten`: họ tên, không có thì tên đăng nhập); `null` (tài khoản không còn) ⇒ "Tài khoản #n". */
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
  sai_dinh_dang: "mã không đúng dạng (phải đúng 9 hoặc 12 chữ số)",
  // Hồ sơ ngoài phạm vi đơn vị của người gọi cũng báo `khong_khop` (máy chủ không phân biệt với "không có").
  khong_khop: "không khớp hồ sơ nào của năm học đã chọn (hoặc hồ sơ ngoài phạm vi của bạn)",
  nhieu_ho_so: "mã khớp nhiều hơn một hồ sơ",
}
export function nhanLyDoDanMa(ly_do: string): string {
  return NHAN_LY_DO_DAN_MA[ly_do] ?? ly_do
}

/** Ngành trên hồ sơ để hiện: hồ sơ không có ngành (máy chủ trả chuỗi rỗng) ⇒ "—", như màn Hồ sơ tuyển sinh. */
export function nganhHienThi(nganh: string): string {
  return nganh.trim() === "" ? "—" : nganh
}

/** "Ngành · trình độ" của một dòng kiểm trước. */
export function nganhTrinhDo(nganh: string, trinhDo: string): string {
  const n = nganhHienThi(nganh)
  return trinhDo ? `${n} · ${trinhDo}` : n
}

/**
 * Nhãn tiếng Việt của TÊN TRƯỜNG ở bước 5 "Đối chiếu bản ký" (máy chủ trả khoá thô của dòng in — `CandidateRowV1`).
 * Bảng TRÌNH BÀY (không phải luật): chỉ khoá nghĩa chắc chắn; khoá khác ⇒ in nguyên khoá, không đoán nghĩa.
 */
const NHAN_TRUONG_DOI_CHIEU: Record<string, string> = {
  ma_ho_so: "Mã hồ sơ",
  ho: "Họ",
  ten: "Tên",
  gioi_tinh: "Giới tính",
  ngay_sinh: "Ngày sinh",
  noi_sinh: "Nơi sinh",
  dan_toc: "Dân tộc",
  dia_chi: "Địa chỉ",
  van_hoa: "Văn hoá",
  nganh: "Ngành",
  ma_nganh: "Mã ngành",
  trinh_do: "Trình độ",
  to_hop: "Tổ hợp",
  phuong_thuc: "Phương thức",
  mon_to_hop: "Môn tổ hợp",
  diem_tb: "Điểm trung bình",
  tong_diem: "Tổng điểm",
  kv: "Khu vực",
  diem_kv: "Điểm khu vực",
  ut_ma: "Đối tượng ưu tiên",
  diem_ut: "Điểm ưu tiên",
}
export function nhanTruongDoiChieu(khoa: string): string {
  return NHAN_TRUONG_DOI_CHIEU[khoa] ?? khoa
}
