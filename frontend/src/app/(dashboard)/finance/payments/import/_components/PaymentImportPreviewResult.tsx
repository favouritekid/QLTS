"use client"

import { CheckCircle2, Loader2 } from "lucide-react"
import { useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useCommitPaymentImport } from "@/hooks/finance/usePaymentImport"
import {
  formatAmount,
  type PaymentImportCommit,
  type PaymentImportPreview,
  type PaymentImportRow,
} from "@/lib/zod/payment-import"

import { RowStatusBadge } from "./ImportStatusBadge"

interface Props {
  preview: PaymentImportPreview
  onCommitted: () => void
  onDiscard: () => void
}

function SummaryStat({
  label,
  value,
  className,
}: {
  label: string
  value: string | number
  className?: string
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold ${className ?? ""}`}>{value}</div>
    </div>
  )
}

const ROW_DISPLAY_CAP = 500

function RowsTable({ rows }: { rows: PaymentImportRow[] }) {
  const shown = rows.slice(0, ROW_DISPLAY_CAP)
  return (
    <div className="space-y-1">
      <div className="max-h-[28rem] overflow-auto rounded-lg border">
        <Table>
          <TableHeader className="sticky top-0 bg-background">
            <TableRow>
              <TableHead className="w-14">Dòng</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead>CCCD</TableHead>
              <TableHead className="text-right">Số tiền</TableHead>
              <TableHead>Phân bổ / Ghi chú</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => (
            <TableRow key={r.row_no}>
              <TableCell className="font-mono text-xs">{r.row_no}</TableCell>
              <TableCell>
                <RowStatusBadge status={r.status} />
              </TableCell>
              <TableCell className="font-mono text-xs">
                {r.citizen_id ?? "—"}
              </TableCell>
              <TableCell className="text-right">{formatAmount(r.amount)}</TableCell>
              <TableCell className="text-xs">
                {r.allocations.length > 0 ? (
                  <span className="text-muted-foreground">
                    {r.allocations
                      .map((a) => `Đợt ${a.installment_no}: ${formatAmount(a.amount)}`)
                      .join(" · ")}
                  </span>
                ) : null}
                {r.message ? (
                  <span
                    className={
                      r.status === "error" ? "text-red-600" : "text-amber-600"
                    }
                  >
                    {r.allocations.length > 0 ? " — " : ""}
                    {r.message}
                  </span>
                ) : null}
              </TableCell>
            </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {rows.length > ROW_DISPLAY_CAP ? (
        <p className="text-xs text-muted-foreground">
          Hiển thị {ROW_DISPLAY_CAP}/{rows.length} dòng đầu — xem file gốc để biết
          đầy đủ.
        </p>
      ) : null}
    </div>
  )
}

export function PaymentImportPreviewResult({
  preview,
  onCommitted,
  onDiscard,
}: Props) {
  const commit = useCommitPaymentImport()
  const [open, setOpen] = useState(false)
  const [committed, setCommitted] = useState<PaymentImportCommit | null>(null)

  const committable = preview.matched_count + preview.warned_count

  const handleCommit = () => {
    commit.mutate(preview.batch_id, {
      onSuccess: (result) => {
        setOpen(false)
        setCommitted(result)
      },
    })
  }

  // ── Sau commit: hiện kết quả + dòng KHÔNG ghi được (TOCTOU) thay vì giấu ──
  if (committed) {
    const errorRows = committed.rows.filter((r) => r.status === "error")
    return (
      <Card>
        <CardHeader>
          <CardTitle>Kết quả ghi tiền — lô #{committed.batch_id}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryStat
              label="Đã ghi"
              value={committed.committed_count}
              className="text-green-700"
            />
            <SummaryStat
              label="Lỗi"
              value={committed.failed_count}
              className="text-red-700"
            />
            <SummaryStat label="Số Payment" value={committed.payment_count} />
            <SummaryStat
              label="Tổng đã ghi"
              value={formatAmount(committed.total_amount)}
            />
          </div>
          {errorRows.length > 0 ? (
            <>
              <p className="text-sm font-medium text-red-700">
                {errorRows.length} dòng KHÔNG ghi được (số dư đổi giữa preview→commit):
              </p>
              <RowsTable rows={errorRows} />
            </>
          ) : (
            <p className="text-sm text-green-700">
              Tất cả dòng hợp lệ đã ghi thành công.
            </p>
          )}
          <div className="flex justify-end">
            <Button onClick={onCommitted}>Xong</Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // ── Trước commit: xem trước 3 nhóm ──
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span>
            Xem trước lô #{preview.batch_id} — HK{preview.semester_no}/
            {preview.academic_year}
          </span>
          <span className="truncate text-sm font-normal text-muted-foreground">
            {preview.file_name}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryStat
            label="Khớp"
            value={preview.matched_count}
            className="text-green-700"
          />
          <SummaryStat
            label="Cảnh báo"
            value={preview.warned_count}
            className="text-amber-700"
          />
          <SummaryStat
            label="Lỗi"
            value={preview.failed_count}
            className="text-red-700"
          />
          <SummaryStat
            label="Tổng dự kiến"
            value={formatAmount(preview.total_amount)}
          />
        </div>

        <RowsTable rows={preview.rows} />

        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" onClick={onDiscard} disabled={commit.isPending}>
            Hủy / chọn file khác
          </Button>
          <AlertDialog open={open} onOpenChange={setOpen}>
            <AlertDialogTrigger asChild>
              <Button disabled={committable === 0 || commit.isPending}>
                {commit.isPending ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="mr-1.5 h-4 w-4" />
                )}
                Ghi tiền ({committable} dòng)
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Xác nhận ghi tiền</AlertDialogTitle>
                <AlertDialogDescription>
                  Hệ thống sẽ tự xác minh và ghi nhận {committable} khoản thu (tổng
                  dự kiến {formatAmount(preview.total_amount)}). Thao tác này ghi
                  tiền vào hồ sơ; muốn rút lại phải đảo (void) lô. Tiếp tục?
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={commit.isPending}>
                  Hủy
                </AlertDialogCancel>
                <AlertDialogAction
                  onClick={(e) => {
                    e.preventDefault()
                    handleCommit()
                  }}
                  disabled={commit.isPending}
                >
                  Ghi tiền
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardContent>
    </Card>
  )
}
