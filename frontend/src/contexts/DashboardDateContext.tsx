// src/contexts/DashboardDateContext.tsx
/**
 * Context for managing dashboard-wide date range filter.
 * All dashboard components can subscribe to this context to filter data.
 * Syncs date range state to URL search params for shareability and back/forward navigation.
 */
"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import type { DateRange } from "react-day-picker";
import { todayVN, subDaysVN, startOfMonthVN } from "@/lib/utils/vn-date";

// Preset options
export type DatePreset = "7d" | "30d" | "this_month" | "custom";

const VALID_PRESETS: DatePreset[] = ["7d", "30d", "this_month", "custom"];

interface DashboardDateContextValue {
  dateRange: DateRange;
  preset: DatePreset;
  setPreset: (preset: DatePreset) => void;
  setCustomRange: (range: DateRange) => void;
  // API-friendly format
  startDate: string; // ISO format YYYY-MM-DD
  endDate: string;
}

const DashboardDateContext = createContext<DashboardDateContextValue | null>(null);

/** Parse a YYYY-MM-DD string into a local Date (noon to avoid DST drift) */
function parseLocalDate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Check if a string is a valid YYYY-MM-DD date */
function isValidDateString(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const date = parseLocalDate(s);
  return !isNaN(date.getTime());
}

function getPresetRange(preset: DatePreset): DateRange {
  const today = todayVN();

  switch (preset) {
    case "7d":
      return { from: parseLocalDate(subDaysVN(today, 6)), to: parseLocalDate(today) };
    case "30d":
      return { from: parseLocalDate(subDaysVN(today, 29)), to: parseLocalDate(today) };
    case "this_month":
      return { from: parseLocalDate(startOfMonthVN(today)), to: parseLocalDate(today) };
    case "custom":
    default:
      return { from: parseLocalDate(subDaysVN(today, 6)), to: parseLocalDate(today) };
  }
}

export function formatDateForAPI(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Read initial date state from URL search params */
function resolveInitialDateState(defaultPreset: DatePreset): { preset: DatePreset; range: DateRange } {
  if (typeof window === "undefined") {
    return { preset: defaultPreset, range: getPresetRange(defaultPreset) };
  }

  const params = new URLSearchParams(window.location.search);
  const urlRange = params.get("range");
  const urlFrom = params.get("from");
  const urlTo = params.get("to");

  // Custom date range from URL
  if (urlFrom && urlTo && isValidDateString(urlFrom) && isValidDateString(urlTo)) {
    return {
      preset: "custom",
      range: { from: parseLocalDate(urlFrom), to: parseLocalDate(urlTo) },
    };
  }

  // Named preset from URL
  if (urlRange && VALID_PRESETS.includes(urlRange as DatePreset) && urlRange !== "custom") {
    const preset = urlRange as DatePreset;
    return { preset, range: getPresetRange(preset) };
  }

  // Fallback to default
  return { preset: defaultPreset, range: getPresetRange(defaultPreset) };
}

/** Update URL search params for date state — uses pushState for back/forward support */
function syncDateToURL(updates: Record<string, string | null>) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null) {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  }
  const qs = params.toString();
  const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  window.history.pushState({ _dashboardDate: true }, "", newUrl);
}

interface DashboardDateProviderProps {
  children: ReactNode;
  defaultPreset?: DatePreset;
}

export function DashboardDateProvider({
  children,
  defaultPreset = "7d",
}: DashboardDateProviderProps) {
  const [preset, setPresetState] = useState<DatePreset>(
    () => resolveInitialDateState(defaultPreset).preset
  );
  const [dateRange, setDateRange] = useState<DateRange>(
    () => resolveInitialDateState(defaultPreset).range
  );

  const setPreset = useCallback((newPreset: DatePreset) => {
    setPresetState(newPreset);
    if (newPreset !== "custom") {
      const range = getPresetRange(newPreset);
      setDateRange(range);
      // Sync to URL: set named preset, remove custom from/to
      syncDateToURL({ range: newPreset, from: null, to: null });
    }
  }, []);

  const setCustomRange = useCallback((range: DateRange) => {
    setPresetState("custom");
    setDateRange(range);
    // Sync to URL: remove named preset, set from/to
    syncDateToURL({
      range: null,
      from: range.from ? formatDateForAPI(range.from) : null,
      to: range.to ? formatDateForAPI(range.to) : null,
    });
  }, []);

  // Restore date state on browser back/forward
  useEffect(() => {
    const handlePopState = () => {
      const restored = resolveInitialDateState(defaultPreset);
      setPresetState(restored.preset);
      setDateRange(restored.range);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [defaultPreset]);

  const value = useMemo<DashboardDateContextValue>(() => ({
    dateRange,
    preset,
    setPreset,
    setCustomRange,
    startDate: dateRange.from ? formatDateForAPI(dateRange.from) : "",
    endDate: dateRange.to ? formatDateForAPI(dateRange.to) : "",
  }), [dateRange, preset, setPreset, setCustomRange]);

  return (
    <DashboardDateContext.Provider value={value}>
      {children}
    </DashboardDateContext.Provider>
  );
}

export function useDashboardDate() {
  const context = useContext(DashboardDateContext);
  if (!context) {
    throw new Error("useDashboardDate must be used within DashboardDateProvider");
  }
  return context;
}

// Export preset labels for UI
export const DATE_PRESET_LABELS: Record<DatePreset, string> = {
  "7d": "7 ngày",
  "30d": "30 ngày",
  "this_month": "Tháng này",
  "custom": "Tùy chọn",
};
