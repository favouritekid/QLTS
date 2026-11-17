/**
 * GĐ1b — duyệt giấy nhanh + duyệt chéo tạm thời: Zod cho MỌI phản hồi / thân yêu cầu GĐ1b.
 *
 * Nguồn: hợp đồng API bản 4 (sha256 `45b718f6…adad`) §1, §2.1–§2.3; đặc tả bản 3.6 (sha256 `9ef02da2…4e2e`) §4.7, §5, §6.
 * Tên trường tiếng Anh (quy ước owner 17-11). Không dữ liệu cá nhân: phản hồi lô / hàng đợi chéo chỉ mang id.
 *
 * ⚠️ `documents_checklist[]` (hợp đồng bản 5 B1): khoá `document_row_id` + `row_version` LUÔN có (không `.optional()`);
 * giá trị `null` ⇔ giấy chưa có dòng `profile_document`, khi đó mọi cờ thao tác `false`. Kiểm chéo: cờ thao tác bật mà
 * định danh `null` ⇒ parse ĐỎ (không im lặng). Mọi phản hồi GĐ1b khác (lô, lịch sử, hàng đợi chéo) khai hai trường là số
 * bắt buộc. Thao tác GĐ1b chỉ dựng trên giấy đã có định danh (`asActionable`).
 */
import { z } from "zod"

// ═══════════════════════ Định danh + cờ máy chủ theo giấy (§4.7) ═══════════════════════

/** `profile_document.id` — mọi giấy, kể cả giấy bản giấy không có tệp. */
export const documentRowIdSchema = z.number().int().positive()
/** Phiên bản dòng giấy — gửi lại thành `expected_row_version`. Trigger CSDL bắt đầu từ 1. */
export const rowVersionSchema = z.number().int().min(1)

/** Hình thức đã xác nhận (máy chủ `VERIFIED_FORMATS`). */
export const VERIFIED_FORMATS = ["original", "certified_copy", "photo"] as const
export const verifiedFormatSchema = z.enum(VERIFIED_FORMATS)
export type VerifiedFormat = z.infer<typeof verifiedFormatSchema>

/** Trạng thái dòng giấy (CHECK `profile_document.status`). */
export const DOCUMENT_ROW_STATUSES = ["missing", "uploaded", "verified", "rejected", "paper_submitted"] as const

/**
 * Một giấy trong `documents_checklist[]` của phản hồi hồ sơ — phần GĐ1b cần để dựng nút / hộp thoại.
 * Cờ do máy chủ tính bằng ĐÚNG `document_review_rules.decide` mà cổng ghi dùng dưới khoá (thin client).
 */
export const gd1bDocumentSchema = z
  .object({
  code: z.string().min(1),
  label: z.string(),
  status: z.enum(DOCUMENT_ROW_STATUSES),
  is_extra: z.boolean().optional(),
  /** id để TẢI tệp — chỉ có khi có tệp (giữ nghĩa cũ, không dùng cho lô / lịch sử). */
  document_id: z.number().int().positive().nullable().optional(),
  actual_submission_format: z.string().nullable().optional(),
  verified_format: verifiedFormatSchema.nullable().optional(),
  // ── GĐ1b §4.7 + bản 5 B1 — khoá bắt buộc; null ⇔ giấy chưa có dòng ──
  document_row_id: documentRowIdSchema.nullable(),
  row_version: rowVersionSchema.nullable(),
  can_verify: z.boolean(),
  can_reject: z.boolean(),
  can_reset: z.boolean(),
  can_view_history: z.boolean(),
  /** own_submission | unknown_submitter | missing_format | outside_config | not_pending | not_permitted | … (mã lạ ⇒ hiện câu chung) */
  verify_block_reason: z.string().nullable(),
  requires_ack: z.boolean(),
  reset_requires_reason: z.boolean(),
  reset_keeps_evidence: z.boolean(),
  })
  .superRefine((d, ctx) => {
    if ((d.document_row_id === null) !== (d.row_version === null)) {
      ctx.addIssue({
        code: "custom",
        path: ["row_version"],
        message: "document_row_id và row_version phải cùng có hoặc cùng null",
      })
    }
    const coDinhDanh = d.document_row_id !== null && d.row_version !== null
    if (!coDinhDanh && (d.can_verify || d.can_reject || d.can_reset || d.can_view_history)) {
      ctx.addIssue({
        code: "custom",
        path: ["document_row_id"],
        message: "Cờ thao tác bật mà giấy chưa có định danh dòng (bản 5 B1)",
      })
    }
  })
export type Gd1bDocument = z.infer<typeof gd1bDocumentSchema>

/** Giấy ĐÃ có dòng — mọi thao tác GĐ1b cần `document_row_id` + `row_version` là số. */
export type Gd1bActionableDocument = Gd1bDocument & { document_row_id: number; row_version: number }

/** Giấy chưa có dòng (định danh null — mọi cờ thao tác đã được kiểm là `false`) ⇒ `null`: không dựng thao tác nào. */
export function asActionable(doc: Gd1bDocument): Gd1bActionableDocument | null {
  if (doc.document_row_id === null || doc.row_version === null) return null
  return { ...doc, document_row_id: doc.document_row_id, row_version: doc.row_version }
}

// ═══════════════════════ Nút lẻ (§1) ═══════════════════════

const reasonSchema = z.string().trim().min(1).max(500)

/** `PATCH …/{profile_id}/documents/{doc_code}/verify-format` (`DocumentFormatVerifyRequest`). */
export const verifyDocumentBodySchema = z
  .object({
    format: verifiedFormatSchema,
    expected_row_version: rowVersionSchema,
    /** bắt buộc khi `unknown_submitter_ack` (máy chủ kiểm) */
    reason: reasonSchema.optional(),
    unknown_submitter_ack: z.boolean(),
  })
  .strict()
export type VerifyDocumentBody = z.infer<typeof verifyDocumentBodySchema>

/** `POST …/reject` (`DocumentRejectRequest`) — lý do bắt buộc. */
export const rejectDocumentBodySchema = z
  .object({
    reason: reasonSchema,
    expected_row_version: rowVersionSchema,
    unknown_submitter_ack: z.boolean(),
  })
  .strict()
export type RejectDocumentBody = z.infer<typeof rejectDocumentBodySchema>

/** `POST …/reset` (`DocumentResetRequest`) — lý do BẮT BUỘC (thiếu ⇒ 422). */
export const resetDocumentBodySchema = z
  .object({
    reason: reasonSchema,
    expected_row_version: rowVersionSchema,
    unknown_submitter_ack: z.boolean(),
  })
  .strict()
export type ResetDocumentBody = z.infer<typeof resetDocumentBodySchema>

/** Phản hồi `reject` (dict của `reject_document`). */
export const rejectDocumentResponseSchema = z.object({
  code: z.string(),
  status: z.string(),
  rejection_reason: z.string().nullable(),
  rejected_at: z.string().nullable(),
  rejected_by_id: z.number().int(),
  document_row_id: documentRowIdSchema,
  row_version: rowVersionSchema,
})
export type RejectDocumentResponse = z.infer<typeof rejectDocumentResponseSchema>

/** Phản hồi `verify-format` / `reset` = cả hồ sơ — GĐ1b chỉ cần biết đó là MỘT hồ sơ (`id`), rồi làm mới chi tiết. */
export const profileAckSchema = z.looseObject({ id: z.number().int().positive() })
export type ProfileAck = z.infer<typeof profileAckSchema>

// ═══════════════════════ Lịch sử giấy K2 (§1) ═══════════════════════

export const documentHistoryEntrySchema = z.object({
  id: z.number().int(),
  action: z.string(),
  at: z.string().min(1),
  actor_user_id: z.number().int().nullable(),
  actor_name: z.string().nullable(),
  old_status: z.string().nullable(),
  new_status: z.string().nullable(),
  via: z.string().nullable(),
  batch_id: z.string().nullable(),
  grant_id: z.number().int().nullable(),
  reason: z.string().nullable(),
  declared_format: z.string().nullable(),
  verified_format: z.string().nullable(),
  unknown_submitter_ack: z.boolean().nullable(),
  file_sha256: z.string().nullable(),
})
export type DocumentHistoryEntry = z.infer<typeof documentHistoryEntrySchema>

export const documentEvidenceEntrySchema = z.object({
  id: z.number().int().positive(),
  verification_audit_id: z.number().int(),
  verified_at: z.string().min(1),
  verified_by_user_id: z.number().int().nullable(),
  sha256: z.string().nullable(),
  file_missing: z.boolean(),
})
export type DocumentEvidenceEntry = z.infer<typeof documentEvidenceEntrySchema>

export const documentHistorySchema = z.object({
  document_row_id: documentRowIdSchema,
  document_type_code: z.string().nullable(),
  status: z.string(),
  row_version: rowVersionSchema,
  entries: z.array(documentHistoryEntrySchema),
  evidence_files: z.array(documentEvidenceEntrySchema),
})
export type DocumentHistory = z.infer<typeof documentHistorySchema>

// ═══════════════════════ Lô duyệt giấy (§2.1) ═══════════════════════

/**
 * `BulkVerifyFilter` = các tham số lọc của `GET /api/admissions` (cùng kiểu với `AdmissionListParams`: danh sách
 * nhiều giá trị là chuỗi ngăn cách bằng dấu phẩy). Máy chủ dùng lại ĐÚNG hàm lọc của danh sách, giao với tập chờ xét,
 * rồi áp phạm vi Quản lý — giao diện KHÔNG tự lọc.
 */
export const PAYMENT_STATUS_FILTERS = ["paid", "unpaid", "partial", "no_fee", "overdue"] as const
/** Khớp `BulkVerifyFilter` (`app/schemas/document_bulk.py`, `extra="forbid"`; bản 5 B2): ngày giờ ISO, `payment_status` enum. */
export const bulkVerifyFilterSchema = z
  .object({
    status: z.string().max(500).optional(),
    search: z.string().max(200).optional(),
    major_id: z.string().max(2000).optional(),
    academic_year: z.number().int().min(1900).max(2999).optional(),
    degree_level: z.string().max(100).optional(),
    payment_status: z.enum(PAYMENT_STATUS_FILTERS).optional(),
    date_from: z.string().optional(),
    date_to: z.string().optional(),
    assigned_officer_id: z.string().max(2000).optional(),
    unit_id: z.number().int().positive().optional(),
    assigned_reviewer_id: z.string().max(2000).optional(),
    unassigned: z.boolean().optional(),
  })
  .strict()
export type BulkVerifyFilter = z.infer<typeof bulkVerifyFilterSchema>

/**
 * Thân `POST …/bulk-verify/preview` — ĐÚNG MỘT trong `profile_ids` / `filter`. Trần 100 hồ sơ / N giấy do MÁY CHỦ
 * giữ (422 kèm số đếm) — giao diện không tự cắt, không tự chặn trước.
 */
export const bulkVerifyPreviewBodySchema = z
  .object({
    profile_ids: z.array(z.number().int().positive()).min(1).optional(),
    filter: bulkVerifyFilterSchema.optional(),
    include_optional: z.boolean(),
  })
  .strict()
  .refine((b) => (b.profile_ids === undefined) !== (b.filter === undefined), {
    message: "Cần đúng một trong hai: danh sách hồ sơ hoặc bộ lọc",
  })
export type BulkVerifyPreviewBody = z.infer<typeof bulkVerifyPreviewBodySchema>

/** Lô chéo (bản 5 B3): CHỈ `profile_ids` (từ hàng đợi chéo) + `grant_id` (= `grant_id_by_action.verify`) — KHÔNG `filter`. */
export const crossBulkVerifyPreviewBodySchema = z
  .object({
    profile_ids: z.array(z.number().int().positive()).min(1),
    include_optional: z.boolean(),
    grant_id: z.number().int().positive(),
  })
  .strict()
export type CrossBulkVerifyPreviewBody = z.infer<typeof crossBulkVerifyPreviewBodySchema>

const countSchema = z.number().int().min(0)
const batchIdSchema = z.uuid()

export const bulkPreviewSchema = z.object({
  batch_id: batchIdSchema,
  expires_at: z.string().min(1),
  counts: z.object({
    profiles: countSchema,
    documents: countSchema,
    required: countSchema,
    optional: countSchema,
  }),
  items: z.array(
    z.object({
      profile_id: z.number().int().positive(),
      document_row_id: documentRowIdSchema,
      document_type_code: z.string().nullable(),
      expected_row_version: rowVersionSchema,
      is_mandatory: z.boolean(),
    }),
  ),
  excluded: z.array(
    z.object({
      profile_id: z.number().int().positive(),
      document_row_id: documentRowIdSchema,
      document_type_code: z.string().nullable(),
      reason_code: z.string(),
    }),
  ),
})
export type BulkPreview = z.infer<typeof bulkPreviewSchema>

/** `status` của một lô theo §5.6 (máy chủ suy từ dòng lô + khoá tư vấn — giao diện KHÔNG suy lại). */
export const BATCH_STATUSES = [
  "not_started",
  "starting",
  "expired",
  "running",
  "unknown",
  "interrupted_unfinalized",
  "completed",
  "stopped",
  "interrupted",
] as const
export const batchStatusSchema = z.enum(BATCH_STATUSES)
export type BatchStatus = z.infer<typeof batchStatusSchema>

export const BATCH_ITEM_RESULTS = ["recorded", "error", "not_processed", "pending"] as const
export const batchItemResultSchema = z.enum(BATCH_ITEM_RESULTS)
export type BatchItemResult = z.infer<typeof batchItemResultSchema>

export const batchCountsSchema = z.object({
  profiles: countSchema,
  recorded: countSchema,
  error: countSchema,
  not_processed: countSchema,
  pending: countSchema,
})
export type BatchCounts = z.infer<typeof batchCountsSchema>

export const batchViewSchema = z.object({
  batch_id: batchIdSchema,
  status: batchStatusSchema,
  created_at: z.string().min(1),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  finalized_at: z.string().nullable(),
  finalized_by_user_id: z.number().int().nullable(),
  finalize_reason: z.string().nullable(),
  counts: batchCountsSchema,
  items: z.array(
    z.object({
      profile_id: z.number().int().positive(),
      document_row_id: documentRowIdSchema,
      document_type_code: z.string().nullable(),
      result: batchItemResultSchema,
      reason_code: z.string().nullable(),
      message: z.string().nullable(),
    }),
  ),
  /** người tạo + `not_started` — nút "Chạy lô này" CHỈ theo cờ này */
  can_execute: z.boolean(),
  /** người tạo / Admin + `interrupted_unfinalized` — nút "Chốt lô" CHỈ theo cờ này */
  can_finalize: z.boolean(),
  /** bản 5 B4: Admin khác người tạo và `can_finalize` ⇒ ô lý do chốt BẮT BUỘC (không suy theo vai) */
  finalize_requires_reason: z.boolean(),
})
export type BatchView = z.infer<typeof batchViewSchema>

/** Thân `execute` — câu xác nhận người bấm đã đọc (máy chủ lưu nguyên văn). */
export const executeBatchBodySchema = z
  .object({ confirmation_text: z.string().min(1).max(200) })
  .strict()
export type ExecuteBatchBody = z.infer<typeof executeBatchBodySchema>

/** Thân `finalize` — lý do BẮT BUỘC khi người gọi là Admin khác người tạo (máy chủ quyết: thiếu ⇒ 422). */
export const finalizeBatchBodySchema = z
  .object({ reason: z.string().trim().min(1).max(500).optional() })
  .strict()
export type FinalizeBatchBody = z.infer<typeof finalizeBatchBodySchema>

export const finalizeBatchResponseSchema = z.object({
  batch: batchViewSchema,
  finalized_now: z.boolean(),
})
export type FinalizeBatchResponse = z.infer<typeof finalizeBatchResponseSchema>

/** Một dòng "lô của tôi" — KHÔNG id hồ sơ / giấy / tên. */
export const batchSummarySchema = z.object({
  batch_id: batchIdSchema,
  status: batchStatusSchema,
  created_at: z.string().min(1),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  profile_count: countSchema,
  counts: batchCountsSchema,
})
export type BatchSummary = z.infer<typeof batchSummarySchema>

export const batchListSchema = z.object({
  items: z.array(batchSummarySchema),
  next_cursor: z.string().nullable(),
  /** bản 5 B4: người gọi được dùng `scope=all` (Admin) — nút "Tất cả lô" CHỈ theo cờ này */
  can_view_all: z.boolean(),
})
export type BatchList = z.infer<typeof batchListSchema>

/**
 * Bản 6 C1 — `GET /api/admissions/documents/bulk-verify/eligibility`: cờ của CHÍNH người gọi = đúng các cổng của
 * `POST …/preview` (Casbin + `require_bulk_verify_reviewer`). Dùng cho mục thanh bên "Lô duyệt giấy" và nút "Duyệt giấy
 * theo bộ lọc hiện tại" — giao diện không suy theo vai.
 */
export const bulkVerifyEligibilitySchema = z.object({ eligible: z.boolean() })
export type BulkVerifyEligibility = z.infer<typeof bulkVerifyEligibilitySchema>

/** Bản 6 C2.3 — sự kiện socket `bulk_verify_finished` (phát tới `user_room_{user_id}` của người tạo, sau commit cuối). */
export const bulkVerifyFinishedEventSchema = z.object({ batch_id: batchIdSchema })

export const BATCH_LIST_SCOPES = ["mine", "all"] as const
export type BatchListScope = (typeof BATCH_LIST_SCOPES)[number]

// ═══════════════════════ Duyệt chéo tạm thời (§2.2) ═══════════════════════

/** `GET …/cross-review/eligibility` — CHỈ quyền còn hiệu lực của CHÍNH người gọi. */
export const crossReviewEligibilitySchema = z.object({
  eligible: z.boolean(),
  grants: z.array(
    z.object({
      grant_id: z.number().int().positive(),
      unit_id: z.number().int().positive(),
      allow_verify: z.boolean(),
      allow_reject: z.boolean(),
      expires_at: z.string().min(1),
    }),
  ),
})
export type CrossReviewEligibility = z.infer<typeof crossReviewEligibilitySchema>

/** Quyền dùng cho TỪNG thao tác (Codex 69): thao tác không có quyền ⇒ `null`. */
export const grantIdByActionSchema = z.object({
  verify: z.number().int().positive().nullable(),
  reject: z.number().int().positive().nullable(),
})

export const crossReviewQueueItemSchema = z.object({
  profile_id: z.number().int().positive(),
  document_row_id: documentRowIdSchema,
  document_type_code: z.string().nullable(),
  row_version: rowVersionSchema,
  actual_submission_format: z.string().nullable(),
  profile_status: z.string(),
  grant_id_by_action: grantIdByActionSchema,
})
export type CrossReviewQueueItem = z.infer<typeof crossReviewQueueItemSchema>

/** `GET …/cross-review/queue?page=&page_size=` (bản 5 B2, `page_size` ≤ 100) — phân trang theo SỐ TRANG, không con trỏ. */
export const CROSS_REVIEW_QUEUE_PAGE_SIZE = 20
export const crossReviewQueuePageSchema = z.object({
  items: z.array(crossReviewQueueItemSchema),
  page: z.number().int().min(1),
  page_size: z.number().int().min(1),
  total_count: countSchema,
})
export type CrossReviewQueuePage = z.infer<typeof crossReviewQueuePageSchema>

/** `POST …/cross-review/verify` · `…/reject` — lệnh duyệt gửi `grant_id_by_action.verify`, từ chối gửi `…reject`. */
export const crossReviewActionBodySchema = z
  .object({
    grant_id: z.number().int().positive(),
    profile_id: z.number().int().positive(),
    document_row_id: documentRowIdSchema,
    expected_row_version: rowVersionSchema,
    reason: reasonSchema.optional(),
  })
  .strict()
export type CrossReviewActionBody = z.infer<typeof crossReviewActionBodySchema>

/** Phản hồi lệnh chéo (bản 5 B2, `CrossReviewActionResponse`). */
export const crossReviewActionResponseSchema = z.object({
  profile_id: z.number().int().positive(),
  document_row_id: documentRowIdSchema,
  action: z.string(),
  new_status: z.string(),
  row_version: rowVersionSchema,
})
export type CrossReviewActionResponse = z.infer<typeof crossReviewActionResponseSchema>

/** Thân cấp quyền (Admin). Trần 14 ngày + "người được cấp là Cán bộ đang hoạt động" do MÁY CHỦ kiểm (422). */
export const crossReviewGrantCreateBodySchema = z
  .object({
    grantee_user_id: z.number().int().positive(),
    unit_id: z.number().int().positive(),
    allow_verify: z.boolean(),
    allow_reject: z.boolean(),
    expires_at: z.string().min(1),
    reason: reasonSchema,
  })
  .strict()
  .refine((b) => b.allow_verify || b.allow_reject, {
    message: "Chọn ít nhất một thao tác được phép",
  })
export type CrossReviewGrantCreateBody = z.infer<typeof crossReviewGrantCreateBodySchema>

export const crossReviewGrantRevokeBodySchema = z.object({ reason: reasonSchema }).strict()
export type CrossReviewGrantRevokeBody = z.infer<typeof crossReviewGrantRevokeBodySchema>

/** `CrossReviewGrantView` (bản 5 B2) — không tên người / đơn vị. `is_active` do máy chủ tính (chưa thu hồi, chưa hết hạn). */
export const crossReviewGrantSchema = z.object({
  id: z.number().int().positive(),
  grantee_user_id: z.number().int().positive(),
  unit_id: z.number().int().positive(),
  allow_verify: z.boolean(),
  allow_reject: z.boolean(),
  granted_by_user_id: z.number().int().positive(),
  granted_at: z.string().min(1),
  expires_at: z.string().min(1),
  reason: z.string(),
  revoked_at: z.string().nullable(),
  revoked_by_user_id: z.number().int().positive().nullable(),
  is_active: z.boolean(),
})
export type CrossReviewGrant = z.infer<typeof crossReviewGrantSchema>

/** Danh sách quyền = MẢNG TRẦN (bản 5 B2, tối đa 500). */
export const crossReviewGrantListSchema = z.array(crossReviewGrantSchema)
export type CrossReviewGrantList = z.infer<typeof crossReviewGrantListSchema>
