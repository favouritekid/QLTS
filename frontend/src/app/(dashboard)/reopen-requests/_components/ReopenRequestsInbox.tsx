"use client"

import { useState } from "react"
import Link from "next/link"
import { Check, Clock, Loader2, RotateCcw, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  useApproveReopenRequest,
  useRejectReopenRequest,
  useReopenRequests,
} from "@/hooks/useLeads"
import type { ReopenRequestItem } from "@/lib/api/leads"

const STATUS_LABEL: Record<string, string> = {
  pending: "Chờ duyệt",
  approved: "Đã duyệt",
  rejected: "Đã từ chối",
  cancelled: "Đã hủy",
}

const STATUS_CLASS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-rose-100 text-rose-700",
  cancelled: "bg-gray-100 text-gray-600",
}

const REJECT_NOTE_MIN = 5

/**
 * Inbox duyệt yêu cầu mở lại (manager/admin). Dữ liệu IDOR-scoped ở backend
 * (manager chỉ thấy request của unit mình). Hành động: duyệt (mở lại lead ngay) /
 * từ chối (note bắt buộc).
 */
export function ReopenRequestsInbox() {
  const [statusFilter, setStatusFilter] = useState<string>("pending")
  const { data: requests, isLoading } = useReopenRequests(
    statusFilter === "all" ? undefined : statusFilter,
  )
  const approve = useApproveReopenRequest()
  const reject = useRejectReopenRequest()

  const [rejectTarget, setRejectTarget] = useState<ReopenRequestItem | null>(null)
  const [rejectNote, setRejectNote] = useState("")
  const rejectValid = rejectNote.trim().length >= REJECT_NOTE_MIN

  function closeReject() {
    if (reject.isPending) return
    setRejectTarget(null)
    setRejectNote("")
  }

  function handleReject() {
    if (!rejectTarget || !rejectValid) return
    reject.mutate(
      { requestId: rejectTarget.id, note: rejectNote.trim() },
      {
        onSuccess: () => {
          setRejectTarget(null)
          setRejectNote("")
        },
      },
    )
  }

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <RotateCcw className="h-6 w-6 text-amber-600" />
            Yêu cầu mở lại tư vấn
          </h1>
          <p className="text-sm text-muted-foreground">
            Officer xin mở lại lead &ldquo;Đã ngừng tư vấn&rdquo; — duyệt để mở
            lại ngay, hoặc từ chối kèm lý do.
          </p>
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pending">Chờ duyệt</SelectItem>
            <SelectItem value="approved">Đã duyệt</SelectItem>
            <SelectItem value="rejected">Đã từ chối</SelectItem>
            <SelectItem value="cancelled">Đã hủy</SelectItem>
            <SelectItem value="all">Tất cả</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-32 rounded-lg" />
          ))}
        </div>
      ) : !requests || requests.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Clock className="mx-auto h-10 w-10 mb-2 opacity-40" />
            Không có yêu cầu nào.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {requests.map((req) => (
            <Card key={req.id}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base">
                    <Link
                      href={`/leads/${req.lead_id}`}
                      className="hover:underline"
                    >
                      {req.lead_name ?? `Lead #${req.lead_id}`}
                    </Link>
                  </CardTitle>
                  <Badge
                    variant="outline"
                    className={`border-0 ${STATUS_CLASS[req.status] ?? ""}`}
                  >
                    {STATUS_LABEL[req.status] ?? req.status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {req.requested_by_name ?? `User #${req.requested_by_id}`}
                  {" • "}
                  {new Date(req.created_at).toLocaleString("vi-VN")}
                </p>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm whitespace-pre-wrap">{req.reason}</p>
                {req.review_note && (
                  <p className="text-xs text-muted-foreground">
                    Ghi chú: {req.review_note}
                  </p>
                )}
                {req.status === "pending" && (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700"
                      disabled={approve.isPending}
                      onClick={() => approve.mutate({ requestId: req.id })}
                    >
                      {approve.isPending ? (
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      ) : (
                        <Check className="mr-1.5 h-4 w-4" />
                      )}
                      Duyệt
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-rose-300 text-rose-700 hover:bg-rose-50"
                      onClick={() => {
                        setRejectTarget(req)
                        setRejectNote("")
                      }}
                    >
                      <X className="mr-1.5 h-4 w-4" />
                      Từ chối
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(o) => {
          if (!o) closeReject()
        }}
      >
        <DialogContent className="sm:max-w-[460px]">
          <DialogHeader>
            <DialogTitle>Từ chối yêu cầu mở lại</DialogTitle>
            <DialogDescription>
              Lead{" "}
              <strong>
                {rejectTarget?.lead_name ?? `#${rejectTarget?.lead_id}`}
              </strong>
              . Lý do từ chối sẽ được gửi tới officer.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="reject-note">
              Lý do từ chối{" "}
              <span className="text-muted-foreground text-xs">
                (bắt buộc, ≥ {REJECT_NOTE_MIN} ký tự)
              </span>
            </Label>
            <Textarea
              id="reject-note"
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              disabled={reject.isPending}
              rows={3}
              placeholder="Ví dụ: lead đã liên hệ nhiều lần không phản hồi, không nên mở lại."
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={reject.isPending}
              onClick={closeReject}
            >
              Hủy
            </Button>
            <Button
              className="bg-rose-600 hover:bg-rose-700"
              disabled={!rejectValid || reject.isPending}
              onClick={handleReject}
            >
              {reject.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Từ chối
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
