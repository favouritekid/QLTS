// src/app/(dashboard)/quota-tables/page.tsx
/**
 * /quota-tables — GĐ2-F1: bảng chỉ tiêu năm / nhóm ngành (GĐ2-A). Máy chủ là chốt: XEM = Admin + Ban thư ký (GĐ2-C C2,
 * cổng `require_review_secretary` — chưa được gán ⇒ 404 thân chung); GHI = chỉ Admin (Casbin + `require_quota_table_admin`).
 * Trang chỉ bọc thành phần phía client.
 *
 * KT-6 (owner 24-11: Thư ký Hội đồng CÓ THỂ là cán bộ thường): trang nằm NGOÀI `/admin/*`. `proxy.ts` đẩy mọi vai ngoài
 * `ADMIN_ROLES` (admin, manager) khỏi `/admin/*` TRƯỚC khi trang chạy ⇒ cán bộ là Thư ký không bao giờ tới được cổng máy chủ nếu
 * trang ở đó. Ở đây proxy chỉ đòi đăng nhập; ai xem được là việc của máy chủ. `/admin/quota-tables` cũ chỉ còn chuyển hướng về
 * đây (dấu trang của Admin). KHÔNG mở rộng `ADMIN_ROLES`.
 */
import { QuotaTablesClient } from "./_components/QuotaTablesClient"

export default function QuotaTablesPage() {
  return <QuotaTablesClient />
}
