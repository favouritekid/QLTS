import { useQuery } from "@tanstack/react-query";

import {
  getAdmissionTrend,
  getAdmissionWow,
  getOfficerMajorMatrix,
  getPipelineFunnel,
  type OverviewParams,
} from "@/lib/api/reports";
import type { ReportGroupBy } from "@/lib/zod/reports";

/**
 * React Query hooks for the admission-overview dashboard panels. Same scope
 * params (Năm · Đợt · Đơn vị) as the weekly report; ``placeholderData: prev``
 * keeps each panel visible (dim, no layout jump) while the slice reloads.
 */
type WowParams = OverviewParams & { group_by: ReportGroupBy };

export const overviewKeys = {
  all: ["admission-overview"] as const,
  funnel: (p: OverviewParams) => [...overviewKeys.all, "funnel", p] as const,
  trend: (p: OverviewParams & { weeks?: number }) =>
    [...overviewKeys.all, "trend", p] as const,
  matrix: (p: OverviewParams) => [...overviewKeys.all, "matrix", p] as const,
  wow: (p: WowParams) => [...overviewKeys.all, "wow", p] as const,
};

export function usePipelineFunnel(params: OverviewParams) {
  return useQuery({
    queryKey: overviewKeys.funnel(params),
    queryFn: () => getPipelineFunnel(params),
    enabled: !!params.academic_year,
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  });
}

export function useAdmissionTrend(params: OverviewParams & { weeks?: number }) {
  return useQuery({
    queryKey: overviewKeys.trend(params),
    queryFn: () => getAdmissionTrend(params),
    enabled: !!params.academic_year,
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  });
}

export function useOfficerMajorMatrix(params: OverviewParams) {
  return useQuery({
    queryKey: overviewKeys.matrix(params),
    queryFn: () => getOfficerMajorMatrix(params),
    enabled: !!params.academic_year,
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  });
}

export function useAdmissionWow(params: WowParams) {
  return useQuery({
    queryKey: overviewKeys.wow(params),
    queryFn: () => getAdmissionWow(params),
    enabled: !!params.academic_year,
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  });
}
