// src/contexts/DashboardDateContext.tsx
/**
 * Context for managing dashboard-wide date range filter.
 * All dashboard components can subscribe to this context to filter data.
 */
"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";
import type { DateRange } from "react-day-picker";
import { todayVN, subDaysVN, startOfMonthVN } from "@/lib/utils/vn-date";

// Preset options
export type DatePreset = "7d" | "30d" | "this_month" | "custom";

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

interface DashboardDateProviderProps {
  children: ReactNode;
  defaultPreset?: DatePreset;
}

export function DashboardDateProvider({
  children,
  defaultPreset = "7d",
}: DashboardDateProviderProps) {
  const [preset, setPresetState] = useState<DatePreset>(defaultPreset);
  const [dateRange, setDateRange] = useState<DateRange>(getPresetRange(defaultPreset));

  const setPreset = useCallback((newPreset: DatePreset) => {
    setPresetState(newPreset);
    if (newPreset !== "custom") {
      setDateRange(getPresetRange(newPreset));
    }
  }, []);

  const setCustomRange = useCallback((range: DateRange) => {
    setPresetState("custom");
    setDateRange(range);
  }, []);

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
