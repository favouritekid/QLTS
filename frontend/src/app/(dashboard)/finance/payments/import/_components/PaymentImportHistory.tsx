"use client"

import { ChevronLeft, ChevronRight } from "lucide-react"
import { useState } from "react"

import { ErrorEmptyState, TableEmptyState } from "@/components/common/EmptyState"
import { Button } from "@/components/ui/button"
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
import { usePaymentImportBatches } from "@/hooks/finance/usePaymentImport"
import { formatAmount } from "@/lib/zod/payment-import"

import { BatchStatusBadge } from "./ImportStatusBadge"
import { PaymentImportVoidDialog } from "./PaymentImportVoidDialog"

const PAGE_SIZE = 20

function formatDate(iso?: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("vi-VN")
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
          Các lô đã xem trước / ghi tiền / đảo (mới nhất trước).
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
                    <TableHead className="w-12">#</TableHead>
                    <TableHead>Năm / Kỳ</TableHead>
                    <TableHead>File</TableHead>
                    <TableHead>Trạng thái</TableHead>
                    <TableHead className="text-center">
                      Khớp / CB / Lỗi
                    </TableHead>
                    <TableHead className="text-right">Tổng tiền</TableHead>
                    <TableHead>Tạo lúc</TableHead>
                    <TableHead className="text-right">Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((b) => (
                    <TableRow key={b.id}>
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
                      <TableCell className="text-right">
                        {formatAmount(b.total_amount)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatDate(b.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {b.can_void ? (
                          <PaymentImportVoidDialog batchId={b.id} />
                        ) : null}
                      </TableCell>
                    </TableRow>
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
