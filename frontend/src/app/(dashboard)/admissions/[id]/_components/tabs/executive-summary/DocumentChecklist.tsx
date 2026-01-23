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
import { FileText, CheckCircle2, Upload, XCircle } from "lucide-react"
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
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface DocumentChecklistProps {
  profile: AdmissionProfileResponse
}

export function DocumentChecklist({ profile }: DocumentChecklistProps) {
  const [isOpen, setIsOpen] = useState(false)

  const mandatoryDocs = (profile.documents_checklist ?? []).filter(
    (doc) => doc.is_mandatory
  )

  // Helper to render status badge
  const renderStatusBadge = (status: string) => {
    const config = getDocumentStatusConfig(status)
    const iconMap = {
      XCircle: XCircle,
      Upload: Upload,
      CheckCircle2: CheckCircle2,
      FileText: FileText,
    }
    const Icon = iconMap[config.iconName]

    return (
      <Badge variant={config.variant} className="gap-1">
        <Icon className="w-3 h-3" />
        {config.label}
      </Badge>
    )
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
                  <TableHead className="text-right min-w-[140px]">
                    Ngày nộp
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mandatoryDocs.map((doc) => (
                  <TableRow key={doc.code}>
                    {/* Document Label */}
                    <TableCell className="font-medium">
                      {doc.label}
                      {doc.requires_upload === false && (
                        <Badge variant="outline" className="ml-2 text-xs">
                          Nộp giấy
                        </Badge>
                      )}
                    </TableCell>

                    {/* Status */}
                    <TableCell className="text-center">
                      {renderStatusBadge(doc.status)}
                    </TableCell>

                    {/* Submission Format */}
                    <TableCell className="text-center">
                      {doc.submission_format && doc.status !== "missing" ? (
                        <Badge variant="secondary" className="font-normal">
                          {getFormatLabel(doc.submission_format)}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-sm">-</span>
                      )}
                    </TableCell>

                    {/* Upload Date */}
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {formatDateTime(doc.uploaded_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {/* Rejection Info */}
            {mandatoryDocs.some((doc) => doc.status === "rejected") && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                <div className="text-sm font-semibold text-red-700 mb-2">
                  Tài liệu bị từ chối:
                </div>
                {mandatoryDocs
                  .filter((doc) => doc.status === "rejected" && doc.rejection_reason)
                  .map((doc) => (
                    <div key={doc.code} className="text-xs text-red-600 mb-1">
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
