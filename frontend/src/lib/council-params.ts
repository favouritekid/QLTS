/**
 * Văn bản Hội đồng — sáu tham số của Quyết định / Biên bản (`DecisionParams`) ở dạng NHẬP của giao diện.
 *
 * Một nguồn cho form cũ (`CreateCouncilSetForm`) và bước 3 của luồng mới. Chỉ ĐỊNH DẠNG (thin validation): luật
 * (đợt số + tháng cùng điền / cùng trống; ngày Biên bản không sau ngày Quyết định) do MÁY CHỦ quyết và báo lỗi.
 */
import type { DecisionParams } from "@/lib/zod/council-documents"

export interface ThamSoNhap {
  so_quyet_dinh: string
  ngay_quyet_dinh: string
  dot_so: string
  dot_thang: string
  so_bien_ban: string
  ngay_bien_ban: string
}

export const THAM_SO_TRONG: ThamSoNhap = {
  so_quyet_dinh: "",
  ngay_quyet_dinh: "",
  dot_so: "",
  dot_thang: "",
  so_bien_ban: "",
  ngay_bien_ban: "",
}

/**
 * Ô nhập danh sách mã ⇒ mảng gửi máy chủ, GIỮ thứ tự VÀ số dòng: dòng thứ i của ô nhập là phần tử thứ i (máy chủ báo
 * lỗi theo SỐ DÒNG, đếm từ 1). Chỉ bỏ các dòng trống ở CUỐI (không làm lệch số dòng nào). Không tự sửa / lọc mã —
 * máy chủ kiểm định dạng, trùng, khớp hồ sơ.
 */
export function dongNhapThanhDanhSach(van_ban: string): string[] {
  const dong = van_ban.split(/\r?\n/)
  while (dong.length > 0 && dong[dong.length - 1].trim() === "") dong.pop()
  return dong
}

/** Chỉ gửi ô đã điền; không điền ô nào ⇒ không gửi tham số (chỗ ấy để trống trên văn bản). */
export function thamSoGui(t: ThamSoNhap): DecisionParams | null {
  const out: DecisionParams = {}
  if (t.so_quyet_dinh.trim()) out.so_quyet_dinh = t.so_quyet_dinh.trim()
  if (t.ngay_quyet_dinh) out.ngay_quyet_dinh = t.ngay_quyet_dinh
  if (t.dot_so.trim()) out.dot_so = t.dot_so.trim()
  if (t.dot_thang.trim()) out.dot_thang = Number(t.dot_thang.trim())
  if (t.so_bien_ban.trim()) out.so_bien_ban = t.so_bien_ban.trim()
  if (t.ngay_bien_ban) out.ngay_bien_ban = t.ngay_bien_ban
  return Object.keys(out).length ? out : null
}
