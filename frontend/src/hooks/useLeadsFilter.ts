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
import type { LeadListParams, LeadStatus } from "@/types/lead.types";
import {
  formatLeadsDateFromApiParam,
  formatLeadsDateToApiParam,
  LEADS_DEFAULT_PAGE_SIZE,
  LEADS_DEFAULT_SORT_BY,
  LEADS_DEFAULT_SORT_ORDER,
} from "@/app/(dashboard)/leads/page.helpers";

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
  // LEAD_FILTER_UX_PLAN §4-§5.6: actionable + consultation-status filters
  overdue: boolean;
  unassigned: boolean;
  isHot: boolean;
  noConsultation: boolean;
  nextActivityFrom: string;
  nextActivityTo: string;
  consultationStatusFilters: string[];
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
  // LEAD_FILTER_UX_PLAN §4-§5.6: actionable + consultation-status filters.
  // unassigned XOR officer enforced here (§5.3 conflict policy).
  handleOverdueChange: (value: boolean) => void;
  handleUnassignedChange: (value: boolean) => void;
  handleIsHotChange: (value: boolean) => void;
  handleNoConsultationChange: (value: boolean) => void;
  handleNextActivityFromChange: (date: string) => void;
  handleNextActivityToChange: (date: string) => void;
  handleConsultationStatusChange: (ids: string[]) => void;
  resetFilters: () => void;
  /** V12: Exit dashboard context, navigate to plain /leads */
  exitDashboardContext: () => void;
}

/** V12: Dashboard navigation context (read-only, from URL) */
export interface DashboardContext {
  navSource?: string;
  action?: string;
  scope?: LeadListParams["scope"];
  scopeOfficerId?: number;
  scopeUnitId?: number;
  includeDescendants: boolean;
  lossReason?: string;
}

export interface UseLeadsFilterReturn {
  state: LeadsFilterState;
  handlers: LeadsFilterHandlers;
  hasActiveFilters: boolean;
  /** §5.0-C: number of filters active INSIDE the drawer (excludes search +
   * sort which live on the bar). Drives the "Bộ lọc (N)" badge. */
  drawerFilterCount: number;
  apiFilters: LeadListParams;
  /** V12: Dashboard context from URL (read-only) */
  dashboardContext: DashboardContext | null;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const LEADS_FILTERS_STORAGE_KEY = "leads_filters";
// ✅ VERSIONING: Increment when StoredFilters schema changes
// v6: + actionable filters (overdue/unassigned/isHot/noConsultation/
//     nextActivityFrom/To) + consultationStatusFilters (LEAD_FILTER_UX_PLAN)
const STORAGE_VERSION = 6;

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
  overdue: false,
  unassigned: false,
  isHot: false,
  noConsultation: false,
  nextActivityFrom: "",
  nextActivityTo: "",
  consultationStatusFilters: [],
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

function arraysEqual<T>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

// =============================================================================
// URL HELPERS
// =============================================================================

// V12: Dashboard context params (read-only, not user-editable filters)
const CONTEXT_PARAMS = ["nav_source", "action", "scope", "scope_officer_id", "scope_unit_id", "include_descendants"] as const;

// V12: Recognized filter params (user-editable filters)
const FILTER_PARAMS = ["page", "q", "status", "source", "validity", "offering", "stage", "officer", "unit_id", "from", "to", "date_field", "score_min", "score_max", "sort_by", "order", "loss_reason", "is_final", "counts_for_funnel", "overdue", "unassigned", "hot", "no_contact", "na_from", "na_to", "cstatus"] as const;

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
function parseDashboardContext(searchParams: URLSearchParams): DashboardContext {
  const rawScope = searchParams.get("scope");
  const normalizedScope = rawScope === "team" ? "unit" : rawScope;
  return {
    navSource: searchParams.get("nav_source") || undefined,
    action: searchParams.get("action") || undefined,
    scope: (normalizedScope as LeadListParams["scope"]) || undefined,
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
    // LEAD_FILTER_UX_PLAN §5.1 — URL keys differ from API field names
    overdue: searchParams.get("overdue") === "1" || searchParams.get("overdue") === "true",
    unassigned: searchParams.get("unassigned") === "1" || searchParams.get("unassigned") === "true",
    isHot: searchParams.get("hot") === "1" || searchParams.get("hot") === "true",
    noConsultation: searchParams.get("no_contact") === "1" || searchParams.get("no_contact") === "true",
    nextActivityFrom: searchParams.get("na_from") || "",
    nextActivityTo: searchParams.get("na_to") || "",
    consultationStatusFilters: searchParams.get("cstatus")?.split(",").filter(Boolean) || [],
  };
}

// =============================================================================
// MAIN HOOK
// =============================================================================

export function useLeadsFilter(
  defaultPageSize: number = LEADS_DEFAULT_PAGE_SIZE,
): UseLeadsFilterReturn {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const isInitialMount = useRef(true);
  const urlUpdateTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  // Track previous searchParams content to avoid false triggers from reference changes.
  // Start at null so the first client render after navigation can still reconcile URL
  // state into hook state, even if the initial lazy state was built from stale params.
  const prevSearchParamsStr = useRef<string | null>(null);

  // Storage-sync bookkeeping: skip clearing storage on the first mount so the
  // restore effect below gets a chance to hydrate from localStorage before
  // the debounced "should save?" check decides we have no filters.
  const isStorageSyncInitialMount = useRef(true);
  const hasInitialUrlFilters = useRef(hasUrlFilterParams(searchParams));

  const initialDashboardContext = useMemo<DashboardContext | null>(() => {
    if (!hasRecognizedContextParams(searchParams)) return null;
    return parseDashboardContext(searchParams);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [dashboardContext, setDashboardContext] = useState<DashboardContext | null>(initialDashboardContext);

  // SSR-safe initial values: URL params > defaults. localStorage is deferred
  // to a post-mount effect (see below) so server and client first renders
  // produce identical DOM — otherwise the client would diverge whenever
  // stored filters exist and React would flag a hydration mismatch.
  const initialValues = useMemo(() => {
    if (hasUrlFilterParams(searchParams)) {
      return parseSearchParams(searchParams);
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
  const [sortBy, setSortBy] = useState(initialValues.sortBy || LEADS_DEFAULT_SORT_BY);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(initialValues.sortOrder || LEADS_DEFAULT_SORT_ORDER);
  // LEAD_FILTER_UX_PLAN §4-§5.6: actionable + consultation-status filters
  const [overdue, setOverdue] = useState<boolean>(initialValues.overdue);
  const [unassigned, setUnassigned] = useState<boolean>(initialValues.unassigned);
  const [isHot, setIsHot] = useState<boolean>(initialValues.isHot);
  const [noConsultation, setNoConsultation] = useState<boolean>(initialValues.noConsultation);
  const [nextActivityFrom, setNextActivityFrom] = useState(initialValues.nextActivityFrom);
  const [nextActivityTo, setNextActivityTo] = useState(initialValues.nextActivityTo);
  const [consultationStatusFilters, setConsultationStatusFilters] = useState<string[]>(initialValues.consultationStatusFilters);

  // ==========================================================================
  // POST-HYDRATION STORAGE RESTORE
  // ==========================================================================
  //
  // If the URL has no filter/context params, pull saved filters from
  // localStorage and apply them AFTER mount. Doing this in an effect (not
  // the initial render) keeps SSR markup and client first-render in sync —
  // React treats the follow-up setStates as normal state updates, not as a
  // hydration mismatch.
  //
  // URL params always win: when the current URL already carries filters
  // (deep-link from a dashboard card, shared URL, etc.) we bail out so the
  // URL stays the source of truth and storage cannot silently override it.

  useEffect(() => {
    if (hasUrlFilterParams(searchParams)) return;

    const stored = loadFiltersFromStorage();
    if (!stored) return;

    setPage((current) => (current === stored.page ? current : stored.page));
    setSearch((current) => (current === stored.search ? current : stored.search));
    setStatusFilters((current) =>
      arraysEqual(current, stored.statusFilters) ? current : [...(stored.statusFilters || [])],
    );
    setSourceFilters((current) =>
      arraysEqual(current, stored.sourceFilters) ? current : [...(stored.sourceFilters || [])],
    );
    setValidityFilters((current) =>
      arraysEqual(current, stored.validityFilters) ? current : [...(stored.validityFilters || [])],
    );
    setOfferingFilters((current) =>
      arraysEqual(current, stored.offeringFilters) ? current : [...(stored.offeringFilters || [])],
    );
    setStageFilters((current) =>
      arraysEqual(current, stored.stageFilters) ? current : [...(stored.stageFilters || [])],
    );
    setOfficerFilters((current) =>
      arraysEqual(current, stored.officerFilters) ? current : [...(stored.officerFilters || [])],
    );
    setUnitId((current) => (current === stored.unitId ? current : stored.unitId));
    setDateFrom((current) => (current === stored.dateFrom ? current : stored.dateFrom));
    setDateTo((current) => (current === stored.dateTo ? current : stored.dateTo));
    setDateField((current) => (current === stored.dateField ? current : stored.dateField));
    setScoreRange((current) => {
      const nextMin = stored.scoreMin ?? 0;
      const nextMax = stored.scoreMax ?? 100;
      if (current[0] === nextMin && current[1] === nextMax) return current;
      return [nextMin, nextMax];
    });
    setSortBy((current) => (current === stored.sortBy ? current : stored.sortBy));
    setSortOrder((current) => (current === stored.sortOrder ? current : stored.sortOrder));
    setOverdue((current) => (current === !!stored.overdue ? current : !!stored.overdue));
    setUnassigned((current) => (current === !!stored.unassigned ? current : !!stored.unassigned));
    setIsHot((current) => (current === !!stored.isHot ? current : !!stored.isHot));
    setNoConsultation((current) => (current === !!stored.noConsultation ? current : !!stored.noConsultation));
    setNextActivityFrom((current) => (current === (stored.nextActivityFrom || "") ? current : (stored.nextActivityFrom || "")));
    setNextActivityTo((current) => (current === (stored.nextActivityTo || "") ? current : (stored.nextActivityTo || "")));
    setConsultationStatusFilters((current) =>
      arraysEqual(current, stored.consultationStatusFilters || []) ? current : [...(stored.consultationStatusFilters || [])],
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    // LEAD_FILTER_UX_PLAN §4-§5.6 actionable + consultation-status filters
    if (urlFilters.overdue !== overdue) setOverdue(urlFilters.overdue);
    if (urlFilters.unassigned !== unassigned) setUnassigned(urlFilters.unassigned);
    if (urlFilters.isHot !== isHot) setIsHot(urlFilters.isHot);
    if (urlFilters.noConsultation !== noConsultation) setNoConsultation(urlFilters.noConsultation);
    if (urlFilters.nextActivityFrom !== nextActivityFrom) setNextActivityFrom(urlFilters.nextActivityFrom);
    if (urlFilters.nextActivityTo !== nextActivityTo) setNextActivityTo(urlFilters.nextActivityTo);
    if (JSON.stringify(urlFilters.consultationStatusFilters) !== JSON.stringify(consultationStatusFilters)) {
      setConsultationStatusFilters(urlFilters.consultationStatusFilters);
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
    overdue,
    unassigned,
    isHot,
    noConsultation,
    nextActivityFrom,
    nextActivityTo,
    consultationStatusFilters,
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

      // LEAD_FILTER_UX_PLAN §5.1 — URL keys (na_from/na_to stay YYYY-MM-DD;
      // the +07:00 formatting happens only when mapping to API params).
      if (overdue) params.set("overdue", "1");
      if (unassigned) params.set("unassigned", "1");
      if (isHot) params.set("hot", "1");
      if (noConsultation) params.set("no_contact", "1");
      if (nextActivityFrom) params.set("na_from", nextActivityFrom);
      if (nextActivityTo) params.set("na_to", nextActivityTo);
      if (consultationStatusFilters.length > 0) params.set("cstatus", consultationStatusFilters.join(","));

      if (dashboardContext?.navSource) params.set("nav_source", dashboardContext.navSource);
      if (dashboardContext?.action) params.set("action", dashboardContext.action);
      if (dashboardContext?.scope) params.set("scope", dashboardContext.scope);
      if (dashboardContext?.scopeOfficerId) params.set("scope_officer_id", String(dashboardContext.scopeOfficerId));
      if (dashboardContext?.scopeUnitId) params.set("scope_unit_id", String(dashboardContext.scopeUnitId));
      if (dashboardContext?.includeDescendants) params.set("include_descendants", "1");
      if (dashboardContext?.lossReason) params.set("loss_reason", dashboardContext.lossReason);

      // V12: Preserve consultation status pass-through params only while
      // dashboard context is active. Without this guard, exitDashboardContext
      // clears context but stale searchParams re-adds these on next sync.
      if (dashboardContext) {
        const curIsFinal = searchParams.get("is_final");
        if (curIsFinal === "true" || curIsFinal === "false") params.set("is_final", curIsFinal);
        const curFunnel = searchParams.get("counts_for_funnel");
        if (curFunnel === "true" || curFunnel === "false") params.set("counts_for_funnel", curFunnel);
      }

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
    overdue, unassigned, isHot, noConsultation, nextActivityFrom, nextActivityTo,
    consultationStatusFilters,
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
      overdue,
      unassigned,
      isHot,
      noConsultation,
      nextActivityFrom,
      nextActivityTo,
      consultationStatusFilters,
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
      overdue ||
      unassigned ||
      isHot ||
      noConsultation ||
      nextActivityFrom ||
      nextActivityTo ||
      consultationStatusFilters.length > 0 ||
      sortBy !== LEADS_DEFAULT_SORT_BY ||
      sortOrder !== LEADS_DEFAULT_SORT_ORDER;

    // Skip clear on the very first mount when the URL had no filter params.
    // Without this guard, the storage-sync effect would wipe out the saved
    // filters BEFORE the post-hydration restore effect has a chance to copy
    // them into state.
    if (isStorageSyncInitialMount.current) {
      isStorageSyncInitialMount.current = false;
      if (!hasInitialUrlFilters.current && !shouldSave) {
        return;
      }
    }

    if (shouldSave) {
      saveFiltersToStorage(filtersToSave);
    } else {
      clearFiltersFromStorage();
    }
  }, [
    page, search, statusFilters, sourceFilters, validityFilters, offeringFilters,
    stageFilters, officerFilters, unitId, dateFrom, dateTo, dateField, scoreRange,
    sortBy, sortOrder,
    overdue, unassigned, isHot, noConsultation, nextActivityFrom, nextActivityTo,
    consultationStatusFilters,
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
    // §5.3 conflict policy: officer XOR unassigned. Selecting an officer
    // clears "unassigned" (BE ANDs them → would be empty otherwise).
    if (officers.length > 0) setUnassigned(false);
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

  // === LEAD_FILTER_UX_PLAN §4-§5.6 handlers ===
  const handleOverdueChange = useCallback((value: boolean) => {
    setOverdue(value);
    setPage(1);
  }, []);

  const handleUnassignedChange = useCallback((value: boolean) => {
    setUnassigned(value);
    // §5.3 conflict policy: unassigned XOR officer. Turning on "unassigned"
    // clears any officer filter so the BE AND doesn't yield an empty set.
    if (value) setOfficerFilters([]);
    setPage(1);
  }, []);

  const handleIsHotChange = useCallback((value: boolean) => {
    setIsHot(value);
    setPage(1);
  }, []);

  const handleNoConsultationChange = useCallback((value: boolean) => {
    setNoConsultation(value);
    setPage(1);
  }, []);

  const handleNextActivityFromChange = useCallback((date: string) => {
    setNextActivityFrom(date);
    // Auto-clear "to" if it falls before the new "from"
    setNextActivityTo(prev => (prev && date && prev < date) ? "" : prev);
    setPage(1);
  }, []);

  const handleNextActivityToChange = useCallback((date: string) => {
    setNextActivityTo(date);
    // Auto-clear "from" if it falls after the new "to"
    setNextActivityFrom(prev => (prev && date && prev > date) ? "" : prev);
    setPage(1);
  }, []);

  const handleConsultationStatusChange = useCallback((ids: string[]) => {
    setConsultationStatusFilters(ids);
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
    setOverdue(false);
    setUnassigned(false);
    setIsHot(false);
    setNoConsultation(false);
    setNextActivityFrom("");
    setNextActivityTo("");
    setConsultationStatusFilters([]);
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
      dateTo ||
      overdue ||
      unassigned ||
      isHot ||
      noConsultation ||
      nextActivityFrom ||
      nextActivityTo ||
      consultationStatusFilters.length > 0
    );
  }, [
    search, statusFilters, sourceFilters, validityFilters, offeringFilters,
    stageFilters, officerFilters, unitId, hasScoreFilter, dateFrom, dateTo,
    overdue, unassigned, isHot, noConsultation, nextActivityFrom, nextActivityTo,
    consultationStatusFilters,
  ]);

  // §5.0-C: count of filters active INSIDE the drawer. Search + sort live on
  // the bar and are excluded. Each active group counts once (a preset that
  // flips `overdue=true` counts as that 1 filter — no separate preset unit).
  const drawerFilterCount = useMemo(() => {
    let n = 0;
    if (statusFilters.length > 0) n++;
    if (sourceFilters.length > 0) n++;
    if (validityFilters.length > 0) n++;
    if (offeringFilters.length > 0) n++;
    if (stageFilters.length > 0) n++;
    if (officerFilters.length > 0) n++;
    if (unitId) n++;
    if (hasScoreFilter) n++;
    if (dateFrom || dateTo) n++;
    if (consultationStatusFilters.length > 0) n++;
    if (overdue) n++;
    if (unassigned) n++;
    if (isHot) n++;
    if (noConsultation) n++;
    if (nextActivityFrom || nextActivityTo) n++;
    return n;
  }, [
    statusFilters, sourceFilters, validityFilters, offeringFilters, stageFilters,
    officerFilters, unitId, hasScoreFilter, dateFrom, dateTo,
    consultationStatusFilters, overdue, unassigned, isHot, noConsultation,
    nextActivityFrom, nextActivityTo,
  ]);

  const apiFilters = useMemo<LeadListParams>(() => {
    const params: LeadListParams = {
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
    // §5.3 conflict policy (defensive): `unassigned` and an officer filter are
    // mutually exclusive (BE ANDs them → empty). Handlers enforce this on user
    // input, but a deep-link / shared URL / stale localStorage can carry both —
    // so here `unassigned` wins and we drop assigned_officer_id.
    if (officerFilters.length > 0 && !unassigned) params.assigned_officer_id = officerFilters.join(",");
    if (unitId) params.unit_id = parseInt(unitId, 10);

    // Use the shared +07:00 formatter so SSR prefetch and client query keys
    // produce byte-identical strings. `new Date(...).toISOString()` would
    // drift based on the runtime timezone (server UTC vs browser VN) even
    // though the underlying instants are equal.
    if (dateFrom) params.date_from = formatLeadsDateFromApiParam(dateFrom);
    if (dateTo) params.date_to = formatLeadsDateToApiParam(dateTo);
    if (dateFrom || dateTo) params.date_field = dateField;

    // === SCORE RANGE FILTER (server-side) ===
    if (scoreRange[0] > 0) params.score_min = scoreRange[0];
    if (scoreRange[1] < 100) params.score_max = scoreRange[1];

    // === LEAD_FILTER_UX_PLAN §4-§5.6: actionable + consultation-status ===
    // Bools only set when active (mirror BE `is True`). na_from/na_to MUST use
    // the shared +07:00 formatter (same as date_from/to) so SSR prefetch and
    // client query keys are byte-identical — otherwise na_to drops most of the
    // day. URL stores YYYY-MM-DD; the offset is applied only here.
    if (overdue) params.overdue = true;
    if (unassigned) params.unassigned = true;
    if (isHot) params.is_hot = true;
    if (noConsultation) params.no_consultation = true;
    if (nextActivityFrom) params.next_activity_from = formatLeadsDateFromApiParam(nextActivityFrom);
    if (nextActivityTo) params.next_activity_to = formatLeadsDateToApiParam(nextActivityTo);
    if (consultationStatusFilters.length > 0) params.consultation_status_id = consultationStatusFilters.join(",");

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
    overdue, unassigned, isHot, noConsultation, nextActivityFrom, nextActivityTo,
    consultationStatusFilters,
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
      overdue,
      unassigned,
      isHot,
      noConsultation,
      nextActivityFrom,
      nextActivityTo,
      consultationStatusFilters,
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
      handleOverdueChange,
      handleUnassignedChange,
      handleIsHotChange,
      handleNoConsultationChange,
      handleNextActivityFromChange,
      handleNextActivityToChange,
      handleConsultationStatusChange,
      resetFilters,
      exitDashboardContext,
    },
    hasActiveFilters,
    drawerFilterCount,
    apiFilters,
    dashboardContext,
  };
}

export default useLeadsFilter;
