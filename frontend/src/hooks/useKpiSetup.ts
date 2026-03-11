// hooks/useKpiSetup.ts
import { useQuery } from "@tanstack/react-query";
import type { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import type { CoverageReport } from "@/types/kpi-setup.types";

interface ApiError {
  detail: string;
}

export const kpiSetupKeys = {
  all: ["kpi-setup"] as const,
  coverage: (fy: number) => [...kpiSetupKeys.all, "coverage", fy] as const,
};

export function useKpiCoverage(fiscalYear: number) {
  return useQuery<CoverageReport, AxiosError<ApiError>>({
    queryKey: kpiSetupKeys.coverage(fiscalYear),
    queryFn: async () => {
      const res = await api.get<CoverageReport>("/api/admin/kpi-setup/coverage", {
        params: { fiscal_year: fiscalYear },
      });
      return res.data;
    },
    staleTime: 2 * 60 * 1000,
  });
}
