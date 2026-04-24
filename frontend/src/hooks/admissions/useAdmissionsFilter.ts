// src/hooks/admissions/useAdmissionsFilter.ts
/**
 * Admissions Filter Hook
 *
 * Manages all filter state for the Admissions list page:
 * - SSR-safe init: URL params > defaults, then localStorage after hydration
 * - URL sync via debounced History.replaceState (no RSC refetch)
 * - Versioned localStorage persistence
 * - Tab ↔ statusFilter synchronisation
 * - Computed apiFilters / countFilters for React-Query
 *
 * Pattern source: useLeadsFilter.ts (proven in Leads module)
 */

"use client"

import { useState, useMemo, useCallback, useEffect, useRef } from "react"
import { useSearchParams, usePathname } from "next/navigation"
import type { AdmissionListParams } from "@/lib/zod/admissions"
import {
  ADMISSIONS_DEFAULT_PAGE_SIZE,
  CURRENT_ADMISSIONS_YEAR,
} from "./filterDefaults"

// =============================================================================
// TYPES
// =============================================================================

export interface StoredFilters {
  page: number
  search: string
  statusFilters: string[]
  majorFilter: string
  academicYear: number | undefined
  degreeLevelFilter: string
  paymentStatusFilter: string
  dateFrom: string
  dateTo: string
  activeTab: string
}

export interface AdmissionsFilterState extends StoredFilters {
  pageSize: number
  sortBy: string
  sortOrder: "asc" | "desc"
}

export interface AdmissionsFilterHandlers {
  setPage: (page: number) => void
  handleSearchChange: (value: string) => void
  handleStatusChange: (statuses: string[]) => void
  handleMajorChange: (majorId: string) => void
  handleYearChange: (year: number | undefined) => void
  handleDegreeLevelChange: (level: string) => void
  handlePaymentStatusChange: (status: string) => void
  handleDateFromChange: (date: string) => void
  handleDateToChange: (date: string) => void
  handleSortChange: (sortBy: string, sortOrder: "asc" | "desc") => void
  handleTabClick: (tabKey: string) => void
  resetFilters: () => void
}

export interface UseAdmissionsFilterReturn {
  state: AdmissionsFilterState
  handlers: AdmissionsFilterHandlers
  hasActiveFilters: boolean
  apiFilters: AdmissionListParams
  countFilters: Record<string, unknown>
}

// =============================================================================
// CONSTANTS
// =============================================================================

const STORAGE_KEY = "admissions_filters"
const STORAGE_VERSION = 1

interface VersionedStorage {
  version: number
  data: StoredFilters
}

/** Tab definitions — group statuses for quick filtering */
const STATUS_TABS: ReadonlyArray<{
  key: string
  statuses: readonly string[]
}> = [
  { key: "all", statuses: [] },
  { key: "draft", statuses: ["draft"] },
  { key: "pending", statuses: ["submitted", "resubmitted", "revision_requested"] },
  { key: "approved", statuses: ["approved", "confirmed", "overridden"] },
  { key: "enrolled", statuses: ["enrolled"] },
  { key: "rejected", statuses: ["rejected", "withdrawn"] },
]

const DEFAULT_FILTERS: StoredFilters = {
  page: 1,
  search: "",
  statusFilters: [],
  majorFilter: "",
  academicYear: CURRENT_ADMISSIONS_YEAR,
  degreeLevelFilter: "",
  paymentStatusFilter: "",
  dateFrom: "",
  dateTo: "",
  activeTab: "all",
}

// =============================================================================
// STORAGE HELPERS (versioned)
// =============================================================================

function saveFiltersToStorage(filters: StoredFilters) {
  if (typeof window === "undefined") return
  try {
    const versioned: VersionedStorage = { version: STORAGE_VERSION, data: filters }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(versioned))
  } catch {
    // Ignore localStorage errors
  }
}

function loadFiltersFromStorage(): StoredFilters | null {
  if (typeof window === "undefined") return null
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (parsed?.version !== STORAGE_VERSION) {
        localStorage.removeItem(STORAGE_KEY)
        return null
      }
      return parsed.data as StoredFilters
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

function arraysEqual<T>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index])
}

function normalizeStoredFilters(filters: StoredFilters): StoredFilters {
  return {
    ...DEFAULT_FILTERS,
    ...filters,
    statusFilters: Array.isArray(filters.statusFilters) ? filters.statusFilters : [],
  }
}

// =============================================================================
// URL HELPERS
// =============================================================================

function hasUrlFilterParams(sp: URLSearchParams): boolean {
  return !!(
    sp.get("page") ||
    sp.get("q") ||
    sp.get("status") ||
    sp.get("major") ||
    sp.get("year") ||
    sp.get("degree") ||
    sp.get("payment") ||
    sp.get("from") ||
    sp.get("to") ||
    sp.get("tab")
  )
}

function parseSearchParams(sp: URLSearchParams): StoredFilters {
  const yearStr = sp.get("year")
  return {
    page: parseInt(sp.get("page") || "1"),
    search: sp.get("q") || "",
    statusFilters: sp.get("status")?.split(",").filter(Boolean) || [],
    majorFilter: sp.get("major") || "",
    academicYear: yearStr ? Number(yearStr) : CURRENT_ADMISSIONS_YEAR,
    degreeLevelFilter: sp.get("degree") || "",
    paymentStatusFilter: sp.get("payment") || "",
    dateFrom: sp.get("from") || "",
    dateTo: sp.get("to") || "",
    activeTab: sp.get("tab") || "all",
  }
}

// =============================================================================
// MAIN HOOK
// =============================================================================

export function useAdmissionsFilter(
  defaultPageSize: number = ADMISSIONS_DEFAULT_PAGE_SIZE,
): UseAdmissionsFilterReturn {
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

  // ── STATE ─────────────────────────────────────────────────────────────
  const [page, setPage] = useState(initialValues.page)
  const [pageSize] = useState(defaultPageSize)
  const [search, setSearch] = useState(initialValues.search)
  const [statusFilters, setStatusFilters] = useState<string[]>(initialValues.statusFilters)
  const [majorFilter, setMajorFilter] = useState(initialValues.majorFilter)
  const [academicYear, setAcademicYear] = useState<number | undefined>(initialValues.academicYear)
  const [degreeLevelFilter, setDegreeLevelFilter] = useState(initialValues.degreeLevelFilter)
  const [paymentStatusFilter, setPaymentStatusFilter] = useState(initialValues.paymentStatusFilter)
  const [dateFrom, setDateFrom] = useState(initialValues.dateFrom)
  const [dateTo, setDateTo] = useState(initialValues.dateTo)
  const [activeTab, setActiveTab] = useState(initialValues.activeTab)
  const [sortBy, setSortBy] = useState("created_at")
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc")

  // Restore persisted filters only after hydration. URL params stay as the
  // source of truth because the server can render them, while localStorage cannot.
  useEffect(() => {
    if (hasUrlFilterParams(searchParams)) return

    const stored = loadFiltersFromStorage()
    if (!stored) return

    const restored = normalizeStoredFilters(stored)

    setPage((current) => (current === restored.page ? current : restored.page))
    setSearch((current) => (current === restored.search ? current : restored.search))
    setStatusFilters((current) =>
      arraysEqual(current, restored.statusFilters) ? current : [...restored.statusFilters],
    )
    setMajorFilter((current) => (current === restored.majorFilter ? current : restored.majorFilter))
    setAcademicYear((current) =>
      current === restored.academicYear ? current : restored.academicYear,
    )
    setDegreeLevelFilter((current) =>
      current === restored.degreeLevelFilter ? current : restored.degreeLevelFilter,
    )
    setPaymentStatusFilter((current) =>
      current === restored.paymentStatusFilter ? current : restored.paymentStatusFilter,
    )
    setDateFrom((current) => (current === restored.dateFrom ? current : restored.dateFrom))
    setDateTo((current) => (current === restored.dateTo ? current : restored.dateTo))
    setActiveTab((current) => (current === restored.activeTab ? current : restored.activeTab))
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
    if (!hasUrlFilterParams(searchParams)) return

    const url = parseSearchParams(searchParams)
    if (JSON.stringify(url.statusFilters) !== JSON.stringify(statusFilters)) setStatusFilters(url.statusFilters)
    if (url.search !== search) setSearch(url.search)
    if (url.page !== page) setPage(url.page)
    if (url.majorFilter !== majorFilter) setMajorFilter(url.majorFilter)
    if (url.academicYear !== academicYear) setAcademicYear(url.academicYear)
    if (url.degreeLevelFilter !== degreeLevelFilter) setDegreeLevelFilter(url.degreeLevelFilter)
    if (url.paymentStatusFilter !== paymentStatusFilter) setPaymentStatusFilter(url.paymentStatusFilter)
    if (url.dateFrom !== dateFrom) setDateFrom(url.dateFrom)
    if (url.dateTo !== dateTo) setDateTo(url.dateTo)
    if (url.activeTab !== activeTab) setActiveTab(url.activeTab)
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
      if (statusFilters.length > 0) params.set("status", statusFilters.join(","))
      if (majorFilter) params.set("major", majorFilter)
      if (academicYear !== undefined && academicYear !== CURRENT_ADMISSIONS_YEAR) {
        params.set("year", academicYear.toString())
      }
      if (degreeLevelFilter) params.set("degree", degreeLevelFilter)
      if (paymentStatusFilter) params.set("payment", paymentStatusFilter)
      if (dateFrom) params.set("from", dateFrom)
      if (dateTo) params.set("to", dateTo)
      if (activeTab !== "all") params.set("tab", activeTab)

      const qs = params.toString()
      const newUrl = qs ? `${pathname}?${qs}` : pathname

      isInternalUrlChange.current = true
      window.history.replaceState(window.history.state, "", newUrl)
    }, 100)

    return () => {
      if (urlUpdateTimeoutRef.current) clearTimeout(urlUpdateTimeoutRef.current)
    }
  }, [
    page, search, statusFilters, majorFilter, academicYear,
    degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, activeTab,
    pathname,
  ])

  // ── LOCALSTORAGE SYNC ─────────────────────────────────────────────────
  useEffect(() => {
    const data: StoredFilters = {
      page, search, statusFilters, majorFilter, academicYear,
      degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, activeTab,
    }

    const shouldSave =
      page > 1 ||
      search ||
      statusFilters.length > 0 ||
      majorFilter ||
      (academicYear !== undefined && academicYear !== CURRENT_ADMISSIONS_YEAR) ||
      degreeLevelFilter ||
      paymentStatusFilter ||
      dateFrom ||
      dateTo ||
      activeTab !== "all"

    if (isStorageSyncInitialMount.current) {
      isStorageSyncInitialMount.current = false
      if (!hasInitialUrlFilters.current) return
    }

    if (shouldSave) {
      saveFiltersToStorage(data)
    } else {
      clearFiltersFromStorage()
    }
  }, [
    page, search, statusFilters, majorFilter, academicYear,
    degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, activeTab,
  ])

  // ── HANDLERS (all reset page to 1) ────────────────────────────────────
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value)
    setPage(1)
  }, [])

  const handleStatusChange = useCallback((statuses: string[]) => {
    setStatusFilters(statuses)
    setActiveTab("all") // manual status selection resets tab
    setPage(1)
  }, [])

  const handleMajorChange = useCallback((majorId: string) => {
    setMajorFilter(majorId)
    setPage(1)
  }, [])

  const handleYearChange = useCallback((year: number | undefined) => {
    setAcademicYear(year)
    setPage(1)
  }, [])

  const handleDegreeLevelChange = useCallback((level: string) => {
    setDegreeLevelFilter(level)
    setPage(1)
  }, [])

  const handlePaymentStatusChange = useCallback((status: string) => {
    setPaymentStatusFilter(status)
    setPage(1)
  }, [])

  const handleDateFromChange = useCallback((date: string) => {
    setDateFrom(date)
    setPage(1)
  }, [])

  const handleDateToChange = useCallback((date: string) => {
    setDateTo(date)
    setPage(1)
  }, [])

  const handleSortChange = useCallback((newSortBy: string, newSortOrder: "asc" | "desc") => {
    setSortBy(newSortBy)
    setSortOrder(newSortOrder)
    setPage(1)
  }, [])

  const handleTabClick = useCallback((tabKey: string) => {
    setActiveTab(tabKey)
    const tab = STATUS_TABS.find((t) => t.key === tabKey)
    setStatusFilters(tab?.statuses ? [...tab.statuses] : [])
    setPage(1)
  }, [])

  const resetFilters = useCallback(() => {
    setSearch("")
    setStatusFilters([])
    setMajorFilter("")
    setAcademicYear(CURRENT_ADMISSIONS_YEAR)
    setDegreeLevelFilter("")
    setPaymentStatusFilter("")
    setDateFrom("")
    setDateTo("")
    setActiveTab("all")
    setSortBy("created_at")
    setSortOrder("desc")
    setPage(1)
    clearFiltersFromStorage()
  }, [])

  // ── COMPUTED VALUES ───────────────────────────────────────────────────
  const hasActiveFilters = useMemo(() => {
    return !!(
      search ||
      statusFilters.length > 0 ||
      majorFilter ||
      degreeLevelFilter ||
      paymentStatusFilter ||
      dateFrom ||
      dateTo ||
      (academicYear !== undefined && academicYear !== CURRENT_ADMISSIONS_YEAR)
    )
  }, [
    search, statusFilters, majorFilter, degreeLevelFilter,
    paymentStatusFilter, dateFrom, dateTo, academicYear,
  ])

  /** Params sent to useListAdmissions */
  const apiFilters: AdmissionListParams = useMemo(() => {
    const params: AdmissionListParams = {
      page,
      page_size: pageSize,
      sort_by: sortBy as AdmissionListParams["sort_by"],
      order: sortOrder,
    }

    if (search) params.search = search
    if (statusFilters.length > 0) params.status = statusFilters.join(",")
    if (majorFilter) params.major_id = majorFilter
    if (academicYear !== undefined) params.academic_year = academicYear
    if (degreeLevelFilter) params.degree_level = degreeLevelFilter
    if (paymentStatusFilter) params.payment_status = paymentStatusFilter
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo

    return params
  }, [
    page, pageSize, search, statusFilters, majorFilter, academicYear,
    degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, sortBy, sortOrder,
  ])

  /** Params for useAdmissionStatusCounts (excludes page/status/sort) */
  const countFilters: Record<string, unknown> = useMemo(() => {
    const params: Record<string, unknown> = {}

    if (search) params.search = search
    if (majorFilter) params.major_id = majorFilter
    if (academicYear !== undefined) params.academic_year = academicYear
    if (degreeLevelFilter) params.degree_level = degreeLevelFilter
    if (paymentStatusFilter) params.payment_status = paymentStatusFilter
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo

    return params
  }, [search, majorFilter, academicYear, degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo])

  // ── RETURN ────────────────────────────────────────────────────────────
  return {
    state: {
      page, pageSize, search, statusFilters, majorFilter, academicYear,
      degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, activeTab,
      sortBy, sortOrder,
    },
    handlers: {
      setPage,
      handleSearchChange,
      handleStatusChange,
      handleMajorChange,
      handleYearChange,
      handleDegreeLevelChange,
      handlePaymentStatusChange,
      handleDateFromChange,
      handleDateToChange,
      handleSortChange,
      handleTabClick,
      resetFilters,
    },
    hasActiveFilters,
    apiFilters,
    countFilters,
  }
}

export default useAdmissionsFilter
