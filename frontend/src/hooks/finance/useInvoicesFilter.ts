// src/hooks/finance/useInvoicesFilter.ts
/**
 * Invoices ("Thu học phí") Filter Hook
 *
 * Manages all filter state for the collection workspace list:
 * - SSR-safe init: URL params > defaults, then localStorage after hydration
 * - URL sync via debounced History.replaceState (no RSC refetch)
 * - Versioned localStorage persistence
 * - Tab ↔ status/overdue synchronisation
 * - Computed apiFilters (list) / countFilters (status-counts) for React-Query
 *
 * Pattern source: useAdmissionsFilter.ts (proven in Admissions module). Adapted
 * to the invoice contract: search / feeType / sortBy(priority default) /
 * sortOrder / page / activeTab, plus a deep-link-only `fee_id` scope.
 */

"use client"

import { useState, useMemo, useCallback, useEffect, useRef } from "react"
import { useSearchParams, usePathname } from "next/navigation"
import type {
  FeeType,
  InvoiceFilters,
  InvoiceStatusCountFilters,
  InvoiceWorkspaceFilters,
} from "@/types/finance.types"
import {
  INVOICES_DEFAULT_PAGE_SIZE,
  INVOICES_DEFAULT_SORT_BY,
  INVOICES_DEFAULT_SORT_ORDER,
  INVOICE_STATUS_TABS as STATUS_TABS,
} from "./filterDefaults"

// =============================================================================
// TYPES
// =============================================================================

export interface StoredInvoiceFilters {
  page: number
  search: string
  feeType: string
  activeTab: string
  sortBy: string
  sortOrder: "asc" | "desc"
}

export interface InvoicesFilterState extends StoredInvoiceFilters {
  pageSize: number
  /** Deep-link-only fee scope (from `?fee_id=`); no user-facing control in PR1. */
  feeId: number | undefined
  /** Deep-link-only profile scope (from `?profile_id=`, admission TuitionTab). */
  profileId: number | undefined
  /**
   * Collection-drawer selection (from `?profile=`). DISTINCT from `profileId`
   * (`?profile_id=`, a LIST filter): this opens the FinanceProfileDrawer over
   * the workspace. Reflected in the URL for deep-link / back / reload-restore.
   */
  drawerProfileId: number | undefined
  /** Workspace filters (ngành/trình độ/năm-HK/TVV/đơn vị/hạn). */
  workspaceFilters: InvoiceWorkspaceFilters
}

export interface InvoicesFilterHandlers {
  setPage: (page: number) => void
  handleSearchChange: (value: string) => void
  handleFeeTypeChange: (feeType: string) => void
  handleSortChange: (sortBy: string, sortOrder: "asc" | "desc") => void
  handleTabClick: (tabKey: string) => void
  resetFilters: () => void
  /** Open the collection drawer for a profile (writes `?profile=<id>`). */
  openDrawer: (profileId: number) => void
  /** Close the collection drawer (drops `?profile=`). */
  closeDrawer: () => void
  /** Set/clear 1 workspace filter (undefined/null/"" = xoá). */
  setWorkspaceFilter: <K extends keyof InvoiceWorkspaceFilters>(
    key: K,
    value: InvoiceWorkspaceFilters[K],
  ) => void
}

export interface UseInvoicesFilterReturn {
  state: InvoicesFilterState
  handlers: InvoicesFilterHandlers
  hasActiveFilters: boolean
  apiFilters: InvoiceFilters
  countFilters: InvoiceStatusCountFilters
}

// =============================================================================
// CONSTANTS
// =============================================================================

const STORAGE_KEY = "invoices_filters"
const STORAGE_VERSION = 1

interface VersionedStorage {
  version: number
  data: StoredInvoiceFilters
}

const DEFAULT_FILTERS: StoredInvoiceFilters = {
  page: 1,
  search: "",
  feeType: "",
  activeTab: "all",
  sortBy: INVOICES_DEFAULT_SORT_BY,
  sortOrder: INVOICES_DEFAULT_SORT_ORDER,
}

// =============================================================================
// STORAGE HELPERS (versioned)
// =============================================================================

function saveFiltersToStorage(filters: StoredInvoiceFilters) {
  if (typeof window === "undefined") return
  try {
    const versioned: VersionedStorage = { version: STORAGE_VERSION, data: filters }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(versioned))
  } catch {
    // Ignore localStorage errors
  }
}

function loadFiltersFromStorage(): StoredInvoiceFilters | null {
  if (typeof window === "undefined") return null
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (parsed?.version !== STORAGE_VERSION) {
        localStorage.removeItem(STORAGE_KEY)
        return null
      }
      return parsed.data as StoredInvoiceFilters
    }
  } catch {
    localStorage.removeItem(STORAGE_KEY)
  }
  return null
}

function clearFiltersFromStorage() {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Ignore
  }
}

function normalizeStoredFilters(filters: StoredInvoiceFilters): StoredInvoiceFilters {
  const merged = { ...DEFAULT_FILTERS, ...filters }
  // The "pending" queue is a transient grain, never a restorable invoice
  // filter. Coerce any stale persisted value (written before the save-side
  // guard) so an old localStorage entry can't open the queue on first load.
  if (merged.activeTab === "pending") merged.activeTab = "all"
  return merged
}

// =============================================================================
// URL HELPERS
// =============================================================================

function hasUrlFilterParams(sp: URLSearchParams): boolean {
  return !!(
    sp.get("page") ||
    sp.get("q") ||
    sp.get("fee_type") ||
    sp.get("fee_id") ||
    sp.get("profile_id") ||
    sp.get("tab") ||
    sp.get("sort") ||
    sp.get("order") ||
    // Legacy deep-link params (kept so the URL still counts as "has filters").
    sp.get("overdue_only") ||
    sp.get("status")
  )
}

function parseSearchParams(sp: URLSearchParams): StoredInvoiceFilters {
  const order = sp.get("order")
  // Back-compat: dashboard cards + admission TuitionTab still deep-link with
  // ?overdue_only=true / ?status=overdue (pre-tab era) → land on the "Quá hạn"
  // tab so the list opens filtered instead of unfiltered.
  let activeTab = sp.get("tab") || "all"
  if (
    activeTab === "all" &&
    (sp.get("overdue_only") === "true" || sp.get("status") === "overdue")
  ) {
    activeTab = "overdue"
  }
  // Guard against `?page=abc` → NaN → 422 from the API. Fall back to page 1 for
  // any non-finite or non-positive value.
  const parsedPage = parseInt(sp.get("page") || "1", 10)
  return {
    page: Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1,
    search: sp.get("q") || "",
    feeType: sp.get("fee_type") || "",
    activeTab,
    sortBy: sp.get("sort") || INVOICES_DEFAULT_SORT_BY,
    sortOrder: order === "asc" || order === "desc" ? order : INVOICES_DEFAULT_SORT_ORDER,
  }
}

function parseIdParam(sp: URLSearchParams, key: string): number | undefined {
  const raw = sp.get(key)
  if (!raw) return undefined
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) ? n : undefined
}

function parseFeeId(sp: URLSearchParams): number | undefined {
  return parseIdParam(sp, "fee_id")
}

function parseProfileId(sp: URLSearchParams): number | undefined {
  return parseIdParam(sp, "profile_id")
}

function parseDrawerProfileId(sp: URLSearchParams): number | undefined {
  return parseIdParam(sp, "profile")
}

// =============================================================================
// MAIN HOOK
// =============================================================================

export function useInvoicesFilter(
  defaultPageSize: number = INVOICES_DEFAULT_PAGE_SIZE,
): UseInvoicesFilterReturn {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const isInitialMount = useRef(true)
  const isStorageSyncInitialMount = useRef(true)
  const hasInitialUrlFilters = useRef(hasUrlFilterParams(searchParams))
  const urlUpdateTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const prevSearchParamsStr = useRef(searchParams.toString())

  // Determine initial values without reading localStorage, so SSR and hydration match.
  const initialValues = useMemo(() => {
    if (hasUrlFilterParams(searchParams)) {
      return parseSearchParams(searchParams)
    }
    return DEFAULT_FILTERS
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // fee_id / profile_id are deep-link scopes only (no user control) → straight
  // from URL. profile_id powers the admission TuitionTab "xem hóa đơn của HS này".
  const initialFeeId = useMemo(
    () => parseFeeId(searchParams),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const initialProfileId = useMemo(
    () => parseProfileId(searchParams),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const initialDrawerProfileId = useMemo(
    () => parseDrawerProfileId(searchParams),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  // ── STATE ─────────────────────────────────────────────────────────────
  const [page, setPage] = useState(initialValues.page)
  const [pageSize] = useState(defaultPageSize)
  const [search, setSearch] = useState(initialValues.search)
  const [feeType, setFeeType] = useState(initialValues.feeType)
  const [activeTab, setActiveTab] = useState(initialValues.activeTab)
  const [sortBy, setSortBy] = useState(initialValues.sortBy)
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(initialValues.sortOrder)
  const [feeId, setFeeId] = useState<number | undefined>(initialFeeId)
  const [profileId, setProfileId] = useState<number | undefined>(initialProfileId)
  const [drawerProfileId, setDrawerProfileId] = useState<number | undefined>(
    initialDrawerProfileId,
  )
  // Workspace filters (ngành/trình độ/năm-HK/TVV/đơn vị/hạn). Session-only state
  // (URL/localStorage persistence → follow-up). Đưa vào CẢ apiFilters lẫn
  // countFilters để badge tab khớp danh sách (parity P1).
  const [workspaceFilters, setWorkspaceFilters] =
    useState<InvoiceWorkspaceFilters>({})

  // Restore persisted filters only after hydration. URL params stay the source
  // of truth (server can render them; localStorage cannot).
  useEffect(() => {
    if (hasUrlFilterParams(searchParams)) return

    const stored = loadFiltersFromStorage()
    if (!stored) return

    const restored = normalizeStoredFilters(stored)

    setPage((current) => (current === restored.page ? current : restored.page))
    setSearch((current) => (current === restored.search ? current : restored.search))
    setFeeType((current) => (current === restored.feeType ? current : restored.feeType))
    setActiveTab((current) => (current === restored.activeTab ? current : restored.activeTab))
    setSortBy((current) => (current === restored.sortBy ? current : restored.sortBy))
    setSortOrder((current) => (current === restored.sortOrder ? current : restored.sortOrder))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── EXTERNAL URL CHANGE DETECTION ─────────────────────────────────────
  const isInternalUrlChange = useRef(false)

  useEffect(() => {
    const currentStr = searchParams.toString()
    if (currentStr === prevSearchParamsStr.current) return
    prevSearchParamsStr.current = currentStr

    if (isInternalUrlChange.current) {
      isInternalUrlChange.current = false
      return
    }

    // Drawer selection follows browser back/forward / reload INDEPENDENTLY of
    // filter params (a drawer-only URL `?profile=5` has no filter params, so
    // this must run BEFORE the hasUrlFilterParams guard or Back-to-close breaks).
    const urlDrawerProfileId = parseDrawerProfileId(searchParams)
    if (urlDrawerProfileId !== drawerProfileId) setDrawerProfileId(urlDrawerProfileId)

    if (!hasUrlFilterParams(searchParams)) return

    const url = parseSearchParams(searchParams)
    if (url.search !== search) setSearch(url.search)
    if (url.page !== page) setPage(url.page)
    if (url.feeType !== feeType) setFeeType(url.feeType)
    if (url.activeTab !== activeTab) setActiveTab(url.activeTab)
    if (url.sortBy !== sortBy) setSortBy(url.sortBy)
    if (url.sortOrder !== sortOrder) setSortOrder(url.sortOrder)
    const urlFeeId = parseFeeId(searchParams)
    if (urlFeeId !== feeId) setFeeId(urlFeeId)
    const urlProfileId = parseProfileId(searchParams)
    if (urlProfileId !== profileId) setProfileId(urlProfileId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  // ── URL SYNC (debounced replaceState) ─────────────────────────────────
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false
      return
    }

    if (urlUpdateTimeoutRef.current) clearTimeout(urlUpdateTimeoutRef.current)

    urlUpdateTimeoutRef.current = setTimeout(() => {
      const params = new URLSearchParams()

      if (page > 1) params.set("page", page.toString())
      if (search) params.set("q", search)
      if (feeType) params.set("fee_type", feeType)
      if (feeId !== undefined) params.set("fee_id", String(feeId))
      if (profileId !== undefined) params.set("profile_id", String(profileId))
      if (activeTab !== "all") params.set("tab", activeTab)
      if (sortBy !== INVOICES_DEFAULT_SORT_BY) params.set("sort", sortBy)
      if (sortOrder !== INVOICES_DEFAULT_SORT_ORDER) params.set("order", sortOrder)
      // Collection drawer selection — last so it reads naturally in the URL.
      if (drawerProfileId !== undefined) params.set("profile", String(drawerProfileId))

      const qs = params.toString()
      const newUrl = qs ? `${pathname}?${qs}` : pathname

      isInternalUrlChange.current = true
      window.history.replaceState(window.history.state, "", newUrl)
    }, 100)

    return () => {
      if (urlUpdateTimeoutRef.current) clearTimeout(urlUpdateTimeoutRef.current)
    }
  }, [page, search, feeType, feeId, profileId, drawerProfileId, activeTab, sortBy, sortOrder, pathname])

  // ── LOCALSTORAGE SYNC ─────────────────────────────────────────────────
  useEffect(() => {
    // The "pending" tab is the payment maker-checker queue (a different grain,
    // not an invoice filter) and must NOT survive a reload — persisting it would
    // resurrect the queue instead of the invoice list on the next no-query visit.
    // Coerce it to "all" for storage and never let it alone trigger a save.
    const persistTab = activeTab === "pending" ? "all" : activeTab
    const data: StoredInvoiceFilters = {
      page, search, feeType, activeTab: persistTab, sortBy, sortOrder,
    }

    const shouldSave =
      page > 1 ||
      !!search ||
      !!feeType ||
      persistTab !== "all" ||
      sortBy !== INVOICES_DEFAULT_SORT_BY ||
      sortOrder !== INVOICES_DEFAULT_SORT_ORDER

    if (isStorageSyncInitialMount.current) {
      isStorageSyncInitialMount.current = false
      if (!hasInitialUrlFilters.current) return
    }

    if (shouldSave) {
      saveFiltersToStorage(data)
    } else {
      clearFiltersFromStorage()
    }
  }, [page, search, feeType, activeTab, sortBy, sortOrder])

  // ── HANDLERS (all reset page to 1) ────────────────────────────────────
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value)
    setPage(1)
  }, [])

  const handleFeeTypeChange = useCallback((value: string) => {
    setFeeType(value)
    setPage(1)
  }, [])

  const handleSortChange = useCallback((newSortBy: string, newSortOrder: "asc" | "desc") => {
    setSortBy(newSortBy)
    setSortOrder(newSortOrder)
    setPage(1)
  }, [])

  const handleTabClick = useCallback((tabKey: string) => {
    setActiveTab(tabKey)
    setPage(1)
  }, [])

  const resetFilters = useCallback(() => {
    setSearch("")
    setFeeType("")
    setActiveTab("all")
    setSortBy(INVOICES_DEFAULT_SORT_BY)
    setSortOrder(INVOICES_DEFAULT_SORT_ORDER)
    setFeeId(undefined)
    setProfileId(undefined)
    setWorkspaceFilters({})
    setPage(1)
    clearFiltersFromStorage()
    // NOTE: deliberately does NOT close the drawer — "clear filters" is about the
    // list, not the open student. Use closeDrawer() for that.
  }, [])

  const openDrawer = useCallback((id: number) => setDrawerProfileId(id), [])
  const closeDrawer = useCallback(() => setDrawerProfileId(undefined), [])

  /** Set/clear 1 workspace filter (undefined/null/"" = xoá). Reset về trang 1. */
  const setWorkspaceFilter = useCallback(
    <K extends keyof InvoiceWorkspaceFilters>(
      key: K,
      value: InvoiceWorkspaceFilters[K],
    ) => {
      setWorkspaceFilters((prev) => {
        const next = { ...prev }
        if (value === undefined || value === null || (value as unknown) === "") {
          delete next[key]
        } else {
          next[key] = value
        }
        return next
      })
      setPage(1)
    },
    [],
  )

  // ── COMPUTED VALUES ───────────────────────────────────────────────────
  const hasActiveFilters = useMemo(() => {
    return !!(
      search ||
      feeType ||
      feeId !== undefined ||
      profileId !== undefined ||
      activeTab !== "all" ||
      Object.keys(workspaceFilters).length > 0
    )
  }, [search, feeType, feeId, profileId, activeTab, workspaceFilters])

  /** Params sent to useInvoices (list). */
  const apiFilters: InvoiceFilters = useMemo(() => {
    const params: InvoiceFilters = {
      page,
      page_size: pageSize,
      sort_by: sortBy as InvoiceFilters["sort_by"],
      sort_order: sortOrder,
      // Workspace filters (ngành/trình độ/năm-HK/TVV/đơn vị/hạn).
      ...workspaceFilters,
    }

    if (search) params.search = search
    if (feeType) params.fee_type = feeType as FeeType
    if (feeId !== undefined) params.fee_id = feeId
    if (profileId !== undefined) params.profile_id = profileId

    // Tab → filter: the "Quá hạn" tab uses the DERIVED overdue predicate
    // (overdue_only=true), NOT status=overdue. Other tabs map to status enum(s).
    const tab = STATUS_TABS.find((t) => t.key === activeTab)
    if (tab?.overdue) {
      params.overdue_only = true
    } else if (tab?.awaitingMajorChange) {
      // Lens đổi ngành: cờ nằm trên KHOẢN PHÍ cha, không phải trạng thái hoá đơn.
      params.awaiting_major_change = true
    } else if (tab && tab.statuses.length > 0) {
      params.status = tab.statuses.join(",")
    }

    return params
  }, [
    page, pageSize, search, feeType, feeId, profileId, activeTab,
    sortBy, sortOrder, workspaceFilters,
  ])

  /**
   * Params for useInvoiceStatusCounts (context only: no status/page/sort).
   * PARITY (P1): workspaceFilters phải spread Y HỆT apiFilters, nếu không badge
   * tab đếm lệch so với danh sách.
   */
  const countFilters: InvoiceStatusCountFilters = useMemo(() => {
    const params: InvoiceStatusCountFilters = { ...workspaceFilters }
    if (search) params.search = search
    if (feeType) params.fee_type = feeType as FeeType
    if (feeId !== undefined) params.fee_id = feeId
    if (profileId !== undefined) params.profile_id = profileId
    return params
  }, [search, feeType, feeId, profileId, workspaceFilters])

  // ── RETURN ────────────────────────────────────────────────────────────
  return {
    state: {
      page, pageSize, search, feeType, activeTab, sortBy, sortOrder,
      feeId, profileId, drawerProfileId, workspaceFilters,
    },
    handlers: {
      setPage,
      handleSearchChange,
      handleFeeTypeChange,
      handleSortChange,
      handleTabClick,
      resetFilters,
      openDrawer,
      closeDrawer,
      setWorkspaceFilter,
    },
    hasActiveFilters,
    apiFilters,
    countFilters,
  }
}

export default useInvoicesFilter
