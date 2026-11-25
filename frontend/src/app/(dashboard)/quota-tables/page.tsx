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
 *
 * GĐ2-B F1 (đính chính §2 + đính chính 2 §3): nhận năm qua URL `?year=<năm>` — liên kết từ 409 `REVIEW_QUOTA_TABLE_MISSING` của
 * màn lần xét mở ĐÚNG năm chưa có bảng, không lùi về năm mặc định (năm có thể đã có bảng ⇒ người dùng tưởng nhầm). Chỉ nhận dạng
 * `^\d{4}$`; sai dạng / khoá lặp ⇒ năm mặc định. `searchParams` là dữ liệu lúc chạy ⇒ chờ BÊN TRONG `<Suspense>`
 * (cacheComponents của Next 16). `key` theo năm ⇒ đổi `?year=` trên URL dựng lại thành phần với năm mới.
 */
import { Suspense } from "react"

import { readYearSearchParam, type PageSearchParams } from "@/lib/utils/search-params"

import { QuotaTablesClient } from "./_components/QuotaTablesClient"

interface PageProps {
  searchParams: Promise<PageSearchParams>
}

export default function QuotaTablesPage({ searchParams }: PageProps) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Đang tải bảng chỉ tiêu…</p>}>
      <QuotaTablesFromUrl searchParams={searchParams} />
    </Suspense>
  )
}

async function QuotaTablesFromUrl({ searchParams }: PageProps) {
  const year = readYearSearchParam((await searchParams).year)
  return <QuotaTablesClient key={year ?? "nam-mac-dinh"} initialYear={year} />
}
