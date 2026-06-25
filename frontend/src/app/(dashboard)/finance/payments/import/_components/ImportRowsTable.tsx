"use client"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatAmount, type PaymentImportRow } from "@/lib/zod/payment-import"

import { RowStatusBadge } from "./ImportStatusBadge"

const ROW_DISPLAY_CAP = 500

/** Bảng per-row dùng chung: preview (trước commit) + lịch sử (xem lại sau commit). */
export function ImportRowsTable({ rows }: { rows: PaymentImportRow[] }) {
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
                        .map(
                          (a) => `Đợt ${a.installment_no}: ${formatAmount(a.amount)}`,
                        )
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
          Hiển thị {ROW_DISPLAY_CAP}/{rows.length} dòng đầu — xem file gốc để biết đầy
          đủ.
        </p>
      ) : null}
    </div>
  )
}
