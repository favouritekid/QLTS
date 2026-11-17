"use client"

/**
 * GĐ1b §2.2 / §6 — trang duyệt chéo tạm thời của CÁN BỘ được cấp quyền.
 *
 * - Có hiện trang hay không: `eligibility.eligible` của máy chủ (không theo vai).
 * - Nút từng giấy theo `grant_id_by_action` (Codex 69): "Duyệt" chỉ khi `verify ≠ null` và gửi ĐÚNG `verify`; "Từ chối"
 *   chỉ khi `reject ≠ null` và gửi ĐÚNG `reject`. Giao diện KHÔNG tự chọn / đổi quyền.
 * - 409 `actor_not_authorized` / `version_changed`, 404 ⇒ làm mới hàng đợi + quyền.
 * - Không Đặt lại, không lịch sử, không mở hồ sơ chung (phản hồi hẹp — chỉ id).
 * - Lô chéo: theo TỪNG quyền duyệt (`grant_id_by_action.verify`), `profile_ids` = các hồ sơ đang hiện có giấy dùng
 *   quyền ấy.
 */
import { useId, useState } from "react"
import axios from "axios"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  useCrossReviewEligibility,
  useCrossReviewQueue,
  useCrossReviewReject,
  useCrossReviewVerify,
} from "@/hooks/document-review/useCrossReview"
import { describeCrossActionError, formatDateTimeVN, formatLabel } from "@/lib/document-review/messages"
import { getStatusConfig } from "@/lib/status-config"
import type { CrossReviewQueueItem } from "@/lib/zod/document-review"

import { BatchListPanel } from "../bulk/BatchListPanel"
import { BatchStatusPanel } from "../bulk/BatchStatusPanel"
import { BulkVerifyDialog } from "../bulk/BulkVerifyDialog"

function RejectCrossDialog({ item, onClose }: { item: CrossReviewQueueItem; onClose: () => void }) {
  const reasonId = useId()
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const reject = useCrossReviewReject()
  const grantId = item.grant_id_by_action.reject
  const trimmed = reason.trim()

  const submit = () => {
    if (grantId === null || !trimmed || reject.isPending) return
    setError(null)
    reject.mutate(
      {
        grant_id: grantId,
        profile_id: item.profile_id,
        document_row_id: item.document_row_id,
        expected_row_version: item.row_version,
        reason: trimmed,
      },
      {
        onSuccess: () => {
          toast.success("Đã từ chối giấy")
          onClose()
        },
        onError: (e) => {
          const v = describeCrossActionError(e)
          if (v.kind === "refresh_queue") {
            toast.warning(v.message)
            onClose()
          } else setError(v.message)
        },
      },
    )
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Từ chối giấy (duyệt chéo)</DialogTitle>
          <DialogDescription>
            Hồ sơ #{item.profile_id} · {item.document_type_code ?? `giấy #${item.document_row_id}`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={reasonId}>Lý do từ chối (bắt buộc)</Label>
          <Textarea
            id={reasonId}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            autoComplete="off"
            rows={3}
            disabled={reject.isPending}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={reject.isPending}>
            Huỷ
          </Button>
          <Button variant="destructive" onClick={submit} disabled={!trimmed || reject.isPending}>
            {reject.isPending ? "Đang từ chối…" : "Từ chối"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CrossReviewClient() {
  const eligibility = useCrossReviewEligibility()
  const eligible = eligibility.data?.eligible === true
  const [page, setPage] = useState(1)
  const queue = useCrossReviewQueue(eligible, page)
  const verify = useCrossReviewVerify()
  const [rejecting, setRejecting] = useState<CrossReviewQueueItem | null>(null)
  const [bulkGrant, setBulkGrant] = useState<number | null>(null)
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null)
  const [busyRow, setBusyRow] = useState<number | null>(null)

  if (eligibility.isLoading) return <p className="text-sm text-muted-foreground">Đang kiểm quyền duyệt chéo…</p>
  if (eligibility.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Không kiểm được quyền duyệt chéo — thử lại sau.
      </p>
    )
  }
  if (!eligible) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="khong-co-quyen-cheo">
        Bạn chưa có quyền duyệt chéo còn hiệu lực. Quyền do Admin cấp theo từng cán bộ, đơn vị và thao tác.
      </p>
    )
  }

  const items = queue.data?.items ?? []
  const totalPages = queue.data ? Math.max(1, Math.ceil(queue.data.total_count / queue.data.page_size)) : 1
  const queueForbidden =
    axios.isAxiosError(queue.error) && (queue.error.response?.status === 403 || queue.error.response?.status === 404)
  // nhóm hồ sơ theo quyền DUYỆT mà máy chủ chọn cho từng giấy (trình bày, không chọn quyền)
  const byVerifyGrant = new Map<number, Set<number>>()
  for (const it of items) {
    const g = it.grant_id_by_action.verify
    if (g === null) continue
    if (!byVerifyGrant.has(g)) byVerifyGrant.set(g, new Set())
    byVerifyGrant.get(g)?.add(it.profile_id)
  }
  const grantsById = new Map((eligibility.data?.grants ?? []).map((g) => [g.grant_id, g]))

  const doVerify = (it: CrossReviewQueueItem) => {
    const grantId = it.grant_id_by_action.verify
    if (grantId === null || verify.isPending) return
    setBusyRow(it.document_row_id)
    verify.mutate(
      {
        grant_id: grantId,
        profile_id: it.profile_id,
        document_row_id: it.document_row_id,
        expected_row_version: it.row_version,
      },
      {
        onSuccess: () => toast.success("Đã duyệt giấy"),
        onError: (e) => toast.warning(describeCrossActionError(e).message),
        onSettled: () => setBusyRow(null),
      },
    )
  }

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Quyền đang có</h2>
        <ul className="space-y-1 text-sm" data-testid="quyen-cheo-dang-co">
          {(eligibility.data?.grants ?? []).map((g) => (
            <li key={g.grant_id}>
              Quyền #{g.grant_id} · đơn vị #{g.unit_id} ·{" "}
              {[g.allow_verify ? "duyệt" : null, g.allow_reject ? "từ chối" : null].filter(Boolean).join(", ")} · hết hạn{" "}
              {formatDateTimeVN(g.expires_at)}
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Giấy chờ duyệt chéo</h2>
          {[...byVerifyGrant.entries()].map(([g, profiles]) => (
            <Button key={g} size="sm" variant="outline" onClick={() => setBulkGrant(g)}>
              Duyệt lô theo quyền #{g}
              {grantsById.get(g) ? ` (đơn vị #${grantsById.get(g)?.unit_id})` : ""} · {profiles.size} hồ sơ
            </Button>
          ))}
        </div>
        {queue.isLoading && <p className="text-sm text-muted-foreground">Đang tải hàng đợi…</p>}
        {queue.isError && (
          <p role="alert" className="text-sm text-destructive">
            {queueForbidden ? "Bạn không có quyền xem hàng đợi duyệt chéo." : "Không tải được hàng đợi — thử lại sau."}
          </p>
        )}
        {queue.isSuccess && items.length === 0 && (
          <p className="text-sm text-muted-foreground">Không có giấy nào chờ duyệt chéo.</p>
        )}
        {items.length > 0 && (
          <ul className="divide-y rounded-md border" data-testid="hang-doi-cheo">
            {items.map((it) => (
              <li key={it.document_row_id} className="flex flex-wrap items-center justify-between gap-2 p-2 text-sm">
                <div className="space-y-0.5">
                  <div>
                    Hồ sơ #{it.profile_id} · {it.document_type_code ?? `giấy #${it.document_row_id}`}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Hình thức lúc nhận: {formatLabel(it.actual_submission_format)} · hồ sơ{" "}
                    <Badge variant="outline">{getStatusConfig(it.profile_status).label}</Badge>
                  </div>
                </div>
                <div className="flex gap-2">
                  {it.grant_id_by_action.verify !== null && (
                    <Button
                      size="sm"
                      onClick={() => doVerify(it)}
                      disabled={verify.isPending}
                      aria-label={`Duyệt giấy ${it.document_type_code ?? `#${it.document_row_id}`} của hồ sơ #${it.profile_id}`}
                    >
                      {busyRow === it.document_row_id ? "Đang duyệt…" : "Duyệt"}
                    </Button>
                  )}
                  {it.grant_id_by_action.reject !== null && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setRejecting(it)}
                      aria-label={`Từ chối giấy ${it.document_type_code ?? `#${it.document_row_id}`} của hồ sơ #${it.profile_id}`}
                    >
                      Từ chối
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {queue.data && totalPages > 1 && (
          <div className="flex items-center gap-2 text-sm" data-testid="phan-trang-cheo">
            <Button size="sm" variant="outline" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
              Trang trước
            </Button>
            <span>
              Trang {queue.data.page}/{totalPages} · {queue.data.total_count} giấy
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
            >
              Trang sau
            </Button>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Lô duyệt chéo của tôi</h2>
        {selectedBatch && (
          <div className="space-y-2 rounded-md border p-4">
            <div className="flex justify-end">
              <Button size="sm" variant="ghost" onClick={() => setSelectedBatch(null)}>
                Đóng
              </Button>
            </div>
            <BatchStatusPanel key={selectedBatch} endpoint={{ mode: "cross" }} batchId={selectedBatch} />
          </div>
        )}
        <BatchListPanel endpoint={{ mode: "cross" }} scope="mine" onSelect={setSelectedBatch} />
      </section>

      {rejecting && <RejectCrossDialog item={rejecting} onClose={() => setRejecting(null)} />}
      {bulkGrant !== null && (
        <BulkVerifyDialog
          open
          onOpenChange={(v) => {
            if (!v) setBulkGrant(null)
          }}
          endpoint={{ mode: "cross", grantId: bulkGrant }}
          selection={{ kind: "profiles", profileIds: [...(byVerifyGrant.get(bulkGrant) ?? [])] }}
          title={`Duyệt lô theo quyền #${bulkGrant}`}
          scopeLabel="các hồ sơ đang hiện trong hàng đợi dùng quyền này"
        />
      )}
    </div>
  )
}
