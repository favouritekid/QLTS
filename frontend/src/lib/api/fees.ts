/**
 * Fees API Client
 * API functions for Fee Management in Finance Module
 *
 * @see Backend_FastAPI/app/routers/fees.py
 */

import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import type {
  Fee,
  FeeDetail,
  FeeFilters,
  FeeCalculateRequest,
  FeeWaiveRequest,
  ProfileFinanceSummary,
} from "@/types/finance.types"

// ============================================================================
// RESPONSE TYPES
// ============================================================================

export interface FeePaginatedResponse {
  items: Fee[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ============================================================================
// FEE CRUD OPERATIONS
// ============================================================================

/**
 * Get list of fees with pagination and filtering
 *
 * @param filters - Query parameters for filtering
 * @returns Paginated list of fees with profile info
 *
 * @example
 * ```ts
 * const fees = await feesApi.getFees({
 *   status: 'pending',
 *   page: 1,
 *   page_size: 20
 * })
 * ```
 */
export async function getFees(filters?: FeeFilters): Promise<FeePaginatedResponse> {
  const response = await api.get<FeePaginatedResponse>(API_ENDPOINTS.FINANCE.FEES.LIST, {
    params: filters,
  })
  return response.data
}

/**
 * Get single fee by ID
 *
 * @param feeId - The fee ID
 * @returns Fee details with invoices and discounts
 *
 * @throws {AxiosError} 404 if fee not found
 */
export async function getFee(feeId: number): Promise<FeeDetail> {
  const response = await api.get<FeeDetail>(API_ENDPOINTS.FINANCE.FEES.DETAIL(feeId))
  return response.data
}

/**
 * Get fees by admission profile ID
 *
 * @param profileId - The admission profile ID
 * @returns List of fees for the profile
 */
export async function getFeesByProfile(profileId: number): Promise<Fee[]> {
  const response = await api.get<Fee[]>(API_ENDPOINTS.FINANCE.FEES.BY_PROFILE(profileId))
  return response.data
}

/**
 * Get finance summary for an admission profile
 * Used for cross-reference from Admission Detail (READ-ONLY badge)
 *
 * @param profileId - The admission profile ID
 * @returns Finance summary with amounts and status
 */
export async function getProfileFinanceSummary(
  profileId: number
): Promise<ProfileFinanceSummary> {
  const response = await api.get<ProfileFinanceSummary>(
    API_ENDPOINTS.FINANCE.FEES.PROFILE_SUMMARY(profileId)
  )
  return response.data
}

// ============================================================================
// FEE ACTIONS
// ============================================================================

/**
 * Calculate fee for an admission profile
 * Creates fee record with invoices based on installment plan
 *
 * @param data - Fee calculation parameters
 * @returns Created fee with detail
 *
 * @throws {AxiosError} 400 if profile not eligible
 * @throws {AxiosError} 409 if fee already exists
 *
 * @example
 * ```ts
 * const fee = await feesApi.calculateFee({
 *   admission_profile_id: 123,
 *   fee_type: 'tuition',
 *   installment_plan_code: 'FULL_PAYMENT'
 * })
 * ```
 */
export async function calculateFee(data: FeeCalculateRequest): Promise<FeeDetail> {
  const response = await api.post<FeeDetail>(API_ENDPOINTS.FINANCE.FEES.CALCULATE, data)
  return response.data
}

/**
 * Waive (discount) a portion of the fee
 *
 * @param feeId - The fee ID
 * @param data - Waive amount and reason
 * @returns Updated fee
 *
 * @throws {AxiosError} 400 if waive amount exceeds remaining
 * @throws {AxiosError} 403 if no permission
 */
export async function waiveFee(feeId: number, data: FeeWaiveRequest): Promise<Fee> {
  const response = await api.post<Fee>(API_ENDPOINTS.FINANCE.FEES.WAIVE(feeId), data)
  return response.data
}

/**
 * Cancel a fee
 *
 * @param feeId - The fee ID
 * @param reason - Cancellation reason
 * @returns Updated fee with cancelled status
 *
 * @throws {AxiosError} 400 if fee has payments
 * @throws {AxiosError} 403 if no permission
 */
export async function cancelFee(feeId: number, reason: string): Promise<Fee> {
  const response = await api.post<Fee>(API_ENDPOINTS.FINANCE.FEES.CANCEL(feeId), { reason })
  return response.data
}

/**
 * Recalculate fee amounts based on current discount policies
 * Use with caution - may change invoice amounts
 *
 * @param feeId - The fee ID
 * @returns Updated fee with recalculated amounts
 *
 * @throws {AxiosError} 400 if fee has verified payments
 * @throws {AxiosError} 403 if no permission
 */
export async function recalculateFee(feeId: number): Promise<FeeDetail> {
  const response = await api.post<FeeDetail>(API_ENDPOINTS.FINANCE.FEES.RECALCULATE(feeId))
  return response.data
}

// ============================================================================
// EXPORTED API OBJECT
// ============================================================================

export const feesApi = {
  // CRUD
  getFees,
  getFee,
  getFeesByProfile,
  getProfileFinanceSummary,
  // Actions
  calculateFee,
  waiveFee,
  cancelFee,
  recalculateFee,
}
