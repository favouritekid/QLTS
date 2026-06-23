import { useQuery } from "@tanstack/react-query";

import {
  getAdmissionWeeklyReport,
  getReportFilters,
  type WeeklyReportParams,
} from "@/lib/api/reports";

export const weeklyReportKeys = {
  all: ["admission-weekly-report"] as const,
  query: (params: WeeklyReportParams) =>
    [...weeklyReportKeys.all, params] as const,
  filters: (year?: number) =>
    [...weeklyReportKeys.all, "filters", year ?? null] as const,
};

/** Năm (config ∪ data) + đợt cho bộ lọc — admin & manager. */
export function useReportFilters(year?: number) {
  return useQuery({
    queryKey: weeklyReportKeys.filters(year),
    queryFn: () => getReportFilters(year),
    staleTime: 5 * 60 * 1000, // catalog rarely changes
  });
}

export function useWeeklyReport(params: WeeklyReportParams) {
  return useQuery({
    queryKey: weeklyReportKeys.query(params),
    queryFn: () => getAdmissionWeeklyReport(params),
    enabled: !!params.academic_year,
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev, // keep table visible while switching week/filter
  });
}
