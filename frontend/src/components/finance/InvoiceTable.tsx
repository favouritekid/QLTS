// src/components/finance/InvoiceTable.tsx
"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Eye,
  MoreHorizontal,
  FileText,
  XCircle,
  CreditCard,
  AlertTriangle,
} from "lucide-react"
import { AmountDisplay, InvoiceStatusBadge } from "@/components/finance"
import { cn } from "@/lib/utils"
import type { InvoiceSummary, Invoice, InvoiceStatus } from "@/types/finance.types"

// =============================================================================
// TYPES
// =============================================================================

export interface InvoiceTableProps {
  /** List of invoices to display */
  invoices: (InvoiceSummary | Invoice)[]
  /** Callback when user clicks view action */
  onView?: (invoice: InvoiceSummary | Invoice) => void
  /** Callback when user clicks issue action */
  onIssue?: (invoice: InvoiceSummary | Invoice) => void
  /** Callback when user clicks cancel action */
  onCancel?: (invoice: InvoiceSummary | Invoice) => void
  /** Callback when user clicks record payment action */
  onRecordPayment?: (invoice: InvoiceSummary | Invoice) => void
  /** Callback when user clicks apply penalty action */
  onApplyPenalty?: (invoice: InvoiceSummary | Invoice) => void
  /** Show actions column */
  showActions?: boolean
  /** Compact mode (less columns) */
  compact?: boolean
  /** Empty state message */
  emptyMessage?: string
  /** Additional class name */
  className?: string
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function formatDate(dateString: string | null): string {
  if (!dateString) return "-"
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(dateString))
}

function isOverdue(dueDate: string, status: InvoiceStatus): boolean {
  if (status === "paid" || status === "cancelled") return false
  return new Date(dueDate) < new Date()
}

function hasPermission(invoice: InvoiceSummary | Invoice, key: keyof Invoice): boolean {
  if (key in invoice) {
    return (invoice as Invoice)[key] === true
  }
  return false
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * InvoiceTable - Reusable invoice list table component
 *
 * Features:
 * - Displays invoice number, installment, status, amounts, due date
 * - Optional action dropdown (view, issue, cancel, record payment, apply penalty)
 * - Compact mode for embedding in other views
 * - Click row to view detail
 *
 * @example
 * ```tsx
 * <InvoiceTable
 *   invoices={fee.invoices}
 *   onView={(inv) => router.push(`/finance/invoices/${inv.id}`)}
 *   onRecordPayment={(inv) => setRecordPaymentInvoice(inv)}
 * />
 * ```
 */
export function InvoiceTable({
  invoices,
  onView,
  onIssue,
  onCancel,
  onRecordPayment,
  onApplyPenalty,
  showActions = true,
  compact = false,
  emptyMessage = "Chưa có hóa đơn nào",
  className,
}: InvoiceTableProps) {
  const router = useRouter()

  const handleRowClick = (invoice: InvoiceSummary | Invoice) => {
    if (onView) {
      onView(invoice)
    } else {
      router.push(`/finance/invoices/${invoice.id}`)
    }
  }

  if (invoices.length === 0) {
    return (
      <Card className={cn("p-8 text-center", className)}>
        <FileText className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
        <p className="text-muted-foreground">{emptyMessage}</p>
      </Card>
    )
  }

  return (
    <Card className={className}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Số HĐ</TableHead>
            <TableHead>Đợt</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="text-right">Số tiền</TableHead>
            {!compact && (
              <TableHead className="text-right">Còn lại</TableHead>
            )}
            <TableHead>Hạn</TableHead>
            {showActions && <TableHead className="w-[50px]"></TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {invoices.map((invoice) => {
            const overdue = isOverdue(invoice.due_date, invoice.status)

            return (
              <TableRow
                key={invoice.id}
                className="cursor-pointer hover:bg-muted/50"
                onClick={() => handleRowClick(invoice)}
              >
                <TableCell className="font-mono text-sm">
                  {invoice.invoice_number}
                </TableCell>
                <TableCell>Đợt {invoice.installment_no}</TableCell>
                <TableCell>
                  <InvoiceStatusBadge status={invoice.status} size="sm" />
                </TableCell>
                <TableCell className="text-right">
                  <AmountDisplay
                    amount={invoice.amount}
                    showCurrency={false}
                    size="sm"
                  />
                </TableCell>
                {!compact && (
                  <TableCell className="text-right">
                    <AmountDisplay
                      amount={invoice.remaining_amount}
                      showCurrency={false}
                      size="sm"
                      className={cn(
                        parseFloat(invoice.remaining_amount) > 0 && "text-warning-600"
                      )}
                    />
                  </TableCell>
                )}
                <TableCell>
                  <span
                    className={cn(
                      "text-sm",
                      overdue && "text-destructive font-medium"
                    )}
                  >
                    {formatDate(invoice.due_date)}
                  </span>
                </TableCell>
                {showActions && (
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => handleRowClick(invoice)}>
                          <Eye className="h-4 w-4 mr-2" />
                          Xem chi tiết
                        </DropdownMenuItem>

                        {hasPermission(invoice, "can_issue") && onIssue && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => onIssue(invoice)}>
                              <FileText className="h-4 w-4 mr-2" />
                              Xuất hóa đơn
                            </DropdownMenuItem>
                          </>
                        )}

                        {hasPermission(invoice, "can_record_payment") && onRecordPayment && (
                          <DropdownMenuItem onClick={() => onRecordPayment(invoice)}>
                            <CreditCard className="h-4 w-4 mr-2" />
                            Ghi nhận thanh toán
                          </DropdownMenuItem>
                        )}

                        {hasPermission(invoice, "can_apply_penalty") && onApplyPenalty && (
                          <DropdownMenuItem
                            onClick={() => onApplyPenalty(invoice)}
                            className="text-warning-600 focus:text-warning-600"
                          >
                            <AlertTriangle className="h-4 w-4 mr-2" />
                            Áp dụng phí trễ hạn
                          </DropdownMenuItem>
                        )}

                        {hasPermission(invoice, "can_cancel") && onCancel && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => onCancel(invoice)}
                              className="text-destructive focus:text-destructive"
                            >
                              <XCircle className="h-4 w-4 mr-2" />
                              Hủy hóa đơn
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                )}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </Card>
  )
}

export default InvoiceTable
