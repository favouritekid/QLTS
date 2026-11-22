// src/app/(dashboard)/admin/review-secretaries/page.tsx
"use client"

import { ReviewSecretariesClient } from "./_components/ReviewSecretariesClient"

/**
 * /admin/review-secretaries — GĐ2-C C1: Admin gán / thu hồi quyền "Thư ký Hội đồng". Chỉ Admin — máy chủ là chốt (Casbin +
 * `require_review_secretary_admin`): không phải Admin ⇒ 403 ⇒ trang báo.
 */
export default function ReviewSecretariesPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Thư ký Hội đồng</h1>
        <p className="text-muted-foreground">
          Gán theo từng người (Quản lý hoặc Cán bộ), lý do bắt buộc. Quyền không hết hạn: chỉ hết khi Admin thu hồi, hoặc tự
          thu hồi khi tài khoản bị khoá hay đổi sang vai khác. Thư ký xem hồ sơ toàn trường trong lần xét.
        </p>
      </header>
      <ReviewSecretariesClient />
    </div>
  )
}
