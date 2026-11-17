/**
 * GĐ1b — Zod: `document_row_id` + `row_version` BẮT BUỘC kiểu số cho phản hồi GĐ1b (đặc tả §4.7), cờ máy chủ bắt buộc,
 * thân xem trước "đúng một trong hai", hình dạng lô / lịch sử / hàng đợi chéo theo hợp đồng bản 4.
 */
import { describe, expect, it } from "vitest"

import {
  batchViewSchema,
  bulkPreviewSchema,
  bulkVerifyPreviewBodySchema,
  crossReviewGrantCreateBodySchema,
  crossReviewQueueItemSchema,
  documentHistorySchema,
  gd1bDocumentSchema,
  rejectDocumentResponseSchema,
  resetDocumentBodySchema,
  verifyDocumentBodySchema,
} from "./document-review"

const B1 = "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60"

const giay = {
  code: "hoc_ba_thpt",
  label: "Học bạ THPT",
  status: "paper_submitted",
  is_extra: false,
  document_id: null,
  actual_submission_format: "original",
  verified_format: null,
  document_row_id: 11,
  row_version: 3,
  can_verify: true,
  can_reject: true,
  can_reset: true,
  can_view_history: true,
  verify_block_reason: null,
  requires_ack: false,
  reset_requires_reason: true,
  reset_keeps_evidence: false,
}

const bo = (k: keyof typeof giay) => {
  const c: Record<string, unknown> = { ...giay }
  delete c[k]
  return c
}

describe("gd1bDocumentSchema — định danh dòng giấy + phiên bản BẮT BUỘC (§4.7)", () => {
  it("đủ trường ⇒ parse được", () => {
    expect(gd1bDocumentSchema.safeParse(giay).success).toBe(true)
  })

  it("thiếu row_version ⇒ đỏ", () => {
    expect(gd1bDocumentSchema.safeParse(bo("row_version")).success).toBe(false)
  })

  it("row_version null ⇒ đỏ (không nullable)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, row_version: null }).success).toBe(false)
  })

  it("row_version là chuỗi số ⇒ đỏ (phải là số)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, row_version: "3" }).success).toBe(false)
  })

  it("row_version 0 ⇒ đỏ (phiên bản bắt đầu từ 1)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, row_version: 0 }).success).toBe(false)
  })

  it("thiếu document_row_id / null ⇒ đỏ", () => {
    expect(gd1bDocumentSchema.safeParse(bo("document_row_id")).success).toBe(false)
    expect(gd1bDocumentSchema.safeParse({ ...giay, document_row_id: null }).success).toBe(false)
  })

  it.each([
    "can_verify",
    "can_reject",
    "can_reset",
    "can_view_history",
    "requires_ack",
    "reset_requires_reason",
    "reset_keeps_evidence",
    "verify_block_reason",
  ] as const)("thiếu cờ %s ⇒ đỏ (không mặc định)", (k) => {
    expect(gd1bDocumentSchema.safeParse(bo(k)).success).toBe(false)
  })

  it("verify_block_reason lạ vẫn parse (giao diện hiện câu chung)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, can_verify: false, verify_block_reason: "ma_moi" }).success).toBe(true)
  })
})

describe("thân nút lẻ gửi expected_row_version", () => {
  it("verify: thiếu expected_row_version ⇒ đỏ; thừa khoá ⇒ đỏ", () => {
    expect(verifyDocumentBodySchema.safeParse({ format: "photo", unknown_submitter_ack: false }).success).toBe(false)
    expect(
      verifyDocumentBodySchema.safeParse({ format: "photo", expected_row_version: 2, unknown_submitter_ack: false, x: 1 })
        .success,
    ).toBe(false)
  })

  it("reset: lý do bắt buộc, chỉ khoảng trắng ⇒ đỏ", () => {
    expect(resetDocumentBodySchema.safeParse({ reason: "   ", expected_row_version: 2, unknown_submitter_ack: false }).success).toBe(false)
    expect(resetDocumentBodySchema.safeParse({ reason: "nhầm", expected_row_version: 2, unknown_submitter_ack: false }).success).toBe(true)
  })

  it("phản hồi reject phải có row_version mới", () => {
    const ok = {
      code: "cccd",
      status: "rejected",
      rejection_reason: "mờ",
      rejected_at: null,
      rejected_by_id: 7,
      document_row_id: 11,
      row_version: 4,
    }
    expect(rejectDocumentResponseSchema.safeParse(ok).success).toBe(true)
    const { row_version: _bo, ...thieu } = ok
    expect(rejectDocumentResponseSchema.safeParse(thieu).success).toBe(false)
  })
})

describe("lô — hợp đồng §2.1", () => {
  it("xem trước: đúng MỘT trong profile_ids / filter", () => {
    expect(bulkVerifyPreviewBodySchema.safeParse({ profile_ids: [1], include_optional: false }).success).toBe(true)
    expect(bulkVerifyPreviewBodySchema.safeParse({ filter: { status: "submitted" }, include_optional: false }).success).toBe(true)
    expect(
      bulkVerifyPreviewBodySchema.safeParse({ profile_ids: [1], filter: {}, include_optional: false }).success,
    ).toBe(false)
    expect(bulkVerifyPreviewBodySchema.safeParse({ include_optional: false }).success).toBe(false)
  })

  it("bộ lọc lạ khoá ⇒ đỏ (không gửi tham số ngoài hợp đồng)", () => {
    expect(
      bulkVerifyPreviewBodySchema.safeParse({ filter: { page: 2 }, include_optional: false }).success,
    ).toBe(false)
  })

  it("mục xem trước: expected_row_version bắt buộc", () => {
    const p = {
      batch_id: B1,
      expires_at: "2026-11-17T08:30:00Z",
      counts: { profiles: 1, documents: 1, required: 1, optional: 0 },
      items: [{ profile_id: 5, document_row_id: 11, document_type_code: "cccd", expected_row_version: 3, is_mandatory: true }],
      excluded: [],
    }
    expect(bulkPreviewSchema.safeParse(p).success).toBe(true)
    expect(
      bulkPreviewSchema.safeParse({ ...p, items: [{ profile_id: 5, document_row_id: 11, document_type_code: "cccd", is_mandatory: true }] })
        .success,
    ).toBe(false)
  })

  it("BatchView: trạng thái ngoài 9 giá trị ⇒ đỏ; cờ can_execute / can_finalize bắt buộc", () => {
    const v = {
      batch_id: B1,
      status: "completed",
      created_at: "2026-11-17T08:00:00Z",
      started_at: null,
      finished_at: null,
      finalized_at: null,
      finalized_by_user_id: null,
      finalize_reason: null,
      counts: { profiles: 0, recorded: 0, error: 0, not_processed: 0, pending: 0 },
      items: [],
      can_execute: false,
      can_finalize: false,
    }
    expect(batchViewSchema.safeParse(v).success).toBe(true)
    expect(batchViewSchema.safeParse({ ...v, status: "previewed" }).success).toBe(false)
    const { can_execute: _a, ...thieu } = v
    expect(batchViewSchema.safeParse(thieu).success).toBe(false)
  })
})

describe("lịch sử + duyệt chéo", () => {
  it("lịch sử: row_version bắt buộc", () => {
    const h = { document_row_id: 11, document_type_code: null, status: "verified", row_version: 5, entries: [], evidence_files: [] }
    expect(documentHistorySchema.safeParse(h).success).toBe(true)
    expect(documentHistorySchema.safeParse({ ...h, row_version: null }).success).toBe(false)
  })

  it("hàng đợi chéo: grant_id_by_action có cả hai khoá, mỗi khoá số hoặc null", () => {
    const it0 = {
      profile_id: 5,
      document_row_id: 11,
      document_type_code: "cccd",
      row_version: 2,
      actual_submission_format: "original",
      profile_status: "submitted",
      grant_id_by_action: { verify: 22, reject: null },
    }
    expect(crossReviewQueueItemSchema.safeParse(it0).success).toBe(true)
    expect(crossReviewQueueItemSchema.safeParse({ ...it0, grant_id_by_action: { verify: 22 } }).success).toBe(false)
  })

  it("cấp quyền: cần ít nhất một thao tác + lý do", () => {
    const b = {
      grantee_user_id: 9,
      unit_id: 3,
      allow_verify: false,
      allow_reject: false,
      expires_at: "2026-11-20T17:00:00+07:00",
      reason: "thiếu người",
    }
    expect(crossReviewGrantCreateBodySchema.safeParse(b).success).toBe(false)
    expect(crossReviewGrantCreateBodySchema.safeParse({ ...b, allow_verify: true }).success).toBe(true)
    expect(crossReviewGrantCreateBodySchema.safeParse({ ...b, allow_verify: true, reason: " " }).success).toBe(false)
  })
})
