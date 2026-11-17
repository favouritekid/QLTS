/**
 * DocumentChecklist Component
 *
 * Section 3.2: Checklist Tài Liệu Bắt Buộc
 * Displays: Table of all mandatory documents with status, format, and submission date
 *
 * GĐ1b (đặc tả §5.9, hợp đồng bản 4 §2.4 + bản 5):
 *  - "Xác nhận kiểm tra" = xem trước + chạy lô cho MỘT hồ sơ (`profile_ids = [id]`) qua `BulkVerifyDialog` — KHÔNG còn
 *    duyệt song song (`Promise.all`), KHÔNG còn chọn / mặc định hình thức ở đây: lô ghi đúng hình thức lúc nhận, giấy
 *    thiếu hình thức bị máy chủ loại (`missing_format`) và được liệt kê ở bản xem trước.
 *  - Từ chối từng giấy qua hộp GĐ1b (`expected_row_version`, cam kết khi `requires_ack`).
 *  - Nút theo CỜ MÁY CHỦ của giấy đã đọc được định danh (`readGd1bDocument`), không theo vai.
 */

"use client"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { FileText, CheckCircle2, XCircle, Eye } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ChevronDown } from "lucide-react"
import { useState } from "react"
import {
  getDocumentStatusConfig,
  getFormatLabel,
} from "@/lib/utils/admission-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { API_BASE_URL } from "@/lib/api/client"
import { BulkVerifyDialog } from "@/components/document-review/bulk/BulkVerifyDialog"
import { RejectDocumentDialog } from "@/components/document-review/RejectDocumentDialog"
import { readGd1bDocument } from "@/lib/document-review/parse-document"

interface DocumentChecklistProps {
  profile: AdmissionProfileResponse
}

export function DocumentChecklist({ profile }: DocumentChecklistProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)

  const mandatoryDocs = (profile.documents_checklist ?? []).filter(
    (doc) => doc.is_mandatory
  )

  // "Xác nhận kiểm tra" chỉ hiện khi máy chủ cho duyệt ít nhất một giấy bắt buộc (`can_verify` của giấy đã có định
  // danh). Giấy nào thật sự vào lô do MÁY CHỦ chọn ở bước xem trước (chỉ giấy bản giấy, chờ xét, có hình thức…).
  const canStartBatch = mandatoryDocs.some((doc) => {
    const r = readGd1bDocument(doc)
    return r.kind === "ok" && r.doc.can_verify
  })

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 rounded-lg transition-colors border">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-muted-foreground" />
          <span className="font-semibold">
            Checklist Tài Liệu Bắt Buộc
            <span className="ml-1 text-muted-foreground text-sm font-normal">
              ({mandatoryDocs.length} tài liệu)
            </span>
          </span>
        </div>
        <ChevronDown
          className={`w-4 h-4 transition-transform ${
            isOpen ? "transform rotate-180" : ""
          }`}
        />
      </CollapsibleTrigger>

      <CollapsibleContent className="p-4 border border-t-0 rounded-b-lg">
        {mandatoryDocs.length === 0 ? (
          <div className="text-center text-muted-foreground py-6">
            Không có tài liệu bắt buộc
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[200px]">Tài liệu</TableHead>
                  <TableHead className="text-center min-w-[120px]">
                    Trạng thái
                  </TableHead>
                  <TableHead className="text-center min-w-[140px]">
                    Loại bản nộp
                  </TableHead>
                  {/* Phase 8: Removed Date column for cleaner review UI */}
                  <TableHead className="text-right w-[100px]">
                    Thao tác
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mandatoryDocs.map((doc) => (
                  <DocumentRow key={doc.code} doc={doc} profile={profile} />
                ))}
              </TableBody>
            </Table>

            {/* "Xác nhận kiểm tra" — lô MỘT hồ sơ (xem trước + ô xác nhận + chạy) */}
            {canStartBatch && (
              <div className="mt-4 flex justify-end">
                <Button
                  onClick={() => setBatchOpen(true)}
                  className="bg-success-600 hover:bg-success-700"
                  aria-label="Xác nhận kiểm tra các giấy bản giấy của hồ sơ này"
                >
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                  Xác nhận kiểm tra
                </Button>
              </div>
            )}

            {/* Rejection Info */}
            {mandatoryDocs.some((doc) => doc.status === "rejected") && (
              <div className="mt-4 p-3 bg-error-50 border border-error-200 rounded-lg">
                <div className="text-sm font-semibold text-error-700 mb-2">
                  Tài liệu bị từ chối:
                </div>
                {mandatoryDocs
                  .filter((doc) => doc.status === "rejected" && doc.rejection_reason)
                  .map((doc) => (
                    <div key={doc.code} className="text-xs text-error-600 mb-1">
                      • <strong>{doc.label}</strong>: {doc.rejection_reason}
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        {batchOpen && (
          <BulkVerifyDialog
            open
            onOpenChange={(v) => {
              if (!v) setBatchOpen(false)
            }}
            endpoint={{ mode: "batch" }}
            selection={{ kind: "profiles", profileIds: [profile.id] }}
            title="Xác nhận kiểm tra giấy của hồ sơ"
            scopeLabel="hồ sơ này"
          />
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

// Helper type for checklist item
type ChecklistItem = AdmissionProfileResponse["documents_checklist"][number]

function DocumentRow({
  doc,
  profile,
}: {
  doc: ChecklistItem
  profile: AdmissionProfileResponse
}) {
  const { status } = doc
  const [rejectOpen, setRejectOpen] = useState(false)
  // GĐ1b: Từ chối CHỈ theo cờ máy chủ của giấy đã đọc được định danh + phiên bản (bản 5 B1).
  const read = readGd1bDocument(doc)
  const gd1b = read.kind === "ok" ? read.doc : null
  const isAwaitingCheck = status === "uploaded" || status === "paper_submitted"

  return (
    <>
      <TableRow>
        <TableCell className="font-medium">{doc.label}</TableCell>

        <TableCell className="text-center">
          {status === "verified" ? (
            // "Đã kiểm tra" — officer-verified, fully complete. Distinct
            // from "ghi nhận" states (uploaded / paper_submitted) which
            // mean we received the row but haven't checked it yet.
            <Badge className="bg-success-600 hover:bg-success-700 gap-1">
              <CheckCircle2 className="w-3 h-3" />
              Đã kiểm tra
            </Badge>
          ) : (
            <Badge
              variant={getDocumentStatusConfig(status).variant as "default" | "secondary" | "destructive" | "outline"}
              className="gap-1"
            >
              {getDocumentStatusConfig(status).label}
            </Badge>
          )}
        </TableCell>

        <TableCell className="text-center">
          {status === "verified" && doc.verified_format ? (
            // Show verified format as badge
            <Badge
              variant="outline"
              className="font-normal border-success-200 bg-success-50 text-success-700"
            >
              {getFormatLabel(doc.verified_format)}
            </Badge>
          ) : doc.actual_submission_format ? (
            // Hình thức lúc nhận — lô ghi ĐÚNG hình thức này (không chọn lại ở đây)
            <Badge
              variant="outline"
              className="font-normal border-info-200 bg-info-50 text-info-700"
            >
              {getFormatLabel(doc.actual_submission_format)}
            </Badge>
          ) : isAwaitingCheck ? (
            // Không dự phòng "photo": thiếu hình thức lúc nhận ⇒ lô loại giấy này, duyệt từng giấy ở bước Tài liệu
            <span className="text-xs text-warning-700" data-testid={`thieu-hinh-thuc-${doc.code}`}>
              Chưa ghi hình thức lúc nhận
            </span>
          ) : (
            <span className="text-muted-foreground text-sm">-</span>
          )}
        </TableCell>

        <TableCell className="text-right">
          <div className="flex justify-end gap-1">
            {/* View Button — show only when a downloadable document_id exists
                (PR2: no fallback to file_path; /uploads is no longer public). */}
            {doc.document_id != null && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 text-info-600 hover:text-info-700 hover:bg-info-50"
                      onClick={() => {
                        const url = getDocumentUrl(profile.id, doc.document_id)
                        if (url) window.open(url, "_blank")
                      }}
                      aria-label="Xem tài liệu"
                    >
                      <Eye className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Xem tài liệu</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}

            {/* Từ chối — CHỈ khi máy chủ trả can_reject cho giấy đã có định danh */}
            {gd1b?.can_reject && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 text-error-600 hover:text-error-700 hover:bg-error-50"
                      onClick={() => setRejectOpen(true)}
                      aria-label={`Từ chối giấy ${doc.label}`}
                    >
                      <XCircle className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Từ chối tài liệu</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        </TableCell>
      </TableRow>

      {rejectOpen && gd1b && (
        <RejectDocumentDialog
          profileId={profile.id}
          document={gd1b}
          open
          onOpenChange={(v) => {
            if (!v) setRejectOpen(false)
          }}
        />
      )}
    </>
  )
}

// Helper function to build the authed document download URL.
// PR2: streams through the IDOR-scoped, audited backend endpoint instead of
// the (now-removed) public /uploads mount. Returns null when there is no
// downloadable artifact so the caller hides the View button.
function getDocumentUrl(profileId: number, documentId?: number | null) {
  if (documentId == null) return null
  return `${API_BASE_URL}/api/admissions/${profileId}/documents/${documentId}/download`
}
