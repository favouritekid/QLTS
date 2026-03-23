// src/hooks/useLeadsFilter.ts
/**
 * ✅ Option D: Extract filter state logic to custom hook
 * 
 * This hook manages all filter state for the Leads page:
 * - Filter states (search, status, source, offering, stage, officer, score, date)
 * - URL sync for sharing/bookmarking
 * - LocalStorage sync for persistence
 * - Filter handlers with page reset
 */

"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useSearchParams, usePathname } from "next/navigation";
import type { LeadStatus } from "@/types/lead.types";

// =============================================================================
// TYPES
// =============================================================================

export interface StoredFilters {
  page: number;
  search: string;
  statusFilters: LeadStatus[];
  sourceFilters: string[];
  validityFilters: string[];
  offeringFilters: string[];
  stageFilters: string[];
  officerFilters: string[];
  unitId: string;
  dateFrom: string;
  dateTo: string;
  dateField: "created_at" | "last_consultation_at";
  scoreMin: number;
  scoreMax: number;
  sortBy: string;
  sortOrder: "asc" | "desc";
}

export interface LeadsFilterState extends StoredFilters {
  pageSize: number;
  scoreRange: [number, number];
  sortBy: string;
  sortOrder: "asc" | "desc";
}

export interface LeadsFilterHandlers {
  setPage: (page: number) => void;
  handleSearchChange: (value: string) => void;
  handleStatusChange: (statuses: LeadStatus[]) => void;
  handleSourceChange: (sources: string[]) => void;
  handleValidityChange: (validity: string[]) => void;
  handleOfferingChange: (offerings: string[]) => void;
  handleStageChange: (stages: string[]) => void;
  handleOfficerChange: (officers: string[]) => void;
  handleScoreRangeChange: (range: [number, number]) => void;
  handleDateFromChange: (date: string) => void;
  handleDateToChange: (date: string) => void;
  handleDateFieldChange: (field: "created_at" | "last_consultation_at") => void;
  handleUnitIdChange: (unitId: string) => void;
  handleSortChange: (sortBy: string, sortOrder: "asc" | "desc") => void;
  resetFilters: () => void;
  /** V12: Exit dashboard context, navigate to plain /leads */
  exitDashboardContext: () => void;
}

/** V12: Dashboard navigation context (read-only, from URL) */
export interface DashboardContext {
  navSource?: string;
  action?: string;
  scope?: string;
  scopeOfficerId?: number;
  scopeUnitId?: number;
  includeDescendants: boolean;
  lossReason?: string;
}

export interface UseLeadsFilterReturn {
  state: LeadsFilterState;
  handlers: LeadsFilterHandlers;
  hasActiveFilters: boolean;
  apiFilters: Record<string, unknown>;
  /** V12: Dashboard context from URL (read-only) */
  dashboardContext: DashboardContext | null;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const LEADS_FILTERS_STORAGE_KEY = "leads_filters";
// ✅ VERSIONING: Increment when StoredFilters schema changes
const STORAGE_VERSION = 5;

interface VersionedStorage {
  version: number;
  data: StoredFilters;
}

const DEFAULT_FILTERS: StoredFilters = {
  page: 1,
  search: "",
  statusFilters: [],
  sourceFilters: [],
  validityFilters: [],
  offeringFilters: [],
  stageFilters: [],
  officerFilters: [],
  unitId: "",
  dateFrom: "",
  dateTo: "",
  dateField: "created_at",
  scoreMin: 0,
  scoreMax: 100,
  sortBy: "created_at",
  sortOrder: "desc",
};

// =============================================================================
// STORAGE HELPERS (with versioning)
// =============================================================================

function saveFiltersToStorage(filters: StoredFilters) {
  if (typeof window === 'undefined') return;
  try {
    // ✅ VERSIONING: Store with version for schema compatibility
    const versioned: VersionedStorage = {
      version: STORAGE_VERSION,
      data: filters,
    };
    localStorage.setItem(LEADS_FILTERS_STORAGE_KEY, JSON.stringify(versioned));
  } catch {
    // Ignore localStorage errors
  }
}

function loadFiltersFromStorage(): StoredFilters | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = localStorage.getItem(LEADS_FILTERS_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);

      // ✅ VERSIONING: Check version and reset if mismatched
      if (parsed?.version !== STORAGE_VERSION) {
        // Clear stale data with incompatible schema
        console.warn(`[useLeadsFilter] Cleared stale filters (v${parsed?.version} → v${STORAGE_VERSION})`);
        localStorage.removeItem(LEADS_FILTERS_STORAGE_KEY);
        return null;
      }

      return parsed.data as StoredFilters;
    }
  } catch {
    // Ignore parse errors, clear corrupted data
    localStorage.removeItem(LEADS_FILTERS_STORAGE_KEY);
  }
  return null;
}

function clearFiltersFromStorage() {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(LEADS_FILTERS_STORAGE_KEY);
  } catch {
    // Ignore
  }
}

// =============================================================================
// URL HELPERS
// =============================================================================

// V12: Dashboard context params (read-only, not user-editable filters)
const CONTEXT_PARAMS = ["nav_source", "action", "scope", "scope_officer_id", "scope_unit_id", "include_descendants"] as const;

// V12: Recognized filter params (user-editable filters)
const FILTER_PARAMS = ["page", "q", "status", "source", "validity", "offering", "stage", "officer", "unit_id", "from", "to", "date_field", "score_min", "score_max", "sort_by", "order", "loss_reason", "is_final", "counts_for_funnel"] as const;

function hasRecognizedContextParams(searchParams: URLSearchParams): boolean {
  return CONTEXT_PARAMS.some(p => searchParams.has(p));
}

function hasRecognizedFilterParams(searchParams: URLSearchParams): boolean {
  return FILTER_PARAMS.some(p => searchParams.has(p));
}

function hasUrlFilterParams(searchParams: URLSearchParams): boolean {
  return hasRecognizedContextParams(searchParams) || hasRecognizedFilterParams(searchParams);
}

/** V12: Parse dashboard context from URL (read-only state) */
function parseDashboardContext(searchParams: URLSearchParams) {
  const rawScope = searchParams.get("scope");
  const normalizedScope = rawScope === "team" ? "unit" : rawScope;
  return {
    navSource: searchParams.get("nav_source") || undefined,
    action: searchParams.get("action") || undefined,
    scope: normalizedScope || undefined,
    scopeOfficerId: searchParams.get("scope_officer_id") ? Number(searchParams.get("scope_officer_id")) : undefined,
    scopeUnitId: searchParams.get("scope_unit_id") ? Number(searchParams.get("scope_unit_id")) : undefined,
    includeDescendants: searchParams.get("include_descendants") === "1" || searchParams.get("include_descendants") === "true",
    lossReason: searchParams.get("loss_reason") || undefined,
  };
}

function dashboardContextsEqual(a: DashboardContext | null, b: DashboardContext | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function parseSearchParams(searchParams: URLSearchParams): StoredFilters {
  return {
    page: parseInt(searchParams.get("page") || "1"),
    search: searchParams.get("q") || "",
    statusFilters: searchParams.get("status")?.split(",").filter(Boolean) as LeadStatus[] || [],
    sourceFilters: searchParams.get("source")?.split(",").filter(Boolean) || [],
    validityFilters: searchParams.get("validity")?.split(",").filter(Boolean) || [],
    offeringFilters: searchParams.get("offering")?.split(",").filter(Boolean) || [],
    stageFilters: searchParams.get("stage")?.split(",").filter(Boolean) || [],
    officerFilters: searchParams.get("officer")?.split(",").filter(Boolean) || [],
    unitId: searchParams.get("unit_id") || "",
    dateFrom: searchParams.get("from") || "",
    dateTo: searchParams.get("to") || "",
    dateField: (searchParams.get("date_field") === "last_consultation_at"
      ? "last_consultation_at"
      : "created_at") as "created_at" | "last_consultation_at",
    scoreMin: parseInt(searchParams.get("score_min") || "0"),
    scoreMax: parseInt(searchParams.get("score_max") || "100"),
    sortBy: searchParams.get("sort_by") || "created_at",
    sortOrder: (searchParams.get("order") === "asc" ? "asc" : "desc") as "asc" | "desc",
  };
}

// =============================================================================
// MAIN HOOK
// =============================================================================

export function useLeadsFilter(defaultPageSize: number = 50): UseLeadsFilterReturn {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const isInitialMount = useRef(true);
  const urlUpdateTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  // Track previous searchParams content to avoid false triggers from reference changes.
  // Start at null so the first client render after navigation can still reconcile URL
  // state into hook state, even if the initial lazy state was built from stale params.
  const prevSearchParamsStr = useRef<string | null>(null);

  const initialDashboardContext = useMemo<DashboardContext | null>(() => {
    if (!hasRecognizedContextParams(searchParams)) return null;
    return parseDashboardContext(searchParams);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [dashboardContext, setDashboardContext] = useState<DashboardContext | null>(initialDashboardContext);

  // V12: URL (context or filter or action) > localStorage > defaults
  // If URL has ANY recognized param, skip localStorage entirely
  const initialValues = useMemo(() => {
    if (hasUrlFilterParams(searchParams)) {
      return parseSearchParams(searchParams);
    }

    const storedFilters = loadFiltersFromStorage();
    if (storedFilters) {
      return storedFilters;
    }

    return DEFAULT_FILTERS;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ==========================================================================
  // STATE
  // ==========================================================================
  
  const [page, setPage] = useState(initialValues.page);
  const [pageSize] = useState(defaultPageSize);
  const [search, setSearch] = useState(initialValues.search);
  const [statusFilters, setStatusFilters] = useState<LeadStatus[]>(initialValues.statusFilters);
  const [sourceFilters, setSourceFilters] = useState<string[]>(initialValues.sourceFilters);
  const [validityFilters, setValidityFilters] = useState<string[]>(initialValues.validityFilters);
  const [scoreRange, setScoreRange] = useState<[number, number]>([
    initialValues.scoreMin ?? 0,
    initialValues.scoreMax ?? 100,
  ]);
  const [offeringFilters, setOfferingFilters] = useState<string[]>(initialValues.offeringFilters);
  const [stageFilters, setStageFilters] = useState<string[]>(initialValues.stageFilters);
  const [officerFilters, setOfficerFilters] = useState<string[]>(initialValues.officerFilters);
  const [unitId, setUnitId] = useState(initialValues.unitId);
  const [dateFrom, setDateFrom] = useState(initialValues.dateFrom);
  const [dateTo, setDateTo] = useState(initialValues.dateTo);
  const [dateField, setDateField] = useState<"created_at" | "last_consultation_at">(
    initialValues.dateField === "created_at" ? "created_at" : "last_consultation_at"
  );
  const [sortBy, setSortBy] = useState(initialValues.sortBy || "created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(initialValues.sortOrder || "desc");

  // ==========================================================================
  // EXTERNAL URL CHANGE DETECTION (e.g., navigation from dashboard)
  // ==========================================================================
  
  // This ref tracks if the URL change was caused by this hook (internal) or external navigation
  const isInternalUrlChange = useRef(false);
  
  // Sync URL params INTO state when URL changes from external navigation  
  // (e.g., clicking funnel stage from dashboard)
  useEffect(() => {
    // Skip if searchParams content didn't actually change (just a new object reference)
    const currentStr = searchParams.toString();
    if (prevSearchParamsStr.current !== null && currentStr === prevSearchParamsStr.current) {
      return;
    }
    prevSearchParamsStr.current = currentStr;

    // Skip if this URL change was caused by our own state update
    if (isInternalUrlChange.current) {
      isInternalUrlChange.current = false;
      return;
    }

    // Only sync if URL has filter params (external navigation)
    if (!hasUrlFilterParams(searchParams)) {
      return;
    }

    const urlFilters = parseSearchParams(searchParams);
    const urlContext = hasRecognizedContextParams(searchParams)
      ? parseDashboardContext(searchParams)
      : null;

    if (!dashboardContextsEqual(urlContext, dashboardContext)) {
      setDashboardContext(urlContext);
    }
    
    // Only update state if it differs from current URL params
    // This avoids infinite loops
    if (JSON.stringify(urlFilters.stageFilters) !== JSON.stringify(stageFilters)) {
      setStageFilters(urlFilters.stageFilters);
    }
    if (JSON.stringify(urlFilters.statusFilters) !== JSON.stringify(statusFilters)) {
      setStatusFilters(urlFilters.statusFilters);
    }
    if (JSON.stringify(urlFilters.sourceFilters) !== JSON.stringify(sourceFilters)) {
      setSourceFilters(urlFilters.sourceFilters);
    }
    if (JSON.stringify(urlFilters.validityFilters) !== JSON.stringify(validityFilters)) {
      setValidityFilters(urlFilters.validityFilters);
    }
    if (JSON.stringify(urlFilters.offeringFilters) !== JSON.stringify(offeringFilters)) {
      setOfferingFilters(urlFilters.offeringFilters);
    }
    if (JSON.stringify(urlFilters.officerFilters) !== JSON.stringify(officerFilters)) {
      setOfficerFilters(urlFilters.officerFilters);
    }
    if (urlFilters.unitId !== unitId) {
      setUnitId(urlFilters.unitId);
    }
    if (urlFilters.search !== search) {
      setSearch(urlFilters.search);
    }
    if (urlFilters.page !== page) {
      setPage(urlFilters.page);
    }
    if (urlFilters.dateFrom !== dateFrom) {
      setDateFrom(urlFilters.dateFrom);
    }
    if (urlFilters.dateTo !== dateTo) {
      setDateTo(urlFilters.dateTo);
    }
    if (urlFilters.dateField !== dateField) {
      setDateField(urlFilters.dateField);
    }
    // ✅ T7 FIX: Sync scoreRange from URL params on external navigation
    const urlScoreMin = urlFilters.scoreMin ?? 0;
    const urlScoreMax = urlFilters.scoreMax ?? 100;
    if (urlScoreMin !== scoreRange[0] || urlScoreMax !== scoreRange[1]) {
      setScoreRange([urlScoreMin, urlScoreMax]);
    }
    if (urlFilters.sortBy && urlFilters.sortBy !== sortBy) {
      setSortBy(urlFilters.sortBy);
    }
    if (urlFilters.sortOrder && urlFilters.sortOrder !== sortOrder) {
      setSortOrder(urlFilters.sortOrder);
    }
  }, [
    searchParams,
    dashboardContext,
    stageFilters,
    statusFilters,
    sourceFilters,
    validityFilters,
    offeringFilters,
    officerFilters,
    unitId,
    search,
    page,
    dateFrom,
    dateTo,
    dateField,
    scoreRange,
    sortBy,
    sortOrder,
  ]);

  // ==========================================================================
  // URL SYNC (Using native History API for better performance)
  // ==========================================================================

  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    // Clear any pending URL update
    if (urlUpdateTimeoutRef.current) {
      clearTimeout(urlUpdateTimeoutRef.current);
    }

    // Debounce URL updates to prevent excessive history changes
    urlUpdateTimeoutRef.current = setTimeout(() => {
      const params = new URLSearchParams();

      if (page > 1) params.set("page", page.toString());
      if (search) params.set("q", search);
      if (statusFilters.length > 0) params.set("status", statusFilters.join(","));
      if (sourceFilters.length > 0) params.set("source", sourceFilters.join(","));
      if (validityFilters.length > 0) params.set("validity", validityFilters.join(","));
      if (offeringFilters.length > 0) params.set("offering", offeringFilters.join(","));
      if (stageFilters.length > 0) params.set("stage", stageFilters.join(","));
      if (officerFilters.length > 0) params.set("officer", officerFilters.join(","));
      if (unitId) params.set("unit_id", unitId);
      if (dateFrom) params.set("from", dateFrom);
      if (dateTo) params.set("to", dateTo);
      if (dateField !== "created_at") params.set("date_field", dateField);
      if (scoreRange[0] > 0) params.set("score_min", scoreRange[0].toString());
      if (scoreRange[1] < 100) params.set("score_max", scoreRange[1].toString());
      if (sortBy !== "created_at") params.set("sort_by", sortBy);
      if (sortOrder !== "desc") params.set("order", sortOrder);

      if (dashboardContext?.navSource) params.set("nav_source", dashboardContext.navSource);
      if (dashboardContext?.action) params.set("action", dashboardContext.action);
      if (dashboardContext?.scope) params.set("scope", dashboardContext.scope);
      if (dashboardContext?.scopeOfficerId) params.set("scope_officer_id", String(dashboardContext.scopeOfficerId));
      if (dashboardContext?.scopeUnitId) params.set("scope_unit_id", String(dashboardContext.scopeUnitId));
      if (dashboardContext?.includeDescendants) params.set("include_descendants", "1");
      if (dashboardContext?.lossReason) params.set("loss_reason", dashboardContext.lossReason);

      // V12: Preserve consultation status pass-through params from dashboard deep-link
      const curIsFinal = searchParams.get("is_final");
      if (curIsFinal === "true" || curIsFinal === "false") params.set("is_final", curIsFinal);
      const curFunnel = searchParams.get("counts_for_funnel");
      if (curFunnel === "true" || curFunnel === "false") params.set("counts_for_funnel", curFunnel);

      const queryString = params.toString();
      const newUrl = queryString ? `${pathname}?${queryString}` : pathname;

      // Mark this URL change as internal to prevent sync effect from re-syncing
      isInternalUrlChange.current = true;

      // ✅ Use native History API instead of router.replace() for better performance
      // This avoids triggering RSC refetch which causes the slow 400ms+ delays
      window.history.replaceState(window.history.state, "", newUrl);
    }, 100); // 100ms debounce

    return () => {
      if (urlUpdateTimeoutRef.current) {
        clearTimeout(urlUpdateTimeoutRef.current);
      }
    };
  }, [
    page, search, statusFilters, sourceFilters, validityFilters, offeringFilters,
    stageFilters, officerFilters, unitId, dateFrom, dateTo, dateField, scoreRange,
    sortBy, sortOrder, pathname, dashboardContext,
  ]);

  // ==========================================================================
  // LOCALSTORAGE SYNC
  // ==========================================================================
  
  useEffect(() => {
    const filtersToSave: StoredFilters = {
      page,
      search,
      statusFilters,
      sourceFilters,
      validityFilters,
      offeringFilters,
      stageFilters,
      officerFilters,
      unitId,
      dateFrom,
      dateTo,
      dateField,
      scoreMin: scoreRange[0],
      scoreMax: scoreRange[1],
      sortBy,
      sortOrder,
    };

    // Save if any filter is active OR if not on page 1
    // ✅ T7 FIX: Include scoreRange in shouldSave check
    const hasScoreFilterActive = scoreRange[0] > 0 || scoreRange[1] < 100;
    const shouldSave =
      page > 1 ||
      search ||
      statusFilters.length > 0 ||
      sourceFilters.length > 0 ||
      validityFilters.length > 0 ||
      offeringFilters.length > 0 ||
      stageFilters.length > 0 ||
      officerFilters.length > 0 ||
      !!unitId ||
      dateFrom ||
      dateTo ||
      hasScoreFilterActive ||
      sortBy !== "created_at" ||
      sortOrder !== "desc";

    if (shouldSave) {
      saveFiltersToStorage(filtersToSave);
    } else {
      clearFiltersFromStorage();
    }
  }, [
    page, search, statusFilters, sourceFilters, validityFilters, offeringFilters,
    stageFilters, officerFilters, unitId, dateFrom, dateTo, dateField, scoreRange,
    sortBy, sortOrder,
  ]);

  // ==========================================================================
  // HANDLERS (with page reset)
  // ==========================================================================
  
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
  }, []);

  const handleStatusChange = useCallback((statuses: LeadStatus[]) => {
    setStatusFilters(statuses);
    setPage(1);
  }, []);

  const handleSourceChange = useCallback((sources: string[]) => {
    setSourceFilters(sources);
    setPage(1);
  }, []);

  const handleValidityChange = useCallback((validity: string[]) => {
    setValidityFilters(validity);
    setPage(1);
  }, []);

  const handleOfferingChange = useCallback((offerings: string[]) => {
    setOfferingFilters(offerings);
    setPage(1);
  }, []);

  const handleStageChange = useCallback((stages: string[]) => {
    setStageFilters(stages);
    setPage(1);
  }, []);

  const handleOfficerChange = useCallback((officers: string[]) => {
    setOfficerFilters(officers);
    setPage(1);
  }, []);

  const handleUnitIdChange = useCallback((newUnitId: string) => {
    setUnitId(newUnitId);
    setPage(1);
  }, []);

  const handleScoreRangeChange = useCallback((range: [number, number]) => {
    setScoreRange(range);
    setPage(1);
  }, []);

  const handleDateFromChange = useCallback((date: string) => {
    setDateFrom(date);
    // Auto-clear dateTo if it's before the new dateFrom
    setDateTo(prev => (prev && date && prev < date) ? "" : prev);
    setPage(1);
  }, []);

  const handleDateToChange = useCallback((date: string) => {
    setDateTo(date);
    // Auto-clear dateFrom if it's after the new dateTo
    setDateFrom(prev => (prev && date && prev > date) ? "" : prev);
    setPage(1);
  }, []);

  const handleDateFieldChange = useCallback((field: "created_at" | "last_consultation_at") => {
    setDateField(field);
    setPage(1);
  }, []);

  const handleSortChange = useCallback((newSortBy: string, newSortOrder: "asc" | "desc") => {
    setSortBy(newSortBy);
    setSortOrder(newSortOrder);
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    // V12: resetFilters only resets user filters, NOT dashboard context
    setSearch("");
    setStatusFilters([]);
    setSourceFilters([]);
    setValidityFilters([]);
    setScoreRange([0, 100]);
    setOfferingFilters([]);
    setStageFilters([]);
    setOfficerFilters([]);
    setUnitId("");
    setDateFrom("");
    setDateTo("");
    setDateField("created_at");
    setSortBy("created_at");
    setSortOrder("desc");
    setPage(1);
    clearFiltersFromStorage();
  }, []);

  /** V12: Exit dashboard context entirely — navigate to plain /leads */
  const exitDashboardContext = useCallback(() => {
    resetFilters();
    setDashboardContext(null);
    // Clear URL completely — removes both context and filter params
    isInternalUrlChange.current = true;
    window.history.replaceState(window.history.state, "", pathname);
  }, [resetFilters, pathname]);

  // ==========================================================================
  // COMPUTED VALUES
  // ==========================================================================
  
  const hasScoreFilter = scoreRange[0] > 0 || scoreRange[1] < 100;
  
  const hasActiveFilters = useMemo(() => {
    return !!(
      search ||
      statusFilters.length > 0 ||
      sourceFilters.length > 0 ||
      validityFilters.length > 0 ||
      offeringFilters.length > 0 ||
      stageFilters.length > 0 ||
      officerFilters.length > 0 ||
      !!unitId ||
      hasScoreFilter ||
      dateFrom ||
      dateTo
    );
  }, [
    search, statusFilters, sourceFilters, validityFilters, offeringFilters,
    stageFilters, officerFilters, unitId, hasScoreFilter, dateFrom, dateTo,
  ]);

  const apiFilters = useMemo(() => {
    const params: Record<string, unknown> = {
      page,
      page_size: pageSize,
      sort_by: sortBy,
      order: sortOrder,
    };

    if (search) params.search = search;
    if (statusFilters.length > 0) params.status = statusFilters.join(",");
    if (sourceFilters.length > 0) params.source = sourceFilters.join(",");
    if (validityFilters.length > 0) params.validity_status = validityFilters.join(",");
    if (offeringFilters.length > 0) params.offering_id = offeringFilters.join(",");
    if (stageFilters.length > 0) params.pipeline_stage_id = stageFilters.join(",");
    if (officerFilters.length > 0) params.assigned_officer_id = officerFilters.join(",");
    if (unitId) params.unit_id = parseInt(unitId, 10);

    if (dateFrom) {
      // Parse as local date (not UTC) to match VN timezone
      const [y, m, d] = dateFrom.split("-").map(Number);
      params.date_from = new Date(y, m - 1, d, 0, 0, 0, 0).toISOString();
    }
    if (dateTo) {
      const [y, m, d] = dateTo.split("-").map(Number);
      params.date_to = new Date(y, m - 1, d, 23, 59, 59, 999).toISOString();
    }
    if (dateFrom || dateTo) params.date_field = dateField;

    // === SCORE RANGE FILTER (server-side) ===
    if (scoreRange[0] > 0) params.score_min = scoreRange[0];
    if (scoreRange[1] < 100) params.score_max = scoreRange[1];

    // V12: Consultation status pass-through (from dashboard deep-link only)
    const isFinalParam = searchParams.get("is_final");
    if (isFinalParam === "true") params.is_final = true;
    else if (isFinalParam === "false") params.is_final = false;
    const countsFunnelParam = searchParams.get("counts_for_funnel");
    if (countsFunnelParam === "true") params.counts_for_funnel = true;
    else if (countsFunnelParam === "false") params.counts_for_funnel = false;

    // V12: Pass dashboard scope context to API
    if (dashboardContext) {
      if (dashboardContext.navSource) params.nav_source = dashboardContext.navSource;
      if (dashboardContext.scope) params.scope = dashboardContext.scope;
      if (dashboardContext.scopeOfficerId) params.scope_officer_id = dashboardContext.scopeOfficerId;
      if (dashboardContext.scopeUnitId) params.scope_unit_id = dashboardContext.scopeUnitId;
      if (dashboardContext.includeDescendants) params.include_descendants = true;
      if (dashboardContext.lossReason) params.loss_reason = dashboardContext.lossReason;
    }

    return params;
  }, [
    page, pageSize, search, statusFilters, sourceFilters, validityFilters,
    offeringFilters, stageFilters, officerFilters, unitId, dateFrom, dateTo, dateField,
    sortBy, sortOrder, scoreRange, dashboardContext, searchParams,
  ]);

  // ==========================================================================
  // RETURN
  // ==========================================================================
  
  return {
    state: {
      page,
      pageSize,
      search,
      statusFilters,
      sourceFilters,
      validityFilters,
      scoreRange,
      scoreMin: scoreRange[0],
      scoreMax: scoreRange[1],
      offeringFilters,
      stageFilters,
      officerFilters,
      unitId,
      dateFrom,
      dateTo,
      dateField,
      sortBy,
      sortOrder,
    },
    handlers: {
      setPage,
      handleSearchChange,
      handleStatusChange,
      handleSourceChange,
      handleValidityChange,
      handleOfferingChange,
      handleStageChange,
      handleOfficerChange,
      handleUnitIdChange,
      handleScoreRangeChange,
      handleDateFromChange,
      handleDateToChange,
      handleDateFieldChange,
      handleSortChange,
      resetFilters,
      exitDashboardContext,
    },
    hasActiveFilters,
    apiFilters,
    dashboardContext,
  };
}

export default useLeadsFilter;
