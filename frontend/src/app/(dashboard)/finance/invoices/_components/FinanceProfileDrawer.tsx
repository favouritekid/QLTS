// src/app/(dashboard)/finance/invoices/_components/FinanceProfileDrawer.tsx
/**
 * FinanceProfileDrawer — the point where the three finance tiers converge for
 * ONE student: identity + money summary + Phí / Hóa đơn / Thanh toán sections,
 * with thu/duyệt/tính-phí inline.
 *
 * Thin-client: every status, can_* flag and `is_overdue` comes straight from
 * `GET /api/fees/collection/{profile_id}`. The drawer only PROJECTS those for
 * display (e.g. "Hạn" = earliest open invoice due, "Next-action" = the first
 * available BE action) — it never decides eligibility/overdue itself.
 *
 * Actions are raised through `onAction` so all dialogs live in ONE host
 * (WorkspaceActionDialogs) shared with the spine row + queue. Post-mutation the
 * drawer stays open and re-fetches via the collection-key invalidation in the
 * mutation hooks (no surprise close).
 *
 * a11y/WIG: Radix Sheet gives focus-trap + Esc + return-focus; the body scrolls
 * with `overscroll-contain` + a mobile safe-area inset; async feedback is the
 * polite toast (sonner) + the aria-live status line below.
 */

"use client"

import * as React from "react"
import Link from "next/link"
import {
  Plus,
  CreditCard,
  FileText,
  MoreVertical,
  QrCode,
  Ban,
  AlertTriangle,
  CheckCircle,
  XCircle,
  CircleDollarSign,
  Clock,
  ArrowUpRight,
  Percent,
  RefreshCw,
  User,
  Phone,
  MapPin,
  Fingerprint,
} from "lucide-react"

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ErrorEmptyState } from "@/components/common/EmptyState"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { formatVND } from "@/lib/zod/finance"
import { formatDate } from "@/lib/utils/admission-helpers"
import { profileFrom, withFrom } from "@/lib/finance/nav-context"
import { CopyableCell } from "@/components/common/CopyableCell"

import { Monogram } from "@/app/(dashboard)/admissions/_components/roster-parts"
import {
  FeeStatusBadge,
  InvoiceStatusBadge,
  PaymentStatusBadge,
} from "@/components/finance"

import { useProfileCollection } from "@/hooks/finance/useFees"
import { calculateOverdueDays } from "@/hooks/finance/useInvoiceViewModel"
import { FEE_TYPE_LABELS, PAYABLE_INVOICE_STATUSES } from "@/types/finance.types"
import type {
  ProfileCollection,
  InvoiceListItem,
  PaymentListItem,
  FeeSummary,
  FeeType,
  PaymentStatus,
  InvoiceStatus,
} from "@/types/finance.types"
import type { WorkspaceDialog } from "./WorkspaceActionDialogs"

// =============================================================================
// HELPERS (presentation only — over BE-owned flags)
// =============================================================================

// "Open" = still collectable. Includes 'overdue' — the daily beat job flips the
// enum issued→overdue once past due, so an only-overdue invoice must still count
// toward "Hạn gần nhất"; otherwise the header shows "Quá hạn" with no due date
// (the BE-owned `is_overdue` already lit hasOverdue). Mirrors PAYABLE_INVOICE_STATUSES.
const OPEN_INVOICE_STATUSES = new Set(PAYABLE_INVOICE_STATUSES)

/** Earliest due date among OPEN (issued/partial/overdue) invoices — drawer "Hạn". */
function nextDue(invoices: InvoiceListItem[]): InvoiceListItem | null {
  const open = invoices.filter((i) => OPEN_INVOICE_STATUSES.has(i.status))
  if (open.length === 0) return null
  return open.reduce((soonest, inv) =>
    new Date(inv.due_date) < new Date(soonest.due_date) ? inv : soonest,
  )
}

interface SummaryView {
  remainingFormatted: string
  hasOverdue: boolean
  isSettled: boolean
  statusLabel: string
  statusTone: "error" | "amber" | "success" | "muted"
  dueLabel: string | null
  dueOverdue: boolean
  nextActionLabel: string
}

function buildSummaryView(collection: ProfileCollection): SummaryView {
  const { summary, invoices } = collection
  const remaining = Number(summary.total_remaining)
  const hasOverdue = invoices.some((i) => i.is_overdue)
  const isSettled = remaining <= 0

  const due = nextDue(invoices)
  // Next-action = the first BE-permitted action across the invoice set.
  let nextActionLabel = "Không có việc cần làm"
  if (invoices.some((i) => i.can_record_payment)) nextActionLabel = "Thu tiền"
  else if (invoices.some((i) => i.can_issue)) nextActionLabel = "Phát hành hóa đơn"
  else if (isSettled && invoices.length > 0) nextActionLabel = "Đã thu đủ"

  return {
    remainingFormatted: formatVND(summary.total_remaining),
    hasOverdue,
    isSettled,
    statusLabel: hasOverdue ? "Quá hạn" : isSettled ? "Đã thu đủ" : "Còn phải thu",
    statusTone: hasOverdue ? "error" : isSettled ? "success" : "amber",
    dueLabel: due ? formatDate(due.due_date) : null,
    dueOverdue: due ? due.is_overdue : false,
    nextActionLabel,
  }
}

// =============================================================================
// COMPONENT
// =============================================================================

interface FinanceProfileDrawerProps {
  profileId: number | null
  onClose: () => void
  onAction: (dialog: WorkspaceDialog) => void
}

export function FinanceProfileDrawer({
  profileId,
  onClose,
  onAction,
}: FinanceProfileDrawerProps) {
  const open = profileId != null
  const { data, isLoading, isError, refetch } = useProfileCollection(profileId, {
    enabled: open,
  })

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        // Override the default padding: fixed header + scrollable body.
        className="flex w-full flex-col gap-0 p-0 sm:max-w-xl"
      >
        {/* Header (fixed) */}
        <SheetHeader className="space-y-0 border-b border-border px-5 py-4 text-left">
          {data ? (
            <DrawerIdentity collection={data} />
          ) : (
            <>
              <SheetTitle className="text-base">Hồ sơ tài chính</SheetTitle>
              <SheetDescription>Đang tải dữ liệu thu học phí…</SheetDescription>
            </>
          )}
        </SheetHeader>

        {/* Body (scrollable; overscroll-contain + mobile safe-area) */}
        <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <p className="sr-only" role="status" aria-live="polite">
            {isLoading
              ? "Đang tải hồ sơ tài chính"
              : data
                ? `Đã tải hồ sơ tài chính của ${data.identity.student_name ?? "học sinh"}`
                : ""}
          </p>

          {isLoading ? (
            <DrawerSkeleton />
          ) : isError ? (
            <ErrorEmptyState
              message="Không thể tải hồ sơ tài chính."
              onRetry={() => refetch()}
            />
          ) : data ? (
            <div className="space-y-6">
              <DrawerSummary collection={data} onAction={onAction} />
              <FeeTree collection={data} onAction={onAction} profileId={profileId} />
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

// =============================================================================
// IDENTITY HEADER
// =============================================================================

function DrawerIdentity({ collection }: { collection: ProfileCollection }) {
  const { identity } = collection
  const name = identity.student_name ?? "Chưa rõ học sinh"
  // Ngành (snapshot Fee.resolved_major) + trình độ. NULL → "(chưa chốt ngành)".
  const major = identity.program_name ?? "(chưa chốt ngành)"
  const sub = [identity.profile_code, major, identity.degree_level]
    .filter(Boolean)
    .join(" · ")
  return (
    <div className="flex items-start gap-3 pr-10">
      <Monogram name={name} className="size-10 shrink-0" />
      <div className="min-w-0 space-y-1">
        <SheetTitle className="truncate text-base">{name}</SheetTitle>
        <SheetDescription className="truncate">{sub || "Hồ sơ tài chính"}</SheetDescription>

        {/* Tư vấn viên phụ trách — tên trần, không nhãn "TVV". */}
        {identity.officer_name ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <User className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{identity.officer_name}</span>
          </p>
        ) : null}

        {/* CCCD (hiển thị che, copy đầy đủ) + SĐT (copy) — click-to-copy. */}
        {(identity.citizen_id_full || identity.citizen_id_masked || identity.phone) ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {identity.citizen_id_full ? (
              <CopyableCell
                value={identity.citizen_id_full}
                displayValue={identity.citizen_id_masked ?? identity.citizen_id_full}
                label="CCCD"
                className="text-muted-foreground"
                icon={<Fingerprint className="size-3.5 text-muted-foreground" aria-hidden="true" />}
              />
            ) : identity.citizen_id_masked ? (
              <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                <Fingerprint className="size-3.5" aria-hidden="true" />
                {identity.citizen_id_masked}
              </span>
            ) : null}
            {identity.phone ? (
              <CopyableCell
                value={identity.phone}
                label="Số điện thoại"
                className="text-muted-foreground"
                icon={<Phone className="size-3.5 text-muted-foreground" aria-hidden="true" />}
              />
            ) : null}
          </div>
        ) : null}

        {/* Địa chỉ thường trú (BE ghép 1 dòng). */}
        {identity.permanent_address ? (
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span className="line-clamp-2">{identity.permanent_address}</span>
          </p>
        ) : null}
      </div>
    </div>
  )
}

// =============================================================================
// SUMMARY (Còn phải thu · Hạn · Trạng thái · Next-action)
// =============================================================================

const TONE_TEXT: Record<SummaryView["statusTone"], string> = {
  error: "text-error-600",
  amber: "text-amber-600",
  success: "text-emerald-600",
  muted: "text-muted-foreground",
}

function DrawerSummary({
  collection,
  onAction,
}: {
  collection: ProfileCollection
  onAction: (d: WorkspaceDialog) => void
}) {
  const v = buildSummaryView(collection)
  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Còn phải thu
          </p>
          <p
            className={cn(
              "mt-0.5 font-display text-2xl font-bold tabular-nums",
              v.isSettled ? "text-emerald-600" : "text-foreground",
            )}
          >
            {v.remainingFormatted}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0"
          onClick={() => onAction({ type: "calculate", profileId: collection.identity.profile_id })}
        >
          <Plus className="size-4" aria-hidden="true" />
          Tính phí
        </Button>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Hạn gần nhất</dt>
          <dd
            className={cn(
              "mt-0.5 font-medium tabular-nums",
              v.dueOverdue && "text-error-600",
            )}
          >
            {v.dueLabel ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Trạng thái</dt>
          <dd className={cn("mt-0.5 font-medium", TONE_TEXT[v.statusTone])}>{v.statusLabel}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Việc cần làm</dt>
          <dd className="mt-0.5 font-medium">{v.nextActionLabel}</dd>
        </div>
      </dl>
    </section>
  )
}

// =============================================================================
// PHÍ SECTION
// =============================================================================

/** Shared 3-dot overflow-menu trigger (vertical, the system row/card convention). */
function OverflowMenuTrigger({ label }: { label: string }) {
  return (
    <DropdownMenuTrigger asChild>
      <Button size="icon" variant="ghost" className="size-8" aria-label={label}>
        <MoreVertical className="size-4" aria-hidden="true" />
      </Button>
    </DropdownMenuTrigger>
  )
}

function FeeTree({
  collection,
  onAction,
  profileId,
}: {
  collection: ProfileCollection
  onAction: (d: WorkspaceDialog) => void
  profileId: number | null
}) {
  const fees = collection.summary.fees
  // Build the hierarchy client-side from the link keys already on each row:
  // fee → its invoices (invoice.fee_id) → their payments (payment.invoice_id).
  // The nesting itself shows the money flow, so rows no longer need "thuộc khoản
  // phí / cho HĐ …" cross-reference labels.
  const invoicesByFee = React.useMemo(() => {
    const m = new Map<number, InvoiceListItem[]>()
    for (const inv of collection.invoices) {
      const arr = m.get(inv.fee_id)
      if (arr) arr.push(inv)
      else m.set(inv.fee_id, [inv])
    }
    return m
  }, [collection.invoices])
  const paymentsByInvoice = React.useMemo(() => {
    const m = new Map<number, PaymentListItem[]>()
    for (const p of collection.payments) {
      const arr = m.get(p.invoice_id)
      if (arr) arr.push(p)
      else m.set(p.invoice_id, [p])
    }
    return m
  }, [collection.payments])

  // Surface the most urgent fee first — overdue, then still-owing, then settled
  // (stable sort keeps the backend order within each bucket). Restores the
  // actionable-first signal the old flat invoice list carried.
  const orderedFees = React.useMemo(() => {
    const rank = (fee: FeeSummary) => {
      const invs = invoicesByFee.get(fee.id) ?? []
      if (invs.some((i) => i.is_overdue)) return 0
      if (Number(fee.remaining_amount) > 0) return 1
      return 2
    }
    return [...fees].sort((a, b) => rank(a) - rank(b))
  }, [fees, invoicesByFee])

  // Defensive: anything the backend sent that doesn't fit the fee→invoice→payment
  // tree (impossible by today's collection contract, but a future overpayment /
  // unallocated row could) is shown in a "Khác" bucket, never silently dropped.
  const feeIds = React.useMemo(() => new Set(fees.map((f) => f.id)), [fees])
  const invoiceIds = React.useMemo(
    () => new Set(collection.invoices.map((i) => i.id)),
    [collection.invoices],
  )
  const orphanInvoices = collection.invoices.filter((i) => !feeIds.has(i.fee_id))
  const orphanPayments = collection.payments.filter((p) => !invoiceIds.has(p.invoice_id))

  const payerName = collection.identity.student_name ?? undefined
  const referenceHint = collection.identity.profile_code

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <CircleDollarSign className="size-4 text-muted-foreground" aria-hidden="true" />
        <h3 className="text-sm font-semibold">Khoản phí</h3>
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-2xs tabular-nums text-muted-foreground">
          {fees.length}
        </span>
      </div>

      {fees.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
          Chưa có khoản phí nào. Dùng “Tính phí” để tạo.
        </p>
      ) : (
        <>
          {/* At-a-glance totals (restored — lost when the 3 section headers
              collapsed into one). */}
          <p className="-mt-1 mb-2 text-xs text-muted-foreground tabular-nums">
            {collection.invoices.length} hóa đơn · {collection.payments.length} thanh toán
          </p>
          <ul className="space-y-2.5">
            {orderedFees.map((fee) => (
              <FeeGroup
                key={fee.id}
                fee={fee}
                invoices={invoicesByFee.get(fee.id) ?? []}
                paymentsByInvoice={paymentsByInvoice}
                onAction={onAction}
                profileId={profileId}
                payerName={payerName}
                referenceHint={referenceHint}
              />
            ))}
          </ul>
        </>
      )}

      {(orphanInvoices.length > 0 || orphanPayments.length > 0) && (
        <div className="mt-3 rounded-xl border border-dashed border-border bg-muted/20 px-3 py-2.5">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Khác (chưa gắn khoản phí)
          </p>
          {orphanInvoices.length > 0 && (
            <ul className="space-y-2">
              {orphanInvoices.map((inv) => (
                <InvoiceNode
                  key={inv.id}
                  invoice={inv}
                  payments={paymentsByInvoice.get(inv.id) ?? []}
                  onAction={onAction}
                  payerName={payerName}
                  referenceHint={referenceHint}
                />
              ))}
            </ul>
          )}
          {orphanPayments.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {orphanPayments.map((p) => (
                <PaymentLeaf key={p.id} payment={p} onAction={onAction} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * FeeGroup — cấp 1 của cây: một khoản phí, với các hóa đơn của nó lồng bên trong
 * (mỗi hóa đơn lại lồng các lần thanh toán). Nesting = mạch "phí → hóa đơn →
 * thanh toán" hiện rõ bằng phân cấp card-trong-card.
 */
function FeeGroup({
  fee,
  invoices,
  paymentsByInvoice,
  onAction,
  profileId,
  payerName,
  referenceHint,
}: {
  fee: FeeSummary
  invoices: InvoiceListItem[]
  paymentsByInvoice: Map<number, PaymentListItem[]>
  onAction: (d: WorkspaceDialog) => void
  profileId: number | null
  payerName?: string
  referenceHint?: string
}) {
  // Backend-owned (role + status + amount, matches each action's route gate) —
  // do NOT re-derive on the client. Tính lại needs base_amount to prefill.
  // Trust the backend capability flags (thin-client); base_amount only prefills
  // the Tính lại dialog and degrades to 0 if ever absent.
  const canWaive = fee.can_waive ?? false
  const canRecalculate = fee.can_recalculate ?? false
  const canCancel = fee.can_cancel ?? false
  const hasMenu = canWaive || canRecalculate || canCancel
  const typeLabel = FEE_TYPE_LABELS[fee.fee_type as FeeType] ?? fee.fee_type
  const semester = fee.semester_no ? ` · HK${fee.semester_no}` : ""
  return (
    <li className="overflow-hidden rounded-xl border border-border bg-card">
      {/* Khoản phí (cấp 1) */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {typeLabel}
            <span className="font-normal text-muted-foreground">{semester}</span>
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
            {formatVND(fee.final_amount)} · còn {formatVND(fee.remaining_amount)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <FeeStatusBadge status={fee.status} size="sm" />
          {/* "Chi tiết" = đào sâu (lịch sử / audit / breakdown) — icon-only. Carries
              `?from=profile` so "Quay lại" reopens THIS drawer (nav-context). */}
          {profileId != null && (
            <Button
              asChild
              size="icon"
              variant="ghost"
              className="size-8 text-muted-foreground"
              title="Mở chi tiết khoản phí"
              aria-label="Mở chi tiết khoản phí"
            >
              <Link href={withFrom(`/finance/fees/${fee.id}`, profileFrom(profileId))}>
                <ArrowUpRight className="size-4" aria-hidden="true" />
              </Link>
            </Button>
          )}
          {/* Fee-level actions in ONE overflow menu at the OUTERMOST edge (vertical
              3-dots, system convention) — each item role-gated by a BE flag. */}
          {hasMenu && (
            <DropdownMenu>
              <OverflowMenuTrigger label={`Thao tác cho khoản ${typeLabel}`} />
              <DropdownMenuContent align="end">
                {canWaive && (
                  <DropdownMenuItem
                    onClick={() =>
                      onAction({
                        type: "waive",
                        feeId: fee.id,
                        maxAmount: fee.remaining_amount,
                        maxAmountFormatted: formatVND(fee.remaining_amount),
                      })
                    }
                  >
                    <Percent className="size-4" aria-hidden="true" />
                    Miễn giảm
                  </DropdownMenuItem>
                )}
                {canRecalculate && (
                  <DropdownMenuItem
                    onClick={() =>
                      onAction({
                        type: "recalculate",
                        feeId: fee.id,
                        feeType: typeLabel,
                        currentBaseAmount: fee.base_amount ?? "0",
                        currentBaseAmountFormatted: formatVND(fee.base_amount ?? "0"),
                      })
                    }
                  >
                    <RefreshCw className="size-4" aria-hidden="true" />
                    Tính lại
                  </DropdownMenuItem>
                )}
                {canCancel && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onClick={() =>
                        onAction({
                          type: "cancel-fee",
                          feeId: fee.id,
                          feeType: typeLabel,
                        })
                      }
                    >
                      <Ban className="size-4" aria-hidden="true" />
                      Hủy khoản phí
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {/* Hóa đơn của khoản phí (cấp 2) */}
      {invoices.length > 0 ? (
        <ul className="space-y-2 border-t border-border/60 bg-muted/20 px-3 py-2.5">
          {invoices.map((inv) => (
            <InvoiceNode
              key={inv.id}
              invoice={inv}
              payments={paymentsByInvoice.get(inv.id) ?? []}
              onAction={onAction}
              payerName={payerName}
              referenceHint={referenceHint}
            />
          ))}
        </ul>
      ) : (
        <p className="border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
          Chưa có hóa đơn cho khoản phí này.
        </p>
      )}
    </li>
  )
}

// =============================================================================
// HÓA ĐƠN NODE (cấp 2) — lồng dưới khoản phí, chứa các lần thanh toán (cấp 3)
// =============================================================================

function InvoiceNode({
  invoice,
  payments,
  onAction,
  payerName,
  referenceHint,
}: {
  invoice: InvoiceListItem
  payments: PaymentListItem[]
  onAction: (d: WorkspaceDialog) => void
  payerName?: string
  referenceHint?: string
}) {
  const overdueDays = invoice.is_overdue ? calculateOverdueDays(invoice.due_date) : 0
  const remainingFormatted = formatVND(invoice.remaining_amount)
  const hasMenu =
    invoice.can_issue || invoice.can_cancel || invoice.can_apply_penalty
  // QR only makes sense once the invoice can actually receive money.
  const canQr = invoice.can_record_payment
  // Fee reference dropped here: the invoice is nested under its fee already.

  return (
    <li
      className={cn(
        "rounded-lg border bg-card",
        invoice.is_overdue ? "border-l-2 border-l-error-500 border-border" : "border-border/70",
      )}
    >
      <div className="flex items-start justify-between gap-3 px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{invoice.invoice_number}</p>
          <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
            Còn {remainingFormatted}
            {overdueDays > 0 && (
              <span className="text-error-600"> · quá {overdueDays} ngày</span>
            )}
            {" · hạn "}
            {formatDate(invoice.due_date)}
          </p>
        </div>
        <InvoiceStatusBadge
          status={(invoice.is_overdue ? "overdue" : invoice.status) as InvoiceStatus}
          size="sm"
        />
      </div>

      {(invoice.can_record_payment || hasMenu) && (
      <div className="flex items-center justify-end gap-1.5 px-3 pb-2">
        {invoice.can_record_payment && (
          <Button
            size="sm"
            className="h-8"
            onClick={() =>
              onAction({
                type: "record",
                invoiceId: invoice.id,
                feeId: invoice.fee_id,
                maxAmountFormatted: remainingFormatted,
                invoiceNumber: invoice.invoice_number,
                payerName,
                referenceHint,
              })
            }
          >
            <CreditCard className="size-4" aria-hidden="true" />
            Thu tiền
          </Button>
        )}
        {(hasMenu || canQr) && (
          <DropdownMenu>
            <OverflowMenuTrigger label={`Thao tác cho hóa đơn ${invoice.invoice_number}`} />
            <DropdownMenuContent align="end">
              {canQr && (
                <DropdownMenuItem
                  onClick={() =>
                    onAction({
                      type: "qr",
                      invoiceId: invoice.id,
                      invoiceNumber: invoice.invoice_number,
                    })
                  }
                >
                  <QrCode className="size-4" aria-hidden="true" />
                  Mã QR chuyển khoản
                </DropdownMenuItem>
              )}
              {invoice.can_issue && (
                <DropdownMenuItem
                  onClick={() =>
                    onAction({
                      type: "issue",
                      invoiceId: invoice.id,
                      feeId: invoice.fee_id,
                      invoiceNumber: invoice.invoice_number,
                    })
                  }
                >
                  <FileText className="size-4" aria-hidden="true" />
                  Phát hành
                </DropdownMenuItem>
              )}
              {invoice.can_apply_penalty && (
                <DropdownMenuItem
                  onClick={() =>
                    onAction({
                      type: "penalty",
                      invoiceId: invoice.id,
                      feeId: invoice.fee_id,
                      invoiceNumber: invoice.invoice_number,
                      daysOverdue: overdueDays,
                    })
                  }
                >
                  <AlertTriangle className="size-4" aria-hidden="true" />
                  Áp phí trễ hạn
                </DropdownMenuItem>
              )}
              {invoice.can_cancel && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onClick={() =>
                      onAction({
                        type: "cancel",
                        invoiceId: invoice.id,
                        feeId: invoice.fee_id,
                        invoiceNumber: invoice.invoice_number,
                      })
                    }
                  >
                    <Ban className="size-4" aria-hidden="true" />
                    Hủy hóa đơn
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      )}

      {/* Thanh toán của hóa đơn (cấp 3) */}
      {payments.length > 0 ? (
        <ul className="space-y-1.5 border-t border-border/50 px-3 py-2">
          {payments.map((p) => (
            <PaymentLeaf key={p.id} payment={p} onAction={onAction} />
          ))}
        </ul>
      ) : invoice.can_record_payment ? (
        <p className="border-t border-border/50 px-3 py-1.5 text-[11px] text-muted-foreground">
          Chưa có lần thu nào.
        </p>
      ) : null}
    </li>
  )
}

const PAYMENT_SOURCE_LABEL: Record<string, string> = {
  online: "Online",
  import: "Qua import",
  manual: "Thu tay",
}

function PaymentLeaf({
  payment,
  onAction,
}: {
  payment: PaymentListItem
  onAction: (d: WorkspaceDialog) => void
}) {
  const reviewTarget = {
    id: payment.id,
    invoice_id: payment.invoice_id,
    reference_code: payment.reference_code,
    amount_formatted: formatVND(payment.amount),
    created_by_display: payment.created_by_name ?? "Không rõ",
  }
  const isPending = payment.status === "pending"
  const sourceLabel = PAYMENT_SOURCE_LABEL[payment.source] ?? "Thu tay"
  // Chi tiết: ai thu · lúc nào · ai duyệt (drawer chi tiết hơn list).
  const collectedAt = payment.payment_date
    ? new Date(payment.payment_date).toLocaleDateString("vi-VN")
    : null
  const detailParts = [
    payment.created_by_name ? `Thu: ${payment.created_by_name}` : null,
    collectedAt,
    payment.verified_by_name ? `Duyệt: ${payment.verified_by_name}` : null,
  ].filter(Boolean)
  return (
    <li className="rounded-md bg-muted/40 px-2.5 py-1.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold tabular-nums">
            {formatVND(payment.amount)}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {payment.reference_code || `#${payment.id}`}
            {payment.payer_name ? ` · ${payment.payer_name}` : ""}
          </p>
          {detailParts.length > 0 ? (
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {detailParts.join(" · ")}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <PaymentStatusBadge status={payment.status as PaymentStatus} size="sm" />
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {sourceLabel}
          </span>
        </div>
      </div>

      {isPending && payment.is_own && (
        <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground" role="note">
          <Clock className="size-3.5 shrink-0" aria-hidden="true" />
          Khoản bạn tạo — cần người khác duyệt
        </p>
      )}

      {(payment.can_verify || payment.can_reject) && (
        <div className="mt-1.5 flex justify-end gap-1.5">
          {payment.can_verify && (
            <Button
              size="sm"
              className="h-8 bg-success-600 hover:bg-success-700"
              onClick={() => onAction({ type: "verify", payment: reviewTarget })}
            >
              <CheckCircle className="size-4" aria-hidden="true" />
              Xác minh
            </Button>
          )}
          {payment.can_reject && (
            <Button
              size="sm"
              variant="destructive"
              className="h-8"
              onClick={() => onAction({ type: "reject", payment: reviewTarget })}
            >
              <XCircle className="size-4" aria-hidden="true" />
              Từ chối
            </Button>
          )}
        </div>
      )}
    </li>
  )
}

// =============================================================================
// SKELETON
// =============================================================================

function DrawerSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-28 w-full rounded-2xl" />
      {[0, 1, 2].map((s) => (
        <div key={s} className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-16 w-full rounded-xl" />
          <Skeleton className="h-16 w-full rounded-xl" />
        </div>
      ))}
    </div>
  )
}

export default FinanceProfileDrawer
