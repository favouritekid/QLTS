/**
 * Q9 #07 Phase E.4 — § 3 UT evidence cards.
 *
 * Per spec adjustment (PR-3 audit cycle 2026-05-20):
 *   - Renamed from UtCandidateCards → UtEvidenceCards (paradigm: officer
 *     nhập từ hồ sơ giấy candidate, không có candidate self-service).
 *   - Verify mutation reads document_id từ priority_evidence_documents
 *     via resolveVerifyDocumentId (PR-2 P1 contract); null chỉ paper-only.
 *   - "Mở tab Giấy tờ" button uses onNavigateToDocuments prop (lifted to
 *     AdmissionDetailClient setCurrentStep(6)).
 *
 * Render order per spec Section II:
 *   1. List ghi nhận codes — per item: status + verify/reject + missing-warning
 *   2. Untick confirm dialog (Decision #4 safety guard)
 *   3. Disclosure "Bổ sung diện UT khác" — full catalog checkboxes
 */
"use client"

import { useState } from "react"
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  ExternalLink,
  Loader2,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
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
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogDescription,
  ResponsiveDialogFooter,
  ResponsiveDialogHeader,
  ResponsiveDialogTitle,
} from "@/components/ui/responsive-dialog"
import { Textarea } from "@/components/ui/textarea"

import {
  useRejectObjectEvidence,
  useUntickPriorityEvidence,
  useVerifyObjectEvidence,
} from "@/lib/hooks/use-priority-evidence"
import { useUtCatalog } from "@/lib/hooks/use-priority-object-catalog"
import type { PriorityObjectCatalogItem } from "@/lib/api/priority-objects"
import {
  findEvidenceDocument,
  getDisplayFilename,
  getEvidence,
  isMissingEvidenceFile,
  resolveVerifyDocumentId,
} from "@/lib/utils/priority-evidence-helpers"
import type {
  AdmissionProfileResponse,
  PriorityEvidenceDocumentItem,
} from "@/lib/zod/admissions"

const MIN_REJECT_REASON = 10
const MAX_REJECT_REASON = 500

// =============================================================================
// MAIN
// =============================================================================

export interface UtEvidenceCardsProps {
  profile: AdmissionProfileResponse
  /** Officer/admin verify permission (BE permission flag). */
  canVerify: boolean
  /** Allow officer to edit codes list (untick + add). */
  isEditable: boolean
  /**
   * Adjustment #3 (PR-3): caller wires to AdmissionDetailClient setCurrentStep(6)
   * so "Mở tab Giấy tờ" navigates user to DocumentsTab.
   */
  onNavigateToDocuments: () => void
  /**
   * Callback when codes list changes (untick or add). Caller persists via
   * profile mutation. Service-layer enforces version guard.
   */
  onCodesChange?: (codes: string[]) => void
  /**
   * Followup fix: form state codes (RHF watch) ưu tiên hơn
   * `profile.priority_object_codes` (server snapshot) để officer tick thêm
   * UT thấy card mới render ngay, không phải chờ save+refetch. Caller
   * (PriorityTab) truyền `form.watch("priority_object_codes")` xuống.
   * Bỏ qua nếu undefined → fallback profile snapshot.
   */
  formCodes?: string[] | null
}

export function UtEvidenceCards({
  profile,
  canVerify,
  isEditable,
  onNavigateToDocuments,
  onCodesChange,
  formCodes,
}: UtEvidenceCardsProps) {
  // Followup fix: trước đây luôn đọc profile.priority_object_codes → tick
  // thêm UT trong form state không reflect render tới save+refetch. Giờ
  // ưu tiên formCodes nếu caller truyền (PriorityTab RHF watch).
  const codes = formCodes ?? profile.priority_object_codes ?? []
  const evidence = getEvidence(profile)
  const verifiedCount = codes.filter((c) => evidence[c]?.status === "verified").length
  const pendingCount = codes.filter((c) => evidence[c]?.status === "pending").length

  // P1 fix: untick state only used cho cards có file (open confirm dialog).
  // Codes không có file → direct mutation, không dialog (Decision #4 chỉ
  // confirm khi có destructive file delete).
  const [rejectCode, setRejectCode] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)

  return (
    <section
      data-testid="ut-evidence-cards"
      className="space-y-3 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Đối tượng ưu tiên</h3>
        {codes.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Đã ghi nhận: {codes.length} diện ({verifiedCount} đã duyệt,{" "}
            {pendingCount} chờ duyệt)
          </p>
        )}
      </div>

      {/* Empty state */}
      {codes.length === 0 && (
        <div
          className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground"
          data-testid="ut-evidence-empty"
        >
          Hồ sơ chưa ghi nhận diện UT nào.
        </div>
      )}

      {/* Per-code cards. P1 fix: untick branching moved INTO card item — items
          với file open confirm dialog inline; items không file untick trực
          tiếp (no destructive action → no confirm). */}
      {codes.map((subCode) => (
        <UtEvidenceCardItem
          key={subCode}
          subCode={subCode}
          profile={profile}
          canVerify={canVerify}
          isEditable={isEditable}
          onReject={() => setRejectCode(subCode)}
          onNavigateToDocuments={onNavigateToDocuments}
        />
      ))}

      {/* Bổ sung diện UT — disclosure */}
      {isEditable && (
        <UtAddDisclosure
          open={addOpen}
          onOpenChange={setAddOpen}
          profile={profile}
          currentCodes={codes}
          onCodesChange={onCodesChange}
        />
      )}

      {/* Reject reason dialog */}
      {rejectCode && (
        <RejectReasonDialog
          subCode={rejectCode}
          profile={profile}
          onClose={() => setRejectCode(null)}
        />
      )}
    </section>
  )
}

// =============================================================================
// Per-code card item
// =============================================================================

interface UtEvidenceCardItemProps {
  subCode: string
  profile: AdmissionProfileResponse
  canVerify: boolean
  isEditable: boolean
  onReject: () => void
  onNavigateToDocuments: () => void
}

function UtEvidenceCardItem({
  subCode,
  profile,
  canVerify,
  isEditable,
  onReject,
  onNavigateToDocuments,
}: UtEvidenceCardItemProps) {
  const evidence = getEvidence(profile)
  const entry = evidence[subCode]
  const docItem = findEvidenceDocument(profile, subCode)
  const isMissing = isMissingEvidenceFile(profile, subCode)
  const status = entry?.status ?? "pending"
  const hasFile = Boolean(docItem?.document_file_path)

  // Adjustment #4 (PR-3): verify mutation MUST pass server doc_id từ
  // priority_evidence_documents projection. Null chỉ paper-only verify.
  const verifyDocId = resolveVerifyDocumentId(profile, subCode)
  const verifyMutation = useVerifyObjectEvidence(profile.id, subCode)
  // P1 fix (PR-3 Step C audit): untick mutation lifted to card item — items
  // có file open confirm dialog, items không file untick trực tiếp.
  const untickMutation = useUntickPriorityEvidence(profile.id, subCode)
  const [showUntickConfirm, setShowUntickConfirm] = useState(false)

  const handleUntickClick = () => {
    if (hasFile) {
      // Destructive — confirm dialog mới (Decision #4).
      setShowUntickConfirm(true)
      return
    }
    // No file → no destructive action → direct mutation, không dialog.
    untickMutation.mutate(
      { version: profile.version ?? 0 },
      {
        onSuccess: () => toast.success(`Đã bỏ chọn UT${subCode}.`),
        onError: (err) => toast.error(`Bỏ chọn UT${subCode} thất bại: ${err.message}`),
      },
    )
  }

  const onVerifyClick = () => {
    verifyMutation.mutate(
      { version: profile.version ?? 0, document_id: verifyDocId },
      {
        onSuccess: () => {
          toast.success(
            verifyDocId
              ? `Đã duyệt UT${subCode} (gắn file ${getDisplayFilename(
                  docItem?.document_file_path ?? null,
                )})`
              : `Đã duyệt UT${subCode} (hồ sơ giấy)`,
          )
        },
        onError: (err) => {
          toast.error(`Duyệt UT${subCode} thất bại: ${err.message}`)
        },
      },
    )
  }

  const verifyButtonLabel =
    verifyDocId === null ? "Duyệt (Hồ sơ giấy)" : "Duyệt"

  return (
    <article
      data-testid={`ut-evidence-card-${subCode}`}
      data-status={status}
      className="space-y-2 rounded-md border border-border p-3"
    >
      <header className="flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h4 className="text-sm font-semibold">UT{subCode}</h4>
          {docItem?.label && (
            <span className="text-sm text-muted-foreground">{docItem.label}</span>
          )}
          {docItem?.bonus_points != null && (
            <span className="text-xs tabular-nums text-muted-foreground">
              +{docItem.bonus_points.toFixed(2)}đ
            </span>
          )}
        </div>
        <StatusBadge status={status} />
      </header>

      {/* Evidence file info (verified/pending with doc) */}
      {docItem?.document_file_path && (
        <p className="text-xs text-muted-foreground">
          Minh chứng: {getDisplayFilename(docItem.document_file_path)}{" "}
          <a
            href={`/${docItem.document_file_path}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-primary hover:underline"
            data-testid={`ut-evidence-view-${subCode}`}
          >
            [Xem PDF] <ExternalLink className="h-3 w-3" />
          </a>
        </p>
      )}

      {/* Verifier info (verified status) */}
      {status === "verified" && entry && "verified_by_name" in entry && entry.verified_by_name && (
        <p className="text-xs text-muted-foreground">
          Bởi <strong>{entry.verified_by_name}</strong>
          {entry.verified_at && (
            <span> · {formatTimestamp(entry.verified_at)}</span>
          )}
          {entry.paper_only_verification && (
            <span className="ml-2 inline-flex items-center gap-1 rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700">
              Hồ sơ giấy
            </span>
          )}
        </p>
      )}

      {/* Reject reason (rejected status) */}
      {status === "rejected" && entry?.reject_reason && (
        <p className="text-xs text-rose-700">
          Lý do từ chối: <em>{entry.reject_reason}</em>
        </p>
      )}

      {/* Missing-file inline warning (Decision #2) */}
      {isMissing && (
        <div
          data-testid={`ut-evidence-missing-warning-${subCode}`}
          className="flex items-center gap-2 rounded-md border border-orange-200 bg-orange-50 p-2 text-xs text-orange-800"
        >
          <span aria-hidden="true">⚠</span>
          <span>Chưa có minh chứng — đính kèm trước khi submit.</span>
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={onNavigateToDocuments}
            className="ml-auto h-auto p-0 text-xs"
            data-testid={`ut-evidence-navigate-documents-${subCode}`}
          >
            → Mở tab Giấy tờ để upload
          </Button>
        </div>
      )}

      {/* Verify/Reject actions (pending status) */}
      {status === "pending" && canVerify && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            type="button"
            size="sm"
            onClick={onVerifyClick}
            disabled={verifyMutation.isPending}
            data-testid={`ut-evidence-verify-${subCode}`}
          >
            {verifyMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <ThumbsUp className="h-4 w-4 mr-2" />
            )}
            {verifyButtonLabel}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onReject}
            data-testid={`ut-evidence-reject-${subCode}`}
          >
            <ThumbsDown className="h-4 w-4 mr-2" />
            Từ chối
          </Button>
        </div>
      )}

      {/* Untick action (officer-edit mode). P1 fix: branch hasFile —
          file present opens confirm dialog (destructive); file absent
          direct mutation (no destructive). */}
      {isEditable && (
        <div className="flex justify-end pt-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleUntickClick}
            disabled={untickMutation.isPending}
            className="h-auto p-0 text-xs text-muted-foreground hover:text-destructive"
            data-testid={`ut-evidence-untick-${subCode}`}
          >
            {untickMutation.isPending ? (
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            ) : null}
            Bỏ chọn diện UT
          </Button>
        </div>
      )}

      {/* Inline confirm dialog for destructive untick (has-file case only) */}
      {showUntickConfirm && hasFile && (
        <UntickConfirmDialog
          subCode={subCode}
          profile={profile}
          onClose={() => setShowUntickConfirm(false)}
        />
      )}
    </article>
  )
}

// =============================================================================
// Untick confirm dialog (Decision #4)
// =============================================================================

interface UntickConfirmDialogProps {
  subCode: string
  profile: AdmissionProfileResponse
  onClose: () => void
}

function UntickConfirmDialog({ subCode, profile, onClose }: UntickConfirmDialogProps) {
  const docItem = findEvidenceDocument(profile, subCode)
  const hasFile = Boolean(docItem?.document_file_path)
  const filename = getDisplayFilename(docItem?.document_file_path ?? null)
  const untickMutation = useUntickPriorityEvidence(profile.id, subCode)

  const handleConfirm = () => {
    untickMutation.mutate(
      { version: profile.version ?? 0 },
      {
        onSuccess: () => {
          toast.success(`Đã bỏ chọn UT${subCode}.`)
          onClose()
        },
        onError: (err) => {
          toast.error(`Bỏ chọn UT${subCode} thất bại: ${err.message}`)
        },
      },
    )
  }

  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent data-testid="ut-untick-confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>Bỏ chọn UT{subCode}?</AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            {hasFile ? (
              <>
                <span className="block">
                  ⚠ Thao tác này sẽ <strong>XOÁ VĨNH VIỄN</strong> file minh chứng:
                </span>
                <span className="block rounded-md border border-border bg-muted p-2 font-mono text-xs">
                  {filename}
                </span>
                <span className="block">
                  Bạn cần upload lại nếu sau này tick UT{subCode} trở lại.
                </span>
              </>
            ) : (
              <span>Bỏ chọn diện UT{subCode}? Không có file đính kèm.</span>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {/* Default focus = Cancel (safer) */}
          <AlertDialogCancel
            autoFocus
            disabled={untickMutation.isPending}
            data-testid="ut-untick-cancel"
          >
            Huỷ
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault()
              handleConfirm()
            }}
            disabled={untickMutation.isPending}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            data-testid="ut-untick-confirm"
          >
            {untickMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            {hasFile ? "Xoá file và bỏ chọn" : "Bỏ chọn"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

// =============================================================================
// Reject reason dialog (10-500 chars)
// =============================================================================

interface RejectReasonDialogProps {
  subCode: string
  profile: AdmissionProfileResponse
  onClose: () => void
}

function RejectReasonDialog({ subCode, profile, onClose }: RejectReasonDialogProps) {
  const [reason, setReason] = useState("")
  const rejectMutation = useRejectObjectEvidence(profile.id, subCode)
  const reasonLen = reason.trim().length
  const isValid = reasonLen >= MIN_REJECT_REASON && reasonLen <= MAX_REJECT_REASON

  const handleSubmit = () => {
    if (!isValid) return
    rejectMutation.mutate(
      { version: profile.version ?? 0, reject_reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success(`Đã từ chối UT${subCode}.`)
          onClose()
        },
        onError: (err) => {
          toast.error(`Từ chối UT${subCode} thất bại: ${err.message}`)
        },
      },
    )
  }

  return (
    <ResponsiveDialog open onOpenChange={(open) => !open && onClose()}>
      <ResponsiveDialogContent data-testid={`ut-reject-dialog-${subCode}`}>
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle>Từ chối UT{subCode}</ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            Nhập lý do từ chối ({MIN_REJECT_REASON}-{MAX_REJECT_REASON} ký tự). Audit
            log sẽ ghi lý do để thanh tra truy được.
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>
        <div className="space-y-2 py-2">
          <Label htmlFor="ut-reject-reason-textarea" className="text-sm">
            Lý do từ chối ({MIN_REJECT_REASON}-{MAX_REJECT_REASON} ký tự)
          </Label>
          <Textarea
            id="ut-reject-reason-textarea"
            aria-label="Lý do từ chối UT evidence"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            maxLength={MAX_REJECT_REASON}
            placeholder="VD: Giấy chứng nhận hết hạn / không khớp thông tin candidate…"
            data-testid="ut-reject-reason-input"
          />
          <p className="text-xs text-muted-foreground tabular-nums">
            {reasonLen}/{MAX_REJECT_REASON}
          </p>
        </div>
        <ResponsiveDialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={rejectMutation.isPending}
          >
            Huỷ
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!isValid || rejectMutation.isPending}
            data-testid="ut-reject-submit"
          >
            {rejectMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            Từ chối
          </Button>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  )
}

// =============================================================================
// Add UT disclosure — catalog checkboxes
// =============================================================================

interface UtAddDisclosureProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  profile: AdmissionProfileResponse
  /**
   * Source-of-truth codes từ caller (UtEvidenceCards `codes` = formCodes ??
   * profile.priority_object_codes). Phải đọc từ form state thay vì
   * `profile.priority_object_codes` trực tiếp — nếu không, tick UT04 xong
   * tick UT07 sẽ overwrite về `[07]` vì profile snapshot chưa save+refetch.
   */
  currentCodes: string[]
  onCodesChange?: (codes: string[]) => void
}

function UtAddDisclosure({
  open,
  onOpenChange,
  profile,
  currentCodes,
  onCodesChange,
}: UtAddDisclosureProps) {
  const { data: catalog = [], isLoading } = useUtCatalog(profile.academic_year ?? new Date().getFullYear())
  const existingCodes = new Set(currentCodes)

  const toggleCode = (subCode: string) => {
    if (existingCodes.has(subCode)) {
      // Untick handled via UntickConfirmDialog; this branch should not fire
      // (catalog checkboxes marked existing as readOnly).
      return
    }
    onCodesChange?.([...currentCodes, subCode])
  }

  return (
    <div className="rounded-md border border-dashed border-border">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => onOpenChange(!open)}
        className="w-full justify-between p-3 text-sm"
        data-testid="ut-add-disclosure-trigger"
      >
        <span>Bổ sung diện UT khác</span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </Button>
      {open && (
        <div className="space-y-2 border-t border-border p-3" data-testid="ut-add-catalog">
          {isLoading && (
            <p className="text-xs text-muted-foreground">Đang tải catalog...</p>
          )}
          {!isLoading && catalog.length === 0 && (
            <p className="text-xs text-muted-foreground">
              Chưa có danh mục đối tượng ưu tiên cho năm {profile.academic_year}.
              Vui lòng liên hệ quản trị hệ thống.
            </p>
          )}
          {catalog.map((item: PriorityObjectCatalogItem) => {
            const alreadyAdded = existingCodes.has(item.sub_code)
            return (
              <Label
                key={item.sub_code}
                className="flex items-start gap-2 text-sm cursor-pointer"
                data-testid={`ut-add-catalog-item-${item.sub_code}`}
              >
                <Checkbox
                  checked={alreadyAdded}
                  disabled={alreadyAdded}
                  onCheckedChange={() => toggleCode(item.sub_code)}
                />
                <span className="flex-1">
                  <strong>UT{item.sub_code}</strong> {item.description}{" "}
                  <span className="tabular-nums text-muted-foreground">
                    (+{item.bonus_points.toFixed(2)}đ)
                  </span>
                  {alreadyAdded && (
                    <span className="ml-1 text-xs italic text-muted-foreground">
                      [đã chọn]
                    </span>
                  )}
                </span>
              </Label>
            )
          })}
        </div>
      )}
    </div>
  )
}

// =============================================================================
// Status badge
// =============================================================================

function StatusBadge({ status }: { status: "pending" | "verified" | "rejected" }) {
  if (status === "verified") {
    return (
      <span
        data-testid="ut-status-badge-verified"
        className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800"
      >
        <CheckCircle2 className="h-3 w-3" /> Đã duyệt
      </span>
    )
  }
  if (status === "rejected") {
    return (
      <span
        data-testid="ut-status-badge-rejected"
        className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-800"
      >
        <XCircle className="h-3 w-3" /> Đã từ chối
      </span>
    )
  }
  return (
    <span
      data-testid="ut-status-badge-pending"
      className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800"
    >
      <Clock className="h-3 w-3" /> Chờ duyệt
    </span>
  )
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}
