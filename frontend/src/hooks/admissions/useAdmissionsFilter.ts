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
  ADMISSION_STATUS_TABS as STATUS_TABS,
  buildCoordinationParams,
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
  // Coordination filters (admin/manager) — Admission List v2
  officerFilters: string[]   // multi-select officer IDs (as strings)
  unitId: string             // single unit ID (as string)
  reviewerFilters: string[]  // multi-select reviewer IDs (as strings)
  unassigned: boolean        // only profiles with no assigned officer
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
  handleOfficerChange: (officerIds: string[]) => void
  handleUnitIdChange: (unitId: string) => void
  handleReviewerChange: (reviewerIds: string[]) => void
  handleUnassignedChange: (unassigned: boolean) => void
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
// v2 (Admission List v2): added officer/unit/reviewer/unassigned coordination
// filters → bump so stale v1 localStorage (without these keys) is discarded.
const STORAGE_VERSION = 2

interface VersionedStorage {
  version: number
  data: StoredFilters
}

// STATUS_TABS is the SHARED `ADMISSION_STATUS_TABS` (imported as STATUS_TABS) —
// the SAME constant the UI renders, so handleTabClick's tab→status mapping can
// never drift from the rendered tabs (the old local copy drifted: it lacked a
// `confirmed` tab and folded `confirmed` into `approved`, breaking the filter).

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
  officerFilters: [],
  unitId: "",
  reviewerFilters: [],
  unassigned: false,
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
    officerFilters: Array.isArray(filters.officerFilters) ? filters.officerFilters : [],
    reviewerFilters: Array.isArray(filters.reviewerFilters) ? filters.reviewerFilters : [],
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
    sp.get("tab") ||
    sp.get("officer") ||
    sp.get("unit_id") ||
    sp.get("reviewer") ||
    sp.get("unassigned")
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
    officerFilters: sp.get("officer")?.split(",").filter(Boolean) || [],
    unitId: sp.get("unit_id") || "",
    reviewerFilters: sp.get("reviewer")?.split(",").filter(Boolean) || [],
    unassigned: sp.get("unassigned") === "1" || sp.get("unassigned") === "true",
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
  // perf/admissions-list: debounce search TRƯỚC khi vào apiFilters (query params)
  // — ô search hiển thị `search` tức thì (gõ mượt), nhưng API `/api/admissions`
  // CHỈ fire sau khi ngưng gõ 300ms. Trước đây `apiFilters` đọc `search` thô →
  // fire GET mỗi phím (mỗi lần lại là 1 query key + fan-out BE). URL-debounce
  // (100ms, effect riêng) không đụng tới đây. Các filter khác đổi 1-phát nên
  // không cần debounce.
  const [debouncedSearch, setDebouncedSearch] = useState(initialValues.search)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])
  const [statusFilters, setStatusFilters] = useState<string[]>(initialValues.statusFilters)
  const [majorFilter, setMajorFilter] = useState(initialValues.majorFilter)
  const [academicYear, setAcademicYear] = useState<number | undefined>(initialValues.academicYear)
  const [degreeLevelFilter, setDegreeLevelFilter] = useState(initialValues.degreeLevelFilter)
  const [paymentStatusFilter, setPaymentStatusFilter] = useState(initialValues.paymentStatusFilter)
  const [dateFrom, setDateFrom] = useState(initialValues.dateFrom)
  const [dateTo, setDateTo] = useState(initialValues.dateTo)
  const [activeTab, setActiveTab] = useState(initialValues.activeTab)
  const [officerFilters, setOfficerFilters] = useState<string[]>(initialValues.officerFilters)
  const [unitId, setUnitId] = useState(initialValues.unitId)
  const [reviewerFilters, setReviewerFilters] = useState<string[]>(initialValues.reviewerFilters)
  const [unassigned, setUnassigned] = useState(initialValues.unassigned)
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
    setOfficerFilters((current) =>
      arraysEqual(current, restored.officerFilters) ? current : [...restored.officerFilters],
    )
    setUnitId((current) => (current === restored.unitId ? current : restored.unitId))
    setReviewerFilters((current) =>
      arraysEqual(current, restored.reviewerFilters) ? current : [...restored.reviewerFilters],
    )
    setUnassigned((current) => (current === restored.unassigned ? current : restored.unassigned))
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
    if (JSON.stringify(url.officerFilters) !== JSON.stringify(officerFilters)) setOfficerFilters(url.officerFilters)
    if (url.unitId !== unitId) setUnitId(url.unitId)
    if (JSON.stringify(url.reviewerFilters) !== JSON.stringify(reviewerFilters)) setReviewerFilters(url.reviewerFilters)
    if (url.unassigned !== unassigned) setUnassigned(url.unassigned)
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
      if (officerFilters.length > 0) params.set("officer", officerFilters.join(","))
      if (unitId) params.set("unit_id", unitId)
      if (reviewerFilters.length > 0) params.set("reviewer", reviewerFilters.join(","))
      if (unassigned) params.set("unassigned", "1")

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
    officerFilters, unitId, reviewerFilters, unassigned,
    pathname,
  ])

  // ── LOCALSTORAGE SYNC ─────────────────────────────────────────────────
  useEffect(() => {
    const data: StoredFilters = {
      page, search, statusFilters, majorFilter, academicYear,
      degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, activeTab,
      officerFilters, unitId, reviewerFilters, unassigned,
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
      activeTab !== "all" ||
      officerFilters.length > 0 ||
      unitId ||
      reviewerFilters.length > 0 ||
      unassigned

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
    officerFilters, unitId, reviewerFilters, unassigned,
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

  const handleOfficerChange = useCallback((officerIds: string[]) => {
    setOfficerFilters(officerIds)
    // XOR: selecting officers clears "unassigned" (else IS NULL AND IN = empty).
    if (officerIds.length > 0) setUnassigned(false)
    setPage(1)
  }, [])

  const handleUnitIdChange = useCallback((nextUnitId: string) => {
    setUnitId(nextUnitId)
    setPage(1)
  }, [])

  const handleReviewerChange = useCallback((reviewerIds: string[]) => {
    setReviewerFilters(reviewerIds)
    setPage(1)
  }, [])

  const handleUnassignedChange = useCallback((next: boolean) => {
    setUnassigned(next)
    // XOR: "unassigned" clears the officer selection.
    if (next) setOfficerFilters([])
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
    setOfficerFilters([])
    setUnitId("")
    setReviewerFilters([])
    setUnassigned(false)
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
      (academicYear !== undefined && academicYear !== CURRENT_ADMISSIONS_YEAR) ||
      officerFilters.length > 0 ||
      unitId ||
      reviewerFilters.length > 0 ||
      unassigned
    )
  }, [
    search, statusFilters, majorFilter, degreeLevelFilter,
    paymentStatusFilter, dateFrom, dateTo, academicYear,
    officerFilters, unitId, reviewerFilters, unassigned,
  ])

  /** Params sent to useListAdmissions */
  const apiFilters: AdmissionListParams = useMemo(() => {
    const params: AdmissionListParams = {
      page,
      page_size: pageSize,
      sort_by: sortBy as AdmissionListParams["sort_by"],
      order: sortOrder,
    }

    if (debouncedSearch) params.search = debouncedSearch
    if (statusFilters.length > 0) params.status = statusFilters.join(",")
    if (majorFilter) params.major_id = majorFilter
    if (academicYear !== undefined) params.academic_year = academicYear
    if (degreeLevelFilter) params.degree_level = degreeLevelFilter
    if (paymentStatusFilter) params.payment_status = paymentStatusFilter
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    // Coordination filters (officer XOR unassigned, unit_id int4-guard, reviewer)
    // — one helper shared with countFilters + export so all three stay in lockstep.
    Object.assign(params, buildCoordinationParams({ officerFilters, unitId, reviewerFilters, unassigned }))

    return params
  }, [
    page, pageSize, debouncedSearch, statusFilters, majorFilter, academicYear,
    degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, sortBy, sortOrder,
    officerFilters, unitId, reviewerFilters, unassigned,
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
    // Coordination filters (parity with apiFilters → tab counts match rows).
    Object.assign(params, buildCoordinationParams({ officerFilters, unitId, reviewerFilters, unassigned }))

    return params
  }, [
    search, majorFilter, academicYear, degreeLevelFilter, paymentStatusFilter,
    dateFrom, dateTo, officerFilters, unitId, reviewerFilters, unassigned,
  ])

  // ── RETURN ────────────────────────────────────────────────────────────
  return {
    state: {
      page, pageSize, search, statusFilters, majorFilter, academicYear,
      degreeLevelFilter, paymentStatusFilter, dateFrom, dateTo, activeTab,
      officerFilters, unitId, reviewerFilters, unassigned,
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
      handleOfficerChange,
      handleUnitIdChange,
      handleReviewerChange,
      handleUnassignedChange,
      resetFilters,
    },
    hasActiveFilters,
    apiFilters,
    countFilters,
  }
}

export default useAdmissionsFilter
