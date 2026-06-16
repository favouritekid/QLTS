"use client"

/**
 * Documents Tab Component
 *
 * Officer-facing documents surface for an admission profile. ADM-031
 * round 5 refactor: replaces the per-row badge cluster with a KPI strip
 * + responsive table layout so officers can see at a glance how many
 * documents exist, what action each row needs, and the current state.
 *
 * Layout:
 * - Top: KPI strip (Tổng tài liệu / Đã ghi nhận / Chờ kiểm tra / Hoàn tất).
 * - Desktop md+: semantic <table> with columns
 *     # | Tên giấy tờ | Yêu cầu | Đã ghi nhận | Cách ghi nhận | Trạng thái | Thao tác
 * - Mobile <md: stacked card per row reusing the same row-state helpers.
 *
 * Rows are sorted by a work-queue priority so missing/rejected docs
 * surface first, uploaded/paper_submitted docs (waiting for verify) are
 * second, and verified docs sink to the bottom. Within the same
 * priority, mandatory docs precede optional ones.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge, badgeVariants } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  AlertCircle,
  AlertTriangle,
  Ban,
  Building2,
  Camera,
  Check,
  Eye,
  FileCheck,
  FileSpreadsheet,
  FileText,
  Globe,
  GraduationCap,
  Loader2,
  RotateCcw,
  Upload,
  XCircle,
} from "lucide-react"
import { PriorityEvidenceUploadCell } from "@/components/documents/PriorityEvidenceUploadCell"
import type {
  AdmissionProfileResponse,
  DocumentItem,
} from "@/lib/zod/admissions"
import {
  useUploadAdmissionDocument,
  useMarkPaperSubmitted,
  useUpdateGraduationProof,
  useRejectDocument,
  useResetDocument,
  useVerifyDocument,
} from "@/hooks/admissions/useAdmissions"
import { useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import {
  DOCUMENT_FORMAT_OPTIONS,
  getFormatLabel,
  getShortFormatLabel,
  isDocumentRecorded,
  isDocumentRequirementSatisfied,
  isDocumentPendingVerification,
} from "@/lib/utils/admission-helpers"
import { API_BASE_URL } from "@/lib/api/client"

interface DocumentsTabProps {
  profile: AdmissionProfileResponse
  isEditable: boolean
}

// ============================================================================
// CONSTANTS
// ============================================================================

// ADM-031 round 9 — Trạng thái cell carries workflow state only.
// Backend strict mode (admission_service.py:566) treats `paper_submitted`
// as already satisfying the mandatory-doc gate alongside `verified`, so
// the badge for that state is "Đã nhận giấy" (officer received the
// paper, no extra verify step needed) — NOT "Chờ duyệt", which would
// imply the row is still pending the manager. "Đã ghi nhận" cell
// separately reports physical reception ("Chưa" / "File scan" /
// "Bản giấy") so the two cells don't echo each other.
const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: typeof AlertCircle }
> = {
  missing: {
    label: "Cần làm",
    color: "bg-muted text-muted-foreground",
    icon: AlertCircle,
  },
  uploaded: {
    label: "Chờ duyệt",
    color: "bg-info-100 text-info-700",
    icon: Upload,
  },
  paper_submitted: {
    // Round 9: backend already treats paper_submitted as "đủ yêu cầu",
    // so the badge reads "Đã nhận giấy" (success-tinted) instead of
    // "Chờ duyệt" — keeping the row consistent with the
    // "Hoàn tất yêu cầu" KPI count.
    label: "Đã nhận giấy",
    color: "bg-success-50 text-success-700",
    icon: FileText,
  },
  verified: {
    label: "Đã duyệt",
    color: "bg-success-100 text-success-700",
    icon: Check,
  },
  rejected: {
    label: "Từ chối",
    color: "bg-error-100 text-error-700",
    icon: XCircle,
  },
}

// Reception bucket — compact "what-was-received" label that mirrors the
// backend mandatory-completion gate. Showing this in the "Đã ghi nhận"
// table cell avoids having to read the full status badge for the common
// case. Round 8: longer phrasing ("File scan" / "Bản giấy") so the
// reception verb is unambiguous on its own line.
const RECEPTION_LABEL: Record<string, string> = {
  missing: "Chưa",
  rejected: "Chưa",
  resubmitted: "File scan",
  revision_requested: "File scan",
  uploaded: "File scan",
  verified: "File scan",
  paper_submitted: "Bản giấy",
}

// Work-queue priority. Officers act on rows in this order: things they
// (or a teammate) still owe -> things waiting for verification -> done.
// Lower number = sorts first.
//
// ADM-031 round 10 review (D1): paper_submitted moved from bucket 2
// (waiting) to bucket 3 (done). Backend strict-mode at
// admission_service.py:566 counts paper_submitted as satisfying the
// mandatory gate (round 9 alignment), the row badge is success-tinted
// "Đã nhận giấy", and isDocumentRequirementSatisfied returns true for
// it. Sorting it next to "uploaded" (Chờ duyệt) put a "done" row in
// the middle of the work queue and contradicted the badge color in
// the same row — keep all three "satisfied" states in one bucket.
const STATUS_PRIORITY: Record<string, number> = {
  missing: 1,
  rejected: 1,
  revision_requested: 1,
  resubmitted: 2,
  uploaded: 2,
  paper_submitted: 3,
  verified: 3,
}

// Icon mapping for submission format. Labels come from admission-helpers
// (single source of truth) — do not duplicate text here.
const FORMAT_ICONS: Record<string, typeof Camera> = {
  photo: Camera,
  certified_copy: FileCheck,
  original: FileSpreadsheet,
}

// ADM-031.5 / WIG: cache the Intl.DateTimeFormat so we don't allocate one
// per row. Vietnamese dd/mm/yyyy.
const VI_DATE_FORMATTER = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
})

// ADM-031 round 10 — full datetime (dd/mm/yyyy hh:mm) used by the verifier
// tooltip on the Trạng thái cell so officers can see the exact verification
// timestamp without hovering long enough for a relative-time tooltip.
const VI_DATETIME_FORMATTER = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
})

// PR #13 — only this document distinguishes the official diploma from the
// provisional graduation certificate ("nợ bằng"). Kept in one place so the
// graduation-proof UI branches stay tied to the backend's hard-checked code.
const GRADUATION_DOC_CODE = "bang_tot_nghiep_thpt"

// Format the supplement due date (backend "YYYY-MM-DD", date-only) → dd/mm/yyyy.
// Parse the parts manually: ``new Date("YYYY-MM-DD")`` is interpreted as UTC
// midnight and would shift back a day when rendered in VN (UTC+7).
function formatSupplementDue(iso: string | null | undefined): string | null {
  if (!iso) return null
  const [y, m, d] = iso.split("-").map(Number)
  if (!y || !m || !d) return null
  return VI_DATE_FORMATTER.format(new Date(y, m - 1, d))
}

// ============================================================================
// HELPERS
// ============================================================================

function getStatusConfig(status: string) {
  return (
    STATUS_CONFIG[status] ?? {
      label: status,
      color: "bg-muted text-muted-foreground",
      icon: AlertCircle,
    }
  )
}

function getFormatBadge(format: string | null | undefined) {
  if (!format) return null
  return {
    label: getFormatLabel(format),
    icon: FORMAT_ICONS[format] ?? FileSpreadsheet,
  }
}

function getReceptionLabel(status: string): string {
  return RECEPTION_LABEL[status] ?? "Chưa"
}

function sortByWorkQueue(docs: DocumentItem[]): DocumentItem[] {
  return [...docs].sort((a, b) => {
    const pa = STATUS_PRIORITY[a.status ?? ""] ?? 99
    const pb = STATUS_PRIORITY[b.status ?? ""] ?? 99
    if (pa !== pb) return pa - pb
    // Mandatory before optional within the same priority bucket.
    const ma = a.is_mandatory ? 0 : 1
    const mb = b.is_mandatory ? 0 : 1
    if (ma !== mb) return ma - mb
    return (a.label ?? a.code ?? "").localeCompare(
      b.label ?? b.code ?? "",
      "vi",
    )
  })
}

// Per-row computed state — extracted so desktop table cells and mobile
// stacked card share the same source of truth.
type RowState = ReturnType<typeof computeRowState>

function computeRowState(doc: DocumentItem) {
  const statusConfig = getStatusConfig(doc.status ?? "missing")
  const requiresUpload = doc.requires_upload !== false
  const isPaperOnly = !requiresUpload
  const formatBadge = getFormatBadge(doc.submission_format ?? null)

  // ADM-031 round 4: officer-declared / manager-verified format.
  const recordedFormatCode =
    doc.status === "verified" && doc.verified_format
      ? doc.verified_format
      : (doc.actual_submission_format ?? null)
  const recordedFormatLabel = recordedFormatCode
    ? getFormatLabel(recordedFormatCode)
    : null
  const recordedDiffersFromRequired =
    !!recordedFormatCode &&
    !!doc.submission_format &&
    recordedFormatCode !== doc.submission_format

  const receptionLabel = getReceptionLabel(doc.status ?? "missing")
  // ADM-031 round 6 — table uses the shorter verb "Tải file" / "Nhận giấy"
  // so the column doesn't drift outside its 5-rem width with the legacy
  // "Nhận giấy tại quầy". Tooltip + aria-label keep the full meaning.
  const howToReceiveLabel = requiresUpload ? "Tải file" : "Nhận giấy"
  const howToReceiveTitle = requiresUpload
    ? "Cần tải ảnh/scan/PDF của giấy tờ lên hệ thống"
    : "Ghi nhận đã nhận bản giấy trực tiếp, không cần upload file"
  const HowToReceiveIcon = requiresUpload ? Globe : Building2

  // Date-of-record — appears under the reception bucket in the
  // "Đã ghi nhận" cell so the title cell can stay focused on doc
  // identity (label + code + reject reason).
  //
  // ADM-031 round 10 review (E1): paper-only rows that progress to
  // verified must keep showing the paper-receipt date. Previous
  // logic flipped to ``uploaded_at`` once status changed away from
  // ``paper_submitted``, but ``uploaded_at`` is null for paper-only
  // docs (no scan ever uploaded), so a verified paper doc rendered
  // with no recorded date at all. Decision tree now:
  //   - paper_submitted              → paper_submitted_at
  //   - paper-only verified          → paper_submitted_at
  //                                    (uploaded_at would be null)
  //   - everything else (uploaded /  → uploaded_at
  //     online verified)
  const requiresUploadField = doc.requires_upload !== false
  const recordedAtIso =
    doc.status === "paper_submitted" || !requiresUploadField
      ? (doc.paper_submitted_at ?? doc.uploaded_at ?? null)
      : (doc.uploaded_at ?? null)
  const recordedAtFormatted = recordedAtIso
    ? VI_DATE_FORMATTER.format(new Date(recordedAtIso))
    : null

  const requiredFormatShort = doc.submission_format
    ? getShortFormatLabel(doc.submission_format)
    : null

  // ADM-031 round 10 — verifier identity for the "Đã duyệt" badge.
  // verifiedDisplayName: full name from backend → fallback "User #<id>" →
  // null when neither id nor timestamp is present (older legacy rows).
  // verifiedAtShort feeds the secondary line under the badge; verifierTooltip
  // is the long-form tooltip ("Duyệt bởi <Tên> lúc dd/mm/yyyy hh:mm").
  const verifiedAtIso = doc.verified_at ?? null
  const verifiedAtShort = verifiedAtIso
    ? VI_DATE_FORMATTER.format(new Date(verifiedAtIso))
    : null
  const verifiedAtLong = verifiedAtIso
    ? VI_DATETIME_FORMATTER.format(new Date(verifiedAtIso))
    : null
  const verifiedDisplayName =
    doc.verified_by_name?.trim() ||
    (doc.verified_by != null ? `User #${doc.verified_by}` : null)
  let verifierTooltip: string | null = null
  if (doc.status === "verified") {
    if (verifiedDisplayName && verifiedAtLong) {
      verifierTooltip = `Duyệt bởi ${verifiedDisplayName} lúc ${verifiedAtLong}`
    } else if (verifiedDisplayName) {
      verifierTooltip = `Duyệt bởi ${verifiedDisplayName}`
    } else if (verifiedAtLong) {
      verifierTooltip = `Đã duyệt lúc ${verifiedAtLong}`
    }
  }

  // PR2: a viewable file requires the ProfileDocument PK (document_id) so the
  // FE can hit the authed download endpoint. NO fallback to file_path — the
  // public /uploads mount was removed, so a raw path link would 404. A doc
  // with a file but a missing document_id (rollback/stale cache) simply has
  // no View button.
  const hasFile =
    doc.document_id != null &&
    (doc.status === "uploaded" || doc.status === "verified")
  const canUpload = doc.can_upload ?? false
  const canMarkPaperSubmitted = doc.can_mark_paper_submitted ?? false
  const canReject = doc.can_reject ?? false
  const canReset = doc.can_reset ?? false
  const canVerify = doc.can_verify ?? false
  const hasAnyAction =
    hasFile || canUpload || canMarkPaperSubmitted || canReject || canReset || canVerify

  return {
    statusConfig,
    requiresUpload,
    isPaperOnly,
    formatBadge,
    requiredFormatShort,
    recordedFormatCode,
    recordedFormatLabel,
    recordedDiffersFromRequired,
    receptionLabel,
    howToReceiveLabel,
    howToReceiveTitle,
    HowToReceiveIcon,
    hasFile,
    canUpload,
    canMarkPaperSubmitted,
    canReject,
    canReset,
    canVerify,
    hasAnyAction,
    recordedAtFormatted,
    // ADM-031 round 10
    verifiedDisplayName,
    verifiedAtShort,
    verifierTooltip,
  }
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

interface KpiTileProps {
  label: string
  value: string | number
  hint?: string
  accent?: "default" | "warning" | "info" | "success"
}

function KpiTile({ label, value, hint, accent = "default" }: KpiTileProps) {
  const accentClass =
    accent === "warning"
      ? "text-warning-700"
      : accent === "info"
        ? "text-info-700"
        : accent === "success"
          ? "text-success-700"
          : "text-foreground"
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${accentClass}`}>
        {value}
      </div>
      {hint && (
        <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
          {hint}
        </div>
      )}
    </div>
  )
}

// ADM fast-track nợ giấy tờ (TUITION_PREPAY_FASTTRACK_PLAN.md §4b ③).
// Render the "Nợ giấy tờ" banner ONLY when there are still-outstanding debt
// codes. The banner self-hides once `outstanding_debt_codes` empties (it goes
// empty once every owed doc is verified/paper_submitted — VERIFIED-based, see
// `_compute_outstanding_debt_codes` BE). L5: each code is labelled either
// "Chưa nộp" (still in `missing_doc_codes`) or "Chờ xác minh" (uploaded but not
// yet verified — in `outstanding_debt_codes` but NOT in `missing_doc_codes`),
// so an officer who just uploaded isn't confused that the badge persists.
function DocumentDebtBanner({ profile }: { profile: AdmissionProfileResponse }) {
  const outstanding = profile.outstanding_debt_codes ?? []
  if (outstanding.length === 0) return null

  const debt = profile.document_debt
  const missingSet = new Set(profile.missing_doc_codes ?? [])
  const codeLabel = new Map<string, string>()
  for (const doc of profile.documents_checklist ?? []) {
    if (doc.code && doc.label) codeLabel.set(doc.code, doc.label)
  }

  const reason = debt?.reason?.trim() || null
  // Guard against a malformed `debt.at` (Invalid Date → Intl.format throws a
  // RangeError that would crash the whole tab). Only format a valid date.
  const debtAt = debt?.at ? new Date(debt.at) : null
  const atFormatted =
    debtAt && !Number.isNaN(debtAt.getTime())
      ? VI_DATETIME_FORMATTER.format(debtAt)
      : null

  return (
    <div
      role="status"
      className="mb-4 rounded-lg border border-warning-300 bg-warning-50 p-4"
    >
      <div className="flex items-center gap-2 text-warning-800">
        <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden="true" />
        <h3 className="font-semibold">Nợ giấy tờ ({outstanding.length})</h3>
      </div>
      <p className="mt-1 text-sm text-warning-700">
        Officer đã cho nợ — học sinh bổ sung sau. Phải bổ sung và được xác minh
        đủ trước khi duyệt hồ sơ.
      </p>
      <ul className="mt-3 space-y-1.5">
        {outstanding.map((code) => {
          // L5 — distinguish not-yet-submitted vs uploaded-pending-verify.
          const pendingVerify = !missingSet.has(code)
          return (
            <li
              key={code}
              className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-warning-800"
            >
              <span className="font-medium break-words">
                {codeLabel.get(code) ?? code}
              </span>
              <Badge
                className={
                  pendingVerify
                    ? "bg-info-100 text-info-700"
                    : "bg-muted text-muted-foreground"
                }
              >
                {pendingVerify ? "Chờ xác minh" : "Chưa nộp"}
              </Badge>
            </li>
          )
        })}
      </ul>
      {(reason || atFormatted) && (
        <p className="mt-3 text-xs text-warning-700 break-words">
          {reason && <span>Lý do: {reason}</span>}
          {reason && atFormatted && <span> · </span>}
          {atFormatted && (
            <span className="tabular-nums">Ghi nhận {atFormatted}</span>
          )}
        </p>
      )}
    </div>
  )
}

interface ActionsCellProps {
  doc: DocumentItem
  state: RowState
  isUploading: boolean
  isPaperPending: boolean
  isResetPending: boolean
  isCurrentResetTarget: boolean
  isVerifyPending: boolean
  isCurrentVerifyTarget: boolean
  isGradPending: boolean
  onView: (documentId: number) => void
  onUpload: (
    code: string,
    label: string,
    requiredFormat?: string,
  ) => void
  onPaperSubmit: (
    code: string,
    label: string,
    requiredFormat?: string,
  ) => void
  onUpdateGraduationProof: (code: string, label: string) => void
  onRejectClick: (code: string, label: string) => void
  onResetClick: (code: string, label: string) => void
  onVerifyClick: (code: string, format: string) => void
  alignEnd?: boolean
}

/**
 * Icon-only button with a Radix Tooltip popup on hover/focus. Uses
 * `aria-label` for the accessible name; the tooltip content is meant
 * to convey extra description ("Đặt lại về Chưa nộp" verbose form vs
 * the short "Đặt lại" name) without duplicating the SR announcement.
 */
function IconActionButton({
  ariaLabel,
  tooltip,
  onClick,
  disabled,
  children,
  className,
}: {
  ariaLabel: string
  tooltip: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
  className?: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          className={`h-8 w-8 p-0 ${className ?? ""}`}
          onClick={onClick}
          disabled={disabled}
          aria-label={ariaLabel}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{tooltip}</TooltipContent>
    </Tooltip>
  )
}

function DocumentRowActions(props: ActionsCellProps) {
  const {
    doc,
    state,
    isUploading,
    isPaperPending,
    isResetPending,
    isCurrentResetTarget,
    isVerifyPending,
    isCurrentVerifyTarget,
    isGradPending,
    onView,
    onUpload,
    onPaperSubmit,
    onUpdateGraduationProof,
    onRejectClick,
    onResetClick,
    onVerifyClick,
    alignEnd,
  } = props

  // PR #13 — "nợ bằng" debt badge (provisional cert still outstanding) +
  // the officer/manager "đã nhận bằng chính thức" action that clears it.
  const isProvisionalDebt = doc.graduation_proof_kind === "provisional_cert"
  const canUpdateGraduationKind = doc.can_update_graduation_kind ?? false
  const supplementDueLabel = formatSupplementDue(doc.supplement_due_date)

  // Verify uses the actual / required format as the format claim. The
  // verify dialog (executive checklist) is the deeper review surface;
  // here the button is a one-click confirm for officers/managers who
  // already match required to actual.
  const verifyFormat =
    doc.actual_submission_format ?? doc.submission_format ?? "photo"

  if (!state.hasAnyAction && !(state.isPaperOnly && doc.status === "paper_submitted")) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  // ADM-031 round 8: 3 visual groups separated by thin dividers so the
  // officer scans intent quickly:
  //   - common: View
  //   - officer (intake): Upload, Mark paper-submitted
  //   - manager (review): Verify, Reject, Reset
  // Each button is icon-only with Radix Tooltip on hover + aria-label
  // for screen readers; no `title` attribute so SR doesn't double-read.
  const hasCommon = state.hasFile
  const hasOfficerGroup = state.canUpload || state.canMarkPaperSubmitted
  const hasManagerGroup = state.canVerify || state.canReject || state.canReset

  return (
    <TooltipProvider delayDuration={150}>
      <div
        className={`flex flex-wrap items-center gap-0.5 ${alignEnd ? "justify-end" : ""}`}
      >
        {/* Common */}
        {state.hasFile && (
          <IconActionButton
            ariaLabel="Xem tài liệu"
            tooltip="Xem file đã tải lên"
            onClick={() => doc.document_id != null && onView(doc.document_id)}
          >
            <Eye className="h-4 w-4" />
          </IconActionButton>
        )}

        {hasCommon && (hasOfficerGroup || hasManagerGroup) && (
          <span
            aria-hidden="true"
            className="mx-1 inline-block h-4 w-px bg-border"
          />
        )}

        {/* Officer / intake group */}
        {state.canUpload && (
          <IconActionButton
            ariaLabel="Tải file"
            tooltip="Tải file ảnh/scan/PDF lên hệ thống"
            disabled={isUploading}
            onClick={() =>
              onUpload(doc.code, doc.label, doc.submission_format ?? undefined)
            }
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
          </IconActionButton>
        )}

        {state.canMarkPaperSubmitted && (
          <IconActionButton
            ariaLabel="Đánh dấu đã nhận giấy"
            tooltip="Đánh dấu đã nhận bản giấy tại quầy"
            disabled={isPaperPending}
            onClick={() =>
              onPaperSubmit(
                doc.code,
                doc.label,
                doc.submission_format ?? undefined,
              )
            }
          >
            {isPaperPending ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <Building2 className="h-4 w-4" />
            )}
          </IconActionButton>
        )}

        {state.isPaperOnly &&
          doc.status === "paper_submitted" &&
          !state.canReject &&
          !state.canReset &&
          !state.canVerify && (
            <span className="inline-flex items-center text-success-600 text-xs">
              <Check className="h-4 w-4" aria-hidden="true" />
            </span>
          )}

        {/* PR #13 — "nợ bằng" debt badge + clear-debt action. */}
        {isProvisionalDebt && (
          <span
            className="inline-flex items-center gap-1 rounded bg-warning-50 px-1.5 py-0.5 text-xs font-medium text-warning-700"
            title={
              supplementDueLabel
                ? `Hạn bổ sung bằng: ${supplementDueLabel}`
                : undefined
            }
          >
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            Nợ bằng{supplementDueLabel ? ` — hạn ${supplementDueLabel}` : ""}
          </span>
        )}

        {canUpdateGraduationKind && (
          <IconActionButton
            ariaLabel="Đã nhận bằng chính thức"
            tooltip="Ghi nhận đã nhận bằng tốt nghiệp THPT chính thức (xoá nợ bằng)"
            className="text-success-700 hover:text-success-800 hover:bg-success-50"
            disabled={isGradPending}
            onClick={() => onUpdateGraduationProof(doc.code, doc.label)}
          >
            {isGradPending ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <GraduationCap className="h-4 w-4" />
            )}
          </IconActionButton>
        )}

        {hasOfficerGroup && hasManagerGroup && (
          <span
            aria-hidden="true"
            className="mx-1 inline-block h-4 w-px bg-border"
          />
        )}

        {/* Manager / review group */}
        {state.canVerify && (
          <IconActionButton
            ariaLabel="Duyệt tài liệu"
            tooltip="Duyệt — xác nhận tài liệu hợp lệ"
            className="text-success-700 hover:text-success-800 hover:bg-success-50"
            disabled={isVerifyPending && isCurrentVerifyTarget}
            onClick={() => onVerifyClick(doc.code, verifyFormat)}
          >
            {isVerifyPending && isCurrentVerifyTarget ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <Check className="h-4 w-4" />
            )}
          </IconActionButton>
        )}

        {state.canReject && (
          <IconActionButton
            ariaLabel="Từ chối tài liệu"
            tooltip="Từ chối — yêu cầu nộp lại"
            className="text-error-600 hover:text-error-700 hover:bg-error-50"
            onClick={() => onRejectClick(doc.code, doc.label)}
          >
            <Ban className="h-4 w-4" />
          </IconActionButton>
        )}

        {state.canReset && (
          <IconActionButton
            ariaLabel="Đặt lại tài liệu về Chưa nộp"
            tooltip="Đặt lại — đưa về trạng thái Chưa nộp"
            className="text-warning-600 hover:text-warning-700 hover:bg-warning-50"
            disabled={isResetPending && isCurrentResetTarget}
            onClick={() => onResetClick(doc.code, doc.label)}
          >
            {isResetPending && isCurrentResetTarget ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RotateCcw className="h-4 w-4" />
            )}
          </IconActionButton>
        )}
      </div>
    </TooltipProvider>
  )
}

// ============================================================================
// COMPONENT
// ============================================================================

export function DocumentsTab({ profile }: DocumentsTabProps) {
  // `isEditable` is retained on the props contract for parent callers, but
  // per-row visibility is now fully driven by `doc.can_*` flags (PR #5).
  // We deliberately don't destructure it here — keeping it on the type so
  // TS still validates parent usage without triggering no-unused-vars.
  //
  // ADM-031 round 10 review: wrap the documents array in useMemo so the
  // identity is stable across renders. Without this, `useMemo`-based hooks
  // downstream (sortedDocs, KPI counts memoizations) re-fire on every
  // render because `profile.documents_checklist || []` allocates a fresh
  // [] when the field is null.
  const documents = useMemo(
    () => profile.documents_checklist || [],
    [profile.documents_checklist],
  )
  const uploadMutation = useUploadAdmissionDocument(profile.id)
  const paperMutation = useMarkPaperSubmitted(profile.id)
  const updateGradMutation = useUpdateGraduationProof(profile.id)
  const rejectMutation = useRejectDocument(profile.id)
  const resetMutation = useResetDocument(profile.id)
  const verifyMutation = useVerifyDocument(profile.id)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedDocCode, setSelectedDocCode] = useState<string | null>(null)

  // Submission Format Dialog State
  const [submissionFormatDialog, setSubmissionFormatDialog] = useState<{
    isOpen: boolean
    docCode: string
    docLabel: string
    requiredFormat?: string
    action: "upload" | "paper"
    file?: File
  } | null>(null)
  const [selectedFormat, setSelectedFormat] = useState<string>("")

  // PR #13 — graduation proof kind chosen inside the paper-submit dialog,
  // only for GRADUATION_DOC_CODE. Review F1: NO default — the officer must
  // explicitly pick official vs provisional (a default would let a
  // provisional cert be recorded as an official diploma, hiding the debt).
  // provisional_cert requires a supplement due date.
  const [graduationKind, setGraduationKind] = useState<
    "" | "official_diploma" | "provisional_cert"
  >("")
  const [supplementDue, setSupplementDue] = useState<string>("")

  // Reset/Undo Confirmation Dialog State
  const [pendingResetDoc, setPendingResetDoc] = useState<{
    code: string
    label: string
  } | null>(null)

  // Review F2 — confirm before clearing the "nợ bằng" debt (one-click +
  // irreversible via this flow: the endpoint only accepts official_diploma).
  const [pendingGradUpdate, setPendingGradUpdate] = useState<{
    code: string
    label: string
  } | null>(null)

  // Rejection Dialog State
  const [rejectItem, setRejectItem] = useState<{
    code: string
    label: string
  } | null>(null)
  const [rejectReason, setRejectReason] = useState("")

  // Upload config
  const uploadConfig = profile.applied_rules.upload_config
  const allowedTypes = uploadConfig?.allowed_types || []
  const maxFileSize = uploadConfig?.max_file_size || 0
  const maxFileSizeMB =
    maxFileSize > 0 ? Math.round(maxFileSize / (1024 * 1024)) : 10
  const allowedExtensionsDisplay = uploadConfig?.allowed_extensions?.length
    ? uploadConfig.allowed_extensions.map((ext) => `.${ext}`).join(", ")
    : "N/A"
  const acceptAttr = uploadConfig?.allowed_extensions?.length
    ? uploadConfig.allowed_extensions.map((ext) => `.${ext}`).join(",")
    : ""

  // BR2 (2026-04-29): split rows into the active checklist (snapshot
  // mandatory) and extras (ProfileDocument rows whose code is no
  // longer in the current applied_rules.mandatory_docs — backend now
  // surfaces them with is_extra=true instead of silently dropping).
  // KPI counts and the work-queue sort run on activeDocs only —
  // extras are evidence-only and would muddy the "what's left to do"
  // signal if mixed in.
  const activeDocs = useMemo(
    () => documents.filter((d) => !d.is_extra),
    [documents],
  )
  const extraDocs = useMemo(
    () => documents.filter((d) => d.is_extra),
    [documents],
  )

  // Q9 #07 Phase E.4 PR-3 — Eligibility summary footer (spec V3 §III).
  // Strict ``verified`` count (NOT isDocumentRequirementSatisfied which
  // also counts paper_submitted). Spec text: "Bắt buộc: 2/5 verified ·
  // cần 3 nữa" — semantic is "manager already cleared file" not
  // "officer recorded paper at counter", so paper_submitted excluded.
  const priorityEvidenceDocs = profile.priority_evidence_documents ?? []
  const eligibilitySummary = useMemo(() => {
    const mandatoryAll = activeDocs.filter((d) => d.is_mandatory)
    const mandatoryVerified = mandatoryAll.filter(
      (d) => d.status === "verified",
    ).length
    const mandatoryTotal = mandatoryAll.length
    const mandatoryRemaining = Math.max(0, mandatoryTotal - mandatoryVerified)

    const priorityUploaded = priorityEvidenceDocs.filter(
      (d) => d.document_file_path != null,
    ).length
    const priorityTotal = priorityEvidenceDocs.length
    const priorityMissingCodes = priorityEvidenceDocs
      .filter((d) => d.document_file_path == null)
      .map((d) => `UT${d.sub_code}`)

    return {
      mandatoryVerified,
      mandatoryTotal,
      mandatoryRemaining,
      priorityUploaded,
      priorityTotal,
      priorityMissingCodes,
      visible: mandatoryTotal > 0 || priorityTotal > 0,
    }
  }, [activeDocs, priorityEvidenceDocs])

  // Sort docs by work-queue priority — only resort when documents change.
  const sortedDocs = useMemo(() => sortByWorkQueue(activeDocs), [activeDocs])

  // KPI counts. Keep on the unsorted array — totals don't depend on order.
  const total = activeDocs.length
  const recordedCount = activeDocs.filter((d) =>
    isDocumentRecorded(d.status ?? ""),
  ).length
  const satisfiedCount = activeDocs.filter((d) =>
    isDocumentRequirementSatisfied(d.status ?? ""),
  ).length
  const pendingCount = activeDocs.filter((d) =>
    isDocumentPendingVerification(d.status ?? ""),
  ).length
  const mandatoryDocs = activeDocs.filter((d) => d.is_mandatory)
  const mandatorySatisfiedCount = mandatoryDocs.filter((d) =>
    isDocumentRequirementSatisfied(d.status ?? ""),
  ).length
  const satisfiedPercent =
    total > 0 ? Math.round((satisfiedCount / total) * 100) : 0

  // -- Action handlers -------------------------------------------------------

  const handleUploadClick = (
    code: string,
    label: string,
    requiredFormat?: string,
  ) => {
    setSelectedDocCode(code)
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
      fileInputRef.current.click()
    }

    setSubmissionFormatDialog({
      isOpen: false,
      docCode: code,
      docLabel: label,
      requiredFormat,
      action: "upload",
    })
    setSelectedFormat(requiredFormat || "")
  }

  const validateFile = (file: File): string | null => {
    if (allowedTypes.length > 0 && !allowedTypes.includes(file.type)) {
      return `Loại file không hợp lệ. Chỉ chấp nhận: ${allowedExtensionsDisplay}`
    }
    if (maxFileSize > 0 && file.size > maxFileSize) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1)
      return `File quá lớn (${sizeMB} MB). Tối đa ${maxFileSizeMB} MB.`
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

    if (submissionFormatDialog) {
      setSubmissionFormatDialog({
        ...submissionFormatDialog,
        isOpen: true,
        file,
      })
    }
  }

  const handlePaperSubmit = (
    code: string,
    label: string,
    requiredFormat?: string,
  ) => {
    setSubmissionFormatDialog({
      isOpen: true,
      docCode: code,
      docLabel: label,
      requiredFormat,
      action: "paper",
    })
    setSelectedFormat(requiredFormat || "")
    // PR #13 / review F1 — reset the graduation choice to UNSELECTED so the
    // officer must explicitly pick official vs provisional each time.
    setGraduationKind("")
    setSupplementDue("")
  }

  const handleSubmissionFormatConfirm = async () => {
    if (!submissionFormatDialog || !selectedFormat) return

    const { action, docCode, file } = submissionFormatDialog

    if (action === "upload" && file) {
      uploadMutation.mutate({
        docCode,
        file,
        actualSubmissionFormat: selectedFormat,
      })
    } else if (action === "paper") {
      const isGraduation = docCode === GRADUATION_DOC_CODE
      // Review F1 — the graduation doc must be classified explicitly (no
      // default); block until the officer picks a kind. The confirm button is
      // also disabled — this is defense-in-depth.
      if (isGraduation && !graduationKind) {
        toast.error("Vui lòng chọn loại giấy tốt nghiệp")
        return
      }
      // provisional_cert ("nợ bằng") requires a supplement due date.
      if (
        isGraduation &&
        graduationKind === "provisional_cert" &&
        !supplementDue
      ) {
        toast.error(
          "Vui lòng nhập hạn bổ sung bằng cho Giấy CN tốt nghiệp tạm thời",
        )
        return
      }
      paperMutation.mutate({
        docCode,
        actualSubmissionFormat: selectedFormat,
        ...(isGraduation && graduationKind
          ? {
              graduationProofKind: graduationKind,
              supplementDueDate:
                graduationKind === "provisional_cert"
                  ? supplementDue
                  : undefined,
            }
          : {}),
      })
    }

    setSubmissionFormatDialog(null)
    setSelectedFormat("")
    setGraduationKind("")
    setSupplementDue("")
  }

  // PR #13 / review F2 — officer records the official diploma after a
  // provisional cert (clears the "nợ bằng" debt). One-click + irreversible via
  // this flow, so it goes through a confirm dialog first.
  const handleUpdateGraduationProof = (code: string, label: string) => {
    setPendingGradUpdate({ code, label })
  }
  const handleGradUpdateConfirm = () => {
    if (pendingGradUpdate) {
      updateGradMutation.mutate({
        docCode: pendingGradUpdate.code,
        kind: "official_diploma",
      })
    }
    setPendingGradUpdate(null)
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
        },
      },
    )
  }

  const handleViewDocument = (documentId: number) => {
    // PR2: stream the document through the authed, IDOR-scoped, audited
    // backend endpoint. This is a top-level GET on the same origin, so the
    // access_token cookie (path "/", samesite "lax") is sent automatically.
    // API_BASE_URL is the Zod-validated host (no /api suffix); the endpoint
    // lives under /api.
    const url = `${API_BASE_URL}/api/admissions/${profile.id}/documents/${documentId}/download`
    window.open(url, "_blank", "noopener,noreferrer")
  }

  const handleResetClick = (code: string, label: string) => {
    setPendingResetDoc({ code, label })
  }

  const handleResetConfirm = () => {
    if (pendingResetDoc) {
      resetMutation.mutate(pendingResetDoc.code)
    }
    setPendingResetDoc(null)
  }

  const handleVerifyClick = (code: string, format: string) => {
    verifyMutation.mutate({ docCode: code, format })
  }

  // -- Per-row mutation helpers ---------------------------------------------

  const isUploadingForCode = (code: string) =>
    uploadMutation.isPending && selectedDocCode === code
  const isPaperPendingForCode = (code: string) =>
    paperMutation.isPending && paperMutation.variables?.docCode === code
  const isResetPendingForCode = (code: string) =>
    resetMutation.isPending && resetMutation.variables === code
  const isVerifyPendingForCode = (code: string) =>
    verifyMutation.isPending && verifyMutation.variables?.docCode === code

  // ============================================================================
  // RENDER
  // ============================================================================

  return (
    // ADM-031 round 10 — wrap the whole tab in a single TooltipProvider so
    // the Trạng thái-cell verifier tooltip and the action-icon tooltips
    // (DocumentRowActions has its own provider for legacy reasons; nested
    // is harmless) both have a context.
    <TooltipProvider delayDuration={150}>
      {/* Fast-track nợ giấy tờ banner — self-hides when no outstanding debt. */}
      <DocumentDebtBanner profile={profile} />

      {/* KPI strip — 4 tiles so officer reads the global state at a glance.
          Counts use tabular-nums so the digits stay aligned across columns. */}
      <div
        role="group"
        aria-label="Tổng quan tài liệu"
        className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4"
      >
        <KpiTile label="Tổng tài liệu" value={total} />
        <KpiTile
          label="Đã ghi nhận"
          value={`${recordedCount}/${total}`}
          accent="info"
          hint={
            mandatoryDocs.length > 0
              ? `Bắt buộc: ${mandatoryDocs.length}`
              : undefined
          }
        />
        <KpiTile
          // Round 9: rename to "File chờ duyệt" so the tile matches the
          // helper (`isDocumentPendingVerification`) which only counts
          // `uploaded`. paper_submitted rows are NOT pending — backend
          // already accepts them as satisfied.
          label="File chờ duyệt"
          value={pendingCount}
          accent={pendingCount > 0 ? "warning" : "default"}
          hint={pendingCount > 0 ? "Cần manager duyệt format" : "Không có"}
        />
        <KpiTile
          // ADM-031 round 10 review (D2): headline shows the
          // mandatory ratio because "yêu cầu" semantically refers to
          // the submission gate (which is mandatory-only). Total
          // (incl. optional) is demoted to the hint so the number
          // officers act on is the gating one.
          label="Hoàn tất yêu cầu"
          value={
            mandatoryDocs.length > 0
              ? `${mandatorySatisfiedCount}/${mandatoryDocs.length}`
              : `${satisfiedCount}/${total}`
          }
          accent="success"
          hint={
            mandatoryDocs.length > 0
              ? `Tổng: ${satisfiedCount}/${total} • ${satisfiedPercent}%`
              : `${satisfiedPercent}%`
          }
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between md:gap-4">
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="h-5 w-5" aria-hidden="true" />
                Tài liệu hồ sơ
              </CardTitle>
              <CardDescription>
                Sắp xếp theo việc cần làm: cần làm / từ chối trước, kế đến là
                chờ duyệt, cuối cùng là đã duyệt.
              </CardDescription>
            </div>
            <p
              className="text-xs text-muted-foreground tabular-nums"
              id="documents-upload-rules"
            >
              Định dạng: {allowedExtensionsDisplay} • Tối đa {maxFileSizeMB}
              {" "}MB
            </p>
          </div>
        </CardHeader>

        <CardContent className="pt-0">
          {documents.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-3 opacity-20" aria-hidden="true" />
              <p>Chưa có danh sách tài liệu</p>
            </div>
          ) : (
            <>
              {/* ----- Desktop: semantic table ----- */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                      <th scope="col" className="py-2 pr-3 text-left font-medium">
                        Tên giấy tờ
                      </th>
                      <th scope="col" className="py-2 pr-3 text-left font-medium">
                        Yêu cầu
                      </th>
                      <th scope="col" className="py-2 pr-3 text-left font-medium">
                        Đã ghi nhận
                      </th>
                      <th scope="col" className="py-2 pr-3 text-left font-medium">
                        Trạng thái
                      </th>
                      <th
                        scope="col"
                        className="py-2 pl-3 text-right font-medium"
                      >
                        Thao tác
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {sortedDocs.map((doc, i) => {
                      const state = computeRowState(doc)
                      const StatusIcon = state.statusConfig.icon
                      const HowIcon = state.HowToReceiveIcon
                      const FormatIcon = state.formatBadge?.icon
                      return (
                        <tr
                          key={doc.code || i}
                          className="hover:bg-muted/30 motion-reduce:transition-none"
                        >
                          {/* ----- Tên giấy tờ ----- round 8:
                              line 1 = name
                              line 2 = Bắt buộc / Tùy chọn
                              Mã (doc.code) moves to a hover title on the
                              name so officers don't see the technical
                              token in the main UI but can still inspect
                              it for support / debug. */}
                          <td className="py-3 pr-3 align-top min-w-0">
                            <div
                              className="font-medium text-pretty break-words"
                              title={`Mã: ${doc.code}`}
                            >
                              {doc.label}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {doc.is_mandatory ? "Bắt buộc" : "Tùy chọn"}
                            </div>
                            {doc.status === "rejected" && doc.rejection_reason && (
                              <div className="text-xs text-error-700 mt-1 break-words">
                                Lý do: {doc.rejection_reason}
                              </div>
                            )}
                          </td>

                          {/* ----- Yêu cầu ----- round 8: 2 lines stacked
                              line 1 = format (Gốc / Chứng thực / Chụp/scan)
                              line 2 = how-to (Tải file / Nhận giấy)
                              Use `flex` (not inline-flex) on each line so
                              each div takes its own row, matching the
                              2 stacked lines in "Đã ghi nhận". */}
                          <td className="py-3 pr-3 align-top">
                            {state.requiredFormatShort && state.formatBadge ? (
                              <div
                                className="text-sm flex items-center gap-1"
                                title={state.formatBadge.label}
                              >
                                {FormatIcon && (
                                  <FormatIcon
                                    className="h-3 w-3 shrink-0 text-muted-foreground"
                                    aria-hidden="true"
                                  />
                                )}
                                <span aria-label={state.formatBadge.label}>
                                  {state.requiredFormatShort}
                                </span>
                              </div>
                            ) : (
                              <div className="text-sm text-muted-foreground">
                                —
                              </div>
                            )}
                            <div
                              className="text-xs text-muted-foreground flex items-center gap-1 mt-1"
                              title={state.howToReceiveTitle}
                              aria-label={state.howToReceiveTitle}
                            >
                              <HowIcon
                                className="h-3 w-3 shrink-0"
                                aria-hidden="true"
                              />
                              <span>{state.howToReceiveLabel}</span>
                            </div>
                          </td>

                          {/* ----- Đã ghi nhận ----- round 8: 2 lines
                              line 1 = actual format short + recorded date
                                       (e.g. "Chứng thực · 29/04/2026")
                                       — empty for missing/rejected.
                              line 2 = reception bucket
                                       ("File scan" / "Bản giấy" / "Chưa")
                              Alignment matches the 2 lines in "Yêu cầu"
                              so a row reads as a 2x2 mini grid. */}
                          <td className="py-3 pr-3 align-top">
                            {state.recordedFormatLabel ? (
                              <>
                                <div
                                  className={`text-sm flex items-center gap-1 break-words ${
                                    state.recordedDiffersFromRequired
                                      ? "text-warning-700"
                                      : ""
                                  }`}
                                  title={
                                    state.recordedDiffersFromRequired
                                      ? `Đã ghi nhận: ${state.recordedFormatLabel} — KHÁC yêu cầu hồ sơ (${state.formatBadge?.label ?? doc.submission_format})`
                                      : `Đã ghi nhận: ${state.recordedFormatLabel}`
                                  }
                                >
                                  {state.recordedDiffersFromRequired && (
                                    <AlertTriangle
                                      className="h-3 w-3 shrink-0"
                                      aria-label="Khác yêu cầu hồ sơ"
                                    />
                                  )}
                                  <span>
                                    {state.recordedFormatCode
                                      ? getShortFormatLabel(state.recordedFormatCode)
                                      : state.recordedFormatLabel}
                                  </span>
                                  {state.recordedAtFormatted && (
                                    <span className="text-muted-foreground tabular-nums">
                                      · {state.recordedAtFormatted}
                                    </span>
                                  )}
                                </div>
                                <div className="text-xs text-muted-foreground mt-1">
                                  {state.receptionLabel}
                                </div>
                              </>
                            ) : (
                              // Nothing recorded yet — show only the reception
                              // bucket ("Chưa"). No leading em-dash so the cell
                              // doesn't read as "— Chưa".
                              <div className="text-sm">{state.receptionLabel}</div>
                            )}
                          </td>
                          <td className="py-3 pr-3 align-top">
                            {state.verifierTooltip ? (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  {/* P3 review fix: tooltip trigger must
                                      be focusable (Badge is a non-focusable
                                      <div>). Render as a real <button> styled
                                      with badgeVariants() so keyboard users
                                      can read the long-form tooltip
                                      ("Duyệt bởi <Tên> lúc dd/mm/yyyy hh:mm")
                                      via Tab + focus. aria-label carries the
                                      same content as a fallback for SR users
                                      who don't get tooltip events. */}
                                  <button
                                    type="button"
                                    aria-label={state.verifierTooltip}
                                    className={cn(
                                      badgeVariants(),
                                      state.statusConfig.color,
                                      "gap-1 cursor-help",
                                    )}
                                  >
                                    <StatusIcon
                                      className="h-3 w-3 shrink-0"
                                      aria-hidden="true"
                                    />
                                    {state.statusConfig.label}
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent>
                                  {state.verifierTooltip}
                                </TooltipContent>
                              </Tooltip>
                            ) : (
                              <Badge
                                className={`${state.statusConfig.color} gap-1`}
                              >
                                <StatusIcon
                                  className="h-3 w-3 shrink-0"
                                  aria-hidden="true"
                                />
                                {state.statusConfig.label}
                              </Badge>
                            )}
                            {doc.status === "verified" &&
                              (state.verifiedDisplayName ||
                                state.verifiedAtShort) && (
                                <div className="mt-1 text-xs text-muted-foreground break-words">
                                  {state.verifiedDisplayName}
                                  {state.verifiedDisplayName &&
                                  state.verifiedAtShort
                                    ? " · "
                                    : ""}
                                  {state.verifiedAtShort && (
                                    <span className="tabular-nums">
                                      {state.verifiedAtShort}
                                    </span>
                                  )}
                                </div>
                              )}
                          </td>
                          <td className="py-3 pl-3 align-top">
                            <DocumentRowActions
                              doc={doc}
                              state={state}
                              isUploading={isUploadingForCode(doc.code)}
                              isPaperPending={isPaperPendingForCode(doc.code)}
                              isResetPending={resetMutation.isPending}
                              isCurrentResetTarget={isResetPendingForCode(doc.code)}
                              isVerifyPending={verifyMutation.isPending}
                              isCurrentVerifyTarget={isVerifyPendingForCode(doc.code)}
                              isGradPending={updateGradMutation.isPending}
                              onView={handleViewDocument}
                              onUpload={handleUploadClick}
                              onPaperSubmit={handlePaperSubmit}
                              onUpdateGraduationProof={handleUpdateGraduationProof}
                              onRejectClick={handleRejectClick}
                              onResetClick={handleResetClick}
                              onVerifyClick={handleVerifyClick}
                              alignEnd
                            />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* ----- Mobile: stacked card per row, fewer badges, dl key/value ----- */}
              <ul className="md:hidden space-y-3">
                {sortedDocs.map((doc, i) => {
                  const state = computeRowState(doc)
                  const StatusIcon = state.statusConfig.icon
                  const HowIcon = state.HowToReceiveIcon
                  return (
                    <li
                      key={doc.code || i}
                      className="rounded-lg border p-3 motion-reduce:transition-none"
                    >
                      <div className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                          <div
                            className="font-medium text-pretty break-words"
                            title={`Mã: ${doc.code}`}
                          >
                            {doc.label}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {doc.is_mandatory ? "Bắt buộc" : "Tùy chọn"}
                          </div>
                          {doc.status === "rejected" && doc.rejection_reason && (
                            <div className="text-xs text-error-700 mt-1 break-words">
                              Lý do: {doc.rejection_reason}
                            </div>
                          )}
                        </div>
                        <div className="flex flex-col items-end gap-0.5 shrink-0">
                          {state.verifierTooltip ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <button
                                  type="button"
                                  aria-label={state.verifierTooltip}
                                  className={cn(
                                    badgeVariants(),
                                    state.statusConfig.color,
                                    "gap-1 cursor-help",
                                  )}
                                >
                                  <StatusIcon
                                    className="h-3 w-3 shrink-0"
                                    aria-hidden="true"
                                  />
                                  {state.statusConfig.label}
                                </button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {state.verifierTooltip}
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            <Badge
                              className={`${state.statusConfig.color} gap-1`}
                            >
                              <StatusIcon
                                className="h-3 w-3 shrink-0"
                                aria-hidden="true"
                              />
                              {state.statusConfig.label}
                            </Badge>
                          )}
                          {doc.status === "verified" &&
                            (state.verifiedDisplayName ||
                              state.verifiedAtShort) && (
                              <div className="text-xs text-muted-foreground text-right max-w-[10rem] break-words">
                                {state.verifiedDisplayName}
                                {state.verifiedDisplayName &&
                                state.verifiedAtShort
                                  ? " · "
                                  : ""}
                                {state.verifiedAtShort && (
                                  <span className="tabular-nums">
                                    {state.verifiedAtShort}
                                  </span>
                                )}
                              </div>
                            )}
                        </div>
                      </div>

                      <dl className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1.5 mt-3 text-sm">
                        <dt className="text-xs text-muted-foreground self-start mt-1">
                          Yêu cầu
                        </dt>
                        <dd className="break-words">
                          {state.requiredFormatShort && state.formatBadge ? (
                            <div
                              className="flex items-center gap-1"
                              title={state.formatBadge.label}
                            >
                              <span aria-label={state.formatBadge.label}>
                                {state.requiredFormatShort}
                              </span>
                            </div>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                          <div
                            className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5"
                            title={state.howToReceiveTitle}
                            aria-label={state.howToReceiveTitle}
                          >
                            <HowIcon
                              className="h-3 w-3 shrink-0"
                              aria-hidden="true"
                            />
                            <span>{state.howToReceiveLabel}</span>
                          </div>
                        </dd>

                        <dt className="text-xs text-muted-foreground self-start mt-1">
                          Đã ghi nhận
                        </dt>
                        <dd className="break-words">
                          {state.recordedFormatLabel ? (
                            <>
                              <div
                                className={`flex items-center gap-1 ${
                                  state.recordedDiffersFromRequired
                                    ? "text-warning-700"
                                    : ""
                                }`}
                                title={
                                  state.recordedDiffersFromRequired
                                    ? `Đã ghi nhận: ${state.recordedFormatLabel} — KHÁC yêu cầu hồ sơ`
                                    : `Đã ghi nhận: ${state.recordedFormatLabel}`
                                }
                              >
                                {state.recordedDiffersFromRequired && (
                                  <AlertTriangle
                                    className="h-3 w-3 shrink-0"
                                    aria-label="Khác yêu cầu hồ sơ"
                                  />
                                )}
                                <span>
                                  {state.recordedFormatCode
                                    ? getShortFormatLabel(state.recordedFormatCode)
                                    : state.recordedFormatLabel}
                                </span>
                                {state.recordedAtFormatted && (
                                  <span className="text-muted-foreground tabular-nums">
                                    · {state.recordedAtFormatted}
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-muted-foreground mt-0.5">
                                {state.receptionLabel}
                              </div>
                            </>
                          ) : (
                            // Nothing recorded yet — single "Chưa" line, no
                            // em-dash placeholder above it.
                            <div>{state.receptionLabel}</div>
                          )}
                        </dd>
                      </dl>

                      {state.hasAnyAction && (
                        <div className="mt-3 pt-3 border-t">
                          <DocumentRowActions
                            doc={doc}
                            state={state}
                            isUploading={isUploadingForCode(doc.code)}
                            isPaperPending={isPaperPendingForCode(doc.code)}
                            isResetPending={resetMutation.isPending}
                            isCurrentResetTarget={isResetPendingForCode(doc.code)}
                            isVerifyPending={verifyMutation.isPending}
                            isCurrentVerifyTarget={isVerifyPendingForCode(doc.code)}
                            isGradPending={updateGradMutation.isPending}
                            onView={handleViewDocument}
                            onUpload={handleUploadClick}
                            onPaperSubmit={handlePaperSubmit}
                            onUpdateGraduationProof={handleUpdateGraduationProof}
                            onRejectClick={handleRejectClick}
                            onResetClick={handleResetClick}
                            onVerifyClick={handleVerifyClick}
                          />
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </CardContent>

        {/* Hidden file input */}
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          onChange={handleFileChange}
          accept={acceptAttr}
          aria-describedby="documents-upload-rules"
        />
      </Card>

      {/*
        BR2 (2026-04-29): extras section.
        ProfileDocument rows that exist in the DB but are no longer in
        the path's mandatory_docs snapshot — usually because the path
        was edited after the profile was created. Backend marks them
        is_extra=true; we surface them so officers see prior evidence
        wasn't silently dropped, but render read-only (action buttons
        suppressed via backend can_* = false). A future explicit
        "Đồng bộ yêu cầu tài liệu" action will own cleanup.
      */}
      {/* Q9 #07 Phase E.4 PR-3 — Priority evidence section. Per spec V3
          Section III: DocumentsTab quản lý cả path documents (above)
          + priority evidence documents (this section, Option A
          centralization). Rows derive từ profile.priority_evidence_documents
          server projection (G0a), 1:1 với priority_object_codes. */}
      {(profile.priority_evidence_documents ?? []).length > 0 && (
        <Card className="mt-4" data-testid="documents-tab-priority-section">
          <CardHeader>
            <CardTitle className="text-base">
              Giấy tờ minh chứng ưu tiên (UT)
            </CardTitle>
            <CardDescription>
              Minh chứng cho diện ưu tiên đã ghi nhận trong{" "}
              <em>tab Ưu tiên tuyển sinh</em>. Trạng thái duyệt thuộc về
              tab đó; ở đây chỉ quản lý file upload/xem/tải lại.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {(profile.priority_evidence_documents ?? []).map((item) => (
              <div
                key={item.sub_code}
                data-testid={`documents-tab-priority-row-${item.sub_code}`}
                className="space-y-2 rounded-md border border-border p-3"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">
                      UT{item.sub_code} — {item.label}
                    </p>
                    <p className="text-xs text-muted-foreground tabular-nums">
                      +{item.bonus_points.toFixed(2)}đ
                      {item.verification_status && (
                        <span className="ml-2">
                          · Duyệt:{" "}
                          {item.verification_status === "verified"
                            ? "✅ đã duyệt"
                            : item.verification_status === "rejected"
                              ? "✗ từ chối"
                              : "⏳ chờ duyệt"}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <PriorityEvidenceUploadCell
                  profile={profile}
                  subCode={item.sub_code}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Q9 #07 Phase E.4 PR-3 — Eligibility summary footer (spec V3 §III).
          Surface "Bắt buộc verified" + "Ưu tiên uploaded" + missing UT codes
          at the bottom so officer sees gate-state at a glance without
          re-scanning the table above. Lines hide individually when their
          domain is empty (no mandatory docs / no priority codes). */}
      {eligibilitySummary.visible && (
        <Card className="mt-4" data-testid="documents-tab-eligibility-summary">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Tóm tắt điều kiện hồ sơ</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            {eligibilitySummary.mandatoryTotal > 0 && (
              <p
                data-testid="eligibility-summary-mandatory"
                className="tabular-nums"
              >
                <span className="font-medium">Bắt buộc:</span>{" "}
                {eligibilitySummary.mandatoryVerified}/
                {eligibilitySummary.mandatoryTotal} đã duyệt
                {eligibilitySummary.mandatoryRemaining > 0 && (
                  <span className="text-muted-foreground">
                    {" · cần "}
                    {eligibilitySummary.mandatoryRemaining} nữa
                  </span>
                )}
              </p>
            )}
            {eligibilitySummary.priorityTotal > 0 && (
              <p
                data-testid="eligibility-summary-priority"
                className="tabular-nums"
              >
                <span className="font-medium">Ưu tiên:</span>{" "}
                {eligibilitySummary.priorityUploaded}/
                {eligibilitySummary.priorityTotal} đã tải lên
                {eligibilitySummary.priorityMissingCodes.length > 0 && (
                  <span className="text-muted-foreground">
                    {" · "}
                    {eligibilitySummary.priorityMissingCodes.join(", ")} thiếu
                    minh chứng
                  </span>
                )}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {extraDocs.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-base">
              Tài liệu ngoài yêu cầu hiện tại
            </CardTitle>
            <CardDescription>
              Đây là các tài liệu thí sinh đã nộp ở phương thức tuyển sinh
              trước đó. Hiện không còn nằm trong yêu cầu hồ sơ. Giữ lại để
              lưu vết hồ sơ; không thể chỉnh trực tiếp ở đây.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {extraDocs.map((doc, i) => {
                const state = computeRowState(doc)
                const StatusIcon = state.statusConfig.icon
                return (
                  <li
                    key={doc.code || `extra-${i}`}
                    className="rounded-md border bg-muted/30 p-3 flex items-start gap-3"
                  >
                    <div className="flex-1 min-w-0">
                      <div
                        className="font-medium break-words"
                        title={`Mã: ${doc.code}`}
                      >
                        {doc.label}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {state.recordedFormatLabel
                          ? `${state.recordedFormatLabel}`
                          : "—"}
                        {state.recordedAtFormatted && (
                          <span className="tabular-nums">
                            {" · "}
                            {state.recordedAtFormatted}
                          </span>
                        )}
                      </div>
                    </div>
                    <Badge
                      className={`${state.statusConfig.color} gap-1 shrink-0`}
                    >
                      <StatusIcon
                        className="h-3 w-3 shrink-0"
                        aria-hidden="true"
                      />
                      {state.statusConfig.label}
                    </Badge>
                  </li>
                )
              })}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Submission Format Selection Dialog */}
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
                className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-muted/50 motion-reduce:transition-none"
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

          {/* PR #13 — graduation proof kind (only for the graduation doc). */}
          {submissionFormatDialog?.action === "paper" &&
            submissionFormatDialog?.docCode === GRADUATION_DOC_CODE && (
              <div className="space-y-3 rounded-lg border border-info-200 bg-info-50/40 p-3">
                <p className="text-sm font-medium">Loại giấy tốt nghiệp</p>
                <RadioGroup
                  value={graduationKind}
                  onValueChange={(v) =>
                    setGraduationKind(
                      v as "official_diploma" | "provisional_cert",
                    )
                  }
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem
                      value="official_diploma"
                      id="grad-official"
                    />
                    <Label
                      htmlFor="grad-official"
                      className="flex-1 cursor-pointer"
                    >
                      <div className="font-medium">
                        Bằng tốt nghiệp THPT (chính thức)
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Thí sinh đã có bằng tốt nghiệp chính thức.
                      </div>
                    </Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem
                      value="provisional_cert"
                      id="grad-provisional"
                    />
                    <Label
                      htmlFor="grad-provisional"
                      className="flex-1 cursor-pointer"
                    >
                      <div className="font-medium">
                        Giấy CN tốt nghiệp tạm thời
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Chưa có bằng chính thức — cần bổ sung sau (nợ bằng).
                      </div>
                    </Label>
                  </div>
                </RadioGroup>

                {graduationKind === "provisional_cert" && (
                  <div className="space-y-1">
                    <Label htmlFor="supplement-due" className="text-sm">
                      Hạn bổ sung bằng{" "}
                      <span className="text-error-600">*</span>
                    </Label>
                    <input
                      id="supplement-due"
                      type="date"
                      value={supplementDue}
                      onChange={(e) => setSupplementDue(e.target.value)}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </div>
                )}
              </div>
            )}

          {submissionFormatDialog?.requiredFormat &&
            selectedFormat &&
            selectedFormat !== submissionFormatDialog.requiredFormat && (
              <div
                className="flex items-start gap-2 rounded-md border border-warning-300 bg-warning-50 px-3 py-2 text-sm text-warning-800"
                role="alert"
              >
                <AlertTriangle
                  className="h-4 w-4 mt-0.5 flex-shrink-0"
                  aria-hidden="true"
                />
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
              disabled={
                !selectedFormat ||
                // Review F1 — for the graduation doc, block until the officer
                // explicitly picks a kind, and (if provisional) fills the due
                // date. No default kind → no silent mis-classification.
                (submissionFormatDialog?.action === "paper" &&
                  submissionFormatDialog?.docCode === GRADUATION_DOC_CODE &&
                  (!graduationKind ||
                    (graduationKind === "provisional_cert" &&
                      !supplementDue)))
              }
            >
              {submissionFormatDialog?.action === "paper"
                ? "Ghi nhận giấy"
                : "Tải file"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rejection Dialog */}
      <Dialog
        open={!!rejectItem}
        onOpenChange={(open) => !open && setRejectItem(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Từ chối tài liệu</DialogTitle>
            <DialogDescription>
              Vui lòng nhập lý do từ chối tài liệu{" "}
              <strong>{rejectItem?.label}</strong>. Học sinh sẽ nhận được thông
              báo để nộp lại.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <Label htmlFor="reject-reason" className="mb-2 block">
              Lý do từ chối
            </Label>
            <Textarea
              id="reject-reason"
              placeholder="VD: Tài liệu mờ, không đúng định dạng…"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
              autoFocus
              spellCheck={false}
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectItem(null)}>
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={confirmReject}
              disabled={rejectMutation.isPending || !rejectReason.trim()}
            >
              {rejectMutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
              )}
              Xác nhận từ chối
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset/Undo Document Confirmation Dialog */}
      <AlertDialog
        open={!!pendingResetDoc}
        onOpenChange={(open) => !open && setPendingResetDoc(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Hoàn tác tài liệu?</AlertDialogTitle>
            <AlertDialogDescription>
              Hoàn tác tài liệu &ldquo;{pendingResetDoc?.label}&rdquo;?
            </AlertDialogDescription>
            <p className="text-sm text-muted-foreground">
              Tài liệu sẽ về trạng thái &ldquo;Chưa nộp&rdquo; và file sẽ bị xóa
              (nếu có).
            </p>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleResetConfirm}
            >
              Hoàn tác
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Review F2 — confirm before clearing the "nợ bằng" debt. */}
      <AlertDialog
        open={!!pendingGradUpdate}
        onOpenChange={(open) => !open && setPendingGradUpdate(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Đã nhận bằng chính thức?</AlertDialogTitle>
            <AlertDialogDescription>
              Ghi nhận đã nhận bằng tốt nghiệp THPT chính thức cho
              &ldquo;{pendingGradUpdate?.label}&rdquo;?
            </AlertDialogDescription>
            <p className="text-sm text-muted-foreground">
              Thao tác này xoá trạng thái &ldquo;nợ bằng&rdquo; (giấy tạm thời)
              và không thể hoàn tác từ thao tác này.
            </p>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-success-700 text-white hover:bg-success-800"
              onClick={handleGradUpdateConfirm}
            >
              Xác nhận đã nhận bằng
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TooltipProvider>
  )
}
