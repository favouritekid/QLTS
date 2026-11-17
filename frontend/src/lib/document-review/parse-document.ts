/**
 * GĐ1b — MỘT chỗ đọc một phần tử `documents_checklist[]` thành giấy dựng được thao tác GĐ1b (bản 5 B1).
 *
 *  - `ok`             : parse đủ + đã có dòng ⇒ dùng `doc` (định danh + phiên bản là số) cho nút / hộp thoại.
 *  - `no_row`         : giấy chưa có dòng (`document_row_id` / `row_version` null, mọi cờ thao tác `false`) ⇒ không thao tác.
 *  - `contract_error` : thiếu khoá / sai kiểu / cờ bật mà định danh null ⇒ KHÔNG dựng nút (fail-closed); `claimsAction`
 *                       cho biết máy chủ có bật cờ nào không (để báo một dòng thay vì im lặng).
 *
 * Không suy theo vai, không `console.*`.
 */
import { z } from "zod"

import { asActionable, gd1bDocumentSchema, type Gd1bActionableDocument } from "@/lib/zod/document-review"

export type Gd1bDocumentRead =
  | { kind: "ok"; doc: Gd1bActionableDocument }
  | { kind: "no_row" }
  | { kind: "contract_error"; claimsAction: boolean }

/** Chỉ để chẩn đoán lệch hợp đồng — KHÔNG dùng để dựng nút. */
const claimedFlagsSchema = z.object({
  can_verify: z.boolean().optional(),
  can_reject: z.boolean().optional(),
  can_reset: z.boolean().optional(),
  can_view_history: z.boolean().optional(),
})

export function readGd1bDocument(raw: unknown): Gd1bDocumentRead {
  const parsed = gd1bDocumentSchema.safeParse(raw)
  if (!parsed.success) {
    const claims = claimedFlagsSchema.safeParse(raw)
    const claimsAction = claims.success && Object.values(claims.data).some((v) => v === true)
    return { kind: "contract_error", claimsAction }
  }
  const doc = asActionable(parsed.data)
  return doc ? { kind: "ok", doc } : { kind: "no_row" }
}

/** Lý do khoá Duyệt đáng giải thích trên từng giấy (mã khác — vd không có quyền — không cần nói ở đây). */
export const EXPLAINED_BLOCK_REASONS: ReadonlySet<string> = new Set([
  "own_submission",
  "unknown_submitter",
  "missing_format",
  "outside_config",
])

export function explainedBlockReason(doc: Gd1bActionableDocument): string | null {
  return !doc.can_verify && doc.verify_block_reason && EXPLAINED_BLOCK_REASONS.has(doc.verify_block_reason)
    ? doc.verify_block_reason
    : null
}
