// src/app/(dashboard)/finance/invoices/_components/InvoiceCard.tsx
/**
 * InvoiceCard — mobile tile cho 1 hóa đơn (list-first, single-scroll).
 *
 * Status SPINE = `border-l-2` màu theo enum + is_overdue ĐỎ override. "Thu tiền"
 * (can_record_payment) LUÔN hiện (touch không hover). Menu ⋯ chỉ secondary.
 * Thuần trình bày.
 */

"use client"

import { cn } from "@/lib/utils"
import { getInvoiceStatusSpineColor } from "@/lib/status-config"
import { Monogram } from "@/app/(dashboard)/admissions/_components/roster-parts"
import type { InvoiceListItemViewModel } from "@/hooks/finance/useInvoiceViewModel"
import { InvoiceStatusDot } from "./InvoiceStatusDot"
import {
  AmountSubline,
  InvoiceRowActionsMenu,
  RecordPaymentButton,
  feeLineLabel,
} from "./InvoiceColumns"

/** Enter/Space kích hoạt card, bỏ qua khi focus ở element interactive bên trong. */
function activateCard(e: React.KeyboardEvent, fn: () => void) {
  if (e.key !== "Enter" && e.key !== " ") return
  const target = e.target as HTMLElement
  const inner = target.closest("button, a, input, [role='menuitem']")
  if (inner && inner !== e.currentTarget) return
  e.preventDefault()
  fn()
}

export interface InvoiceCardProps {
  invoice: InvoiceListItemViewModel
  onOpen: (invoice: InvoiceListItemViewModel) => void
  onIssue: (invoice: InvoiceListItemViewModel) => void
  onCancel: (invoice: InvoiceListItemViewModel) => void
  onPenalty: (invoice: InvoiceListItemViewModel) => void
  onRecordPayment: (invoice: InvoiceListItemViewModel) => void
}

export function InvoiceCard({
  invoice,
  onOpen,
  onIssue,
  onCancel,
  onPenalty,
  onRecordPayment,
}: InvoiceCardProps) {
  const name = invoice.profile_name ?? "Chưa rõ học sinh"
  const spine = getInvoiceStatusSpineColor(invoice.status, invoice.is_overdue)
  // Mirror AmountCell: penalty rolls into remaining, so headline = total_due.
  const headline = invoice.has_penalty ? invoice.total_due_formatted : invoice.amount_formatted

  return (
    <article
      role="link"
      tabIndex={0}
      aria-label={`Hóa đơn ${invoice.invoice_number} — ${name}`}
      onClick={() => onOpen(invoice)}
      onKeyDown={(e) => activateCard(e, () => onOpen(invoice))}
      className={cn(
        "touch-manipulation rounded-2xl border border-l-2 bg-card p-3 shadow-xs outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring hover:bg-muted/40",
        spine,
      )}
    >
      <div className="flex items-start gap-2.5">
        <Monogram name={name} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-display text-sm font-semibold text-foreground">{name}</div>
              {/* Identity = người: mã HS · ngành (KHÔNG nhồi loại phí ở đây) */}
              <div className="truncate text-xs text-muted-foreground">
                {invoice.profile_code ?? invoice.invoice_number}
                {invoice.program_name ? ` · ${invoice.program_name}` : ""}
              </div>
              {/* Khoản thu = loại phí · kỳ/đợt (tách riêng khỏi danh tính) */}
              <div className="truncate text-xs text-muted-foreground/80">{feeLineLabel(invoice)}</div>
            </div>
            <InvoiceRowActionsMenu
              invoice={invoice}
              onIssue={onIssue}
              onCancel={onCancel}
              onPenalty={onPenalty}
            />
          </div>

          {/* Amount + status + urgency */}
          <div className="mt-2 flex items-end justify-between gap-2">
            <div className="min-w-0">
              <div className="font-display text-base font-semibold tabular-nums text-foreground">
                {headline}
              </div>
              <AmountSubline invoice={invoice} align="left" />
            </div>
            <InvoiceStatusDot status={invoice.status} isOverdue={invoice.is_overdue} />
          </div>

          {/* Primary action — LUÔN hiện trên mobile (touch không hover) */}
          {invoice.can_record_payment && (
            <div className="mt-3">
              <RecordPaymentButton
                invoice={invoice}
                onRecordPayment={onRecordPayment}
                alwaysVisible
                className="w-full min-h-11"
              />
            </div>
          )}
        </div>
      </div>
    </article>
  )
}
