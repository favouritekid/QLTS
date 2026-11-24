// src/app/(dashboard)/admin/quota-tables/page.tsx
/**
 * /admin/quota-tables — GĐ2-F1: bảng chỉ tiêu năm / nhóm ngành (GĐ2-A). Máy chủ là chốt: XEM = Admin + Ban thư ký (GĐ2-C C2,
 * cổng `require_review_secretary` — chưa được gán ⇒ 404 thân chung); GHI = chỉ Admin (Casbin + `require_quota_table_admin`).
 * Trang chỉ bọc thành phần phía client.
 */
import { QuotaTablesClient } from "./_components/QuotaTablesClient"

export default function QuotaTablesPage() {
  return <QuotaTablesClient />
}
