/**
 * Accounting API Client
 * API functions for Accounting Period Management in Finance Module
 *
 * @see Backend_FastAPI/app/routers/accounting.py
 */

import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import type { AccountingPeriod } from "@/types/finance.types"

// ============================================================================
// REQUEST TYPES
// ============================================================================

export interface AccountingPeriodCreateRequest {
  month: number
  year: number
}

export interface AccountingPeriodFilters {
  year?: number
  is_closed?: boolean
}

export interface AccountingPeriodSummary {
  period_id: number
  period_key: string
  month: number
  year: number
  is_closed: boolean
  total_payments: string
  total_refunds: string
  net_revenue: string
  opened_at: string | null
  closed_at: string | null
}

// ============================================================================
// ACCOUNTING PERIOD OPERATIONS
// ============================================================================

/**
 * Get list of accounting periods with optional filters
 *
 * @param filters - Optional year and is_closed filters
 * @returns List of accounting periods
 *
 * @example
 * ```ts
 * const periods = await accountingApi.getPeriods({ year: 2026 })
 * ```
 */
export async function getPeriods(
  filters?: AccountingPeriodFilters
): Promise<AccountingPeriod[]> {
  const response = await api.get<AccountingPeriod[]>(
    API_ENDPOINTS.FINANCE.ACCOUNTING.PERIODS,
    { params: filters }
  )
  return response.data
}

/**
 * Get current open accounting period
 *
 * @returns Current open period or null if none exists
 */
export async function getCurrentPeriod(): Promise<AccountingPeriod | null> {
  const response = await api.get<AccountingPeriod | null>(
    `${API_ENDPOINTS.FINANCE.ACCOUNTING.PERIODS}/current`
  )
  return response.data
}

/**
 * Get accounting period by ID
 *
 * @param periodId - The period ID
 * @returns Period details
 *
 * @throws {AxiosError} 404 if period not found
 */
export async function getPeriod(periodId: number): Promise<AccountingPeriod> {
  const response = await api.get<AccountingPeriod>(
    API_ENDPOINTS.FINANCE.ACCOUNTING.PERIOD_DETAIL(periodId)
  )
  return response.data
}

/**
 * Get summary report for an accounting period
 *
 * @param periodId - The period ID
 * @returns Period summary with totals
 */
export async function getPeriodSummary(
  periodId: number
): Promise<AccountingPeriodSummary> {
  const response = await api.get<AccountingPeriodSummary>(
    `${API_ENDPOINTS.FINANCE.ACCOUNTING.PERIOD_DETAIL(periodId)}/summary`
  )
  return response.data
}

/**
 * Create a new accounting period
 * Only one open period allowed at a time
 *
 * @param data - Month and year for the new period
 * @returns Created period
 *
 * @throws {AxiosError} 400 if previous period not closed
 * @throws {AxiosError} 403 if not admin
 * @throws {AxiosError} 409 if period already exists
 *
 * @example
 * ```ts
 * const period = await accountingApi.createPeriod({ month: 2, year: 2026 })
 * ```
 */
export async function createPeriod(
  data: AccountingPeriodCreateRequest
): Promise<AccountingPeriod> {
  const response = await api.post<AccountingPeriod>(
    API_ENDPOINTS.FINANCE.ACCOUNTING.PERIODS,
    data
  )
  return response.data
}

/**
 * Close an accounting period
 *
 * @param periodId - The period ID to close
 * @param notes - Optional closing notes
 * @returns Updated closed period
 *
 * @throws {AxiosError} 400 if period already closed or has pending payments
 * @throws {AxiosError} 403 if not admin
 * @throws {AxiosError} 404 if period not found
 */
export async function closePeriod(
  periodId: number,
  notes?: string
): Promise<AccountingPeriod> {
  const response = await api.put<AccountingPeriod>(
    API_ENDPOINTS.FINANCE.ACCOUNTING.CLOSE_PERIOD(periodId),
    null,
    { params: notes ? { notes } : undefined }
  )
  return response.data
}

// ============================================================================
// EXPORTED API OBJECT
// ============================================================================

export const accountingApi = {
  getPeriods,
  getCurrentPeriod,
  getPeriod,
  getPeriodSummary,
  createPeriod,
  closePeriod,
}
