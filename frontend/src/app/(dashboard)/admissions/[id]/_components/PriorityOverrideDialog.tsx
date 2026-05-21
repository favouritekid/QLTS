"use client"

/**
 * PriorityOverrideDialog — Q9 #07 Phase E.2 (officer/admin write-path).
 *
 * Triggered từ PriorityTab "Cán bộ ấn định thủ công" button (gated by
 * `profile.permissions.override_priority_kv`). Submits POST
 * /api/v2/admissions/{id}/override-priority-kv với optimistic-lock
 * version + 20-500 char reason.
 *
 * UX:
 * * KV Select — 4 options (KV1 / KV2-NT / KV2 / KV3) sourced từ KV_BADGE
 * * Reason Textarea — 20-500 chars với live counter
 * * BEFORE → AFTER inline preview (current snapshot.kv_resolved → user-picked)
 * * Submit gates: reason length OK + KV changed (no-op if same KV)
 * * Admin escape hatch: secondary checkbox cho post-publish profile
 *   (status enrolled/approved/confirmed/...) — required by BE service
 *   layer's `acknowledge_post_publish` flag.
 * * On 409 ConflictError → toast "Hồ sơ vừa cập nhật bởi người khác,
 *   vui lòng refresh" + invalidate detail cache (handled inside the
 *   mutation hook).
 *
 * BE service contract:
 * * Version guard FIRST per memory `version-guard-before-state-machine`
 * * Officer status whitelist {submitted, reviewing, revision_requested};
 *   hard-deny {draft, withdrawn, dropped, rejected}; post-publish requires
 *   admin + ack flag.
 * * Snapshot mutation overwrites manual_override_* keys (Decision D1);
 *   audit log preserves chain.
 */
import { useCallback, useState } from "react"
import { AlertTriangle, ShieldCheck } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

import { KV_BADGE } from "@/components/admissions/kv-labels"
import { useOverridePriorityKv } from "@/lib/hooks/use-priority-override"
import {
  KV_CODES,
  type KvCode,
} from "@/lib/zod/priority-override"

const POST_PUBLISH_STATUS = new Set([
  "approved",
  "confirmed",
  "enrolled",
  "overridden",
  "result_published",
  "admitted",
  "waitlisted",
])

const MIN_REASON = 20
const MAX_REASON = 500

export interface PriorityOverrideDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  profileId: number
  profileVersion: number
  profileStatus: string
  currentKv: string | null | undefined
  /**
   * Caller's role. Service-layer enforces full rules; UI gates the
   * "acknowledge post-publish" checkbox cho admin role.
   *
   * Commit 3: thêm explicit `manager` mode (trước đây bị fallback sang
   * `officer` ở PriorityTab → manager experience lệch với quyền thật).
   * BE service treat manager + officer chung whitelist {submitted,
   * reviewing, revision_requested}; chỉ admin được override post-publish
   * với ack flag. Mode `manager` ở FE phục vụ copy/disclosure.
   */
  mode?: "officer" | "manager" | "admin"
}

export function PriorityOverrideDialog({
  open,
  onOpenChange,
  profileId,
  profileVersion,
  profileStatus,
  currentKv,
  mode = "officer",
}: PriorityOverrideDialogProps) {
  const [kvResolved, setKvResolved] = useState<KvCode | "">("")
  const [reason, setReason] = useState("")
  const [acknowledgePostPublish, setAcknowledgePostPublish] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutation = useOverridePriorityKv(profileId)

  // Reset state khi dialog đóng — handled trong onOpenChange wrapper
  // thay vì useEffect (avoids React 19 cascading setState rule + eliminates
  // race when parent re-opens dialog ngay sau khi close).
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        setKvResolved("")
        setReason("")
        setAcknowledgePostPublish(false)
        setError(null)
      }
      onOpenChange(next)
    },
    [onOpenChange],
  )

  const isPostPublish = POST_PUBLISH_STATUS.has(profileStatus)
  const requiresAck = isPostPublish && mode === "admin"
  const reasonLen = reason.trim().length
  const reasonValid = reasonLen >= MIN_REASON && reasonLen <= MAX_REASON
  const kvChanged = kvResolved !== "" && kvResolved !== currentKv
  const canSubmit =
    kvChanged &&
    reasonValid &&
    (!requiresAck || acknowledgePostPublish) &&
    !mutation.isPending

  const handleSubmit = async () => {
    if (!canSubmit || !kvResolved) return
    setError(null)
    try {
      await mutation.mutateAsync({
        version: profileVersion,
        kv_resolved: kvResolved,
        reason: reason.trim(),
        evidence_file_id: null,
        acknowledge_post_publish: acknowledgePostPublish,
      })
      toast.success("Đã ấn định KV thành công")
      handleOpenChange(false)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        toast.error(
          "Hồ sơ vừa cập nhật bởi người khác. Vui lòng refresh và thử lại."
        )
        setError(
          "Phiên bản hồ sơ đã thay đổi — cache đã refresh, vui lòng đóng dialog và mở lại."
        )
      } else if (status === 403) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail
        toast.error(detail || "Bạn không có quyền override KV trên hồ sơ này.")
        setError(detail || "Không có quyền override.")
      } else if (status === 400) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail
        toast.error(detail || "Yêu cầu không hợp lệ.")
        setError(detail || "Yêu cầu không hợp lệ.")
      } else {
        toast.error("Không thể override KV. Vui lòng thử lại.")
        setError("Lỗi server. Vui lòng thử lại sau.")
      }
    }
  }

  const beforeLabel = currentKv ? KV_BADGE[currentKv]?.label ?? currentKv : "—"
  const afterLabel = kvResolved ? KV_BADGE[kvResolved]?.label ?? kvResolved : "—"

  return (
    <ResponsiveDialog open={open} onOpenChange={handleOpenChange}>
      <ResponsiveDialogContent className="sm:max-w-[480px]">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            Cán bộ ấn định KV thủ công
          </ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            Override Khu vực ưu tiên trên hồ sơ này. Thay đổi sẽ được ghi vào
            audit log với lý do bạn cung cấp.
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>

        <div className="grid gap-4 py-4">
          {/* BEFORE → AFTER preview */}
          <div
            className="rounded-md border border-border bg-muted/40 p-3 text-sm"
            data-testid="priority-override-preview"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-muted-foreground">Hiện tại:</span>
              <span className="font-medium" data-testid="override-before-kv">
                {beforeLabel}
              </span>
              <span className="text-muted-foreground">→</span>
              <span className="text-muted-foreground">Sau:</span>
              <span className="font-bold text-primary" data-testid="override-after-kv">
                {afterLabel}
              </span>
            </div>
          </div>

          {/* KV Select */}
          <div className="grid gap-2">
            <Label htmlFor="override-kv">
              KV mới <span className="text-error-500">*</span>
            </Label>
            <Select
              value={kvResolved}
              onValueChange={(v) => setKvResolved(v as KvCode)}
            >
              <SelectTrigger id="override-kv" data-testid="override-kv-select">
                <SelectValue placeholder="Chọn KV mới..." />
              </SelectTrigger>
              <SelectContent>
                {KV_CODES.map((code) => (
                  <SelectItem key={code} value={code}>
                    {KV_BADGE[code]?.label ?? code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Reason textarea với counter */}
          <div className="grid gap-2">
            <Label htmlFor="override-reason">
              Lý do ấn định <span className="text-error-500">*</span>
            </Label>
            <Textarea
              id="override-reason"
              data-testid="override-reason-input"
              placeholder={`Nhập lý do ấn định (tối thiểu ${MIN_REASON} ký tự)...`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={4}
              maxLength={MAX_REASON}
            />
            <p
              className={`text-xs text-right ${
                reasonLen < MIN_REASON || reasonLen > MAX_REASON
                  ? "text-error-500"
                  : "text-muted-foreground"
              }`}
              data-testid="override-reason-counter"
            >
              {reasonLen}/{MAX_REASON} (tối thiểu {MIN_REASON})
            </p>
          </div>

          {/* Admin escape hatch — post-publish profile */}
          {requiresAck && (
            <div
              className="rounded-md border border-warning-300 bg-warning-50 p-3 text-sm flex items-start gap-2"
              data-testid="override-post-publish-warning"
            >
              <AlertTriangle className="h-4 w-4 shrink-0 text-warning-700 mt-0.5" />
              <div className="space-y-2 flex-1">
                <p className="text-warning-900 font-medium">
                  Hồ sơ đã ở trạng thái post-publish: {profileStatus}
                </p>
                <p className="text-warning-800 text-xs">
                  Override KV sau khi hồ sơ đã được công bố kết quả là thao tác
                  hiếm gặp. Hành động này sẽ được ghi vào audit log với metadata
                  acknowledged_post_publish=true.
                </p>
                <div className="flex items-start gap-2">
                  <Checkbox
                    id="ack-post-publish"
                    data-testid="override-ack-checkbox"
                    checked={acknowledgePostPublish}
                    onCheckedChange={(v) => setAcknowledgePostPublish(!!v)}
                  />
                  <Label
                    htmlFor="ack-post-publish"
                    className="text-warning-900 cursor-pointer"
                  >
                    Tôi xác nhận muốn override hồ sơ post-publish.
                  </Label>
                </div>
              </div>
            </div>
          )}

          {/* Server / validation error */}
          {error && (
            <p
              className="text-sm text-error-600"
              data-testid="override-error"
              role="alert"
            >
              {error}
            </p>
          )}
        </div>

        <ResponsiveDialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Hủy
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit}
            data-testid="override-submit"
          >
            {mutation.isPending ? "Đang lưu..." : "Ấn định KV"}
          </Button>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  )
}
