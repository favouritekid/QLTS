"use client"

/**
 * GĐ2-C C1 — Admin gán / thu hồi / xem quyền "Thư ký Hội đồng" (khuôn màn hình quyền duyệt chéo GĐ1b).
 * Gán theo TỪNG người (Quản lý / Cán bộ), lý do bắt buộc; KHÔNG hết hạn (owner C1) — chỉ hết khi Admin thu hồi hoặc tài khoản
 * bị khoá / đổi vai; phạm vi toàn trường (owner C2). Chỉ thu hồi, không xoá. Mọi luật do MÁY CHỦ kiểm; giao diện không suy
 * vai — không phải Admin ⇒ máy chủ 403 ⇒ trang báo.
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
import { formatDateTimeVN } from "@/lib/document-review/messages"
import {
  useCreateReviewSecretaryGrant,
  useReviewSecretaryGrants,
  useRevokeReviewSecretaryGrant,
} from "@/lib/hooks/use-review-secretaries"
import { describeReviewSecretaryError, roleLabel } from "@/lib/review-secretaries/messages"
import type { ReviewSecretaryGrant } from "@/lib/zod/review-secretaries"

function positiveInt(v: string): number | null {
  if (!/^\d+$/.test(v.trim())) return null
  const n = Number(v.trim())
  return Number.isSafeInteger(n) && n > 0 ? n : null
}

/** "Họ tên (tên đăng nhập) · Cán bộ · #id" — thiếu tóm tắt ⇒ chỉ mã. */
export function grantPersonLabel(g: ReviewSecretaryGrant): string {
  if (!g.user) return `Người dùng #${g.user_id}`
  const ten = g.user.full_name ? `${g.user.full_name} (${g.user.username})` : g.user.username
  return `${ten} · ${roleLabel(g.user.role)} · #${g.user.id}`
}

function CreateGrantForm() {
  const baseId = useId()
  const [user, setUser] = useState("")
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const create = useCreateReviewSecretaryGrant()

  const userId = positiveInt(user)
  const canSubmit = userId !== null && reason.trim().length > 0 && !create.isPending

  const submit = () => {
    if (!canSubmit || userId === null) return
    setError(null)
    create.mutate(
      { user_id: userId, reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success("Đã gán quyền Thư ký Hội đồng")
          setUser("")
          setReason("")
        },
        onError: (e) => setError(describeReviewSecretaryError(e)),
      },
    )
  }

  return (
    <section className="space-y-3 rounded-md border p-4" data-testid="gan-thu-ky">
      <h2 className="text-lg font-semibold">Gán Thư ký Hội đồng</h2>
      <div className="space-y-1">
        <Label htmlFor={`${baseId}-nguoi`}>Mã người dùng (Quản lý hoặc Cán bộ đang hoạt động)</Label>
        <Input
          id={`${baseId}-nguoi`}
          inputMode="numeric"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          className="sm:max-w-xs"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${baseId}-ly-do`}>Lý do gán (bắt buộc)</Label>
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
        {create.isPending ? "Đang gán…" : "Gán quyền"}
      </Button>
    </section>
  )
}

function RevokeDialog({ grant, onClose }: { grant: ReviewSecretaryGrant; onClose: () => void }) {
  const reasonId = useId()
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const revoke = useRevokeReviewSecretaryGrant()
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
        onError: (e) => setError(describeReviewSecretaryError(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Thu hồi quyền Thư ký #{grant.id}</DialogTitle>
          <DialogDescription>
            {grantPersonLabel(grant)}. Thu hồi có hiệu lực ngay; quyền không bị xoá, vẫn còn trong lịch sử. Muốn gán lại phải
            gán mới, có lý do.
          </DialogDescription>
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

export function ReviewSecretariesClient() {
  const activeId = useId()
  const [activeOnly, setActiveOnly] = useState(true)
  const grants = useReviewSecretaryGrants(activeOnly ? { active: true } : {})
  const [revoking, setRevoking] = useState<ReviewSecretaryGrant | null>(null)

  if (grants.isError) {
    return (
      <p role="alert" className="text-sm text-destructive" data-testid="thu-ky-loi">
        {describeReviewSecretaryError(grants.error)}
      </p>
    )
  }

  return (
    <div className="space-y-6">
      <CreateGrantForm />
      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">Quyền đã gán</h2>
          <div className="flex items-center gap-2">
            <Checkbox id={activeId} checked={activeOnly} onCheckedChange={(v) => setActiveOnly(v === true)} />
            <Label htmlFor={activeId} className="font-normal">
              Chỉ quyền còn hiệu lực
            </Label>
          </div>
        </div>
        {grants.isLoading && <p className="text-sm text-muted-foreground">Đang tải…</p>}
        {grants.data && grants.data.length === 0 && (
          <p className="text-sm text-muted-foreground">Chưa có Thư ký Hội đồng nào.</p>
        )}
        {grants.data && grants.data.length > 0 && (
          <ul className="divide-y rounded-md border" data-testid="danh-sach-thu-ky">
            {grants.data.map((g) => (
              <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 p-2 text-sm">
                <div className="min-w-0 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Quyền #{g.id}</span>
                    <span className="break-words">{grantPersonLabel(g)}</span>
                    {g.is_active ? (
                      <Badge variant="success">Còn hiệu lực</Badge>
                    ) : (
                      <Badge variant="secondary">Đã thu hồi</Badge>
                    )}
                  </div>
                  <div className="break-words text-xs text-muted-foreground">
                    Gán {formatDateTimeVN(g.granted_at)} · lý do: {g.reason}
                    {g.revoked_at ? ` · thu hồi ${formatDateTimeVN(g.revoked_at)} · lý do thu hồi: ${g.revoke_reason ?? ""}` : ""}
                  </div>
                </div>
                {g.is_active && (
                  <Button size="sm" variant="outline" onClick={() => setRevoking(g)} aria-label={`Thu hồi quyền #${g.id}`}>
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
