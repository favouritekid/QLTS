/**
 * Q9 #07 Phase E.4 — Per-UT priority evidence upload cell.
 *
 * Wrap generic `FileUpload` cho DocumentsTab Priority section. One cell
 * per UT sub_code (from `priority_evidence_documents` server projection).
 *
 * Guardrail #2 (PR-3 audit cycle 2026-05-20): FileUpload.onUpload signature
 * `(file: File) => Promise<string>` expects URL/path return. Wrapper:
 *   1. Invoke useUploadPriorityEvidence mutation
 *   2. Read updated profile.priority_evidence_documents[item].document_file_path
 *   3. Return basename string (FE display)
 *
 * P1 fix (PR-3 Step C audit): two-mode render — view mode (server has file)
 * shows summary + [Xem PDF] + [Tải lại]; replace mode renders empty
 * FileUpload dropzone. Without this fix, re-upload bị block vì FileUpload
 * controlled value đầy chỗ với maxFiles=1.
 *
 * Mutation success invalidates admission detail cache → DocumentsTab
 * re-renders row với new file (auto exit replace mode).
 */
"use client"

import { ExternalLink, Loader2, Upload } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { FileUpload } from "@/components/common/upload/FileUpload"
import { useUploadPriorityEvidence } from "@/lib/hooks/use-priority-evidence"
import {
  findEvidenceDocument,
  getDisplayFilename,
} from "@/lib/utils/priority-evidence-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export interface PriorityEvidenceUploadCellProps {
  profile: AdmissionProfileResponse
  subCode: string
  /** Disabled state (vd: profile post-submit frozen). */
  disabled?: boolean
}

export function PriorityEvidenceUploadCell({
  profile,
  subCode,
  disabled = false,
}: PriorityEvidenceUploadCellProps) {
  const uploadMutation = useUploadPriorityEvidence(profile.id, subCode)
  const docItem = findEvidenceDocument(profile, subCode)
  const hasFile = Boolean(docItem?.document_file_path)

  // P1 fix: two-mode render. View mode = server has file → summary + buttons.
  // Replace mode = no server file OR user clicked "Tải lại" → FileUpload
  // dropzone visible cho re-upload.
  const [replaceMode, setReplaceMode] = useState(false)
  const showUploader = !hasFile || replaceMode

  // Guardrail #2: onUpload returns Promise<string> với document_file_path
  // từ updated response. FileUpload uses return value to mark item
  // status='success' + display url.
  const handleUpload = async (file: File): Promise<string> => {
    const updated = await uploadMutation.mutateAsync({ file })
    const updatedDoc = (updated.priority_evidence_documents ?? []).find(
      (item) => item.sub_code === subCode,
    )
    if (!updatedDoc?.document_file_path) {
      // Should not happen — BE just persisted file_path. Defensive.
      throw new Error(
        `Upload thành công nhưng response thiếu document_file_path cho UT${subCode}`,
      )
    }
    // Exit replace mode — server doc updated, view mode shows new file.
    setReplaceMode(false)
    return updatedDoc.document_file_path
  }

  return (
    <div
      data-testid={`priority-evidence-upload-cell-${subCode}`}
      className="space-y-2"
    >
      {/* View mode — file exists + not actively replacing */}
      {!showUploader && docItem?.document_file_path && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/30 p-2 text-sm">
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">
              {getDisplayFilename(docItem.document_file_path)}
            </p>
            <p className="text-xs text-muted-foreground">
              UT{subCode}
              {docItem.label ? ` — ${docItem.label}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <a
              href={`/${docItem.document_file_path}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-2 py-1 text-xs hover:bg-accent"
              data-testid={`priority-evidence-view-${subCode}`}
            >
              <ExternalLink className="h-3 w-3" />
              Xem PDF
            </a>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setReplaceMode(true)}
              disabled={disabled}
              className="h-auto px-2 py-1 text-xs"
              data-testid={`priority-evidence-replace-${subCode}`}
            >
              <Upload className="h-3 w-3 mr-1" />
              Tải lại
            </Button>
          </div>
        </div>
      )}

      {/* Replace mode — empty FileUpload dropzone */}
      {showUploader && (
        <div className="space-y-1">
          {hasFile && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                Đang thay file: {getDisplayFilename(docItem?.document_file_path ?? null)}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setReplaceMode(false)}
                disabled={uploadMutation.isPending}
                className="h-auto p-0 text-xs"
                data-testid={`priority-evidence-cancel-replace-${subCode}`}
              >
                Huỷ
              </Button>
            </div>
          )}
          <FileUpload
            value={[]}
            onUpload={handleUpload}
            accept="application/pdf,image/jpeg,image/png"
            maxSize={10 * 1024 * 1024}
            maxFiles={1}
            disabled={disabled || uploadMutation.isPending}
            description={`UT${subCode}${docItem?.label ? ` — ${docItem.label}` : ""}`}
          />
          {uploadMutation.isPending && (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Đang upload...
            </p>
          )}
        </div>
      )}
    </div>
  )
}
