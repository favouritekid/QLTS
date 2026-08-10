"use client"

import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
} from "lucide-react"
import { useState } from "react"

import { ErrorEmptyState, TableEmptyState } from "@/components/common/EmptyState"
import { Button } from "@/components/ui/button"
import { ResumeReviewAction } from "./ResumeReviewAction"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { TableSkeleton } from "@/components/ui/skeletons"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  usePaymentImportBatchDetail,
  usePaymentImportBatches,
  useDownloadPaymentImportResult,
} from "@/hooks/finance/usePaymentImport"
import {
  formatAmount,
  type PaymentImportBatchSummary,
} from "@/lib/zod/payment-import"

import { ImportRowsTable } from "./ImportRowsTable"
import { BatchStatusBadge } from "./ImportStatusBadge"
import { PaymentImportVoidDialog } from "./PaymentImportVoidDialog"

const PAGE_SIZE = 20
const COL_COUNT = 9 // số cột (gồm cột expand) → colSpan dòng chi tiết

function formatDate(iso?: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("vi-VN")
}

/** 1 dòng lô + (mở rộng) chi tiết per-row. Hook detail/download gọi top-level ở đây. */
function BatchRow({ b }: { b: PaymentImportBatchSummary }) {
  const [expanded, setExpanded] = useState(false)
  const detail = usePaymentImportBatchDetail(b.id, expanded)
  const download = useDownloadPaymentImportResult()

  return (
    <>
      <TableRow>
        <TableCell className="w-8 pr-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={expanded ? "Thu gọn" : "Xem chi tiết"}
            onClick={() => setExpanded((e) => !e)}
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </Button>
        </TableCell>
        <TableCell className="font-mono text-xs">{b.id}</TableCell>
        <TableCell className="whitespace-nowrap text-sm">
          HK{b.semester_no}/{b.academic_year}
        </TableCell>
        <TableCell className="max-w-[12rem] truncate text-sm">
          {b.file_name}
        </TableCell>
        <TableCell>
          <BatchStatusBadge status={b.status} />
        </TableCell>
        <TableCell className="text-center text-xs">
          <span className="text-green-700">{b.matched_count}</span>
          {" / "}
          <span className="text-amber-700">{b.warned_count}</span>
          {" / "}
          <span className="text-red-700">{b.failed_count}</span>
        </TableCell>
        <TableCell className="text-right">{formatAmount(b.total_amount)}</TableCell>
        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
          {formatDate(b.created_at)}
        </TableCell>
        <TableCell className="text-right">
          <div className="flex items-center justify-end gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={download.isPending}
              aria-label="Tải file kết quả (Excel)"
              onClick={() => download.mutate({ batchId: b.id, format: "xlsx" })}
            >
              <Download className="h-4 w-4" />
            </Button>
            {/* Đường ghi tiếp cho lô còn dòng chờ soát. Điều kiện hiện nút do
                MÁY CHỦ quyết (`can_resume_commit`); ở đây chỉ đọc cờ. Thiếu nút
                này thì lô mắc kẹt ngay khi người dùng refresh hoặc đóng tab —
                backend vẫn nhận `confirmed_rows` nhưng không còn chỗ nào gửi. */}
            {b.can_resume_commit ? (
              <ResumeReviewAction
                batchId={b.id}
                reviewRequiredCount={b.review_required_count}
              />
            ) : null}
            {b.can_void ? <PaymentImportVoidDialog batchId={b.id} /> : null}
          </div>
        </TableCell>
      </TableRow>
      {expanded ? (
        <TableRow>
          <TableCell colSpan={COL_COUNT} className="bg-muted/30">
            {detail.isLoading ? (
              <TableSkeleton rows={3} />
            ) : detail.isError ? (
              <ErrorEmptyState message="Không tải được chi tiết lô." />
            ) : detail.data ? (
              <ImportRowsTable rows={detail.data.rows} batchStatus={b.status} />
            ) : null}
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}

export function PaymentImportHistory() {
  const [page, setPage] = useState(1)
  const { data, isLoading, isError } = usePaymentImportBatches(page, PAGE_SIZE)

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Card>
      <CardHeader>
        <CardTitle>Lịch sử lô import</CardTitle>
        <CardDescription>
          Các lô đã xem trước / ghi tiền / đảo (mới nhất trước). Mở rộng để xem từng
          dòng; tải file kết quả để đối soát.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <TableSkeleton rows={5} />
        ) : isError ? (
          <ErrorEmptyState message="Không tải được lịch sử lô." />
        ) : !data || data.items.length === 0 ? (
          <TableEmptyState title="Chưa có lô import nào." />
        ) : (
          <>
            <div className="overflow-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead className="w-12">#</TableHead>
                    <TableHead>Năm / Kỳ</TableHead>
                    <TableHead>File</TableHead>
                    <TableHead>Trạng thái</TableHead>
                    <TableHead className="text-center">Khớp / CB / Lỗi</TableHead>
                    <TableHead className="text-right">Tổng tiền</TableHead>
                    <TableHead>Tạo lúc</TableHead>
                    <TableHead className="text-right">Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((b) => (
                    <BatchRow key={b.id} b={b} />
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                Trang {page}/{totalPages} · {data.total} lô
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
