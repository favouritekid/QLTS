// src/app/(dashboard)/admin/council-documents/page.tsx
"use client"

import { CouncilDocumentsClient } from "./_components/CouncilDocumentsClient"

/**
 * Văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1): kho mẫu, bộ văn bản dựng từ
 * danh sách mã hồ sơ, nhật ký. Mọi nút / thẻ ẩn hiện theo cờ quyền của máy chủ
 * (`GET /api/admission-config/council-documents/quyen`).
 */
export default function CouncilDocumentsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Văn bản Hội đồng tuyển sinh</h1>
        <p className="text-muted-foreground">
          Dựng bộ Biên bản · Quyết định · Danh sách xét tuyển từ danh sách mã hồ sơ đã chọn sẵn; tải lại đúng
          tệp đã lưu.
        </p>
      </header>
      <CouncilDocumentsClient />
    </div>
  )
}
