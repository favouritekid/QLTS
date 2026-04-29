"use client"

/**
 * Documents Tab Component (REFACTORED)
 * 
 * Comprehensive document submission table per wireframe:
 * - Tên giấy tờ | Loại nộp | Hình thức | Trạng thái | Thao tác
 * 
 * Features:
 * - Display ALL documents from doc_configs (not just requires_upload=true)
 * - submission_format badges (photo, certified_copy, original)
 * - requires_upload column (Online vs Nộp giấy)
 * - paper_submitted status support
 * - Officer-only checkbox for paper submission
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  FileText, Check, AlertCircle, XCircle, Upload, Loader2, Eye,
  Camera, FileCheck, FileSpreadsheet, Globe, Building2, Ban, RotateCcw,
  AlertTriangle,
} from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { useUploadAdmissionDocument, useMarkPaperSubmitted, useRejectDocument, useResetDocument } from "@/hooks/admissions/useAdmissions"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { isSafeFilePath } from "@/lib/utils"
import {
  DOCUMENT_FORMAT_OPTIONS,
  getFormatLabel,
  isDocumentRecorded,
  isDocumentRequirementSatisfied,
  isDocumentPendingVerification,
} from "@/lib/utils/admission-helpers"

interface DocumentsTabProps {
  profile: AdmissionProfileResponse
  isEditable: boolean
}

// ============================================================================
// STATUS CONFIG
// ============================================================================

// Status labels distinguish "ghi nhận" (received) from "kiểm tra" (verified):
// uploaded / paper_submitted are received but officer-review still pending,
// while verified means officer has confirmed the submitted format.
const STATUS_CONFIG: Record<string, {
  label: string
  color: string
  icon: typeof AlertCircle
}> = {
  missing: {
    label: "Chưa nộp",
    color: "bg-muted text-muted-foreground",
    icon: AlertCircle,
  },
  uploaded: {
    label: "Đã ghi nhận file",
    color: "bg-info-100 text-info-700",
    icon: Upload,
  },
  paper_submitted: {
    label: "Đã nhận bản giấy",
    color: "bg-info-100 text-info-700",
    icon: FileText,
  },
  verified: {
    label: "Đã kiểm tra",
    color: "bg-success-100 text-success-700",
    icon: Check,
  },
  rejected: {
    label: "Không hợp lệ",
    color: "bg-error-100 text-error-700",
    icon: XCircle,
  },
}

// Icon mapping for submission format badges. Labels come from
// admission-helpers (single source of truth) — do not duplicate text here.
const FORMAT_ICONS: Record<string, typeof Camera> = {
  photo: Camera,
  certified_copy: FileCheck,
  original: FileSpreadsheet,
}

function getStatusConfig(status: string) {
  return STATUS_CONFIG[status] ?? {
    label: status,
    color: "bg-muted text-muted-foreground",
    icon: AlertCircle,
  }
}

function getFormatBadge(format: string | null | undefined) {
  if (!format) return null
  return {
    label: getFormatLabel(format),
    icon: FORMAT_ICONS[format] ?? FileSpreadsheet,
  }
}

// ============================================================================
// COMPONENT
// ============================================================================

export function DocumentsTab({ profile, isEditable: _isEditable }: DocumentsTabProps) {
  // `isEditable` is retained on the props contract for parent callers, but
  // per-row visibility is now fully driven by `doc.can_*` flags (PR #5).
  const documents = profile.documents_checklist || []
  const uploadMutation = useUploadAdmissionDocument(profile.id)
  const paperMutation = useMarkPaperSubmitted(profile.id)
  const rejectMutation = useRejectDocument(profile.id)
  const resetMutation = useResetDocument(profile.id)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedDocCode, setSelectedDocCode] = useState<string | null>(null)

  // Submission Format Dialog State
  const [submissionFormatDialog, setSubmissionFormatDialog] = useState<{
    isOpen: boolean
    docCode: string
    docLabel: string
    requiredFormat?: string
    action: 'upload' | 'paper'
    file?: File
  } | null>(null)
  const [selectedFormat, setSelectedFormat] = useState<string>("")

  // Reset/Undo Confirmation Dialog State
  const [pendingResetDoc, setPendingResetDoc] = useState<{code: string, label: string} | null>(null)

  // Rejection Dialog State
  const [rejectItem, setRejectItem] = useState<{code: string, label: string} | null>(null)
  const [rejectReason, setRejectReason] = useState("")

  // Upload config
  const uploadConfig = profile.applied_rules.upload_config
  const allowedTypes = uploadConfig?.allowed_types || []
  const maxFileSize = uploadConfig?.max_file_size || 0
  const maxFileSizeMB = maxFileSize > 0 ? Math.round(maxFileSize / (1024 * 1024)) : 10
  const allowedExtensionsDisplay = uploadConfig?.allowed_extensions?.length
    ? uploadConfig.allowed_extensions.map(ext => `.${ext}`).join(", ")
    : "N/A"
  // Separate accept value — never use display fallback "N/A" for the file input
  const acceptAttr = uploadConfig?.allowed_extensions?.length
    ? uploadConfig.allowed_extensions.map(ext => `.${ext}`).join(",")
    : ""

  const handleUploadClick = (code: string, label: string, requiredFormat?: string) => {
    setSelectedDocCode(code)
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
      fileInputRef.current.click()
    }

    // Prepare dialog for format selection after file is chosen
    setSubmissionFormatDialog({
      isOpen: false, // Will open after file selection
      docCode: code,
      docLabel: label,
      requiredFormat,
      action: 'upload'
    })
    setSelectedFormat(requiredFormat || "")
  }

  const validateFile = (file: File): string | null => {
    if (allowedTypes.length > 0 && !allowedTypes.includes(file.type)) {
      return `Loại file không hợp lệ. Chỉ chấp nhận: ${allowedExtensionsDisplay}`
    }
    if (maxFileSize > 0 && file.size > maxFileSize) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1)
      return `File quá lớn (${sizeMB}MB). Tối đa ${maxFileSizeMB}MB.`
    }
    return null
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !selectedDocCode) return

    const error = validateFile(file)
    if (error) {
      toast.error(error)
      return
    }

    // Open format selection dialog with file
    if (submissionFormatDialog) {
      setSubmissionFormatDialog({
        ...submissionFormatDialog,
        isOpen: true,
        file
      })
    }
  }

  const handlePaperSubmit = (code: string, label: string, requiredFormat?: string) => {
    // Open format selection dialog
    setSubmissionFormatDialog({
      isOpen: true,
      docCode: code,
      docLabel: label,
      requiredFormat,
      action: 'paper'
    })
    setSelectedFormat(requiredFormat || "")
  }

  const handleSubmissionFormatConfirm = async () => {
    if (!submissionFormatDialog || !selectedFormat) return

    const { action, docCode, file } = submissionFormatDialog

    if (action === 'upload' && file) {
      // Upload with format
      uploadMutation.mutate({
        docCode,
        file,
        actualSubmissionFormat: selectedFormat
      })
    } else if (action === 'paper') {
      // Mark paper submitted with format
      paperMutation.mutate({
        docCode,
        actualSubmissionFormat: selectedFormat
      })
    }

    // Close dialog
    setSubmissionFormatDialog(null)
    setSelectedFormat("")
  }

  const handleRejectClick = (code: string, label: string) => {
    setRejectItem({ code, label })
    setRejectReason("")
  }
  
  const confirmReject = () => {
    if (!rejectItem) return
    if (!rejectReason.trim()) {
      toast.error("Vui lòng nhập lý do từ chối")
      return
    }
    
    rejectMutation.mutate(
      { docCode: rejectItem.code, reason: rejectReason },
      {
        onSuccess: () => {
          setRejectItem(null)
        }
      }
    )
  }

  const handleViewDocument = (filePath: string) => {
    if (!isSafeFilePath(filePath)) return
    const cleanPath = filePath.startsWith("/") ? filePath.slice(1) : filePath
    const url = `${process.env.NEXT_PUBLIC_API_URL || ""}/${cleanPath}`
    window.open(url, "_blank", "noopener,noreferrer")
  }
  
  // Stats — split into three buckets so the surface matches the backend
  // mandatory-doc gate (admission_service.py:566) without losing officer
  // workflow visibility:
  //   recordedCount   -> received in any form (uploaded | paper_submitted | verified)
  //   satisfiedCount  -> backend would treat as completing the requirement
  //                       (verified | paper_submitted). This is the
  //                       "Hoàn tất yêu cầu" metric for the progress bar.
  //   pendingCount    -> uploaded but not yet officer-verified ("Chờ kiểm tra")
  // Without the satisfied/pending split, a paper-only mandatory row sitting
  // at paper_submitted would render as incomplete in the UI even though
  // the backend already accepts it as satisfied. ADM-031.6 follow-up.
  const recordedCount = documents.filter((d) => isDocumentRecorded(d.status)).length
  const satisfiedCount = documents.filter((d) => isDocumentRequirementSatisfied(d.status)).length
  const pendingCount = documents.filter((d) => isDocumentPendingVerification(d.status)).length
  const mandatoryDocs = documents.filter((d) => d.is_mandatory)
  const mandatorySatisfiedCount = mandatoryDocs.filter((d) =>
    isDocumentRequirementSatisfied(d.status),
  ).length

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="h-5 w-5" />
                Tài liệu hồ sơ
              </CardTitle>
              <CardDescription>
                Đã ghi nhận {recordedCount}/{documents.length}
                {pendingCount > 0 && (
                  <> • Chờ kiểm tra {pendingCount}</>
                )}
                {" • "}
                Hoàn tất yêu cầu {satisfiedCount}/{documents.length}
                {mandatoryDocs.length > 0 && (
                  <span className="ml-2">
                    (Bắt buộc đã hoàn tất: {mandatorySatisfiedCount}/{mandatoryDocs.length})
                  </span>
                )}
              </CardDescription>
            </div>
            {/* Progress bar reflects backend mandatory-completion semantics:
                the success fill = `verified | paper_submitted` (rows the
                backend already accepts as satisfying the requirement), the
                lighter background fill = total received including the
                pending-verify queue. Aligning with the backend gate
                prevents paper-only rows that have been correctly logged as
                paper_submitted from looking incomplete. ADM-031.6
                follow-up. */}
            <div className="flex items-center gap-2">
              <div
                className="relative w-32 h-2 bg-muted rounded-full overflow-hidden"
                role="progressbar"
                aria-label="Tiến độ hoàn tất tài liệu"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={
                  documents.length > 0
                    ? Math.round((satisfiedCount / documents.length) * 100)
                    : 0
                }
              >
                <div
                  className="absolute inset-y-0 left-0 bg-info-200 transition-[width] duration-300"
                  style={{
                    width: documents.length > 0
                      ? `${(recordedCount / documents.length) * 100}%`
                      : "0%",
                  }}
                />
                <div
                  className="absolute inset-y-0 left-0 bg-success-600 transition-[width] duration-300"
                  style={{
                    width: documents.length > 0
                      ? `${(satisfiedCount / documents.length) * 100}%`
                      : "0%",
                  }}
                />
              </div>
              <span className="text-sm text-muted-foreground font-medium">
                {documents.length > 0
                  ? Math.round((satisfiedCount / documents.length) * 100)
                  : 0}%
              </span>
            </div>
          </div>
          
          <p className="text-xs text-muted-foreground mt-2">
            Định dạng: {allowedExtensionsDisplay} • Tối đa {maxFileSizeMB}MB
          </p>
        </CardHeader>
        
        <CardContent>
          {documents.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p>Chưa có danh sách tài liệu</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc, index) => {
                const statusConfig = getStatusConfig(doc.status)
                const formatBadge = getFormatBadge(doc.submission_format)
                const StatusIcon = statusConfig.icon
                const FormatIcon = formatBadge?.icon || FileSpreadsheet

                const isUploading = uploadMutation.isPending && selectedDocCode === doc.code
                const isPaperPending = paperMutation.isPending && paperMutation.variables?.docCode === doc.code
                const hasFile = doc.file_path && (doc.status === "uploaded" || doc.status === "verified")
                const requiresUpload = doc.requires_upload !== false // Default true if undefined
                const isPaperDoc = !requiresUpload
                // Task-oriented hint surfaced inline for missing rows so the
                // officer/applicant immediately knows the next physical step
                // ("upload a scan" vs "bring paper to counter").
                const isMissing = doc.status === "missing"
                const taskHint = isMissing
                  ? requiresUpload
                    ? "Cần tải ảnh/scan"
                    : "Nhận bản giấy tại quầy"
                  : null
                // PR #5: per-row permission flags from backend replace the
                // coarse `can('edit')` gate — the matching button shows iff
                // the route would authorise the action for this user.
                const canUpload = doc.can_upload ?? false
                const canReject = doc.can_reject ?? false
                const canReset = doc.can_reset ?? false
                const canMarkPaperSubmitted = doc.can_mark_paper_submitted ?? false
                
                // ADM-031 round 2: mode badge replaces the old "Online" /
                // "Nộp giấy" pair so the wording matches the actual workflow
                // ("Cần file" = needs upload, "Ghi nhận giấy" = paper-only
                // checklist). Tooltip explains the difference for officers
                // unfamiliar with the term.
                const modeLabel = requiresUpload ? "Cần file" : "Ghi nhận giấy"
                const modeTitle = requiresUpload
                  ? "Cần tải ảnh/scan/PDF của giấy tờ lên hệ thống"
                  : "Chỉ ghi nhận đã nhận bản giấy, không cần upload file"
                const ModeIcon = requiresUpload ? Globe : Building2

                // ADM-031 round 4: surface the actually-recorded format so
                // officers can verify what they (or a teammate) declared at
                // upload/paper-receipt time. Priority mirrors the executive
                // summary view: verified > actual > none. The required
                // format stays in the "Yêu cầu bản nộp" badge regardless,
                // so a mismatch between required and actual is visually
                // diff-able at a glance.
                const recordedFormatCode =
                  doc.status === "verified" && doc.verified_format
                    ? doc.verified_format
                    : doc.actual_submission_format ?? null
                const recordedFormatLabel = recordedFormatCode
                  ? getFormatLabel(recordedFormatCode)
                  : null
                const recordedLabelHeader =
                  doc.status === "verified" ? "Đã kiểm tra (loại bản)" : "Đã ghi nhận (loại bản)"
                const recordedFormatColor =
                  doc.status === "verified"
                    ? "border-success-300 bg-success-50 text-success-800"
                    : "border-info-300 bg-info-50 text-info-800"
                const recordedDiffersFromRequired =
                  recordedFormatCode &&
                  doc.submission_format &&
                  recordedFormatCode !== doc.submission_format

                return (
                  <div
                    key={doc.code || index}
                    className="flex flex-col gap-3 p-3 border rounded-lg hover:bg-muted/30 transition-colors md:flex-row md:items-center md:gap-4"
                  >
                    {/* Title block — name + mandatory star + meta + task hint.
                        Same on mobile and desktop. */}
                    <div className="flex items-start gap-3 flex-1 min-w-0">
                      <div className="p-2 bg-muted rounded shrink-0">
                        <FileText className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium flex items-center gap-1 truncate">
                          {doc.label}
                          {doc.is_mandatory && (
                            <span className="text-error-500 text-xs">*</span>
                          )}
                        </p>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                          <span>Mã: {doc.code}</span>
                          {doc.uploaded_at && (
                            <span>• {new Date(doc.uploaded_at).toLocaleDateString("vi-VN")}</span>
                          )}
                          {doc.status === "rejected" && doc.rejection_reason && (
                            <span className="text-error-600 font-medium">
                              • Lý do: {doc.rejection_reason}
                            </span>
                          )}
                        </div>
                        {taskHint && (
                          <p className="text-xs text-warning-700 font-medium mt-1">
                            {taskHint}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Metadata block — labelled key/value rows on mobile per
                        ADM-031 round 2 wireframe; collapses to horizontal
                        badge cluster on desktop. The labels are
                        ``md:hidden`` so they vanish on desktop without
                        wrapping the badges in extra DOM. */}
                    <div className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 text-sm md:flex md:flex-wrap md:items-center md:gap-2 md:max-w-[22rem] md:justify-end">
                      {formatBadge && (
                        <>
                          <span className="text-xs text-muted-foreground self-center md:hidden">
                            Yêu cầu bản nộp
                          </span>
                          <Badge
                            variant="outline"
                            className="text-xs gap-1 max-w-full justify-start md:justify-center"
                            title={`Yêu cầu hồ sơ: ${formatBadge.label}`}
                          >
                            <FormatIcon className="h-3 w-3 shrink-0" />
                            <span className="truncate">{formatBadge.label}</span>
                          </Badge>
                        </>
                      )}
                      {/* ADM-031 round 4: show the actual / verified format so
                          officers don't have to re-open the document to recall
                          what they declared. Border colour signals the source
                          (verified vs officer-declared) without an extra
                          legend; mismatch with the required format is also
                          flagged via title tooltip. */}
                      {recordedFormatLabel && (
                        <>
                          <span className="text-xs text-muted-foreground self-center md:hidden">
                            {recordedLabelHeader}
                          </span>
                          <Badge
                            variant="outline"
                            className={`text-xs gap-1 max-w-full justify-start md:justify-center ${recordedFormatColor}`}
                            title={
                              recordedDiffersFromRequired
                                ? `${recordedLabelHeader}: ${recordedFormatLabel} — KHÁC yêu cầu hồ sơ (${formatBadge?.label ?? doc.submission_format})`
                                : `${recordedLabelHeader}: ${recordedFormatLabel}`
                            }
                          >
                            <FormatIcon className="h-3 w-3 shrink-0" />
                            <span className="truncate">{recordedFormatLabel}</span>
                            {recordedDiffersFromRequired && (
                              <AlertTriangle
                                className="h-3 w-3 shrink-0 text-warning-700"
                                aria-label="Khác yêu cầu hồ sơ"
                              />
                            )}
                          </Badge>
                        </>
                      )}
                      <span className="text-xs text-muted-foreground self-center md:hidden">
                        Cách ghi nhận
                      </span>
                      <Badge
                        variant="secondary"
                        className="text-xs gap-1 justify-start md:justify-center w-fit"
                        title={modeTitle}
                      >
                        <ModeIcon className="h-3 w-3" />
                        {modeLabel}
                      </Badge>
                      <span className="text-xs text-muted-foreground self-center md:hidden">
                        Trạng thái
                      </span>
                      <Badge
                        className={`${statusConfig.color} max-w-full justify-start md:justify-center`}
                        title={statusConfig.label}
                      >
                        <StatusIcon className="h-3 w-3 mr-1 shrink-0" />
                        <span className="truncate">{statusConfig.label}</span>
                      </Badge>
                    </div>

                    {/* Actions — labelled on mobile, compact horizontal cluster
                        on desktop. Inner div keeps the buttons grouped so
                        flex-wrap operates within the action area only. */}
                    <div className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 md:flex md:flex-wrap md:items-center md:gap-2 md:justify-end md:shrink-0">
                      <span className="text-xs text-muted-foreground self-center md:hidden">
                        Thao tác
                      </span>
                      <div className="flex flex-wrap items-center gap-2">
                      {/* View button for uploaded documents */}
                      {hasFile && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleViewDocument(doc.file_path!)}
                          title="Xem tài liệu"
                          aria-label="Xem tài liệu"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                      )}

                      {/* Upload action — requires_upload=true rows. Label is
                          "Tải file" to match the task-oriented hint above. */}
                      {canUpload && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleUploadClick(doc.code, doc.label, doc.submission_format ?? undefined)}
                          disabled={uploadMutation.isPending}
                          aria-label="Tải file"
                        >
                          {isUploading ? (
                            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                          ) : (
                            <Upload className="h-4 w-4 mr-1" />
                          )}
                          Tải file
                        </Button>
                      )}

                      {/* Paper-receipt action — requires_upload=false rows.
                          Officer-only by backend permission flag. The spec
                          replaced the old "Đã nộp" checkbox with an explicit
                          button so the action is unambiguous. */}
                      {canMarkPaperSubmitted && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handlePaperSubmit(doc.code, doc.label, doc.submission_format ?? undefined)}
                          disabled={isPaperPending}
                          aria-label="Đánh dấu đã nhận giấy"
                        >
                          {isPaperPending ? (
                            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                          ) : (
                            <Building2 className="h-4 w-4 mr-1" />
                          )}
                          Đánh dấu đã nhận giấy
                        </Button>
                      )}

                      {/* Paper already submitted indicator */}
                      {isPaperDoc && doc.status === "paper_submitted" && (
                        <Check className="h-4 w-4 text-success-600" />
                      )}
                      
                      {/* Reject Button (Officer Only) */}
                      {canReject && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-error-600 hover:text-error-700 hover:bg-error-50"
                          onClick={() => handleRejectClick(doc.code, doc.label)}
                          title="Từ chối tài liệu"
                          aria-label="Từ chối"
                        >
                          <Ban className="h-4 w-4" />
                        </Button>
                      )}

                      {/* Reset/Undo Button — gated by backend can_reset flag */}
                      {canReset && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-warning-600 hover:text-warning-700 hover:bg-warning-50"
                          onClick={() => setPendingResetDoc({ code: doc.code, label: doc.label })}
                          disabled={resetMutation.isPending}
                          title="Hoàn tác (đưa về trạng thái chưa nộp)"
                          aria-label="Đặt lại"
                        >
                          {resetMutation.isPending && resetMutation.variables === doc.code ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <RotateCcw className="h-4 w-4" />
                          )}
                        </Button>
                      )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
        
        {/* Hidden File Input */}
        <input 
          type="file" 
          ref={fileInputRef} 
          className="hidden" 
          onChange={handleFileChange}
          accept={acceptAttr}
        />
      </Card>
      
      {/* Submission Format Selection Dialog
          Officer / applicant declares the *actual* paper/file type they
          just received. ADM-031 round 2 splits the wording per action so
          the upload flow ("File này là bản gì?") and the paper-receipt
          flow ("Bản giấy vừa nhận là bản gì?") are unambiguous. The dialog
          deliberately does NOT ask for an extra evidence document. */}
      <Dialog
        open={submissionFormatDialog?.isOpen || false}
        onOpenChange={(open) => !open && setSubmissionFormatDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {submissionFormatDialog?.action === "paper"
                ? "Xác nhận bản giấy vừa nhận"
                : "Tải file tài liệu"}
            </DialogTitle>
            <DialogDescription>
              Tài liệu: <strong>{submissionFormatDialog?.docLabel}</strong>
            </DialogDescription>
          </DialogHeader>

          {submissionFormatDialog?.requiredFormat && (
            <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
              <span className="text-muted-foreground">Yêu cầu hồ sơ: </span>
              <span className="font-medium">
                {getFormatLabel(submissionFormatDialog.requiredFormat)}
              </span>
            </div>
          )}

          <p className="text-sm font-medium">
            {submissionFormatDialog?.action === "paper"
              ? "Bản giấy vừa nhận là bản gì?"
              : "File này là bản gì?"}
          </p>

          <RadioGroup value={selectedFormat} onValueChange={setSelectedFormat}>
            {DOCUMENT_FORMAT_OPTIONS.map((option) => (
              <div
                key={option.value}
                className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-muted/50 transition-colors"
              >
                <RadioGroupItem value={option.value} id={option.value} />
                <Label htmlFor={option.value} className="flex-1 cursor-pointer">
                  <div className="font-medium">{option.label}</div>
                  <div className="text-xs text-muted-foreground">
                    {option.description}
                  </div>
                </Label>
              </div>
            ))}
          </RadioGroup>

          {/* Soft warning — selected actual format does not match the
              required format. Allowed (officer may still proceed) but
              flagged so officer notices any mismatch before saving.
              Wording is action-aware: upload flow says "trước khi tải
              file"; paper flow says "trước khi ghi nhận". */}
          {submissionFormatDialog?.requiredFormat &&
            selectedFormat &&
            selectedFormat !== submissionFormatDialog.requiredFormat && (
              <div
                className="flex items-start gap-2 rounded-md border border-warning-300 bg-warning-50 px-3 py-2 text-sm text-warning-800"
                role="alert"
              >
                <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <span>
                  {submissionFormatDialog.action === "paper"
                    ? "Bản giấy thực tế khác yêu cầu hồ sơ. Hãy kiểm tra lại trước khi ghi nhận."
                    : "Loại bản trong file khác yêu cầu hồ sơ. Hãy kiểm tra lại trước khi tải file."}
                </span>
              </div>
            )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setSubmissionFormatDialog(null)}>
              Hủy
            </Button>
            <Button
              onClick={handleSubmissionFormatConfirm}
              disabled={!selectedFormat}
            >
              {submissionFormatDialog?.action === "paper" ? "Ghi nhận giấy" : "Tải file"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rejection Dialog */}
      <Dialog open={!!rejectItem} onOpenChange={(open) => !open && setRejectItem(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Từ chối tài liệu</DialogTitle>
            <DialogDescription>
              Vui lòng nhập lý do từ chối tài liệu <strong>{rejectItem?.label}</strong>.
              Học sinh sẽ nhận được thông báo để nộp lại.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <Label htmlFor="reject-reason" className="mb-2 block">Lý do từ chối</Label>
            <Textarea
              id="reject-reason"
              placeholder="VD: Tài liệu mờ, không đúng định dạng..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectItem(null)}>Huỷ</Button>
            <Button
              variant="destructive"
              onClick={confirmReject}
              disabled={rejectMutation.isPending || !rejectReason.trim()}
            >
              {rejectMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Xác nhận từ chối
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset/Undo Document Confirmation Dialog */}
      <AlertDialog open={!!pendingResetDoc} onOpenChange={(open) => !open && setPendingResetDoc(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Hoàn tác tài liệu?</AlertDialogTitle>
            <AlertDialogDescription>
              Hoàn tác tài liệu &ldquo;{pendingResetDoc?.label}&rdquo;?
              {"\n\n"}Tài liệu sẽ về trạng thái &ldquo;Chưa nộp&rdquo; và file sẽ bị xóa (nếu có).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (pendingResetDoc) {
                  resetMutation.mutate(pendingResetDoc.code)
                }
                setPendingResetDoc(null)
              }}
            >
              Hoàn tác
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
