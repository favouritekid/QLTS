/**
 * GĐ1b — Zod: `document_row_id` + `row_version` BẮT BUỘC kiểu số cho phản hồi GĐ1b (đặc tả §4.7), cờ máy chủ bắt buộc,
 * thân xem trước "đúng một trong hai", hình dạng lô / lịch sử / hàng đợi chéo theo hợp đồng bản 4.
 */
import { describe, expect, it } from "vitest"

import {
  asActionable,
  batchListSchema,
  batchViewSchema,
  crossReviewActionResponseSchema,
  crossReviewGrantListSchema,
  crossReviewQueuePageSchema,
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

  it("row_version null mà document_row_id có ⇒ đỏ (hai trường cùng có hoặc cùng null)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, row_version: null }).success).toBe(false)
  })

  it("giấy chưa có dòng: cả hai null + mọi cờ thao tác tắt ⇒ parse được, asActionable = null", () => {
    const r = gd1bDocumentSchema.safeParse({
      ...giay,
      status: "missing",
      document_row_id: null,
      row_version: null,
      can_verify: false,
      can_reject: false,
      can_reset: false,
      can_view_history: false,
    })
    expect(r.success).toBe(true)
    if (r.success) expect(asActionable(r.data)).toBeNull()
  })

  it.each(["can_verify", "can_reject", "can_reset", "can_view_history"] as const)(
    "bản 5 B1: định danh null mà %s bật ⇒ đỏ (không im lặng)",
    (co) => {
      const r = gd1bDocumentSchema.safeParse({
        ...giay,
        document_row_id: null,
        row_version: null,
        can_verify: false,
        can_reject: false,
        can_reset: false,
        can_view_history: false,
        [co]: true,
      })
      expect(r.success).toBe(false)
    },
  )

  it("owner 18-11: can_change_format bật mà can_verify tắt ⇒ đỏ; bật cùng can_verify ⇒ parse được", () => {
    expect(
      gd1bDocumentSchema.safeParse({ ...giay, can_verify: false, can_change_format: true }).success,
    ).toBe(false)
    expect(
      gd1bDocumentSchema.safeParse({ ...giay, can_verify: true, can_change_format: true }).success,
    ).toBe(true)
  })

  it("giấy có dòng ⇒ asActionable trả định danh + phiên bản là số", () => {
    const d = asActionable(gd1bDocumentSchema.parse(giay))
    expect(d?.document_row_id).toBe(11)
    expect(d?.row_version).toBe(3)
  })

  it("row_version là chuỗi số ⇒ đỏ (phải là số)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, row_version: "3" }).success).toBe(false)
  })

  it("row_version 0 ⇒ đỏ (phiên bản bắt đầu từ 1)", () => {
    expect(gd1bDocumentSchema.safeParse({ ...giay, row_version: 0 }).success).toBe(false)
  })

  it("thiếu KHOÁ document_row_id ⇒ đỏ; document_row_id null mà row_version có ⇒ đỏ", () => {
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
      finalize_requires_reason: false,
    }
    expect(batchViewSchema.safeParse(v).success).toBe(true)
    expect(batchViewSchema.safeParse({ ...v, status: "previewed" }).success).toBe(false)
    const { can_execute: _a, ...thieu } = v
    expect(batchViewSchema.safeParse(thieu).success).toBe(false)
    const { finalize_requires_reason: _b, ...thieuCoLyDo } = v
    expect(batchViewSchema.safeParse(thieuCoLyDo).success).toBe(false)
  })

  it("danh sách lô: cờ can_view_all bắt buộc (bản 5 B4)", () => {
    expect(batchListSchema.safeParse({ items: [], next_cursor: null, can_view_all: false }).success).toBe(true)
    expect(batchListSchema.safeParse({ items: [], next_cursor: null }).success).toBe(false)
  })
})

describe("duyệt chéo — hình dạng theo schema backend (bản 5 B2)", () => {
  it("hàng đợi phân trang theo số trang: {items, page, page_size, total_count}", () => {
    expect(
      crossReviewQueuePageSchema.safeParse({ items: [], page: 1, page_size: 20, total_count: 0 }).success,
    ).toBe(true)
    expect(crossReviewQueuePageSchema.safeParse({ items: [], next_cursor: null }).success).toBe(false)
  })

  it("phản hồi lệnh chéo: {profile_id, document_row_id, action, new_status, row_version}", () => {
    const r = { profile_id: 5, document_row_id: 11, action: "verify", new_status: "verified", row_version: 4 }
    expect(crossReviewActionResponseSchema.safeParse(r).success).toBe(true)
    const { row_version: _x, ...thieu } = r
    expect(crossReviewActionResponseSchema.safeParse(thieu).success).toBe(false)
  })

  it("danh sách quyền là MẢNG TRẦN, mỗi quyền có is_active", () => {
    const q = {
      id: 1,
      grantee_user_id: 9,
      unit_id: 3,
      allow_verify: true,
      allow_reject: false,
      granted_by_user_id: 1,
      granted_at: "2026-11-17T01:00:00Z",
      expires_at: "2026-11-24T01:00:00Z",
      reason: "thiếu người",
      revoked_at: null,
      revoked_by_user_id: null,
      is_active: true,
    }
    expect(crossReviewGrantListSchema.safeParse([q]).success).toBe(true)
    expect(crossReviewGrantListSchema.safeParse({ items: [q] }).success).toBe(false)
    const { is_active: _y, ...thieu } = q
    expect(crossReviewGrantListSchema.safeParse([thieu]).success).toBe(false)
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
