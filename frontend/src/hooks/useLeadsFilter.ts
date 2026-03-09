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
}

export interface UseLeadsFilterReturn {
  state: LeadsFilterState;
  handlers: LeadsFilterHandlers;
  hasActiveFilters: boolean;
  apiFilters: Record<string, unknown>;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const LEADS_FILTERS_STORAGE_KEY = "leads_filters";
// ✅ VERSIONING: Increment when StoredFilters schema changes
const STORAGE_VERSION = 4;

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

function hasUrlFilterParams(searchParams: URLSearchParams): boolean {
  return !!(
    searchParams.get("page") ||
    searchParams.get("q") ||
    searchParams.get("status") ||
    searchParams.get("source") ||
    searchParams.get("validity") ||
    searchParams.get("offering") ||
    searchParams.get("stage") ||
    searchParams.get("officer") ||
    searchParams.get("unit_id") ||
    searchParams.get("from") ||
    searchParams.get("to") ||
    searchParams.get("score_min") ||
    searchParams.get("score_max")
  );
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
  // Track previous searchParams content to avoid false triggers from reference changes
  const prevSearchParamsStr = useRef(searchParams.toString());

  // Determine initial values: URL params > localStorage > defaults
  const initialValues = useMemo(() => {
    if (hasUrlFilterParams(searchParams)) {
      return parseSearchParams(searchParams);
    }
    
    const storedFilters = loadFiltersFromStorage();
    if (storedFilters) {
      return storedFilters; // storedFilters already includes page
    }
    
    return DEFAULT_FILTERS; // DEFAULT_FILTERS already includes page: 1
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
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

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
    if (currentStr === prevSearchParamsStr.current) {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]); // Only trigger on searchParams change

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
    pathname,
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
    };

    // Save if any filter is active OR if not on page 1
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
      dateTo;

    if (shouldSave) {
      saveFiltersToStorage(filtersToSave);
    } else {
      clearFiltersFromStorage();
    }
  }, [
    page, search, statusFilters, sourceFilters, validityFilters, offeringFilters,
    stageFilters, officerFilters, unitId, dateFrom, dateTo, dateField,
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
    setPage(1);
  }, []);

  const handleDateToChange = useCallback((date: string) => {
    setDateTo(date);
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

    if (dateFrom) params.date_from = new Date(dateFrom).toISOString();
    if (dateTo) {
      const endDate = new Date(dateTo);
      endDate.setHours(23, 59, 59, 999);
      params.date_to = endDate.toISOString();
    }
    if (dateFrom || dateTo) params.date_field = dateField;

    // === SCORE RANGE FILTER (server-side) ===
    if (scoreRange[0] > 0) params.score_min = scoreRange[0];
    if (scoreRange[1] < 100) params.score_max = scoreRange[1];

    return params;
  }, [
    page, pageSize, search, statusFilters, sourceFilters, validityFilters,
    offeringFilters, stageFilters, officerFilters, unitId, dateFrom, dateTo, dateField,
    sortBy, sortOrder, scoreRange,
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
    },
    hasActiveFilters,
    apiFilters,
  };
}

export default useLeadsFilter;
