"use client"

/**
 * GĐ1b §6 (C9, C11) — Admin cấp / thu hồi / xem quyền duyệt chéo tạm thời.
 * Cấp theo TỪNG cán bộ được nêu tên, theo đơn vị + thao tác; hạn tối đa 14 ngày, lý do bắt buộc; không gia hạn — cấp lại
 * là dòng mới có lý do; chỉ thu hồi, không xoá. Mọi luật do MÁY CHỦ kiểm (422 / 403); giao diện không suy vai —
 * không phải Admin ⇒ máy chủ từ chối ⇒ trang báo.
 */
import { useId, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  useCreateCrossReviewGrant,
  useCrossReviewGrants,
  useRevokeCrossReviewGrant,
} from "@/hooks/document-review/useCrossReview"
import { describeGrantError, formatDateTimeVN } from "@/lib/document-review/messages"
import type { CrossReviewGrant } from "@/lib/zod/document-review"

/** `datetime-local` (giờ Việt Nam, không DST) ⇒ ISO có độ lệch +07:00. Trả `null` khi trống / sai dạng. */
export function vnLocalToIso(value: string): string | null {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) ? `${value}:00+07:00` : null
}

function positiveInt(v: string): number | null {
  if (!/^\d+$/.test(v.trim())) return null
  const n = Number(v.trim())
  return Number.isSafeInteger(n) && n > 0 ? n : null
}

function CreateGrantForm() {
  const baseId = useId()
  const [grantee, setGrantee] = useState("")
  const [unit, setUnit] = useState("")
  const [allowVerify, setAllowVerify] = useState(true)
  const [allowReject, setAllowReject] = useState(false)
  const [expires, setExpires] = useState("")
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const create = useCreateCrossReviewGrant()

  const granteeId = positiveInt(grantee)
  const unitId = positiveInt(unit)
  const expiresIso = vnLocalToIso(expires)
  const canSubmit =
    granteeId !== null &&
    unitId !== null &&
    expiresIso !== null &&
    (allowVerify || allowReject) &&
    reason.trim().length > 0 &&
    !create.isPending

  const submit = () => {
    if (!canSubmit || granteeId === null || unitId === null || expiresIso === null) return
    setError(null)
    create.mutate(
      {
        grantee_user_id: granteeId,
        unit_id: unitId,
        allow_verify: allowVerify,
        allow_reject: allowReject,
        expires_at: expiresIso,
        reason: reason.trim(),
      },
      {
        onSuccess: () => {
          toast.success("Đã cấp quyền duyệt chéo")
          setReason("")
        },
        onError: (e) => setError(describeGrantError(e)),
      },
    )
  }

  return (
    <section className="space-y-3 rounded-md border p-4" data-testid="cap-quyen-cheo">
      <h2 className="text-lg font-semibold">Cấp quyền mới</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor={`${baseId}-nguoi`}>Mã người dùng của cán bộ được cấp</Label>
          <Input id={`${baseId}-nguoi`} inputMode="numeric" value={grantee} onChange={(e) => setGrantee(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${baseId}-don-vi`}>Mã đơn vị được duyệt chéo</Label>
          <Input id={`${baseId}-don-vi`} inputMode="numeric" value={unit} onChange={(e) => setUnit(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${baseId}-han`}>Hết hạn (giờ Việt Nam, tối đa 14 ngày)</Label>
          <Input
            id={`${baseId}-han`}
            type="datetime-local"
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
          />
        </div>
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">Thao tác được phép</legend>
          <div className="flex items-center gap-2">
            <Checkbox id={`${baseId}-duyet`} checked={allowVerify} onCheckedChange={(v) => setAllowVerify(v === true)} />
            <Label htmlFor={`${baseId}-duyet`} className="font-normal">
              Duyệt
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id={`${baseId}-tu-choi`} checked={allowReject} onCheckedChange={(v) => setAllowReject(v === true)} />
            <Label htmlFor={`${baseId}-tu-choi`} className="font-normal">
              Từ chối
            </Label>
          </div>
        </fieldset>
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${baseId}-ly-do`}>Lý do cấp (bắt buộc)</Label>
        <Textarea
          id={`${baseId}-ly-do`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          autoComplete="off"
          rows={2}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button onClick={submit} disabled={!canSubmit}>
        {create.isPending ? "Đang cấp…" : "Cấp quyền"}
      </Button>
    </section>
  )
}

function RevokeDialog({ grant, onClose }: { grant: CrossReviewGrant; onClose: () => void }) {
  const reasonId = useId()
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const revoke = useRevokeCrossReviewGrant()
  const trimmed = reason.trim()

  const submit = () => {
    if (!trimmed || revoke.isPending) return
    setError(null)
    revoke.mutate(
      { grantId: grant.id, reason: trimmed },
      {
        onSuccess: () => {
          toast.success(`Đã thu hồi quyền #${grant.id}`)
          onClose()
        },
        onError: (e) => setError(describeGrantError(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Thu hồi quyền #{grant.id}</DialogTitle>
          <DialogDescription>Thu hồi có hiệu lực ngay; quyền không bị xoá, vẫn còn trong lịch sử.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={reasonId}>Lý do thu hồi (bắt buộc)</Label>
          <Textarea
            id={reasonId}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            autoComplete="off"
            rows={3}
            disabled={revoke.isPending}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={revoke.isPending}>
            Huỷ
          </Button>
          <Button variant="destructive" onClick={submit} disabled={!trimmed || revoke.isPending}>
            {revoke.isPending ? "Đang thu hồi…" : "Thu hồi"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CrossReviewGrantsClient() {
  const activeId = useId()
  const [activeOnly, setActiveOnly] = useState(true)
  const grants = useCrossReviewGrants(activeOnly ? { active: true } : {})
  const [revoking, setRevoking] = useState<CrossReviewGrant | null>(null)

  if (grants.isError) {
    return (
      <p role="alert" className="text-sm text-destructive" data-testid="quyen-cheo-loi">
        {describeGrantError(grants.error)}
      </p>
    )
  }

  return (
    <div className="space-y-6">
      <CreateGrantForm />
      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">Quyền đã cấp</h2>
          <div className="flex items-center gap-2">
            <Checkbox id={activeId} checked={activeOnly} onCheckedChange={(v) => setActiveOnly(v === true)} />
            <Label htmlFor={activeId} className="font-normal">
              Chỉ quyền còn hiệu lực
            </Label>
          </div>
        </div>
        {grants.isLoading && <p className="text-sm text-muted-foreground">Đang tải…</p>}
        {grants.data && grants.data.items.length === 0 && (
          <p className="text-sm text-muted-foreground">Chưa có quyền nào.</p>
        )}
        {grants.data && grants.data.items.length > 0 && (
          <ul className="divide-y rounded-md border" data-testid="danh-sach-quyen-cheo">
            {grants.data.items.map((g) => (
              <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 p-2 text-sm">
                <div className="space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Quyền #{g.id}</span>
                    <span>
                      {g.grantee_name ?? `Người dùng #${g.grantee_user_id}`} · {g.unit_name ?? `đơn vị #${g.unit_id}`}
                    </span>
                    {g.allow_verify && <Badge variant="outline">Duyệt</Badge>}
                    {g.allow_reject && <Badge variant="outline">Từ chối</Badge>}
                    {g.revoked_at && <Badge variant="secondary">Đã thu hồi</Badge>}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Cấp {formatDateTimeVN(g.granted_at)} · hết hạn {formatDateTimeVN(g.expires_at)}
                    {g.revoked_at ? ` · thu hồi ${formatDateTimeVN(g.revoked_at)}` : ""} · lý do: {g.reason}
                  </div>
                </div>
                {!g.revoked_at && (
                  <Button size="sm" variant="outline" onClick={() => setRevoking(g)}>
                    Thu hồi
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      {revoking && <RevokeDialog grant={revoking} onClose={() => setRevoking(null)} />}
    </div>
  )
}
