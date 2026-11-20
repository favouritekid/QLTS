/**
 * GĐ2-A / GĐ2-F1 — bảng chỉ tiêu năm / nhóm ngành (`/api/admission-config/quota-tables/{năm}`).
 *
 * Mirror `Backend_FastAPI/app/schemas/admission_quota_table.py` (`QuotaTableOut`, `QuotaTablePut`, `QuotaTableLockIn`,
 * `QuotaTableUnlockIn`). Không trường nào mang dữ liệu cá nhân.
 *
 * Lệch CHỦ Ý so với Pydantic ở thân PUT: `ceiling` / `annual_admission_quota` nhận `null` — ô TRỐNG đi tới máy chủ đúng là
 * "trống" (máy chủ trả 422 vì schema bắt buộc số ≥ 0), KHÔNG BAO GIỜ bị đổi thành 0 ở giao diện (quyết định owner 19-11
 * câu 4: trống ≠ 0; 0 chỉ khi nhập rõ).
 */
import { z } from "zod"

export const QUOTA_TABLE_ACTIONS = ["edit", "lock", "unlock"] as const
export type QuotaTableAction = (typeof QUOTA_TABLE_ACTIONS)[number]

export const groupUsageSchema = z
  .object({
    publish_count: z.number().int(),
    approved_count: z.number().int(),
    used: z.number().int(),
  })
  .strict()

export const quotaGroupMemberOutSchema = z
  .object({
    offering_academic_info_id: z.number().int(),
    offering_id: z.number().int(),
    major_code: z.string().nullable(),
    major_name: z.string().nullable(),
    offering_type: z.string().nullable(),
    /** `null` = ngành CHƯA có chỉ tiêu năm (≠ 0). */
    annual_admission_quota: z.number().int().nullable(),
  })
  .strict()

export const quotaGroupOutSchema = z
  .object({
    id: z.number().int(),
    code: z.string(),
    name: z.string(),
    ceiling: z.number().int(),
    usage: groupUsageSchema,
    members: z.array(quotaGroupMemberOutSchema),
  })
  .strict()

/**
 * Codex lượt 3 (rà độc lập) — một học vụ của năm (MỌI dòng của năm, kể cả đã xoá mềm), đọc CÙNG lần với `quota_fingerprint`
 * (`read_quota_snapshot` ở máy chủ). Là nguồn DUY NHẤT của danh sách "thêm ngành" + giá trị điền sẵn trong trình soạn — không
 * lấy từ bộ đệm danh mục học vụ (`["academic-infos"]`, có thể cũ hơn dấu ⇒ điền chỉ tiêu cũ rồi lưu với dấu mới ⇒ ghi đè im lặng).
 */
export const quotaYearAcademicInfoSchema = z
  .object({
    offering_academic_info_id: z.number().int(),
    offering_id: z.number().int(),
    major_code: z.string().nullable(),
    major_name: z.string().nullable(),
    offering_type: z.string().nullable(),
    /** `null` = ngành CHƯA có chỉ tiêu năm (≠ 0). */
    annual_admission_quota: z.number().int().nullable(),
    is_deleted: z.boolean(),
  })
  .strict()

export type QuotaYearAcademicInfo = z.infer<typeof quotaYearAcademicInfoSchema>

/** Thân 404 (năm chưa có bảng): danh sách học vụ đọc cùng lần với dấu. Thiếu / sai dạng ⇒ `[]` (không thêm được ngành — không
 * rơi về nguồn khác). */
export function parseYearAcademicInfos(raw: unknown): QuotaYearAcademicInfo[] {
  const r = z.array(quotaYearAcademicInfoSchema).safeParse(raw)
  return r.success ? r.data : []
}

export const quotaTableOutSchema = z
  .object({
    academic_year: z.number().int(),
    status: z.string(),
    version: z.number().int(),
    locked_by_user_id: z.number().int().nullable(),
    locked_at: z.string().nullable(),
    /** Thao tác người xem làm được — CÙNG hàm với cổng ghi (`quota_table_actions`). Giao diện hiện nút theo cờ này. */
    available_actions: z.array(z.enum(QUOTA_TABLE_ACTIONS)),
    /** GĐ2-F1 — dấu chỉ tiêu ngành của năm (mọi học vụ của năm). Gửi lại NGUYÊN VĂN dấu lúc mở khi PUT / khoá. */
    quota_fingerprint: z.string(),
    groups: z.array(quotaGroupOutSchema),
    /** Codex lượt 3 — học vụ của năm CÙNG ảnh với `quota_fingerprint` (danh sách chọn + giá trị điền sẵn của trình soạn). */
    academic_infos: z.array(quotaYearAcademicInfoSchema),
  })
  .strict()

export type QuotaGroupMemberOut = z.infer<typeof quotaGroupMemberOutSchema>
export type QuotaGroupOut = z.infer<typeof quotaGroupOutSchema>
export type QuotaTableOut = z.infer<typeof quotaTableOutSchema>

export const quotaGroupMemberInSchema = z
  .object({
    offering_academic_info_id: z.number().int().positive(),
    annual_admission_quota: z.number().nullable(),
  })
  .strict()

export const quotaGroupInSchema = z
  .object({
    code: z.string(),
    name: z.string(),
    ceiling: z.number().nullable(),
    members: z.array(quotaGroupMemberInSchema),
  })
  .strict()

export const quotaTablePutSchema = z
  .object({
    /** Phiên bản bảng đang xem; 0 = năm chưa có bảng (tạo mới). */
    version: z.number().int().min(0),
    /** GĐ2-F1 — dấu chỉ tiêu lúc mở (GET; năm chưa có bảng: trong thân 404). Lệch ⇒ 409 `quota_table_stale`. */
    quota_fingerprint: z.string(),
    groups: z.array(quotaGroupInSchema),
  })
  .strict()

export const quotaTableLockSchema = z
  .object({ version: z.number().int().min(1), quota_fingerprint: z.string() })
  .strict()

export const quotaTableUnlockSchema = z
  .object({
    version: z.number().int().min(1),
    /** Bắt buộc, khác rỗng sau khi bỏ khoảng trắng hai đầu (máy chủ kiểm lại — 422). */
    reason: z.string().trim().min(1).max(1000),
  })
  .strict()

export type QuotaTablePut = z.infer<typeof quotaTablePutSchema>
export type QuotaTableLock = z.infer<typeof quotaTableLockSchema>
export type QuotaTableUnlock = z.infer<typeof quotaTableUnlockSchema>
