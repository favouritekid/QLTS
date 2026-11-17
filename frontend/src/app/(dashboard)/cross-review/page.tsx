// src/app/(dashboard)/cross-review/page.tsx
"use client"

import { CrossReviewClient } from "@/components/document-review/cross/CrossReviewClient"

/**
 * GĐ1b — "Duyệt chéo": hàng đợi giấy bản giấy cán bộ được cấp quyền duyệt / từ chối tạm thời. Hiện theo
 * `eligibility` của máy chủ. Trang ĐỨNG RIÊNG — mục thanh bên (cờ `cross-review` trong `useServerFlagNavigation`) chờ
 * biên bản V4 vì sửa khung chung.
 */
export default function CrossReviewPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Duyệt chéo giấy</h1>
        <p className="text-muted-foreground">
          Duyệt / từ chối giấy bản giấy của đơn vị khác trong thời hạn được cấp. Không có Đặt lại.
        </p>
      </header>
      <CrossReviewClient />
    </div>
  )
}
