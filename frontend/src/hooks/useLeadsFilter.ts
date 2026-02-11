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
  offeringFilters: string[];
  stageFilters: string[];
  officerFilters: string[];
  dateFrom: string;
  dateTo: string;
  dateField: "created_at" | "last_consultation_at";
}

export interface LeadsFilterState extends StoredFilters {
  pageSize: number;
  scoreRange: [number, number];
}

export interface LeadsFilterHandlers {
  setPage: (page: number) => void;
  handleSearchChange: (value: string) => void;
  handleStatusChange: (statuses: LeadStatus[]) => void;
  handleSourceChange: (sources: string[]) => void;
  handleOfferingChange: (offerings: string[]) => void;
  handleStageChange: (stages: string[]) => void;
  handleOfficerChange: (officers: string[]) => void;
  handleScoreRangeChange: (range: [number, number]) => void;
  handleDateFromChange: (date: string) => void;
  handleDateToChange: (date: string) => void;
  handleDateFieldChange: (field: "created_at" | "last_consultation_at") => void;
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
const STORAGE_VERSION = 2;

interface VersionedStorage {
  version: number;
  data: StoredFilters;
}

const DEFAULT_FILTERS: StoredFilters = {
  page: 1,
  search: "",
  statusFilters: [],
  sourceFilters: [],
  offeringFilters: [],
  stageFilters: [],
  officerFilters: [],
  dateFrom: "",
  dateTo: "",
  dateField: "created_at",
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
    searchParams.get("offering") ||
    searchParams.get("stage") ||
    searchParams.get("officer") ||
    searchParams.get("from") ||
    searchParams.get("to")
  );
}

function parseSearchParams(searchParams: URLSearchParams): StoredFilters {
  return {
    page: parseInt(searchParams.get("page") || "1"),
    search: searchParams.get("q") || "",
    statusFilters: searchParams.get("status")?.split(",").filter(Boolean) as LeadStatus[] || [],
    sourceFilters: searchParams.get("source")?.split(",").filter(Boolean) || [],
    offeringFilters: searchParams.get("offering")?.split(",").filter(Boolean) || [],
    stageFilters: searchParams.get("stage")?.split(",").filter(Boolean) || [],
    officerFilters: searchParams.get("officer")?.split(",").filter(Boolean) || [],
    dateFrom: searchParams.get("from") || "",
    dateTo: searchParams.get("to") || "",
    dateField: (searchParams.get("date_field") === "last_consultation_at" 
      ? "last_consultation_at" 
      : "created_at") as "created_at" | "last_consultation_at",
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
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100]);
  const [offeringFilters, setOfferingFilters] = useState<string[]>(initialValues.offeringFilters);
  const [stageFilters, setStageFilters] = useState<string[]>(initialValues.stageFilters);
  const [officerFilters, setOfficerFilters] = useState<string[]>(initialValues.officerFilters);
  const [dateFrom, setDateFrom] = useState(initialValues.dateFrom);
  const [dateTo, setDateTo] = useState(initialValues.dateTo);
  const [dateField, setDateField] = useState<"created_at" | "last_consultation_at">(
    initialValues.dateField === "created_at" ? "created_at" : "last_consultation_at"
  );

  // ==========================================================================
  // EXTERNAL URL CHANGE DETECTION (e.g., navigation from dashboard)
  // ==========================================================================
  
  // This ref tracks if the URL change was caused by this hook (internal) or external navigation
  const isInternalUrlChange = useRef(false);
  
  // Sync URL params INTO state when URL changes from external navigation  
  // (e.g., clicking funnel stage from dashboard)
  useEffect(() => {
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
    if (JSON.stringify(urlFilters.offeringFilters) !== JSON.stringify(offeringFilters)) {
      setOfferingFilters(urlFilters.offeringFilters);
    }
    if (JSON.stringify(urlFilters.officerFilters) !== JSON.stringify(officerFilters)) {
      setOfficerFilters(urlFilters.officerFilters);
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
      if (offeringFilters.length > 0) params.set("offering", offeringFilters.join(","));
      if (stageFilters.length > 0) params.set("stage", stageFilters.join(","));
      if (officerFilters.length > 0) params.set("officer", officerFilters.join(","));
      if (dateFrom) params.set("from", dateFrom);
      if (dateTo) params.set("to", dateTo);
      if (dateField !== "created_at") params.set("date_field", dateField);

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
    page, search, statusFilters, sourceFilters, offeringFilters,
    stageFilters, officerFilters, dateFrom, dateTo, dateField,
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
      offeringFilters,
      stageFilters,
      officerFilters,
      dateFrom,
      dateTo,
      dateField,
    };

    // Save if any filter is active OR if not on page 1
    const shouldSave =
      page > 1 ||
      search ||
      statusFilters.length > 0 ||
      sourceFilters.length > 0 ||
      offeringFilters.length > 0 ||
      stageFilters.length > 0 ||
      officerFilters.length > 0 ||
      dateFrom ||
      dateTo;

    if (shouldSave) {
      saveFiltersToStorage(filtersToSave);
    } else {
      clearFiltersFromStorage();
    }
  }, [
    page, search, statusFilters, sourceFilters, offeringFilters,
    stageFilters, officerFilters, dateFrom, dateTo, dateField,
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

  const handleScoreRangeChange = useCallback((range: [number, number]) => {
    setScoreRange(range);
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

  const resetFilters = useCallback(() => {
    setSearch("");
    setStatusFilters([]);
    setSourceFilters([]);
    setScoreRange([0, 100]);
    setOfferingFilters([]);
    setStageFilters([]);
    setOfficerFilters([]);
    setDateFrom("");
    setDateTo("");
    setDateField("created_at");
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
      offeringFilters.length > 0 ||
      stageFilters.length > 0 ||
      officerFilters.length > 0 ||
      hasScoreFilter ||
      dateFrom ||
      dateTo
    );
  }, [
    search, statusFilters, sourceFilters, offeringFilters,
    stageFilters, officerFilters, hasScoreFilter, dateFrom, dateTo,
  ]);

  const apiFilters = useMemo(() => {
    const params: Record<string, unknown> = {
      page,
      page_size: pageSize,
      sort_by: "created_at",
      order: "desc",
    };

    if (search) params.search = search;
    if (statusFilters.length > 0) params.status = statusFilters.join(",");
    if (sourceFilters.length > 0) params.source = sourceFilters.join(",");
    if (offeringFilters.length > 0) params.offering_id = offeringFilters.join(",");
    if (stageFilters.length > 0) params.pipeline_stage_id = stageFilters.join(",");
    if (officerFilters.length > 0) params.assigned_officer_id = officerFilters.join(",");

    if (dateFrom) params.date_from = new Date(dateFrom).toISOString();
    if (dateTo) {
      const endDate = new Date(dateTo);
      endDate.setHours(23, 59, 59, 999);
      params.date_to = endDate.toISOString();
    }
    if (dateFrom || dateTo) params.date_field = dateField;

    return params;
  }, [
    page, pageSize, search, statusFilters, sourceFilters,
    offeringFilters, stageFilters, officerFilters, dateFrom, dateTo, dateField,
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
      scoreRange,
      offeringFilters,
      stageFilters,
      officerFilters,
      dateFrom,
      dateTo,
      dateField,
    },
    handlers: {
      setPage,
      handleSearchChange,
      handleStatusChange,
      handleSourceChange,
      handleOfferingChange,
      handleStageChange,
      handleOfficerChange,
      handleScoreRangeChange,
      handleDateFromChange,
      handleDateToChange,
      handleDateFieldChange,
      resetFilters,
    },
    hasActiveFilters,
    apiFilters,
  };
}

export default useLeadsFilter;
