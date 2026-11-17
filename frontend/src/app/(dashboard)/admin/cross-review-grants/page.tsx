// src/app/(dashboard)/admin/cross-review-grants/page.tsx
"use client"

import { CrossReviewGrantsClient } from "@/components/document-review/cross/CrossReviewGrantsClient"

/** GĐ1b — Admin cấp / thu hồi quyền duyệt chéo tạm thời (đặc tả §6). Máy chủ là chốt: không phải Admin ⇒ trang báo. */
export default function CrossReviewGrantsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Quyền duyệt chéo</h1>
        <p className="text-muted-foreground">
          Cấp theo từng cán bộ, đơn vị và thao tác; tối đa 14 ngày mỗi lần; không gia hạn — cấp lại phải có lý do.
        </p>
      </header>
      <CrossReviewGrantsClient />
    </div>
  )
}
