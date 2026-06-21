// src/hooks/finance/filterDefaults.ts
/**
 * Filter defaults + status tabs for the "Thu học phí" (collection) workspace.
 *
 * `INVOICE_STATUS_TABS` is the SINGLE source for both the tab UI
 * (InvoiceListClient renders `label` + count) and the tab→filter mapping
 * (useInvoicesFilter maps each tab to either a `status` enum filter or, for the
 * "Quá hạn" tab, the DERIVED `overdue_only=true` predicate). Keeping ONE
 * constant prevents drift between rendered tabs and applied filters.
 *
 * Grain note: PR1 only covers invoice-status tabs. The payment maker-checker
 * queue tab ("Chờ duyệt") is PR2 (different entity → different count meaning).
 */

import type { InvoiceFilters } from "@/types/finance.types"

/**
 * A status tab.
 * - `statuses`: enum statuses summed for the count + sent as `status=` filter.
 * - `overdue`: when true, this tab uses the DERIVED overdue predicate instead —
 *   count = `overdue_derived`, filter = `overdue_only=true` (NOT `status=overdue`).
 *   The enum `overdue` lags (job-driven), so deriving keeps tab/rows in sync.
 */
export interface InvoiceStatusTab {
  key: string
  label: string
  statuses: readonly string[]
  overdue?: boolean
}

// Order matters. "Quá hạn" is an ORTHOGONAL lens (overdue_derived), NOT part of
// the mutually-exclusive status partition (issued/partial/paid/draft/cancelled).
// An issued-overdue invoice is counted in BOTH "Chờ thu" and "Quá hạn", so the
// chips do not sum to "Tất cả". Placing "Quá hạn" right after "Tất cả" puts the
// urgency lens next to the total and visually separates it from the status group,
// preventing an "additive" misread.
export const INVOICE_STATUS_TABS: ReadonlyArray<InvoiceStatusTab> = [
  { key: "all", label: "Tất cả", statuses: [] },
  { key: "overdue", label: "Quá hạn", statuses: [], overdue: true }, // orthogonal lens
  { key: "issued", label: "Chờ thu", statuses: ["issued"] },
  { key: "partial", label: "Một phần", statuses: ["partial"] },
  { key: "paid", label: "Đã thu", statuses: ["paid"] },
  { key: "draft", label: "Nháp", statuses: ["draft"] },
  { key: "cancelled", label: "Đã hủy", statuses: ["cancelled"] },
]

export const INVOICES_DEFAULT_PAGE_SIZE = 20
/** Default sort = priority (actionable-first): overdue > issued > partial > draft > paid > cancelled, then due_date asc. */
export const INVOICES_DEFAULT_SORT_BY: NonNullable<InvoiceFilters["sort_by"]> = "priority"
export const INVOICES_DEFAULT_SORT_ORDER: NonNullable<InvoiceFilters["sort_order"]> = "asc"
