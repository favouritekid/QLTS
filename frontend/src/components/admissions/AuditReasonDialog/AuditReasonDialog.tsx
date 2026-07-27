"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Day 10 — AuditReasonDialog.
 *
 * Reusable confirmation dialog for audit-gated mutations (T10 waitlist
 * promote, T11 waitlist reject, T12 manual decision, T17 admin rollback).
 *
 * UX:
 *   1. Title + description per-action (from AUDIT_ACTION_CONFIG)
 *   2. Optional dropdown of canned templates → appended to textarea
 *   3. Free-text textarea (REQUIRED, min length validate)
 *   4. Recent-reasons quick-pick (localStorage, last 5 per-action)
 *   5. Confirm button disabled until min length met
 *   6. On confirm → parent receives the FINAL reason string, owns mutation
 *
 * Parent owns the mutation — this component is a pure controlled dialog.
 * Reason is committed to localStorage recent-list AFTER successful confirm
 * (parent must call `pushRecentReason` on its mutation success — exposed
 * via `recentReasonHandler` callback prop).
 */
import { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Checkbox } from "@/components/ui/checkbox"
import {
  AUDIT_ACTION_CONFIG,
  loadRecentReasons,
  type AuditAction,
} from "./reason-templates"

export interface AuditReasonDialogProps {
  action: AuditAction
  open: boolean
  onOpenChange: (open: boolean) => void
  /**
   * Fired only when user clicks confirm and reason passes min length.
   * ``allowMajorChange`` = trạng thái checkbox đổi ngành (false nếu không hiện).
   */
  onConfirm: (reason: string, allowMajorChange: boolean) => void
  /** Optional disable state — caller may disable while parent mutation is pending. */
  isSubmitting?: boolean
  /**
   * C2: hiện checkbox "Cho phép đổi ngành" (mở chu kỳ định giá lại + kế toán xác
   * nhận). Chỉ dùng cho request_revision / admin_rollback trên hồ sơ đã đóng HP.
   */
  showMajorChangeToggle?: boolean
}

export function AuditReasonDialog({
  action,
  open,
  onOpenChange,
  onConfirm,
  isSubmitting = false,
  showMajorChangeToggle = false,
}: AuditReasonDialogProps) {
  const config = AUDIT_ACTION_CONFIG[action]
  const [reason, setReason] = useState("")
  const [allowMajorChange, setAllowMajorChange] = useState(false)
  const [recent, setRecent] = useState<string[]>(() =>
    open ? loadRecentReasons(action) : [],
  )

  // Reload recent reasons whenever dialog opens (localStorage may have
  // updated between opens) + reset reason text. React docs-blessed
  // "reset state on prop change" pattern — setState during render avoids
  // the useEffect cascade and the `react-hooks/set-state-in-effect` lint
  // error. See:
  // https://react.dev/learn/you-might-not-need-an-effect#resetting-all-state-when-a-prop-changes
  const [lastOpenAction, setLastOpenAction] = useState<{ open: boolean; action: AuditAction }>({
    open,
    action,
  })
  if (lastOpenAction.open !== open || lastOpenAction.action !== action) {
    setLastOpenAction({ open, action })
    if (open) {
      setReason("")
      setAllowMajorChange(false)
      setRecent(loadRecentReasons(action))
    }
  }

  const trimmed = reason.trim()
  const tooShort = trimmed.length < config.minLength
  const tooLong = trimmed.length > config.maxLength
  const invalid = tooShort || tooLong
  const charCount = trimmed.length

  const errorMessage = tooShort
    ? `Cần tối thiểu ${config.minLength} ký tự (hiện: ${charCount}).`
    : tooLong
    ? `Vượt giới hạn ${config.maxLength} ký tự.`
    : null

  const handleTemplateSelect = (templateValue: string) => {
    const template = config.templates.find((t) => t.value === templateValue)
    if (!template) return
    // Append template label as starting text; user customizes further
    setReason((prev) =>
      prev.trim() ? `${prev.trim()}\n${template.label}` : template.label,
    )
  }

  const handleRecentSelect = (recentValue: string) => {
    setReason(recentValue)
  }

  const handleConfirm = () => {
    if (invalid) return
    onConfirm(trimmed, showMajorChangeToggle ? allowMajorChange : false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="audit-reason-dialog">
        <DialogHeader>
          <DialogTitle>{config.title}</DialogTitle>
          <DialogDescription>{config.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {config.templates.length > 0 && (
            <div className="space-y-1">
              <Label htmlFor={`audit-template-${action}`}>
                Mẫu lý do (gợi ý)
              </Label>
              <Select
                onValueChange={handleTemplateSelect}
                disabled={isSubmitting}
              >
                <SelectTrigger
                  id={`audit-template-${action}`}
                  data-testid="audit-template-select"
                >
                  <SelectValue placeholder="Chọn mẫu lý do…" />
                </SelectTrigger>
                <SelectContent>
                  {config.templates.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {recent.length > 0 && (
            <div className="space-y-1">
              <Label htmlFor={`audit-recent-${action}`}>
                Lý do gần đây
              </Label>
              <Select
                onValueChange={handleRecentSelect}
                disabled={isSubmitting}
              >
                <SelectTrigger
                  id={`audit-recent-${action}`}
                  data-testid="audit-recent-select"
                >
                  <SelectValue placeholder="Chọn lại lý do trước…" />
                </SelectTrigger>
                <SelectContent>
                  {recent.map((r, idx) => (
                    <SelectItem key={idx} value={r}>
                      {r.length > 60 ? `${r.slice(0, 60)}…` : r}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor={`audit-reason-${action}`}>
              Lý do <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id={`audit-reason-${action}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={`Nhập tối thiểu ${config.minLength} ký tự để ghi audit log…`}
              rows={4}
              disabled={isSubmitting}
              aria-invalid={invalid && charCount > 0}
              aria-describedby={
                errorMessage && charCount > 0
                  ? `audit-reason-${action}-error`
                  : `audit-reason-${action}-count`
              }
              data-testid="audit-reason-textarea"
            />
            <div className="flex items-center justify-between text-xs">
              <span
                id={`audit-reason-${action}-count`}
                className="text-muted-foreground"
                data-testid="audit-reason-counter"
              >
                {charCount}/{config.maxLength}
              </span>
              {errorMessage && charCount > 0 && (
                <span
                  id={`audit-reason-${action}-error`}
                  role="alert"
                  className="text-destructive"
                  data-testid="audit-reason-error"
                >
                  {errorMessage}
                </span>
              )}
            </div>
          </div>

          {showMajorChangeToggle && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950/40">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <Checkbox
                  checked={allowMajorChange}
                  onCheckedChange={(v) => setAllowMajorChange(v === true)}
                  disabled={isSubmitting}
                  className="mt-0.5"
                  data-testid="allow-major-change-checkbox"
                />
                <span className="text-sm">
                  <span className="font-medium">Cho phép đổi ngành</span> — mở
                  chu kỳ định giá lại học phí theo ngành mới; kế toán phải xác
                  nhận trước khi xuất giấy báo. Chỉ chọn khi thí sinh thực sự đổi
                  ngành.
                </span>
              </label>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
          >
            Huỷ
          </Button>
          <Button
            type="button"
            onClick={handleConfirm}
            disabled={invalid || isSubmitting}
            aria-disabled={invalid || isSubmitting}
            data-testid="audit-reason-confirm"
          >
            {isSubmitting ? "Đang xử lý…" : "Xác nhận"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
