// src/app/(dashboard)/admin/quota-tables/page.tsx
/**
 * Đường CŨ của "Bảng chỉ tiêu năm" (GĐ2-F1 đã lên production ở đây) — nay CHỈ chuyển hướng sang `/quota-tables` (KT-6, owner
 * 24-11: Thư ký Hội đồng có thể là cán bộ thường, mà `proxy.ts` chặn cán bộ ở mọi `/admin/*`). Giữ để dấu trang của Admin /
 * Quản lý không gãy. Cán bộ mở đường này vẫn bị proxy đẩy về `/dashboard` như mọi `/admin/*` — đường của Thư ký là
 * `/quota-tables`. Không hiển thị gì ở đây: MỘT chỗ dựng trang.
 */
import { redirect } from "next/navigation"

export default function AdminQuotaTablesRedirect() {
  redirect("/quota-tables")
}
