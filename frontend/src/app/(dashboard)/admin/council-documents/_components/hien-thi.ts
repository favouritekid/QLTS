/**
 * Văn bản Hội đồng — định dạng HIỂN THỊ (không quyết định nghiệp vụ gì).
 */

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
