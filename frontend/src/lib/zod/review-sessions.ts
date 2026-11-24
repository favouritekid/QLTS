/**
 * GĐ2-B — schema của 9 API lần xét nháp (hợp đồng API GĐ2-B bản 4 `b877fba1…` §1–§4; máy chủ:
 * `Backend_FastAPI/app/schemas/admission_review.py`).
 *
 * Quy ước (thiết kế giao diện GĐ2-B §6.1, HĐ4 §1.8):
 *  - Thân REQUEST `.strict()` — máy chủ `extra = "forbid"` (khoá lạ ⇒ 422, kể cả mọi khoá kiểu "vượt chỉ tiêu").
 *  - Thân PHẢN HỒI KHÔNG `.strict()` — trường lạ bị bỏ qua (thêm trường là thay đổi "không phá").
 *  - `status`, `tab`, mã lý do / cờ / gợi ý / hành động là `z.string()` (không `z.enum`): giá trị mới (GĐ2-C thêm `locked`,
 *    `excluded`, …) không làm hỏng cả trang; giao diện tra nhãn, lạ ⇒ hiện chữ máy chủ / câu chung.
 *  - Điểm là CHUỖI đúng hai chữ số (`^\d{1,3}\.\d{2}$`, HĐ3) — giữ nguyên chuỗi, không đổi sang số; `null` giữ nguyên `null`
 *    (không đổi thành 0 — `frontend/CLAUDE.md` "Default business values").
 *  - Trường "không áp dụng" là `null`, KHÔNG bỏ khoá (HĐ4 §1.4) ⇒ `.nullable()` chứ không `.optional()`.
 */
import { z } from "zod"

// ───────────────────────────── giới hạn kỹ thuật (HĐ4 §1.6, §2 E4 / E5) ─────────────────────────────
export const LIST_PAGE_SIZE_DEFAULT = 20 // E2, E7
export const LIST_PAGE_SIZE_MAX = 100
export const ROWS_PAGE_SIZE_DEFAULT = 50 // E9
export const ROWS_PAGE_SIZE_MAX = 200
export const FLOORS_MAX_ITEMS = 500
export const CANCEL_REASON_MAX_LENGTH = 1000

/** Chuỗi điểm của PHẢN HỒI (HĐ4 §1.4, HĐ3). */
export const SCORE_TEXT_PATTERN = /^\d{1,3}\.\d{2}$/
/** Chuỗi điểm của REQUEST E4 — cùng mẫu máy chủ `_SCORE_IN_TEXT` (chữ số ASCII, tối đa 2 chữ số thập phân). */
export const FLOOR_SCORE_INPUT_PATTERN = /^[0-9]{1,3}(\.[0-9]{1,2})?$/

const id = z.number().int().positive()
const int = z.number().int()
const isoTime = z.string().min(1)
const scoreText = z.string().regex(SCORE_TEXT_PATTERN)
const countMap = z.record(z.string(), int)

/** Độ dài theo KÝ TỰ (code point) như `len()` của Python ở máy chủ — không theo đơn vị UTF-16 của JS. */
export function codePointLength(s: string): number {
  return Array.from(s).length
}

// ═══════════════════════════════════════════ request ═══════════════════════════════════════════
/** E1 — `ReviewSessionCreateIn`. */
export const reviewSessionCreateBodySchema = z
  .object({
    academic_year: int.min(2000).max(2100),
    admission_round_id: id,
  })
  .strict()
export type ReviewSessionCreateBody = z.infer<typeof reviewSessionCreateBodySchema>

/** E4 — một dòng `ReviewFloorIn` (gửi CHUỖI điểm đã chuẩn hoá dấu chấm). */
export const reviewFloorInSchema = z
  .object({
    offering_academic_info_id: id,
    floor_score: z.string().regex(FLOOR_SCORE_INPUT_PATTERN),
  })
  .strict()
export type ReviewFloorIn = z.infer<typeof reviewFloorInSchema>

/** E4 — `ReviewFloorsPutIn`: thay TOÀN BỘ; mảng rỗng = xoá hết. */
export const reviewFloorsPutBodySchema = z
  .object({
    version: id,
    floors: z.array(reviewFloorInSchema).max(FLOORS_MAX_ITEMS),
  })
  .strict()
export type ReviewFloorsPutBody = z.infer<typeof reviewFloorsPutBodySchema>

/** E5 — `ReviewSessionCancelIn`: lý do 1–1000 ký tự SAU khi cắt khoảng trắng (kiểm DẠNG; máy chủ là chốt). */
export const reviewSessionCancelBodySchema = z
  .object({
    version: id,
    reason: z.string().refine((s) => {
      const n = codePointLength(s.trim())
      return n >= 1 && n <= CANCEL_REASON_MAX_LENGTH
    }),
  })
  .strict()
export type ReviewSessionCancelBody = z.infer<typeof reviewSessionCancelBodySchema>

/** E6 — `ReviewRunCreateIn`: chỉ `kind = "evaluate"` + `session_version`; KHÔNG trường nào khác (HĐ10). */
export const reviewRunCreateBodySchema = z
  .object({
    kind: z.literal("evaluate"),
    session_version: id,
  })
  .strict()
export type ReviewRunCreateBody = z.infer<typeof reviewRunCreateBodySchema>

// ═══════════════════════════════════════════ phản hồi ═══════════════════════════════════════════
export const admissionRoundRefSchema = z.object({
  id: int,
  round_code: z.string(),
  round_name: z.string(),
})

/** `SessionOut.quota_table` = bảng chỉ tiêu năm HIỆN TẠI; `RunInputs.quota_table` = lúc chạy. */
export const quotaTableStateSchema = z.object({
  status: z.string(),
  version: int,
  quota_fingerprint: z.string(),
})

/** `FloorOut`. `annual_admission_quota`: `null` = chưa cấu hình, `0` = đóng tuyệt đối (HĐ4 §1.4). */
export const floorSchema = z.object({
  offering_academic_info_id: int,
  floor_score: scoreText,
  major_code: z.string().nullable(),
  major_name: z.string().nullable(),
  offering_type: z.string().nullable(),
  annual_admission_quota: int.nullable(),
  group_code: z.string().nullable(),
  is_deleted: z.boolean(),
  updated_by_user_id: int,
  updated_at: isoTime,
})
export type ReviewFloor = z.infer<typeof floorSchema>

/** `RunSummaryOut` — dòng của E7 / `latest_run` của E2, E3. */
export const runSummarySchema = z.object({
  id: int,
  kind: z.string(),
  status: z.string(),
  rule_version: z.string(),
  requested_by_user_id: int,
  requested_at: isoTime,
  finished_at: isoTime.nullable(),
  duration_ms: int.nullable(),
  tab_counts: countMap.nullable(),
  /** Tính LÚC GET (HĐ4 §3.3) — mọi query mang trường này không được giữ bản cũ (đính chính 2 §1). */
  config_changed_since_run: z.boolean(),
})
export type ReviewRunSummary = z.infer<typeof runSummarySchema>

/** `SessionOut` — E1, E3, E4, E5. `floors` luôn `[]` khi đã huỷ (P4). */
export const sessionSchema = z.object({
  id: int,
  academic_year: int,
  admission_round: admissionRoundRefSchema,
  seq_no: int,
  status: z.string(),
  version: int,
  created_by_user_id: int,
  created_at: isoTime,
  updated_at: isoTime,
  cancelled_by_user_id: int.nullable(),
  cancelled_at: isoTime.nullable(),
  cancel_reason: z.string().nullable(),
  quota_table: quotaTableStateSchema,
  floors: z.array(floorSchema),
  latest_run: runSummarySchema.nullable(),
  latest_done_run_id: int.nullable(),
  /** Một nguồn với cổng ghi (`session_actions`) — nút hiện theo đây, KHÔNG theo `status` / vai. */
  available_actions: z.array(z.string()),
})
export type ReviewSession = z.infer<typeof sessionSchema>

/** `SessionListItemOut` — dòng của E2. */
export const sessionListItemSchema = z.object({
  id: int,
  academic_year: int,
  admission_round: admissionRoundRefSchema,
  seq_no: int,
  status: z.string(),
  version: int,
  created_by_user_id: int,
  created_at: isoTime,
  floor_count: int,
  latest_run: runSummarySchema.nullable(),
})
export type ReviewSessionListItem = z.infer<typeof sessionListItemSchema>

/** Dạng trang chung (HĐ4 §1.6) — trừ `items`. */
const pageShape = {
  total: int,
  page: int,
  page_size: int,
  total_pages: int,
}

export const sessionPageSchema = z.object({ items: z.array(sessionListItemSchema), ...pageShape })
export type ReviewSessionPage = z.infer<typeof sessionPageSchema>

export const runFloorInputSchema = z.object({
  offering_academic_info_id: int,
  floor_score: scoreText,
})

/** `RunInputs` — BẤT BIẾN; `floors` là ảnh chụp GIÁ TRỊ (P4). */
export const runInputsSchema = z.object({
  academic_year: int,
  session_version: int,
  floors: z.array(runFloorInputSchema),
  quota_table: quotaTableStateSchema,
  fee_gate_mode: z.string(),
  snapshot_at: isoTime,
})

/** `RunSummary` (HĐ4 §3.3). */
export const runSummaryCountsSchema = z.object({
  rows_total: int,
  pool_total: int,
  tab_counts: countMap,
  reason_counts: countMap,
  flag_counts: countMap,
  warnings: z.array(z.string()),
})

export const quotaViewMajorSchema = z.object({
  offering_academic_info_id: int,
  offering_id: int.nullable(),
  major_code: z.string().nullable(),
  major_name: z.string().nullable(),
  offering_type: z.string().nullable(),
  group_id: int.nullable(),
  group_code: z.string().nullable(),
  annual_admission_quota: int.nullable(),
  floor_score: scoreText.nullable(),
  used_publish: int,
  used_approved: int,
  used: int,
  remaining: int.nullable(),
  state: z.string(),
  candidates: int,
  auto: int,
  needs_decision: int,
  offering_inactive: z.boolean(),
  major_inactive: z.boolean(),
})

export const quotaViewGroupSchema = z.object({
  group_id: int,
  code: z.string(),
  name: z.string(),
  ceiling: int,
  used_publish: int,
  used_approved: int,
  used: int,
  auto_in_run: int,
  /** Có thể ÂM — chỉ cảnh báo (QĐB:25); giao diện không tự tính lại. */
  remaining_after_auto: int,
  would_exceed: z.boolean(),
})

export const quotaViewSchema = z.object({
  majors: z.array(quotaViewMajorSchema),
  groups: z.array(quotaViewGroupSchema),
})

/** `RunOut` — E6 (202), E8. */
export const runSchema = z.object({
  id: int,
  session_id: int,
  kind: z.string(),
  status: z.string(),
  rule_version: z.string(),
  requested_by_user_id: int,
  requested_at: isoTime,
  started_at: isoTime.nullable(),
  finished_at: isoTime.nullable(),
  duration_ms: int.nullable(),
  error_code: z.string().nullable(),
  inputs: runInputsSchema,
  summary: runSummaryCountsSchema.nullable(),
  quota_view: quotaViewSchema.nullable(),
  /** Tính LÚC GET — xem `runSummarySchema`. */
  config_changed_since_run: z.boolean(),
})
export type ReviewRun = z.infer<typeof runSchema>

export const runPageSchema = z.object({ items: z.array(runSummarySchema), ...pageShape })
export type ReviewRunPage = z.infer<typeof runPageSchema>

export const documentGapsSchema = z.object({
  missing: z.array(z.string()),
  not_verified: z.array(z.string()),
})

export const consideredChoiceSchema = z.object({
  choice_id: int,
  display_order: int,
  offering_academic_info_id: int,
  offering_id: int,
  admission_path_id: int,
  major_code: z.string().nullable(),
  major_name: z.string().nullable(),
  offering_type: z.string().nullable(),
})

export const scorePartsSchema = z.object({
  subject_total: scoreText.nullable(),
  area: scoreText.nullable(),
  object: scoreText.nullable(),
  priority_total: scoreText.nullable(),
})

export const perChoiceSchema = z.object({
  choice_id: int,
  display_order: int,
  offering_academic_info_id: int.nullable(),
  status: z.string(),
  reason_codes: z.array(z.string()),
  review_total: scoreText.nullable(),
  floor_score: scoreText.nullable(),
})

/** Cờ A13 kèm năm + căn cứ (phụ lục kỹ thuật đợt 1 — trường thêm "không phá"). */
export const priorYearFindingSchema = z.object({
  year: int,
  basis: z.string(),
  status: z.string().nullable(),
})

/** `RowOut` — một em trong một lượt kiểm (E9). `full_name` / `unit_id` đọc LÚC GET; mọi trường khác bất biến. */
export const rowSchema = z.object({
  profile_id: int,
  /** `null` = hồ sơ không còn (HĐ4 §3.5). */
  full_name: z.string().nullable(),
  unit_id: int.nullable(),
  profile_status: z.string(),
  tab: z.string(),
  reason_codes: z.array(z.string()),
  flags: z.array(z.string()),
  decision_hints: z.array(z.string()),
  document_gaps: documentGapsSchema.nullable(),
  considered_choice: consideredChoiceSchema.nullable(),
  review_total: scoreText.nullable(),
  score_parts: scorePartsSchema.nullable(),
  floor_score: scoreText.nullable(),
  rank_in_major: int.nullable(),
  within_seats: z.boolean().nullable(),
  ethnic_priority_state: z.string().nullable(),
  per_choice: z.array(perChoiceSchema),
  prior_year_findings: z.array(priorYearFindingSchema),
  row_hash: z.string(),
})
export type ReviewRow = z.infer<typeof rowSchema>

/** E9 — trang dòng + `tab_counts` của CẢ lượt (không theo bộ lọc). */
export const rowPageSchema = z.object({
  items: z.array(rowSchema),
  ...pageShape,
  tab_counts: countMap,
})
export type ReviewRowPage = z.infer<typeof rowPageSchema>

// ───────────────────── đợt tuyển sinh cho hộp "Tạo lần xét" (route có sẵn `GET /api/v2/admin/years/{năm}/rounds`) ─────────────────────
/** CHỈ phần hộp thoại cần (bỏ qua trường khác). Đợt nào được chọn do MÁY CHỦ quyết (owner G1) — giao diện chỉ hiện nhãn. */
export const reviewRoundOptionSchema = z.object({
  id: id,
  round_code: z.string(),
  round_name: z.string(),
  is_active: z.boolean(),
  archived_at: z.string().nullable(),
})
export type ReviewRoundOption = z.infer<typeof reviewRoundOptionSchema>

export const reviewRoundListSchema = z.object({
  items: z.array(reviewRoundOptionSchema),
})
export type ReviewRoundList = z.infer<typeof reviewRoundListSchema>
