// src/app/(dashboard)/finance/invoices/_components/PendingPaymentsTab.tsx
/**
 * "Chờ duyệt" — the maker-checker verification queue inside the workspace.
 *
 * GRAIN SWITCH: this tab lists PAYMENTS (per transaction), not invoices, so its
 * count means something different from the status tabs. The workspace renders a
 * divider + icon before this tab to make that switch explicit.
 *
 * Manual-only: backed by `usePendingPayments` (intent_id IS NULL) — an online,
 * auto-verified payment can never appear here. A payment the current user
 * created shows a "needs another reviewer" reason instead of a verify button
 * (maker-checker, via `is_own`). Empty = good news (everything processed).
 */

"use client"

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import { CheckCircle2, AlertTriangle } from "lucide-react"

import { EmptyState, ErrorEmptyState } from "@/components/common/EmptyState"
import { Skeleton } from "@/components/ui/skeleton"
import { PendingPaymentCard } from "@/components/finance"
import { usePendingPayments } from "@/hooks/finance/usePayments"
import {
  toPendingPaymentListViewModel,
  type PendingPaymentViewModel,
} from "@/hooks/finance/usePaymentViewModel"
import type { WorkspaceDialog } from "./WorkspaceActionDialogs"

interface PendingPaymentsTabProps {
  onAction: (dialog: WorkspaceDialog) => void
}

export function PendingPaymentsTab({ onAction }: PendingPaymentsTabProps) {
  const router = useRouter()
  const { data, isLoading, isError, refetch } = usePendingPayments()

  const items = data?.items
  const payments = useMemo(
    () => (items ? toPendingPaymentListViewModel(items) : []),
    [items],
  )

  const review = (p: PendingPaymentViewModel) => ({
    id: p.id,
    invoice_id: p.invoice_id,
    reference_code: p.reference_code,
    amount_formatted: p.amount_formatted,
    created_by_display: p.created_by_display,
  })

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-48 rounded-2xl" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-2xl border border-border bg-card">
        <ErrorEmptyState
          message="Không thể tải hàng đợi chờ duyệt."
          onRetry={() => refetch()}
        />
      </div>
    )
  }

  if (payments.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-card">
        <EmptyState
          icon={<CheckCircle2 className="h-12 w-12 text-emerald-500" />}
          title="Không có khoản chờ duyệt"
          description="Mọi khoản thu thủ công đã được xác minh. Khi có khoản mới chờ duyệt, nó sẽ xuất hiện ở đây."
        />
      </div>
    )
  }

  const needsAttention = payments.filter((p) => p.needs_attention).length

  return (
    <div className="space-y-3">
      <p
        className="flex items-center gap-2 text-sm text-muted-foreground"
        role="status"
        aria-live="polite"
      >
        <span className="tabular-nums font-medium text-foreground">{payments.length}</span>
        khoản chờ duyệt (thu thủ công)
        {needsAttention > 0 && (
          <span className="inline-flex items-center gap-1 text-warning-600">
            <AlertTriangle className="size-3.5" aria-hidden="true" />
            {needsAttention} quá 24h
          </span>
        )}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {payments.map((p) => (
          <PendingPaymentCard
            key={p.id}
            payment={p}
            onView={(pay) => router.push(`/finance/invoices/${pay.invoice_id}`)}
            onVerify={(pay) => onAction({ type: "verify", payment: review(pay) })}
            onReject={(pay) => onAction({ type: "reject", payment: review(pay) })}
          />
        ))}
      </div>
    </div>
  )
}

export default PendingPaymentsTab
