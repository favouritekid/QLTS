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
import { subDays, startOfMonth, startOfDay, endOfDay } from "date-fns";
import type { DateRange } from "react-day-picker";

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

function getPresetRange(preset: DatePreset): DateRange {
  const today = new Date();
  
  switch (preset) {
    case "7d":
      return { from: subDays(today, 6), to: today };
    case "30d":
      return { from: subDays(today, 29), to: today };
    case "this_month":
      return { from: startOfMonth(today), to: today };
    case "custom":
    default:
      return { from: subDays(today, 6), to: today };
  }
}

function formatDateForAPI(date: Date): string {
  return date.toISOString().split("T")[0];
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
    startDate: dateRange.from ? formatDateForAPI(startOfDay(dateRange.from)) : "",
    endDate: dateRange.to ? formatDateForAPI(endOfDay(dateRange.to)) : "",
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
