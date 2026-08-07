"use client"

import { CheckCircle2, Download, Loader2 } from "lucide-react"
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
  useCommitPaymentImport,
  useDownloadPaymentImportResult,
} from "@/hooks/finance/usePaymentImport"
import {
  formatAmount,
  type PaymentImportCommit,
  type PaymentImportPreview,
} from "@/lib/zod/payment-import"

import { ImportRowsTable } from "./ImportRowsTable"

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

export function PaymentImportPreviewResult({
  preview,
  onCommitted,
  onDiscard,
}: Props) {
  const commit = useCommitPaymentImport()
  const downloadResult = useDownloadPaymentImportResult()
  const [open, setOpen] = useState(false)
  const [committed, setCommitted] = useState<PaymentImportCommit | null>(null)

  const committable = preview.matched_count + preview.warned_count

  const handleCommit = (
    confirmedRows?: Array<{ row_no: number; review_token: string }>,
  ) => {
    commit.mutate(
      { batchId: preview.batch_id, confirmedRows },
      {
        onSuccess: (result) => {
          setOpen(false)
          setCommitted(result)
        },
      },
    )
  }

  // ── Sau commit: hiện kết quả + dòng KHÔNG ghi được (TOCTOU) thay vì giấu ──
  if (committed) {
    // Dòng bị hàng rào nghi trùng giữ lại — khác hẳn dòng hỏng vì số dư đổi:
    // chúng ghi lại được, và máy chủ cố ý KHÔNG đóng lô khi còn dòng như vậy.
    //
    // 🔴 Lọc trên TOÀN BỘ `rows`, KHÔNG lọc trong nhóm `error`: máy chủ giữ
    // những dòng này ở trạng thái `warned` chính vì lượt commit sau chỉ chọn
    // `matched`/`warned`. Lọc theo `error` thì chúng vô hình — nút ghi tiếp
    // không bao giờ hiện, và người dùng thấy "tất cả đã ghi thành công" trong
    // khi không dòng nào vào sổ. (Đã gặp thật khi smoke trên trình duyệt.)
    //
    // Đọc thẳng TRỤC GHI. Bản trước phải dò câu tiếng Việt trong `message`
    // ("nghi trùng") vì thân trả về không mang cờ riêng — mong manh (đổi câu
    // chữ là hỏng) và lẫn với cảnh báo của luật khác cùng chứa cụm từ ấy.
    const dongChoXacNhan = committed.rows.filter(
      (r) => r.commit_status === "duplicate_review_required" && r.review_token,
    )
    // Dòng hỏng THẬT: đã thử ghi và hỏng. Khác hẳn dòng bị giữ lại — cái này
    // phải sửa dữ liệu, cái kia chỉ cần soát rồi xác nhận.
    const errorRows = committed.rows.filter((r) => r.commit_status === "failed")

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
          {errorRows.length > 0 && (
            <>
              <p className="text-sm font-medium text-red-700">
                {errorRows.length} dòng KHÔNG ghi được (số dư đổi giữa preview→commit):
              </p>
              <ImportRowsTable rows={errorRows} />
            </>
          )}

          {/* Khối này phải đứng ĐỘC LẬP với khối lỗi ở trên. Lồng vào trong thì
              một lô mà mọi dòng đều bị giữ vì nghi trùng (không có lỗi thật nào)
              sẽ chẳng hiện gì — đúng ca đã gặp khi smoke. */}
          {dongChoXacNhan.length > 0 && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/40">
              <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
                {dongChoXacNhan.length} dòng bị giữ lại vì nghi trùng phiếu đã ghi
              </p>
              <ImportRowsTable rows={dongChoXacNhan} />
              <p className="mt-1 text-sm text-amber-800 dark:text-amber-300">
                Lô vẫn ở trạng thái xem trước nên những dòng này ghi lại được.
                Đối chiếu với phiếu đã nêu trong cột lý do; nếu đúng là khoản
                thu riêng thì ghi tiếp. Các dòng đã vào sổ sẽ không bị ghi hai lần.
              </p>
              <Button
                variant="outline"
                className="mt-2 border-amber-400 text-amber-900 hover:bg-amber-100 dark:text-amber-200"
                disabled={commit.isPending}
                onClick={() =>
                  // Gửi ĐÚNG phiếu của từng dòng, không phải một cờ cho cả lô.
                  handleCommit(
                    dongChoXacNhan.map((r) => ({
                      row_no: r.row_no,
                      review_token: r.review_token as string,
                    })),
                  )
                }
              >
                {commit.isPending ? (
                  <>
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    Đang ghi…
                  </>
                ) : (
                  "Đã soát — ghi tiếp các dòng nghi trùng"
                )}
              </Button>
            </div>
          )}

          {errorRows.length === 0 && dongChoXacNhan.length === 0 && (
            <p className="text-sm text-green-700">
              Tất cả dòng hợp lệ đã ghi thành công.
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="outline"
              disabled={downloadResult.isPending}
              onClick={() =>
                downloadResult.mutate({
                  batchId: committed.batch_id,
                  format: "xlsx",
                })
              }
            >
              <Download className="mr-1.5 h-4 w-4" />
              Tải kết quả (Excel)
            </Button>
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

        <ImportRowsTable rows={preview.rows} />

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
