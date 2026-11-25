/**
 * Năm cho ô chọn của màn lần xét — chỉ là TIỆN cho người dùng (cùng khoảng trang "Bảng chỉ tiêu năm": năm nay − 2 … năm nay + 3).
 * Năm đang chọn nằm ngoài khoảng (vd mở từ URL) vẫn được thêm vào ô để không mất. Năm nào hợp lệ do máy chủ quyết (E1: 2000–2100).
 */
export function thisYear(): number {
  return new Date().getFullYear()
}

export function yearOptions(selected?: number): number[] {
  const current = thisYear()
  const years = Array.from({ length: 6 }, (_, i) => current - 2 + i)
  if (selected !== undefined && !years.includes(selected)) years.push(selected)
  return years.sort((a, b) => b - a)
}
