/**
 * V3 — Thẻ "Thông tư áp dụng" trong tab Ưu tiên.
 *
 * Thin client: mọi giá trị do BE tính — `applicable_circular_effective`
 * (lưu, hoặc dự kiến theo hôm nay giờ VN cho hồ sơ chưa nộp),
 * `applicable_circular_effective_basis`, `priority_catalog_warning`, và hai cờ
 * `permissions.change_applicable_circular` /
 * `permissions.change_applicable_circular_requires_ack`. FE chỉ đổi mã thành
 * nhãn và định dạng ngày giờ.
 *
 * Đổi thông tư: `POST /api/v2/admissions/{id}/applicable-circular` — BE giữ
 * luật version (409), vai trò/trạng thái (403/400), lý do 20–500.
 */
"use client"

import { useState } from "react"
import { AlertTriangle, BookOpen } from "lucide-react"
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
import { useChangeApplicableCircular } from "@/lib/hooks/use-applicable-circular"
import type { AdmissionProfileResponse, ApplicableCircular } from "@/lib/zod/admissions"

export const CIRCULAR_LABEL: Record<ApplicableCircular, string> = {
  TT05_2021: "TT 05/2021/TT-BLĐTBXH",
  TT76_2026: "TT 76/2026/TT-BGDĐT",
}

const SOURCE_LABEL: Record<string, string> = {
  default_first_submit: "Mặc định theo ngày nộp đầu",
  backfill_first_submit: "Theo ngày nộp đầu (dữ liệu trước khi có tính năng)",
  backfill_missing_evidence: "Gán TT 05/2021 — thiếu ngày nộp đầu",
  manual: "Đặt thủ công",
}

const MIN_REASON = 20
const MAX_REASON = 500

type CircularProfile = Pick<
  AdmissionProfileResponse,
  | "applicable_circular"
  | "applicable_circular_effective"
  | "applicable_circular_effective_basis"
  | "applicable_circular_source"
  | "first_submitted_at"
  | "first_submitted_source"
  | "priority_catalog_warning"
>

export interface CircularDisplay {
  circularLabel: string
  basisLabel: string
  firstSubmittedLabel: string
  warning: string | null
}

function formatNgayGioVN(iso: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso))
}

/** Nhãn hiển thị — hàm thuần, không suy luật nghiệp vụ. */
export function deriveCircularDisplay(profile: CircularProfile): CircularDisplay {
  const circularLabel = CIRCULAR_LABEL[profile.applicable_circular_effective]
  const basisLabel =
    profile.applicable_circular_effective_basis === "predicted"
      ? "Dự kiến — áp dụng nếu nộp hôm nay"
      : SOURCE_LABEL[profile.applicable_circular_source ?? ""] ?? "Đã lưu"
  const firstSubmittedLabel = profile.first_submitted_at
    ? formatNgayGioVN(profile.first_submitted_at)
    : profile.first_submitted_source === "missing_evidence"
      ? "Thiếu ngày nộp đầu (dữ liệu cũ)"
      : "Chưa nộp"
  return {
    circularLabel,
    basisLabel,
    firstSubmittedLabel,
    warning: profile.priority_catalog_warning?.message ?? null,
  }
}

interface ApplicableCircularCardProps {
  profile: CircularProfile &
    Pick<AdmissionProfileResponse, "id" | "version" | "permissions">
}

export function ApplicableCircularCard({ profile }: ApplicableCircularCardProps) {
  const [open, setOpen] = useState(false)
  const view = deriveCircularDisplay(profile)
  const canChange = Boolean(profile.permissions?.change_applicable_circular)

  return (
    <section
      className="rounded-lg border border-border bg-card p-4 space-y-3"
      data-testid="applicable-circular-card"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <BookOpen className="h-4 w-4 text-primary" />
            Thông tư áp dụng
          </h3>
          <p className="text-base font-medium" data-testid="applicable-circular-value">
            {view.circularLabel}
          </p>
          <p className="text-xs text-muted-foreground" data-testid="applicable-circular-basis">
            {view.basisLabel} · Nộp lần đầu: {view.firstSubmittedLabel}
          </p>
        </div>
        {canChange && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setOpen(true)}
            data-testid="applicable-circular-change-button"
          >
            Đổi thông tư
          </Button>
        )}
      </div>

      {view.warning && (
        <div
          className="flex items-start gap-2 rounded-md border border-warning-300 bg-warning-50 p-3 text-sm text-warning-800 dark:border-warning-700 dark:bg-warning-950 dark:text-warning-200"
          role="status"
          data-testid="priority-catalog-warning"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{view.warning}</span>
        </div>
      )}

      {canChange && (
        <ApplicableCircularDialog
          open={open}
          onOpenChange={setOpen}
          profileId={profile.id}
          profileVersion={profile.version ?? 0}
          stored={profile.applicable_circular ?? null}
          effective={profile.applicable_circular_effective}
          requiresAck={Boolean(profile.permissions?.change_applicable_circular_requires_ack)}
        />
      )}
    </section>
  )
}

interface ApplicableCircularDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  profileId: number
  profileVersion: number
  /** Giá trị ĐÃ LƯU (NULL khi chưa nộp và chưa đặt tay) — backend từ chối đổi sang đúng giá trị này. */
  stored: ApplicableCircular | null
  /** Giá trị đang áp/dự kiến do backend tính — chỉ để hiển thị. */
  effective: ApplicableCircular
  requiresAck: boolean
}

export function ApplicableCircularDialog({
  open,
  onOpenChange,
  profileId,
  profileVersion,
  stored,
  effective,
  requiresAck,
}: ApplicableCircularDialogProps) {
  const mutation = useChangeApplicableCircular(profileId)
  const [circular, setCircular] = useState<ApplicableCircular | "">("")
  const [reason, setReason] = useState("")
  const [ack, setAck] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reasonLen = reason.trim().length
  const canSubmit =
    circular !== "" &&
    // So với giá trị ĐÃ LƯU như backend (`cu == circular` ⇒ 400). So với giá trị DỰ KIẾN thì hồ sơ chưa nộp
    // không ghim được chính thông tư đang dự kiến (vd giữ TT 05 qua 03-11).
    circular !== stored &&
    reasonLen >= MIN_REASON &&
    reasonLen <= MAX_REASON &&
    (!requiresAck || ack) &&
    !mutation.isPending

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setCircular("")
      setReason("")
      setAck(false)
      setError(null)
    }
    onOpenChange(next)
  }

  const handleSubmit = async () => {
    // `canSubmit` chứa vế `circular !== ""` ⇒ TS đã thu hẹp `circular` về ApplicableCircular.
    if (!canSubmit) return
    setError(null)
    try {
      await mutation.mutateAsync({
        version: profileVersion,
        circular,
        reason: reason.trim(),
        acknowledge_post_publish: requiresAck ? ack : false,
      })
      toast.success("Đã đổi thông tư áp dụng")
      handleOpenChange(false)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const msg =
        status === 409
          ? "Hồ sơ vừa được người khác cập nhật. Vui lòng đóng hộp thoại, tải lại và thử lại."
          : status === 403
            ? detail || "Bạn không có quyền đổi thông tư trên hồ sơ này."
            : status === 400 || status === 422
              ? detail || "Yêu cầu không hợp lệ."
              : "Không đổi được thông tư. Vui lòng thử lại."
      toast.error(msg)
      setError(msg)
    }
  }

  return (
    <ResponsiveDialog open={open} onOpenChange={handleOpenChange}>
      <ResponsiveDialogContent className="sm:max-w-[480px]">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle>Đổi thông tư áp dụng</ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            {stored
              ? `Đang áp dụng: ${CIRCULAR_LABEL[stored]} (đã lưu).`
              : `Chưa đặt — dự kiến ${CIRCULAR_LABEL[effective]} nếu nộp hôm nay; chọn để ghim.`}{" "}
            Thay đổi được ghi vào nhật ký kèm lý do.
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="circular-select">
              Thông tư mới <span className="text-error-500">*</span>
            </Label>
            <Select value={circular} onValueChange={(v) => setCircular(v as ApplicableCircular)}>
              <SelectTrigger id="circular-select" data-testid="circular-select">
                <SelectValue placeholder="Chọn thông tư…" />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(CIRCULAR_LABEL) as ApplicableCircular[])
                  .filter((c) => c !== stored)
                  .map((c) => (
                    <SelectItem key={c} value={c}>
                      {CIRCULAR_LABEL[c]}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="circular-reason">
              Lý do <span className="text-error-500">*</span>
            </Label>
            <Textarea
              id="circular-reason"
              data-testid="circular-reason-input"
              placeholder={`Nhập lý do (tối thiểu ${MIN_REASON} ký tự)...`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={4}
              maxLength={MAX_REASON}
            />
            <p className="text-xs text-right text-muted-foreground" data-testid="circular-reason-counter">
              {reasonLen}/{MAX_REASON} (tối thiểu {MIN_REASON})
            </p>
          </div>

          {requiresAck && (
            <div className="flex items-start gap-2 rounded-md border border-warning-300 bg-warning-50 p-3 dark:border-warning-700 dark:bg-warning-950">
              <Checkbox
                id="circular-ack"
                checked={ack}
                onCheckedChange={(v) => setAck(v === true)}
                data-testid="circular-ack-checkbox"
              />
              <Label htmlFor="circular-ack" className="text-sm font-normal leading-snug">
                Hồ sơ đã công bố kết quả. Tôi xác nhận đổi thông tư và chịu trách nhiệm về việc này.
              </Label>
            </div>
          )}

          {error && (
            <p className="text-sm text-error-600" role="alert" data-testid="circular-error">
              {error}
            </p>
          )}
        </div>

        <ResponsiveDialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Huỷ
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit} data-testid="circular-submit">
            Xác nhận đổi
          </Button>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  )
}
