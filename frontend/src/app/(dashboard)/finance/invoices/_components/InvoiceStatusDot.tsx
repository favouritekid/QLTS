// src/app/(dashboard)/finance/invoices/_components/InvoiceStatusDot.tsx
/**
 * InvoiceStatusDot — chấm màu + nhãn trạng thái cho danh sách hóa đơn.
 *
 * Mirror admission `StatusDot` nhưng đọc INVOICE_STATUS_CONFIG (single source).
 * `isOverdue` (backend-owned) override → "Quá hạn"/đỏ KỂ CẢ khi enum vẫn là
 * issued/partial; là nguồn DUY NHẤT khớp spine đỏ + tab + overdue_derived.
 * Thuần trình bày — class màu literal static (Tailwind JIT).
 */

"use client"

import { cn } from "@/lib/utils"
import {
  INVOICE_STATUS_CONFIG,
  getInvoiceStatusDotColor,
} from "@/lib/status-config"

export function InvoiceStatusDot({
  status,
  isOverdue,
}: {
  status: string
  /** Backend-owned derived overdue flag — overrides enum label + color when true. */
  isOverdue?: boolean
}) {
  const overdue = !!isOverdue
  const label = overdue
    ? INVOICE_STATUS_CONFIG.overdue.label
    : INVOICE_STATUS_CONFIG[status]?.label ?? status
  const dot = overdue ? "bg-error-500" : getInvoiceStatusDotColor(status)
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className={cn("size-2 shrink-0 rounded-full", dot)} />
      <span className={cn("text-sm", overdue ? "font-medium text-error-700" : "text-foreground")}>
        {label}
      </span>
    </span>
  )
}
