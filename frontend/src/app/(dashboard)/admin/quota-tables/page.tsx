// src/app/(dashboard)/admin/quota-tables/page.tsx
/**
 * /admin/quota-tables — GĐ2-F1: bảng chỉ tiêu năm / nhóm ngành (GĐ2-A). Chỉ Admin — máy chủ là chốt (Casbin +
 * `require_quota_table_admin`): không phải Admin ⇒ 403 ⇒ trang báo. Trang chỉ bọc thành phần phía client.
 */
import { QuotaTablesClient } from "./_components/QuotaTablesClient"

export default function QuotaTablesPage() {
  return <QuotaTablesClient />
}
