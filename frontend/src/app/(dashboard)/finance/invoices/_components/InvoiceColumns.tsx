// src/app/(dashboard)/finance/invoices/_components/InvoiceColumns.tsx
/**
 * Shared presentational parts for the invoice roster (desktop table + mobile
 * card). Thuần trình bày — không logic nghiệp vụ; quyền lấy từ can_* (thin
 * client). Reuse admission `Monogram` (trung tính, KHÔNG avatar màu). Class màu
 * literal static (Tailwind JIT).
 */

"use client"

import Link from "next/link"
import { CreditCard, Eye, FileText, MoreHorizontal, AlertTriangle, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { formatVND } from "@/lib/zod/finance"
import { FEE_TYPE_LABELS, type FeeType } from "@/types/finance.types"
import { Monogram } from "@/app/(dashboard)/admissions/_components/roster-parts"
import type { InvoiceListItemViewModel } from "@/hooks/finance/useInvoiceViewModel"

function feeTypeLabel(feeType: string | null): string | null {
  if (!feeType) return null
  return FEE_TYPE_LABELS[feeType as FeeType] ?? feeType
}

/** Khoản thu label: fee_type + HK{semester} (nếu có) hoặc Đợt {installment}. */
export function feeLineLabel(invoice: InvoiceListItemViewModel): string {
  const base = feeTypeLabel(invoice.fee_type)
  const term = invoice.semester_no != null ? `HK${invoice.semester_no}` : `Đợt ${invoice.installment_no}`
  return base ? `${base} · ${term}` : term
}

/**
 * Cột Học sinh: Monogram + tên (truncate) + dòng phụ `HS-mã · ngành`.
 * KHÔNG nhồi fee_type/HKn (đó là cột Khoản thu).
 */
export function IdentityCell({ invoice }: { invoice: InvoiceListItemViewModel }) {
  const name = invoice.profile_name ?? "Chưa rõ học sinh"
  const code = invoice.profile_code
  const program = invoice.program_name
  const sub = code ? (program ? `${code} · ${program}` : code) : program ?? invoice.invoice_number
  return (
    <div className="flex items-center gap-3 min-w-0">
      <Monogram name={name} />
      <div className="min-w-0">
        <div className="truncate font-medium text-foreground">{name}</div>
        <div className="truncate text-xs text-muted-foreground">{sub}</div>
      </div>
    </div>
  )
}

/** Cột Khoản thu: nhãn loại phí + kỳ/đợt. */
export function FeeCell({ invoice }: { invoice: InvoiceListItemViewModel }) {
  const base = feeTypeLabel(invoice.fee_type)
  const term = invoice.semester_no != null ? `HK${invoice.semester_no}` : `Đợt ${invoice.installment_no}`
  return (
    <div className="min-w-0">
      <div className="truncate text-sm text-foreground">{base ?? "—"}</div>
      <div className="truncate text-xs text-muted-foreground">{term}</div>
    </div>
  )
}

/**
 * Cột Số tiền (phải, tabular-nums): tiền chính + dòng phụ.
 * - has_penalty → tiền chính = total_due (đã gồm phạt) để "Còn" KHÔNG vượt số chính;
 *   không phạt → tiền chính = amount gốc.
 * - is_overdue → "Còn {remaining}₫ · quá N ngày" (đỏ)
 * - paid → "Đã thu đủ" (xanh)
 * - còn lại → "Còn {remaining}₫"
 * Gộp due + urgency vào đây (BỎ cột Hạn riêng).
 */
export function AmountCell({
  invoice,
  align = "right",
}: {
  invoice: InvoiceListItemViewModel
  align?: "right" | "left"
}) {
  // When penalty applies, remaining already includes it → show total_due as the
  // headline so "Còn {remaining}" never exceeds the displayed amount (reads as a bug).
  const headline = invoice.has_penalty ? invoice.total_due_formatted : invoice.amount_formatted
  return (
    <div className={cn("min-w-0", align === "right" ? "text-right" : "text-left")}>
      <div className="font-medium tabular-nums text-foreground">{headline}</div>
      <AmountSubline invoice={invoice} align={align} />
    </div>
  )
}

export function AmountSubline({
  invoice,
  align = "right",
}: {
  invoice: InvoiceListItemViewModel
  align?: "right" | "left"
}) {
  if (invoice.is_paid) {
    return (
      <div className={cn("text-xs tabular-nums text-emerald-600", align === "right" ? "text-right" : "")}>
        Đã thu đủ
      </div>
    )
  }
  return (
    <div className={cn("min-w-0", align === "right" ? "text-right" : "")}>
      <div
        className={cn(
          "flex items-center gap-1 text-xs tabular-nums",
          align === "right" ? "justify-end" : "",
          invoice.is_overdue ? "text-error-600" : "text-muted-foreground",
        )}
      >
        {invoice.is_overdue && <AlertTriangle className="size-3 shrink-0" aria-hidden="true" />}
        <span>
          Còn {invoice.remaining_amount_formatted}
          {invoice.is_overdue && invoice.overdue_days > 0 && ` · quá ${invoice.overdue_days} ngày`}
        </span>
      </div>
      {invoice.has_penalty && (
        <div className="text-[11px] tabular-nums text-muted-foreground">
          (gồm {formatVND(invoice.penalty_amount)} phạt)
        </div>
      )}
    </div>
  )
}

/**
 * Cột "Đã đóng" (tách khỏi "Số tiền") — paid_amount, xanh khi đã thu đủ.
 */
export function PaidCell({ invoice }: { invoice: InvoiceListItemViewModel }) {
  return (
    <div className="text-right tabular-nums">
      <span
        className={cn(
          "font-medium",
          invoice.is_paid ? "text-emerald-600" : "text-foreground",
        )}
      >
        {invoice.paid_amount_formatted}
      </span>
    </div>
  )
}

/**
 * Cột "Còn lại" — remaining (đỏ nếu quá hạn) + dòng phụ quá-N-ngày / phạt.
 * "Đã thu đủ" khi is_paid.
 */
export function RemainingCell({ invoice }: { invoice: InvoiceListItemViewModel }) {
  if (invoice.is_paid) {
    return (
      <div className="text-right text-xs font-medium tabular-nums text-emerald-600">
        Đã thu đủ
      </div>
    )
  }
  return (
    <div className="text-right tabular-nums">
      <div
        className={cn(
          "flex items-center justify-end gap-1 font-medium",
          invoice.is_overdue ? "text-error-600" : "text-foreground",
        )}
      >
        {invoice.is_overdue && (
          <AlertTriangle className="size-3 shrink-0" aria-hidden="true" />
        )}
        <span>{invoice.remaining_amount_formatted}</span>
      </div>
      {invoice.is_overdue && invoice.overdue_days > 0 && (
        <div className="text-[11px] text-error-600">
          quá {invoice.overdue_days} ngày
        </div>
      )}
      {invoice.has_penalty && (
        <div className="text-[11px] tabular-nums text-muted-foreground">
          (gồm {formatVND(invoice.penalty_amount)} phạt)
        </div>
      )}
    </div>
  )
}

/**
 * "Thu tiền" = nút hạng nhất (gate can_record_payment). Desktop: hover-reveal
 * (`opacity-0 group-hover:opacity-100`, luôn hiện khi focus-within). Mobile card:
 * truyền `alwaysVisible` để LUÔN hiện. Keyboard-reachable + aria-label.
 */
export function RecordPaymentButton({
  invoice,
  onRecordPayment,
  alwaysVisible = false,
  className,
}: {
  invoice: InvoiceListItemViewModel
  onRecordPayment: (invoice: InvoiceListItemViewModel) => void
  alwaysVisible?: boolean
  className?: string
}) {
  if (!invoice.can_record_payment) return null
  return (
    <Button
      size="sm"
      className={cn(
        "h-8 gap-1.5",
        !alwaysVisible &&
          "opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100",
        className,
      )}
      aria-label={`Thu tiền hóa đơn ${invoice.invoice_number}`}
      onClick={(e) => {
        e.stopPropagation()
        onRecordPayment(invoice)
      }}
    >
      <CreditCard className="size-4" aria-hidden="true" />
      Thu tiền
    </Button>
  )
}

/**
 * Menu ⋯ — chỉ chứa secondary actions: Phát hành / Hủy / Phạt / Xem chi tiết.
 * "Thu tiền" KHÔNG nằm trong menu (đã là nút hạng nhất).
 */
export function InvoiceRowActionsMenu({
  invoice,
  onIssue,
  onCancel,
  onPenalty,
}: {
  invoice: InvoiceListItemViewModel
  onIssue: (invoice: InvoiceListItemViewModel) => void
  onCancel: (invoice: InvoiceListItemViewModel) => void
  onPenalty: (invoice: InvoiceListItemViewModel) => void
}) {
  const hasSecondary = invoice.can_issue || invoice.can_cancel || invoice.can_apply_penalty
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-10 touch-manipulation md:size-8"
          aria-label={`Thao tác hóa đơn ${invoice.invoice_number}`}
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem asChild>
          <Link href={`/finance/invoices/${invoice.id}`} onClick={(e) => e.stopPropagation()}>
            <Eye className="mr-2 size-4" />
            Xem chi tiết
          </Link>
        </DropdownMenuItem>
        {hasSecondary && <DropdownMenuSeparator />}
        {invoice.can_issue && (
          <DropdownMenuItem onClick={() => onIssue(invoice)}>
            <FileText className="mr-2 size-4" />
            Phát hành
          </DropdownMenuItem>
        )}
        {invoice.can_apply_penalty && (
          <DropdownMenuItem onClick={() => onPenalty(invoice)}>
            <AlertTriangle className="mr-2 size-4" />
            Phạt trễ hạn
          </DropdownMenuItem>
        )}
        {invoice.can_cancel && (
          <DropdownMenuItem
            onClick={() => onCancel(invoice)}
            className="text-error-700 focus:text-error-700"
          >
            <XCircle className="mr-2 size-4" />
            Hủy
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { feeTypeLabel }
