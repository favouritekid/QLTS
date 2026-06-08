import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import type { DebtReportFilters, DebtReportResponse } from "@/types/finance.types"

export async function getDebtReport(filters?: DebtReportFilters): Promise<DebtReportResponse> {
  const response = await api.get<DebtReportResponse>(API_ENDPOINTS.FINANCE.DEBT_REPORT, {
    params: filters,
  })
  return response.data
}

export const financeReportsApi = {
  getDebtReport,
}
