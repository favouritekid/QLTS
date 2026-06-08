/**
 * Invoices API Client
 * API functions for Invoice Management in Finance Module
 *
 * @see Backend_FastAPI/app/routers/invoices.py
 */

import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import { vietQRResponseSchema } from "@/lib/zod/finance"
import type {
  Invoice,
  InvoiceDetail,
  InvoiceFilters,
  InvoicePenaltyRequest,
  VietQRResponse,
} from "@/types/finance.types"

// ============================================================================
// RESPONSE TYPES
// ============================================================================

export interface InvoicePaginatedResponse {
  items: Invoice[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ============================================================================
// INVOICE CRUD OPERATIONS
// ============================================================================

/**
 * Get list of invoices with pagination and filtering
 *
 * @param filters - Query parameters for filtering
 * @returns Paginated list of invoices
 *
 * @example
 * ```ts
 * const invoices = await invoicesApi.getInvoices({
 *   status: 'issued',
 *   overdue_only: true,
 *   page: 1,
 *   page_size: 20
 * })
 * ```
 */
export async function getInvoices(filters?: InvoiceFilters): Promise<InvoicePaginatedResponse> {
  const response = await api.get<InvoicePaginatedResponse>(API_ENDPOINTS.FINANCE.INVOICES.LIST, {
    params: filters,
  })
  return response.data
}

/**
 * Get single invoice by ID
 *
 * @param invoiceId - The invoice ID
 * @returns Invoice details with payments
 *
 * @throws {AxiosError} 404 if invoice not found
 */
export async function getInvoice(invoiceId: number): Promise<InvoiceDetail> {
  const response = await api.get<InvoiceDetail>(API_ENDPOINTS.FINANCE.INVOICES.DETAIL(invoiceId))
  return response.data
}

/**
 * Get invoices by fee ID
 *
 * @param feeId - The fee ID
 * @returns List of invoices for the fee
 */
export async function getInvoicesByFee(feeId: number): Promise<Invoice[]> {
  const response = await api.get<Invoice[]>(API_ENDPOINTS.FINANCE.INVOICES.BY_FEE(feeId))
  return response.data
}

/**
 * Get VietQR payload and PNG for an invoice.
 */
export async function getInvoiceVietQR(invoiceId: number): Promise<VietQRResponse> {
  const response = await api.get<VietQRResponse>(API_ENDPOINTS.FINANCE.INVOICES.VIETQR(invoiceId))
  return vietQRResponseSchema.parse(response.data) as VietQRResponse
}

// ============================================================================
// INVOICE ACTIONS
// ============================================================================

/**
 * Issue an invoice (change from draft to issued)
 *
 * @param invoiceId - The invoice ID
 * @returns Updated invoice with issued status
 *
 * @throws {AxiosError} 400 if already issued
 * @throws {AxiosError} 403 if no permission
 */
export async function issueInvoice(invoiceId: number): Promise<Invoice> {
  const response = await api.put<Invoice>(API_ENDPOINTS.FINANCE.INVOICES.ISSUE(invoiceId))
  return response.data
}

/**
 * Cancel an invoice
 *
 * @param invoiceId - The invoice ID
 * @param reason - Cancellation reason
 * @returns Updated invoice with cancelled status
 *
 * @throws {AxiosError} 400 if invoice has payments
 * @throws {AxiosError} 403 if no permission
 */
export async function cancelInvoice(invoiceId: number, reason: string): Promise<Invoice> {
  const response = await api.put<Invoice>(API_ENDPOINTS.FINANCE.INVOICES.CANCEL(invoiceId), undefined, {
    params: { reason },
  })
  return response.data
}

/**
 * Apply penalty to an overdue invoice
 *
 * @param invoiceId - The invoice ID
 * @param data - Penalty amount
 * @returns Updated invoice with penalty applied
 *
 * @throws {AxiosError} 400 if invoice not overdue
 * @throws {AxiosError} 403 if no permission
 */
export async function applyPenalty(invoiceId: number, data: InvoicePenaltyRequest): Promise<Invoice> {
  const response = await api.post<Invoice>(API_ENDPOINTS.FINANCE.INVOICES.PENALTY(invoiceId), undefined, {
    params: { penalty_amount: data.penalty_amount },
  })
  return response.data
}

// ============================================================================
// EXPORTED API OBJECT
// ============================================================================

export const invoicesApi = {
  // CRUD
  getInvoices,
  getInvoice,
  getInvoicesByFee,
  getInvoiceVietQR,
  // Actions
  issueInvoice,
  cancelInvoice,
  applyPenalty,
}
