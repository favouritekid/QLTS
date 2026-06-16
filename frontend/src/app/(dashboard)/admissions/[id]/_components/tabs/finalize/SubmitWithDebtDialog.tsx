/**
 * SubmitWithDebtDialog — fast-track "Nộp kèm nợ giấy tờ" (TUITION_PREPAY_FASTTRACK_PLAN.md §4 / §4b ②).
 *
 * Officer/owner CTA shown ONLY when the backend grants
 * `profile.can_submit_with_document_debt` (the profile is eligible on every
 * axis EXCEPT it is still missing some mandatory documents). The acting staff
 * confirms a document debt — listing the owed docs + a MANDATORY reason — and
 * the profile transitions to `submitted` while the backend records a
 * `document_debt` snapshot.
 *
 * Thin Client: visibility is driven by the API permission flag
 * `can_submit_with_document_debt`, NEVER by `user.role`. The owed-doc list comes
 * straight from `profile.missing_doc_codes`; codes are humanised against
 * `documents_checklist` labels when available, otherwise the raw code is shown.
 */

"use client"

import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { FileWarning, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

const TRIGGER_CLASS = "w-full sm:w-auto min-w-[200px]"

export interface SubmitWithDebtDialogProps {
  profile: AdmissionProfileResponse
  /** Fires with the submit-with-debt payload after the staff confirms. */
  onConfirm: (payload: { acknowledge_missing_docs: true; document_debt_reason: string }) => void
  isSubmitting: boolean
  className?: string
}

/**
 * Resolve a missing-doc code to its human label using the profile's document
 * checklist (single source of truth for code→label). Falls back to the raw code
 * when no checklist row matches (e.g. a code dropped from the current snapshot).
 */
function buildCodeLabelMap(profile: AdmissionProfileResponse): Map<string, string> {
  const map = new Map<string, string>()
  for (const doc of profile.documents_checklist ?? []) {
    if (doc.code && doc.label) map.set(doc.code, doc.label)
  }
  return map
}

export function SubmitWithDebtDialog({
  profile,
  onConfirm,
  isSubmitting,
  className,
}: SubmitWithDebtDialogProps) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")

  const codeLabelMap = useMemo(() => buildCodeLabelMap(profile), [profile])
  const missingCodes = profile.missing_doc_codes ?? []

  const reasonEmpty = reason.trim().length === 0
  const confirmDisabled = reasonEmpty || isSubmitting

  const handleConfirm = () => {
    const trimmed = reason.trim()
    if (!trimmed) return
    onConfirm({ acknowledge_missing_docs: true, document_debt_reason: trimmed })
    // Leave closing to the caller's mutation success path? The mutation here is
    // fire-and-forget from the dialog's view; close + reset locally so the UI
    // returns to rest immediately (the detail refetch updates the surface).
    setOpen(false)
    setReason("")
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setReason("")
      }}
    >
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="lg"
          className={cn(
            TRIGGER_CLASS,
            "border-warning-300 text-warning-700 hover:bg-warning-50 hover:text-warning-800",
            className,
          )}
        >
          <FileWarning className="w-4 h-4 mr-2" aria-hidden="true" />
          Nộp kèm nợ giấy tờ
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nộp hồ sơ kèm nợ giấy tờ</DialogTitle>
          <DialogDescription>
            Hồ sơ đủ điều kiện nhưng còn thiếu giấy tờ. Officer xác nhận cho nợ — học sinh
            bổ sung sau. Hồ sơ vẫn phải bổ sung và được xác minh đủ trước khi duyệt.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium mb-2">
              Giấy tờ còn nợ ({missingCodes.length})
            </p>
            {missingCodes.length > 0 ? (
              <ul className="space-y-1 rounded-md border border-warning-200 bg-warning-50 p-3">
                {missingCodes.map((code) => (
                  <li
                    key={code}
                    className="flex items-start gap-2 text-sm text-warning-800"
                  >
                    <FileWarning
                      className="h-4 w-4 shrink-0 mt-0.5"
                      aria-hidden="true"
                    />
                    <span className="break-words">{codeLabelMap.get(code) ?? code}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Không có giấy tờ còn thiếu.</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="document-debt-reason">
              Lý do cho nợ <span className="text-error-600">*</span>
            </Label>
            <Textarea
              id="document-debt-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="VD: HS đang xin cấp lại học bạ, hẹn nộp 30/06"
              rows={3}
              // Mirrors the backend `document_debt_reason` Field(max_length=500)
              // so the client can't compose a reason the API would 422-reject.
              maxLength={500}
              aria-required="true"
            />
            {reasonEmpty && (
              <p className="text-xs text-muted-foreground">
                Bắt buộc nhập lý do cho nợ giấy tờ.
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              setOpen(false)
              setReason("")
            }}
            disabled={isSubmitting}
          >
            Hủy
          </Button>
          <Button onClick={handleConfirm} disabled={confirmDisabled}>
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                Đang xử lý…
              </>
            ) : (
              "Xác nhận nộp"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
