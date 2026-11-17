"use client"

/**
 * GĐ1b §7 — nút theo CỜ MÁY CHỦ cho MỘT giấy: Duyệt (`can_verify`), Từ chối (`can_reject`), Đặt lại (`can_reset`),
 * Lịch sử (`can_view_history`); lý do khoá Duyệt (`verify_block_reason`). KHÔNG đọc vai người dùng.
 *
 * ⚠️ CHƯA nối vào `/admissions/[id]` (`DocumentsTab`, `DocumentChecklist`) — chờ biên bản đo nền V4 (hợp đồng §2.4).
 * Đầu vào là phần tử `documents_checklist[]` THÔ: parse bằng `gd1bDocumentSchema`; thiếu `document_row_id` /
 * `row_version` / cờ ⇒ KHÔNG dựng nút nào (fail-closed) và báo một dòng.
 */
import { useState } from "react"
import { z } from "zod"

import { Button } from "@/components/ui/button"
import { documentReasonText } from "@/lib/document-review/messages"
import { gd1bDocumentSchema } from "@/lib/zod/document-review"

import { DocumentHistoryDialog } from "./DocumentHistoryDialog"
import { RejectDocumentDialog } from "./RejectDocumentDialog"
import { ResetDocumentDialog } from "./ResetDocumentDialog"
import { VerifyDocumentDialog } from "./VerifyDocumentDialog"

/** Lý do khoá Duyệt đáng giải thích cho người đang có quyền (mã khác — vd không có quyền — không cần nói trên từng giấy). */
const EXPLAINED_BLOCK_REASONS: ReadonlySet<string> = new Set([
  "own_submission",
  "unknown_submitter",
  "missing_format",
  "outside_config",
])

/** Chỉ để biết máy chủ có BẬT cờ nào cho giấy không parse được (chẩn đoán lệch hợp đồng) — không dùng để dựng nút. */
const claimedFlagsSchema = z.object({
  can_verify: z.boolean().optional(),
  can_reject: z.boolean().optional(),
  can_reset: z.boolean().optional(),
  can_view_history: z.boolean().optional(),
})

type OpenDialog = "verify" | "reject" | "reset" | "history" | null

interface Props {
  profileId: number
  /** một phần tử `documents_checklist[]` của phản hồi hồ sơ (chưa parse) */
  document: unknown
}

export function DocumentReviewActions({ profileId, document: raw }: Props) {
  const [open, setOpen] = useState<OpenDialog>(null)
  const parsed = gd1bDocumentSchema.safeParse(raw)

  if (!parsed.success) {
    // Giấy chưa có dòng (máy chủ trả mọi cờ tắt) ⇒ im lặng. Máy chủ BẬT một cờ mà thiếu định danh / phiên bản ⇒ lệch
    // hợp đồng: không dựng nút, báo một dòng (không `console.*`).
    const claims = claimedFlagsSchema.safeParse(raw)
    const anyOn = claims.success && Object.values(claims.data).some((v) => v === true)
    return anyOn ? (
      <span className="text-xs text-muted-foreground" data-testid="giay-thieu-dinh-danh">
        Thiếu định danh giấy từ máy chủ — không thao tác được ở đây.
      </span>
    ) : null
  }
  const doc = parsed.data
  const close = (v: boolean) => {
    if (!v) setOpen(null)
  }
  const blockReason =
    !doc.can_verify && doc.verify_block_reason && EXPLAINED_BLOCK_REASONS.has(doc.verify_block_reason)
      ? doc.verify_block_reason
      : null

  return (
    <div className="flex flex-wrap items-center gap-2">
      {doc.can_verify && (
        <Button size="sm" onClick={() => setOpen("verify")} aria-label={`Duyệt giấy ${doc.label}`}>
          {doc.requires_ack ? "Duyệt (cam kết)" : "Duyệt"}
        </Button>
      )}
      {doc.can_reject && (
        <Button size="sm" variant="outline" onClick={() => setOpen("reject")} aria-label={`Từ chối giấy ${doc.label}`}>
          Từ chối
        </Button>
      )}
      {doc.can_reset && (
        <Button size="sm" variant="outline" onClick={() => setOpen("reset")} aria-label={`Đặt lại giấy ${doc.label}`}>
          Đặt lại
        </Button>
      )}
      {doc.can_view_history && (
        <Button size="sm" variant="ghost" onClick={() => setOpen("history")} aria-label={`Lịch sử giấy ${doc.label}`}>
          Lịch sử
        </Button>
      )}
      {blockReason && (
        <span className="text-xs text-muted-foreground" data-testid="ly-do-khoa-duyet">
          {documentReasonText(blockReason)}
        </span>
      )}

      {open === "verify" && (
        <VerifyDocumentDialog profileId={profileId} document={doc} open onOpenChange={close} />
      )}
      {open === "reject" && (
        <RejectDocumentDialog profileId={profileId} document={doc} open onOpenChange={close} />
      )}
      {open === "reset" && <ResetDocumentDialog profileId={profileId} document={doc} open onOpenChange={close} />}
      {open === "history" && (
        <DocumentHistoryDialog
          profileId={profileId}
          documentRowId={doc.document_row_id}
          label={doc.label}
          open
          onOpenChange={close}
        />
      )}
    </div>
  )
}
