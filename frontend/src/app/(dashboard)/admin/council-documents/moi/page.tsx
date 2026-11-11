// src/app/(dashboard)/admin/council-documents/moi/page.tsx
import { CouncilNewSetClient } from "../_components/CouncilNewSetClient"

/**
 * Dựng văn bản Hội đồng từ danh sách chọn (đặc tả 5.1, bản 2 mục 5.1): bước 1–3 + phần dựng của bước 4. Trang RIÊNG
 * để lựa chọn giữ qua trang mà không phá chốt xoá lựa chọn của màn "Hồ sơ tuyển sinh" (nơi có Duyệt / Từ chối hàng loạt).
 * URL không mang gì; danh sách chọn chỉ ở store bộ nhớ (không persist).
 */
export default function CouncilNewSetPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Dựng văn bản Hội đồng</h1>
        <p className="text-muted-foreground">
          Chọn hồ sơ từ danh sách → kiểm tra & chốt → nhập tham số → dựng bộ Biên bản · Quyết định · Danh sách xét tuyển.
        </p>
      </header>
      <CouncilNewSetClient />
    </div>
  )
}
