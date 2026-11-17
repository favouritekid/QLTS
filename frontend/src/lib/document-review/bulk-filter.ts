/**
 * Bản 6 C2.2 / đặc tả §5.9 — "Duyệt giấy theo bộ lọc hiện tại": chuyển ĐÚNG bộ lọc đang áp của danh sách `/admissions`
 * (`AdmissionListParams` = tham số của `GET /api/admissions`) thành `BulkVerifyFilter` của bước xem trước.
 *
 *  - Chỉ CHÉP các khoá lọc (cùng tên, cùng kiểu với tham số danh sách — máy chủ dùng lại ĐÚNG hàm lọc của danh sách).
 *  - Bỏ phân trang / sắp xếp (`page`, `page_size`, `sort_by`, `order`): máy chủ chọn MỌI hồ sơ khớp bộ lọc, không theo
 *    trang đang xem. KHÔNG bao giờ mang `profile_ids` của trang.
 *  - Giá trị lạ (vd `payment_status` ngoài enum) ⇒ `null` (không gửi) — KHÔNG bỏ bớt khoá, vì bỏ một khoá lọc là MỞ RỘNG
 *    tập hồ sơ so với danh sách người dùng đang xem.
 */
import type { AdmissionListParams } from "@/lib/zod/admissions"
import { bulkVerifyFilterSchema, type BulkVerifyFilter } from "@/lib/zod/document-review"

export function toBulkVerifyFilter(params: AdmissionListParams): BulkVerifyFilter | null {
  const f: Record<string, string | number | boolean> = {}
  if (params.status) f.status = params.status
  if (params.search) f.search = params.search
  if (params.major_id) f.major_id = params.major_id
  if (params.academic_year !== undefined) f.academic_year = params.academic_year
  if (params.degree_level) f.degree_level = params.degree_level
  if (params.payment_status) f.payment_status = params.payment_status
  if (params.date_from) f.date_from = params.date_from
  if (params.date_to) f.date_to = params.date_to
  if (params.assigned_officer_id) f.assigned_officer_id = params.assigned_officer_id
  if (params.unit_id !== undefined) f.unit_id = params.unit_id
  if (params.assigned_reviewer_id) f.assigned_reviewer_id = params.assigned_reviewer_id
  if (params.unassigned) f.unassigned = true
  const r = bulkVerifyFilterSchema.safeParse(f)
  return r.success ? r.data : null
}
