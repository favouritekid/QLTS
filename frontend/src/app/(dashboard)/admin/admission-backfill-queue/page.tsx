// src/app/(dashboard)/admin/admission-backfill-queue/page.tsx
"use client"

import { AdminBackfillQueue } from "./_components/AdminBackfillQueue"

export default function AdminBackfillQueuePage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">
          Hàng đợi sửa dữ liệu xét tuyển
        </h1>
        <p className="text-muted-foreground">
          Phase 3 Q-P3-09 — xử lý ngoại lệ phát sinh trong quá trình backfill
          dữ liệu xét tuyển từ legacy. Mỗi dòng là một hồ sơ engine không thể
          tự ánh xạ rõ ràng — quản trị viên rà soát rồi đóng với ghi chú.
        </p>
      </header>

      <AdminBackfillQueue />
    </div>
  )
}
