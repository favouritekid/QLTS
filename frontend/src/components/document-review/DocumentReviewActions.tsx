"use client"

/**
 * GĐ1b §7 — nút theo CỜ MÁY CHỦ cho MỘT giấy: Duyệt (`can_verify`), Từ chối (`can_reject`), Đặt lại (`can_reset`),
 * Lịch sử (`can_view_history`); lý do khoá Duyệt (`verify_block_reason`). KHÔNG đọc vai người dùng.
 *
 * Đầu vào là phần tử `documents_checklist[]` THÔ, đọc qua `readGd1bDocument` (bản 5 B1): giấy chưa có dòng ⇒ không nút;
 * lệch hợp đồng ⇒ không nút + báo một dòng nếu máy chủ có bật cờ. Dùng cho mục "Tài liệu ngoài yêu cầu hiện tại" (X1)
 * và nơi cần nút dạng chữ; bảng giấy của `DocumentsTab` dùng nút biểu tượng với cùng hộp thoại.
 */
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { documentReasonText } from "@/lib/document-review/messages"
import { explainedBlockReason, readGd1bDocument } from "@/lib/document-review/parse-document"

import { DocumentHistoryDialog } from "./DocumentHistoryDialog"
import { RejectDocumentDialog } from "./RejectDocumentDialog"
import { ResetDocumentDialog } from "./ResetDocumentDialog"
import { VerifyDocumentDialog } from "./VerifyDocumentDialog"

type OpenDialog = "verify" | "reject" | "reset" | "history" | null

interface Props {
  profileId: number
  /** một phần tử `documents_checklist[]` của phản hồi hồ sơ (chưa parse) */
  document: unknown
}

export function DocumentReviewActions({ profileId, document: raw }: Props) {
  const [open, setOpen] = useState<OpenDialog>(null)
  const read = readGd1bDocument(raw)

  if (read.kind === "no_row") return null
  if (read.kind === "contract_error") {
    return read.claimsAction ? (
      <span className="text-xs text-muted-foreground" data-testid="giay-thieu-dinh-danh">
        Thiếu định danh giấy từ máy chủ — không thao tác được ở đây.
      </span>
    ) : null
  }
  const doc = read.doc
  const close = (v: boolean) => {
    if (!v) setOpen(null)
  }
  const blockReason = explainedBlockReason(doc)

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
