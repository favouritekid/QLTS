// src/app/(dashboard)/finance/invoices/_components/InvoiceListClient.tsx
/**
 * InvoiceListClient — workspace "Thu học phí" (collection desk).
 *
 * Redesign đồng nhất "Operations desk v2" (admission): command header + density
 * → metric rail TIỀN (4 ô) → status tabs gạch chân → InvoiceFilterBar → desktop
 * table (status spine + "Thu tiền" hàng nhất) / mobile cards → Pagination.
 *
 * Thin-client: hiển thị đúng những gì BE trả (status, can_* flags, is_overdue).
 * KHÔNG business logic, KHÔNG bulk-select. Spine đỏ + tab "Quá hạn" + status-pill
 * đều lấy từ is_overdue + overdue_derived (BE-owned) — một định nghĩa quá hạn.
 */

"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Receipt, Plus, ClipboardCheck } from "lucide-react"

import { PageContainer } from "@/components/layouts/PageContainer"
import { EmptyState, ErrorEmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/table/Pagination"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { formatVND } from "@/lib/zod/finance"
import { getInvoiceStatusSpineColor } from "@/lib/status-config"

import {
  useInvoices,
  useInvoiceStatusCounts,
} from "@/hooks/finance/useInvoices"
import { useFinanceDashboard } from "@/hooks/finance/useFinanceDashboard"
import {
  toInvoiceListViewModel,
  type InvoiceListItemViewModel,
} from "@/hooks/finance/useInvoiceViewModel"
import { useInvoicesFilter } from "@/hooks/finance/useInvoicesFilter"
import { INVOICE_STATUS_TABS } from "@/hooks/finance/filterDefaults"

import { AdmissionsStatusTabs } from "@/app/(dashboard)/admissions/_components/AdmissionsStatusTabs"
import {
  AdmissionsMetricRail,
  type MetricItem,
} from "@/app/(dashboard)/admissions/_components/AdmissionsMetricRail"
import { Assignees } from "@/app/(dashboard)/admissions/_components/roster-parts"

import { InvoiceFilterBar } from "./InvoiceFilterBar"
import { InvoiceStatusDot } from "./InvoiceStatusDot"
import { InvoiceCard } from "./InvoiceCard"
import { InvoiceListSkeleton } from "./InvoiceListSkeleton"
import {
  AmountCell,
  FeeCell,
  IdentityCell,
  InvoiceRowActionsMenu,
  RecordPaymentButton,
} from "./InvoiceColumns"
import { FinanceProfileDrawer } from "./FinanceProfileDrawer"
import { PendingPaymentsTab } from "./PendingPaymentsTab"
import { CalculateFeePickerDialog } from "./CalculateFeePickerDialog"
import {
  WorkspaceActionDialogs,
  type WorkspaceDialog,
} from "./WorkspaceActionDialogs"

/** Sentinel tab key for the payment maker-checker queue (grain ≠ invoice). */
const PENDING_TAB = "pending"

const DENSITY_STORAGE_KEY = "invoices:density"
type Density = "comfortable" | "compact"

/** Enter/Space kích hoạt row, bỏ qua khi focus ở element interactive bên trong. */
function activateRow(e: React.KeyboardEvent, fn: () => void) {
  if (e.key !== "Enter" && e.key !== " ") return
  const target = e.target as HTMLElement
  const inner = target.closest("button, a, input, [role='menuitem']")
  if (inner && inner !== e.currentTarget) return
  e.preventDefault()
  fn()
}

export function InvoiceListClient() {
  // ── Filter state (URL + localStorage) ──────────────────────────────────
  const { state, handlers, hasActiveFilters, apiFilters, countFilters } = useInvoicesFilter()

  // "Chờ duyệt" is a payment queue (different grain) — switches the whole
  // content area + suppresses the invoice query while it's active.
  const isPendingTab = state.activeTab === PENDING_TAB

  // ── Action dialogs (shared by row + drawer + queue) ─────────────────────
  const [activeDialog, setActiveDialog] = useState<WorkspaceDialog | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  // CTA deep-link: the Finance dashboard "Tính phí" buttons link to
  // /finance/fees?action=calculate (redirected here). Open the picker once on
  // mount, then strip ?action so a reload / back doesn't re-trigger it.
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search)
    if (sp.get("action") === "calculate") {
      setPickerOpen(true)
      sp.delete("action")
      const qs = sp.toString()
      window.history.replaceState(
        window.history.state,
        "",
        qs ? `${window.location.pathname}?${qs}` : window.location.pathname,
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Density (SSR-safe; read localStorage after mount) ───────────────────
  const [density, setDensity] = useState<Density>("comfortable")
  // `mounted` gates client-only content (the money rail) whose React-Query data
  // is cached app-wide by the sidebar badge counts → present on the client's
  // first render but absent on the server → hydration mismatch. Rendering it
  // only after mount makes server + first client render identical.
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    // localStorage read deferred to post-mount to avoid SSR hydration mismatch
    // (server can't know the persisted density). One-shot init, not a render loop.
    const stored = window.localStorage.getItem(DENSITY_STORAGE_KEY)
    if (stored === "compact" || stored === "comfortable") setDensity(stored)
    setMounted(true)
  }, [])
  const handleDensityChange = useCallback((value: Density) => {
    setDensity(value)
    try {
      window.localStorage.setItem(DENSITY_STORAGE_KEY, value)
    } catch {
      // ignore storage errors
    }
  }, [])
  const compact = density === "compact"

  // ── Data ────────────────────────────────────────────────────────────────
  // Suppress the invoice query on the payment queue tab (different entity).
  const { data, isLoading, isError, isFetching } = useInvoices(apiFilters, {
    enabled: !isPendingTab,
  })
  const { data: statusCounts } = useInvoiceStatusCounts(countFilters)
  const { data: stats } = useFinanceDashboard()

  const items = data?.items
  const invoices = useMemo(() => {
    if (!items) return []
    return toInvoiceListViewModel(items)
  }, [items])

  const totalCount = data?.total ?? 0

  // Empty later-page recovery: if a filter/total shrink (or a reload restoring a
  // stale page from localStorage) leaves us past the last page, the API returns
  // [] and we'd strand the user on "Chưa có hóa đơn nào" with no way back. Pull
  // back to page 1. placeholderData can't help — a reload is a fresh mount.
  useEffect(() => {
    if (
      !isPendingTab &&
      data &&
      !isFetching &&
      totalCount > 0 &&
      (items?.length ?? 0) === 0 &&
      state.page > 1
    ) {
      handlers.setPage(1)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPendingTab, data, isFetching, totalCount, items?.length, state.page])

  // ── Row interactions (PR2) ──────────────────────────────────────────────
  // Clicking a row opens the profile drawer (?profile=<id>); the quick "Thu
  // tiền" + ⋯ menu open the shared action dialogs inline (no page navigation).
  const { openDrawer } = handlers
  const openInvoice = useCallback(
    (inv: InvoiceListItemViewModel) => {
      if (inv.profile_id != null) openDrawer(inv.profile_id)
    },
    [openDrawer],
  )
  const handleRecordPayment = useCallback((inv: InvoiceListItemViewModel) => {
    setActiveDialog({
      type: "record",
      invoiceId: inv.id,
      feeId: inv.fee_id,
      maxAmountFormatted: inv.remaining_amount_formatted,
      invoiceNumber: inv.invoice_number,
      // Prefill from the list row too (highest-traffic entry, not just the
      // drawer) — the view model already carries the identity.
      payerName: inv.profile_name ?? undefined,
      referenceHint: inv.profile_code ?? undefined,
    })
  }, [])
  const handleIssue = useCallback((inv: InvoiceListItemViewModel) => {
    setActiveDialog({
      type: "issue",
      invoiceId: inv.id,
      feeId: inv.fee_id,
      invoiceNumber: inv.invoice_number,
    })
  }, [])
  const handleCancel = useCallback((inv: InvoiceListItemViewModel) => {
    setActiveDialog({
      type: "cancel",
      invoiceId: inv.id,
      feeId: inv.fee_id,
      invoiceNumber: inv.invoice_number,
    })
  }, [])
  const handlePenalty = useCallback((inv: InvoiceListItemViewModel) => {
    setActiveDialog({
      type: "penalty",
      invoiceId: inv.id,
      feeId: inv.fee_id,
      invoiceNumber: inv.invoice_number,
      daysOverdue: inv.overdue_days,
    })
  }, [])
  // "+ Tính phí": prefill the open student, else pick one (no raw-id box).
  const drawerProfileId = state.drawerProfileId
  const handleCalculateFee = useCallback(() => {
    if (drawerProfileId != null) {
      setActiveDialog({ type: "calculate", profileId: drawerProfileId })
    } else {
      setPickerOpen(true)
    }
  }, [drawerProfileId])

  // ── Tab counts ──────────────────────────────────────────────────────────
  // NOTE: "Quá hạn" is an ORTHOGONAL lens (overdue_derived), not a partition —
  // an issued-overdue invoice is counted in BOTH "Chờ thu" and "Quá hạn". So the
  // chips intentionally do NOT sum to "Tất cả". The tab ORDER (filterDefaults:
  // "Quá hạn" sits right after "Tất cả") places the lens next to the total and
  // away from the mutually-exclusive status group to avoid an "additive" misread.
  const tabCounts = useMemo(() => {
    if (!statusCounts?.counts) return undefined
    const result: Record<string, number> = {}
    for (const tab of INVOICE_STATUS_TABS) {
      if (tab.key === "all") {
        result[tab.key] = statusCounts.total
      } else if (tab.overdue) {
        result[tab.key] = statusCounts.overdue_derived
      } else {
        result[tab.key] = tab.statuses.reduce(
          (sum, s) => sum + (statusCounts.counts[s as keyof typeof statusCounts.counts] ?? 0),
          0,
        )
      }
    }
    return result
  }, [statusCounts])

  // ── Metric rail = TIỀN (4 ô) ────────────────────────────────────────────
  const metricItems: MetricItem[] = useMemo(() => {
    if (!stats) return []
    return [
      { key: "outstanding", label: "Còn phải thu", value: formatVND(stats.outstanding_total), dot: "bg-primary" },
      { key: "overdue", label: "Quá hạn", value: formatVND(stats.overdue_amount), dot: "bg-error-500" },
      { key: "monthly", label: "Thu tháng này", value: formatVND(stats.monthly_collections), dot: "bg-emerald-500" },
      { key: "pending", label: "Chờ xác minh", value: stats.pending_payments_count.toLocaleString("vi-VN"), dot: "bg-info-500" },
    ]
  }, [stats])

  return (
    <PageContainer maxWidth="xl">
      <div className="space-y-5">
        {/* Header */}
        <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-2xl bg-primary/10 text-primary sm:size-11">
              <Receipt className="size-5 sm:size-6" aria-hidden="true" />
            </div>
            <div>
              <h1 className="font-display text-xl font-bold tracking-tight md:text-2xl">Thu học phí</h1>
              <p className="text-sm text-muted-foreground" aria-live="polite">
                Quản lý hóa đơn và ghi nhận thu học phí
                {totalCount > 0 && (
                  <>
                    {" · "}
                    <span className="font-medium tabular-nums text-foreground">{totalCount}</span> hóa đơn
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto">
            <Button onClick={handleCalculateFee} className="gap-1.5">
              <Plus className="size-4" aria-hidden="true" />
              Tính phí
            </Button>
            <div className="hidden rounded-full border border-border bg-card p-0.5 sm:inline-flex">
              {(["comfortable", "compact"] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => handleDensityChange(d)}
                  aria-pressed={density === d}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                    density === d ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {d === "comfortable" ? "Thoáng" : "Gọn"}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* Metric rail (TIỀN) — gated on `mounted` (hydration-safe, see above) */}
        {mounted && metricItems.length > 0 && (
          <AdmissionsMetricRail items={metricItems} ariaLabel="Chỉ số thu học phí" />
        )}

        {/* Status tabs (hóa đơn theo trạng thái) + grain switch → "Chờ duyệt"
            (payment queue). The divider + icon make the entity switch explicit,
            not just a sentinel key. */}
        <div className="flex items-stretch gap-1">
          <div className="min-w-0 flex-1">
            <AdmissionsStatusTabs
              tabs={INVOICE_STATUS_TABS}
              activeTab={isPendingTab ? "" : state.activeTab}
              counts={tabCounts}
              onTabClick={handlers.handleTabClick}
            />
          </div>
          <div className="flex items-center border-b border-border pl-1">
            <button
              type="button"
              aria-pressed={isPendingTab}
              onClick={() => handlers.handleTabClick(PENDING_TAB)}
              className={cn(
                "relative flex items-center gap-1.5 whitespace-nowrap border-l border-border py-3 pl-3 text-sm font-medium transition-colors",
                isPendingTab ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <ClipboardCheck className="size-4" aria-hidden="true" />
              Chờ duyệt
              {/* Gated on `mounted`: the count comes from client-only React-Query
                  stats (absent during SSR) → render it only after mount so the
                  server + first client render match (no hydration mismatch). */}
              {mounted && stats?.pending_payments_count ? (
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 text-2xs tabular-nums",
                    isPendingTab ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                  )}
                >
                  {stats.pending_payments_count}
                </span>
              ) : null}
              {isPendingTab && (
                <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />
              )}
            </button>
          </div>
        </div>

        {/* Filter bar — invoice filters only; hidden on the payment queue tab. */}
        {!isPendingTab && (
          <InvoiceFilterBar
            search={state.search}
            onSearchChange={handlers.handleSearchChange}
            feeType={state.feeType}
            onFeeTypeChange={handlers.handleFeeTypeChange}
            sortBy={state.sortBy}
            sortOrder={state.sortOrder}
            onSortChange={handlers.handleSortChange}
            hasActiveFilters={hasActiveFilters}
            onReset={handlers.resetFilters}
          />
        )}

        {/* Content: payment maker-checker queue ("Chờ duyệt") OR invoice list */}
        {isPendingTab ? (
          <PendingPaymentsTab onAction={setActiveDialog} />
        ) : isLoading ? (
          <InvoiceListSkeleton />
        ) : isError ? (
          <div className="rounded-2xl border border-border bg-card">
            <ErrorEmptyState message="Không thể tải danh sách hóa đơn. Vui lòng thử lại." />
          </div>
        ) : invoices.length === 0 ? (
          <div className="rounded-2xl border border-border bg-card">
            <EmptyState
              icon={<Receipt className="h-12 w-12" />}
              title={hasActiveFilters ? "Không tìm thấy hóa đơn" : "Chưa có hóa đơn nào"}
              description={
                hasActiveFilters
                  ? "Thử thay đổi bộ lọc hoặc xóa tất cả bộ lọc để xem kết quả khác"
                  : "Hóa đơn sẽ xuất hiện khi học phí được tính và phát hành"
              }
              action={
                hasActiveFilters && (
                  <Button variant="outline" onClick={handlers.resetFilters}>
                    Xóa tất cả bộ lọc
                  </Button>
                )
              }
            />
          </div>
        ) : (
          <>
            {/* Desktop: roster table */}
            <div
              className={cn(
                "hidden overflow-hidden rounded-2xl border border-border bg-card shadow-xs md:block",
                isFetching && "opacity-60",
              )}
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-3 font-medium">Học sinh</th>
                    <th className="px-3 py-3 font-medium">Khoản thu</th>
                    <th className="px-3 py-3 font-medium">Phụ trách</th>
                    <th className="px-3 py-3 font-medium">Trạng thái</th>
                    <th className="px-3 py-3 text-right font-medium">Số tiền</th>
                    <th className="px-3 py-3 font-medium">
                      <span className="sr-only">Thao tác</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((invoice) => {
                    const spine = getInvoiceStatusSpineColor(invoice.status, invoice.is_overdue)
                    const selected =
                      invoice.profile_id != null &&
                      invoice.profile_id === state.drawerProfileId
                    return (
                      <tr
                        key={invoice.id}
                        role="link"
                        tabIndex={0}
                        aria-label={`Hóa đơn ${invoice.invoice_number} — ${invoice.profile_name ?? "Chưa rõ học sinh"}`}
                        aria-current={selected ? "true" : undefined}
                        onClick={() => openInvoice(invoice)}
                        onKeyDown={(e) => activateRow(e, () => openInvoice(invoice))}
                        className={cn(
                          "group cursor-pointer border-b border-l-2 border-border/60 outline-none transition-colors last:border-b-0 hover:bg-muted/40 focus-visible:bg-muted/40",
                          spine,
                          selected && "bg-primary/5",
                        )}
                      >
                        <td className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}>
                          <IdentityCell invoice={invoice} />
                        </td>
                        <td className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}>
                          <FeeCell invoice={invoice} />
                        </td>
                        <td className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}>
                          <Assignees officer={invoice.officer_name} reviewer={null} />
                        </td>
                        <td className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}>
                          <InvoiceStatusDot status={invoice.status} isOverdue={invoice.is_overdue} />
                        </td>
                        <td className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}>
                          <AmountCell invoice={invoice} />
                        </td>
                        <td
                          className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex items-center justify-end gap-1.5">
                            <RecordPaymentButton invoice={invoice} onRecordPayment={handleRecordPayment} />
                            <InvoiceRowActionsMenu
                              invoice={invoice}
                              onIssue={handleIssue}
                              onCancel={handleCancel}
                              onPenalty={handlePenalty}
                            />
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile: roster tiles */}
            <div className={cn("space-y-2 md:hidden", isFetching && "opacity-60")}>
              {invoices.map((invoice) => (
                <InvoiceCard
                  key={invoice.id}
                  invoice={invoice}
                  onOpen={openInvoice}
                  onIssue={handleIssue}
                  onCancel={handleCancel}
                  onPenalty={handlePenalty}
                  onRecordPayment={handleRecordPayment}
                />
              ))}
            </div>

            {/* Pagination (derives pages from total/pageSize). The empty
                later-page case (page>1, no rows) is handled by the page-clamp
                effect above, not here. */}
            {totalCount > state.pageSize && (
              <Pagination
                page={state.page}
                pageSize={state.pageSize}
                total={totalCount}
                onPageChange={handlers.setPage}
                isLoading={isFetching}
                showTotal
                showPageSizeSelector={false}
                className="border-t pt-4"
              />
            )}
          </>
        )}
      </div>

      {/* Collection drawer (state ⇄ URL ?profile=<id>) — opens on row click. */}
      <FinanceProfileDrawer
        profileId={state.drawerProfileId ?? null}
        onClose={handlers.closeDrawer}
        onAction={setActiveDialog}
      />

      {/* One host for every action dialog (row + drawer + queue raise here). */}
      <WorkspaceActionDialogs dialog={activeDialog} onClose={() => setActiveDialog(null)} onCalculated={handlers.openDrawer} />

      {/* Global "+ Tính phí" picker (only when no student is selected). */}
      <CalculateFeePickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onPick={(profileId) => {
          setPickerOpen(false)
          setActiveDialog({ type: "calculate", profileId })
        }}
      />
    </PageContainer>
  )
}

export default InvoiceListClient
