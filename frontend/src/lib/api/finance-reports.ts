import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import { debtReportResponseSchema } from "@/lib/zod/finance"
import type { DebtReportFilters, DebtReportResponse } from "@/types/finance.types"

export async function getDebtReport(filters?: DebtReportFilters): Promise<DebtReportResponse> {
  const response = await api.get<DebtReportResponse>(API_ENDPOINTS.FINANCE.DEBT_REPORT, {
    params: filters,
  })
  // Runtime-validate the contract (throws on drift) instead of trusting the cast.
  return debtReportResponseSchema.parse(response.data) as DebtReportResponse
}

export const financeReportsApi = {
  getDebtReport,
}
