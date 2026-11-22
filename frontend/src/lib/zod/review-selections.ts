/**
 * GĐ2-C C2 — schema lựa chọn của Ban thư ký (máy chủ: `app/schemas/admission_review_selection.py`).
 *
 * Sáu loại: năm loại ca đặc biệt (ĐT3 §3) + "Vẫn giữ" cho cờ "ngành / loại hình đang ngừng" (owner C5). Thân ghi `strict` như
 * máy chủ (`extra = "forbid"`); `supersedes_id` LUÔN có mặt (`null` = hồ sơ chưa có lựa chọn) — máy chủ trả 409
 * `SELECTION_CHANGED` nếu người khác vừa đổi. Lý do (`note`) bắt buộc với "Loại khỏi lần này" / "Chờ bổ sung" (owner C6) — máy
 * chủ là chốt; giao diện chỉ khoá nút cho đỡ một lượt gửi.
 */
import { z } from "zod"

export const SELECTION_KINDS = [
  "admit_over_major_quota",
  "consider_next_choice",
  "defer_supplement",
  "admit_without_ethnic_bonus",
  "exclude_this_session",
  "keep_despite_inactive",
] as const
export const selectionKindSchema = z.enum(SELECTION_KINDS)
export type SelectionKind = z.infer<typeof selectionKindSchema>

/** Owner C6: hai loại bắt buộc lý do. */
export const SELECTION_KINDS_REASON_REQUIRED: readonly SelectionKind[] = ["exclude_this_session", "defer_supplement"]
/** Cờ "ngành / loại hình đang ngừng" của dòng kết quả GĐ2-B (QĐB:18). */
export const INACTIVE_FLAGS = ["offering_inactive", "major_inactive"] as const

export const NOTE_MAX_LENGTH = 500

export const selectionPutBodySchema = z
  .object({
    kind: selectionKindSchema,
    based_on_row_hash: z.string().regex(/^[0-9a-f]{64}$/),
    supersedes_id: z.number().int().positive().nullable(),
    note: z.string().max(NOTE_MAX_LENGTH).nullable().optional(),
  })
  .strict()
export type SelectionPutBody = z.infer<typeof selectionPutBodySchema>

export const selectionSchema = z.object({
  id: z.number().int().positive(),
  session_id: z.number().int().positive(),
  profile_id: z.number().int().positive(),
  kind: selectionKindSchema,
  choice_id: z.number().int().nullable(),
  based_on_run_id: z.number().int().positive(),
  based_on_row_hash: z.string(),
  decided_by_user_id: z.number().int().positive(),
  decided_by_username: z.string().nullable(),
  decided_by_full_name: z.string().nullable(),
  decided_at: z.string().min(1),
  note: z.string().nullable(),
  supersedes_id: z.number().int().positive().nullable(),
  /** Máy chủ tính: dòng hiện tại không còn hồ sơ này hoặc mã băm đã lệch ⇒ lựa chọn đã CŨ. */
  is_stale: z.boolean(),
})
export type Selection = z.infer<typeof selectionSchema>

export const selectionListSchema = z.object({
  session_id: z.number().int().positive(),
  latest_run_id: z.number().int().positive().nullable(),
  items: z.array(selectionSchema),
})
export type SelectionList = z.infer<typeof selectionListSchema>

export const selectionHistorySchema = z.object({
  session_id: z.number().int().positive(),
  profile_id: z.number().int().positive(),
  effective_selection_id: z.number().int().positive().nullable(),
  items: z.array(selectionSchema),
})
export type SelectionHistory = z.infer<typeof selectionHistorySchema>

/**
 * Phần của MỘT dòng kết quả lần xét mà ô chọn cần (dòng do route kết quả của GĐ2-B trả — lát L4, chưa có). `applicable_kinds`
 * là danh sách loại MÁY CHỦ cho phép với dòng (`admission_review_selection_service.applicable_selection_kinds`) — giao diện không
 * tự suy.
 */
export interface SelectionRowInput {
  profile_id: number
  row_hash: string
  flags: readonly string[]
  applicable_kinds: readonly SelectionKind[]
}
