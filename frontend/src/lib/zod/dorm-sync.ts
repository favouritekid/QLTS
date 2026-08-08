/**
 * Zod schemas cho màn đồng bộ ký túc xá.
 *
 * Mirrors `Backend_FastAPI/app/schemas/dorm_sync.py` và payload công khai của
 * `DormSyncOperationBlockedError` (`app/utils/exceptions.py`).
 *
 * 🔴 `.strict()` ở MỌI schema. Backend khai `ConfigDict(extra="forbid")` cho
 * cùng những hình dạng này; để frontend nhận thêm trường lạ là mở lại đúng
 * khoảng lệch mà bên kia vừa đóng — và nó sẽ lệch âm thầm, vì một trường thừa
 * không làm gì hỏng cho tới lúc ai đó đọc nhầm nó.
 */
import { z } from "zod"

// =============================================================================
// BỐI CẢNH
// =============================================================================

export const dormSyncContextSchema = z
  .object({
    open_academic_years: z.array(z.number().int()),
    /**
     * ⚠️ `null` là câu trả lời HỢP LỆ: hệ KTX chưa mở năm nào. Giao diện phải
     * xử ca đó chứ KHÔNG tự điền năm hiện tại — điền đại một năm là dựng sẵn
     * một lượt ghi vào năm không tồn tại bên đích.
     */
    default_academic_year: z.number().int().nullable(),
  })
  .strict()

export type DormSyncContext = z.infer<typeof dormSyncContextSchema>

// =============================================================================
// XEM TRƯỚC
// =============================================================================

export const dormSyncWarningSchema = z
  .object({
    qlts_profile_id: z.number().int(),
    full_name: z.string(),
    building_name: z.string(),
    room_code: z.string(),
    bed_no: z.number().int(),
    status: z.string(),
  })
  .strict()

export type DormSyncWarning = z.infer<typeof dormSyncWarningSchema>

export const dormSyncSourceCountsSchema = z
  .object({
    khong_ro_gioi_tinh: z.number().int(),
    chua_chot_nganh: z.number().int(),
    chua_ro_trinh_do: z.number().int(),
    ho_so_dang_xet: z.number().int(),
    khong_co_so_lien_he: z.number().int(),
    co_so_phu: z.number().int(),
    so_bi_bo_vi_qua_dai: z.number().int(),
  })
  .strict()

export type DormSyncSourceCounts = z.infer<typeof dormSyncSourceCountsSchema>

export const dormSyncPreviewSchema = z
  .object({
    academic_year: z.number().int(),
    source_count: z.number().int(),
    /**
     * 🔴 Nút Ghi bám vào ĐÂY, không tự suy từ `source_count > 0`. Backend còn
     * chặn vì những lý do frontend không thấy (năm đã đóng sổ, cấu hình
     * thiếu), và suy lại là dựng một định nghĩa thứ hai.
     */
    can_apply: z.boolean(),
    blocked_reason: z.string().nullable(),
    counts: dormSyncSourceCountsSchema.nullable(),
    warnings: z.array(dormSyncWarningSchema),
    source_hash: z.string().nullable(),
    target_fingerprint: z.string().nullable(),
    snapshot_hash: z.string().nullable(),
    snapshot_version: z.number().int().nullable(),
    /** Vé để bấm Ghi. `null` khi chưa ghi được. KHÔNG giải mã nó ở client. */
    preview_token: z.string().nullable(),
    /** Epoch giây. Dùng TRỰC TIẾP, không đọc `exp` bên trong token. */
    expires_at: z.number().int().nullable(),
  })
  .strict()

export type DormSyncPreview = z.infer<typeof dormSyncPreviewSchema>

// =============================================================================
// GHI
// =============================================================================

export const DORM_SYNC_OUTCOMES = [
  "completed",
  "failed",
  "outcome_unknown",
] as const

export const dormSyncApplySchema = z
  .object({
    operation_id: z.string(),
    academic_year: z.number().int(),
    /** Giao diện rẽ nhánh theo ĐÂY, không theo `message`. */
    outcome: z.enum(DORM_SYNC_OUTCOMES),
    message: z.string(),
    ktx_run_id: z.number().int().nullable(),
    upserted: z.number().int(),
    blocked: z.number().int(),
    deactivated: z.number().int(),
    /**
     * `false` = hệ KTX ĐÃ đổi nhưng sổ đối soát không ghi lại được. Việc đã
     * xảy ra; chỉ nhật ký là thiếu. Tuyệt đối không mời bấm lại ở ca này.
     */
    ledger_saved: z.boolean(),
  })
  .strict()

export type DormSyncApplyResult = z.infer<typeof dormSyncApplySchema>

// =============================================================================
// LỖI CHẶN — payload máy đọc được
// =============================================================================

export const DORM_SYNC_BLOCKED_CODE = "DORM_SYNC_OPERATION_BLOCKED"

export const DORM_SYNC_NEXT_ACTIONS = [
  "wait",
  "preview_again",
  "manual_reconcile",
] as const

export type DormSyncNextAction = (typeof DORM_SYNC_NEXT_ACTIONS)[number]

/**
 * 🔴 Giao diện tin `next_action`, KHÔNG suy từ `operation_status`, không suy
 * từ mã HTTP 409, và tuyệt đối không đọc câu `detail`.
 *
 * `handleApiError` cố ý CHE `detail` của mã `CONFLICT` vì mã đó dùng chung cho
 * nhiều thứ, trong đó có chuỗi nội bộ tiếng Anh. Nếu ta suy trạng thái từ câu
 * chữ thì (a) vi phạm thin-client, (b) vỡ ngay lần backend sửa chính tả, và
 * (c) ca đắt nhất — `manual_reconcile` — sẽ bị đối xử như một lỗi tạm thời.
 */
export const dormSyncBlockedSchema = z
  .object({
    detail: z.string(),
    error_code: z.literal(DORM_SYNC_BLOCKED_CODE),
    operation_status: z.enum(["running", "failed", "outcome_unknown"]),
    next_action: z.enum(DORM_SYNC_NEXT_ACTIONS),
  })
  .strict()

export type DormSyncBlocked = z.infer<typeof dormSyncBlockedSchema>

// =============================================================================
// REQUEST
// =============================================================================

export const dormSyncPreviewRequestSchema = z
  .object({ academic_year: z.number().int().min(2000).max(2100) })
  .strict()

/**
 * ⚠️ ĐÚNG một trường. Backend khai `extra="forbid"`, nên gửi kèm
 * `academic_year` hay `operation_id` sẽ nhận 422 — và đó là chủ ý: năm học và
 * `operation_id` đã nằm trong phiếu do server ký.
 */
export const dormSyncApplyRequestSchema = z
  .object({ preview_token: z.string().min(1) })
  .strict()
