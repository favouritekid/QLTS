/**
 * DocumentChecklist Component
 *
 * Section 3.2: Checklist Tài Liệu Bắt Buộc
 * Displays: Table of all mandatory documents with status, format, and submission date
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { FileText, CheckCircle2, Upload, XCircle, Eye } from "lucide-react"
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
  formatDateTime,
} from "@/lib/utils/admission-helpers"
import { useVerifyDocument, useRejectDocument } from "@/hooks/admissions"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { API_BASE_URL } from "@/lib/api/client"

interface DocumentChecklistProps {
  profile: AdmissionProfileResponse
}

export function DocumentChecklist({ profile }: DocumentChecklistProps) {
  const [isOpen, setIsOpen] = useState(false)
  const verifyMutation = useVerifyDocument(profile.id)

  const mandatoryDocs = (profile.documents_checklist ?? []).filter(
    (doc) => doc.is_mandatory
  )

  // Track selected format for each document (for bulk review)
  // Initialize with actual_submission_format or submission_format as default
  const [selectedFormats, setSelectedFormats] = useState<Record<string, string>>(
    () => {
      const initial: Record<string, string> = {}
      mandatoryDocs.forEach((doc) => {
        const isPending = doc.status === "uploaded" || doc.status === "paper_submitted"
        if (isPending) {
          // Default to actual_submission_format (what user/officer declared),
          // fallback to submission_format (config requirement),
          // final fallback to "photo"
          initial[doc.code] = doc.actual_submission_format || doc.submission_format || "photo"
        }
      })
      return initial
    }
  )

  const handleFormatChange = (code: string, format: string) => {
    setSelectedFormats((prev) => ({
      ...prev,
      [code]: format,
    }))
  }

  // Get pending documents (ready for bulk verification)
  const pendingDocs = mandatoryDocs.filter(
    (doc) => doc.status === "uploaded" || doc.status === "paper_submitted"
  )

  // Batch verify all pending documents
  const handleBatchVerify = async () => {
    if (pendingDocs.length === 0) return

    const confirmed = window.confirm(
      `Xác nhận kiểm tra ${pendingDocs.length} tài liệu đang chờ?`
    )
    if (!confirmed) return

    try {
      // Verify all documents in parallel using Promise.all
      await Promise.all(
        pendingDocs.map((doc) =>
          verifyMutation.mutateAsync({
            docCode: doc.code,
            format: selectedFormats[doc.code] || "photo",
          })
        )
      )
      // Success handled by React Query cache invalidation
    } catch (error) {
      // Error toast already shown by mutation onError
      console.error("Batch verify failed:", error)
    }
  }

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
                  <DocumentRow
                    key={doc.code}
                    doc={doc}
                    profile={profile}
                    onFormatChange={handleFormatChange}
                    selectedFormat={selectedFormats[doc.code] || "photo"}
                  />
                ))}
              </TableBody>
            </Table>

            {/* Batch Verify Button */}
            {pendingDocs.length > 0 && (
              <div className="mt-4 flex justify-end">
                <Button
                  onClick={handleBatchVerify}
                  disabled={verifyMutation.isPending}
                  className="bg-success-600 hover:bg-success-700"
                >
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                  {verifyMutation.isPending
                    ? "Đang xác nhận..."
                    : `Xác nhận kiểm tra (${pendingDocs.length})`}
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
      </CollapsibleContent>
    </Collapsible>
  )
}

// Helper type for checklist item
type ChecklistItem = AdmissionProfileResponse["documents_checklist"][number]

function DocumentRow({
  doc,
  profile,
  onFormatChange,
  selectedFormat,
}: {
  doc: ChecklistItem
  profile: AdmissionProfileResponse
  onFormatChange: (code: string, format: string) => void
  selectedFormat: string
}) {
  const { code, status } = doc
  const rejectMutation = useRejectDocument(profile.id)

  const handleReject = () => {
    const reason = window.prompt("Nhập lý do từ chối:")
    if (reason) {
      rejectMutation.mutate({ docCode: code, reason })
    }
  }

  // Only show inline select for pending documents
  const isPending = status === "uploaded" || status === "paper_submitted"

  return (
    <TableRow>
      <TableCell className="font-medium">{doc.label}</TableCell>

      <TableCell className="text-center">
        {status === "verified" ? (
          <Badge className="bg-success-600 hover:bg-success-700 gap-1">
            <CheckCircle2 className="w-3 h-3" />
            Đã xác nhận
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
        {isPending ? (
          // Inline Select for pending documents - Officer can review/correct format
          <Select
            value={selectedFormat}
            onValueChange={(value) => onFormatChange(code, value)}
          >
            <SelectTrigger className="w-[180px] h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="original">Bản gốc</SelectItem>
              <SelectItem value="certified_copy">Bản sao có công chứng</SelectItem>
              <SelectItem value="photo">Bản photo/scan</SelectItem>
            </SelectContent>
          </Select>
        ) : status === "verified" && doc.verified_format ? (
          // Show verified format as badge
          <Badge
            variant="outline"
            className="font-normal border-success-200 bg-success-50 text-success-700"
          >
            {getFormatLabel(doc.verified_format)}
          </Badge>
        ) : doc.actual_submission_format ? (
          // Show user-declared format
          <Badge
            variant="outline"
            className="font-normal border-info-200 bg-info-50 text-info-700"
          >
            {getFormatLabel(doc.actual_submission_format)}
          </Badge>
        ) : (
          <span className="text-muted-foreground text-sm">-</span>
        )}
      </TableCell>

      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          {/* View Button - Always show if file exists */}
          {doc.file_path && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 text-info-600 hover:text-info-700 hover:bg-info-50"
                    onClick={() => {
                      const url = getDocumentUrl(doc.file_path)
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

          {/* Reject Button - Only show for pending documents */}
          {isPending && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 text-error-600 hover:text-error-700 hover:bg-error-50"
                    onClick={handleReject}
                    disabled={rejectMutation.isPending}
                    aria-label="Từ chối tài liệu"
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
  )
}

// Helper function to get document URL
function getDocumentUrl(filePath?: string | null) {
  if (!filePath) return null
  if (filePath.startsWith("http")) return filePath
  // Handle relative paths (remove leading slash if present to avoid double slash)
  const cleanPath = filePath.startsWith("/") ? filePath.slice(1) : filePath
  return `${API_BASE_URL}/${cleanPath}`
}
