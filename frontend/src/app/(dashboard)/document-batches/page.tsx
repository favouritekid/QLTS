// src/app/(dashboard)/document-batches/page.tsx
"use client"

import { DocumentBatchesClient } from "@/components/document-review/bulk/DocumentBatchesClient"

/**
 * GĐ1b — "Lô duyệt giấy": tra kết quả / chạy / chốt lô duyệt giấy hàng loạt (Quản lý / Admin). Mọi nút theo cờ máy
 * chủ (`can_execute`, `can_finalize`). Mục thanh bên "Lô duyệt giấy" hiện theo cờ `bulk-verify/eligibility` (bản 6 C1, C2.1).
 */
export default function DocumentBatchesPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Lô duyệt giấy</h1>
        <p className="text-muted-foreground">
          Kết quả từng lô duyệt giấy bản giấy hàng loạt: đã ghi, lỗi, chưa xử lý, chưa rõ — theo đúng dữ liệu máy chủ.
        </p>
      </header>
      <DocumentBatchesClient endpoint={{ mode: "batch" }} />
    </div>
  )
}
