import { useQuery } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { financeReportsApi } from "@/lib/api/finance-reports"
import type { ApiErrorResponse } from "@/types/api.types"
import type { DebtReportFilters, DebtReportResponse } from "@/types/finance.types"

export const debtReportKeys = {
  all: ["finance", "debt-report"] as const,
  detail: (filters?: DebtReportFilters) => [...debtReportKeys.all, filters] as const,
}

export function useDebtReport(filters?: DebtReportFilters, options?: { enabled?: boolean }) {
  return useQuery<DebtReportResponse, AxiosError<ApiErrorResponse>>({
    queryKey: debtReportKeys.detail(filters),
    queryFn: () => financeReportsApi.getDebtReport(filters),
    enabled: options?.enabled ?? true,
    staleTime: 1000 * 30,
  })
}
