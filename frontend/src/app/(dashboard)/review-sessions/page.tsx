// src/app/(dashboard)/review-sessions/page.tsx
/**
 * /review-sessions — GĐ2-B: lần xét nháp (thiết kế giao diện GĐ2-B, M1). Đường NGOÀI `/admin/*` (KT-5 / R4): GĐ2-C mở màn này
 * cho Ban thư ký, mà `proxy.ts` đẩy cán bộ khỏi `/admin/*` trước khi trang chạy. Ai xem / làm được gì do MÁY CHỦ quyết (GĐ2-B:
 * chỉ Admin); trang không kiểm vai.
 *
 * Bộ khung F0 — danh sách + tạo lần xét đến ở F1.
 */
import { REVIEW_DRAFT_NOTE } from "@/lib/review-sessions/messages"

export default function ReviewSessionsPage() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">Lần xét tuyển</h1>
      <p className="text-sm text-muted-foreground">{REVIEW_DRAFT_NOTE}</p>
    </div>
  )
}
