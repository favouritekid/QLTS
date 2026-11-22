"use client"

/**
 * GĐ2-F1 — xem bảng chỉ tiêu năm + nút Sửa / Khoá / Mở khoá THEO CỜ máy chủ `available_actions` (cùng hàm với cổng ghi —
 * thin client: không suy nút từ `status`, không kiểm vai). Ô chỉ tiêu ngành `null` hiện "Trống — chưa nhập" (≠ 0).
 * `usage` là SỐ THAM KHẢO của máy chủ (`count_by_group`) — giao diện không tự tính "còn lại".
 */
import { useId, useState } from "react"
import { Lock, LockOpen, Pencil } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { useLockQuotaTable, useUnlockQuotaTable } from "@/lib/hooks/use-quota-tables"
import { memberLabel } from "@/lib/quota-tables/draft"
import { describeQuotaTableError } from "@/lib/quota-tables/messages"
import type { QuotaTableOut } from "@/lib/zod/quota-tables"

const STATUS_LABELS: Readonly<Record<string, string>> = {
  draft: "Nháp — đang soạn",
  locked: "Đã khoá",
}

const MAX_UNLOCK_REASON = 1000

interface Props {
  table: QuotaTableOut
  labelOf: (offeringAcademicInfoId: number) => string
  onEdit: () => void
}

export function QuotaTableView({ table, labelOf, onEdit }: Props) {
  const actions = new Set(table.available_actions)
  const [lockOpen, setLockOpen] = useState(false)
  const [unlockOpen, setUnlockOpen] = useState(false)

  return (
    <div className="space-y-4" data-testid="bang-chi-tieu-xem">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge variant={table.status === "locked" ? "success" : "secondary"} data-testid="trang-thai-bang">
            {STATUS_LABELS[table.status] ?? table.status}
          </Badge>
          <span className="text-muted-foreground">Phiên bản {table.version}</span>
          {table.locked_at && (
            <span className="text-muted-foreground">· khoá lúc {formatDateTimeVN(table.locked_at)}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.has("edit") && (
            <Button variant="outline" size="sm" onClick={onEdit} data-testid="nut-sua-bang">
              <Pencil className="mr-1 h-4 w-4" aria-hidden="true" />
              Sửa bảng
            </Button>
          )}
          {actions.has("lock") && (
            <Button size="sm" onClick={() => setLockOpen(true)} data-testid="nut-khoa-bang">
              <Lock className="mr-1 h-4 w-4" aria-hidden="true" />
              Khoá bảng
            </Button>
          )}
          {actions.has("unlock") && (
            <Button variant="outline" size="sm" onClick={() => setUnlockOpen(true)} data-testid="nut-mo-khoa-bang">
              <LockOpen className="mr-1 h-4 w-4" aria-hidden="true" />
              Mở khoá
            </Button>
          )}
        </div>
      </div>

      {table.groups.length === 0 && (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">Bảng chưa có nhóm ngành nào.</p>
      )}

      {table.groups.map((g) => (
        <Card key={g.id} data-testid={`nhom-${g.code}`}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {g.code} — {g.name}
            </CardTitle>
            <CardDescription className="tabular-nums">
              Trần chỉ tiêu nhóm: <strong>{g.ceiling}</strong> · Đã dùng (số tham khảo):{" "}
              <strong data-testid={`da-dung-${g.code}`}>{g.usage.used}</strong> — theo công bố {g.usage.publish_count},
              theo “Phê duyệt” cũ {g.usage.approved_count}. Số chính thức tính lúc khoá lần xét.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {g.members.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nhóm chưa có ngành nào.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ngành</TableHead>
                    <TableHead className="text-right">Chỉ tiêu năm</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {g.members.map((m) => (
                    <TableRow key={m.offering_academic_info_id}>
                      <TableCell>{memberLabel(m)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid={`chi-tieu-${m.offering_academic_info_id}`}>
                        {m.annual_admission_quota === null ? (
                          <span className="text-warning-700">Trống — chưa nhập</span>
                        ) : (
                          m.annual_admission_quota
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      ))}

      {lockOpen && <LockDialog table={table} labelOf={labelOf} onClose={() => setLockOpen(false)} />}
      {unlockOpen && <UnlockDialog table={table} labelOf={labelOf} onClose={() => setUnlockOpen(false)} />}
    </div>
  )
}

function LockDialog({ table, labelOf, onClose }: { table: QuotaTableOut; labelOf: Props["labelOf"]; onClose: () => void }) {
  const year = table.academic_year
  const lock = useLockQuotaTable(year)
  // Phiên bản + dấu chỉ tiêu chốt lúc mở hộp — bảng làm mới sau lỗi không âm thầm đổi bản sẽ khoá (khoá bản chưa xem).
  const [version] = useState(table.version)
  const [quotaFingerprint] = useState(table.quota_fingerprint)
  const [error, setError] = useState<string | null>(null)

  const submit = () => {
    setError(null)
    lock.mutate(
      { version, quota_fingerprint: quotaFingerprint },
      {
        onSuccess: () => {
          toast.success(`Đã khoá bảng chỉ tiêu năm ${year}`)
          onClose()
        },
        onError: (e) => setError(describeQuotaTableError(e, { year, labelOf })),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !lock.isPending && onClose()}>
      <DialogContent data-testid="hop-khoa-bang">
        <DialogHeader>
          <DialogTitle>Khoá bảng chỉ tiêu năm {year}?</DialogTitle>
          <DialogDescription>
            Sau khi khoá, không sửa được chỉ tiêu ngành, nhóm ngành và trần của năm này cho tới khi Admin mở khoá (có lý
            do). Mọi ngành trong bảng phải đã có chỉ tiêu năm.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={lock.isPending}>
            Huỷ
          </Button>
          <Button onClick={submit} disabled={lock.isPending} data-testid="xac-nhan-khoa-bang">
            {lock.isPending ? "Đang khoá…" : "Khoá bảng"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function UnlockDialog({ table, labelOf, onClose }: { table: QuotaTableOut; labelOf: Props["labelOf"]; onClose: () => void }) {
  const baseId = useId()
  const year = table.academic_year
  const unlock = useUnlockQuotaTable(year)
  const [version] = useState(table.version)
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const trimmed = reason.trim()
  const canSubmit = trimmed.length > 0 && trimmed.length <= MAX_UNLOCK_REASON && !unlock.isPending

  const submit = () => {
    if (!canSubmit) return
    setError(null)
    unlock.mutate(
      { version, reason: trimmed },
      {
        onSuccess: () => {
          toast.success(`Đã mở khoá bảng chỉ tiêu năm ${year}`)
          onClose()
        },
        onError: (e) => setError(describeQuotaTableError(e, { year, labelOf })),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !unlock.isPending && onClose()}>
      <DialogContent data-testid="hop-mo-khoa-bang">
        <DialogHeader>
          <DialogTitle>Mở khoá bảng chỉ tiêu năm {year}</DialogTitle>
          <DialogDescription>Lý do mở khoá là bắt buộc và được lưu vào nhật ký (ai, lúc nào, lý do).</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={`${baseId}-ly-do`}>Lý do mở khoá (bắt buộc)</Label>
          <Textarea
            id={`${baseId}-ly-do`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={MAX_UNLOCK_REASON}
            autoComplete="off"
            rows={3}
            disabled={unlock.isPending}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={unlock.isPending}>
            Huỷ
          </Button>
          <Button onClick={submit} disabled={!canSubmit} data-testid="xac-nhan-mo-khoa-bang">
            {unlock.isPending ? "Đang mở khoá…" : "Mở khoá"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
