/**
 * Payments API Client
 * API functions for Payment Management in Finance Module
 *
 * Implements Maker-Checker workflow:
 * - Maker (Accountant): Records payment → status = "pending"
 * - Checker (Manager/Admin): Verifies/Rejects → status = "verified" or "rejected"
 *
 * @see Backend_FastAPI/app/routers/payments.py
 */

import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import type {
  Payment,
  PaymentIntent,
  PaymentMethod,
  PaymentFilters,
  PaymentCreateRequest,
  PaymentIntentCreateRequest,
  PaymentRejectRequest,
  FinanceDashboardStats,
  InstallmentPlan,
} from "@/types/finance.types"

// ============================================================================
// RESPONSE TYPES
// ============================================================================

export interface PaymentPaginatedResponse {
  items: Payment[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ============================================================================
// PAYMENT CRUD OPERATIONS
// ============================================================================

/**
 * Get list of payments with pagination and filtering
 *
 * @param filters - Query parameters for filtering
 * @returns Paginated list of payments
 *
 * @example
 * ```ts
 * // Get pending payments for verification queue
 * const payments = await paymentsApi.getPayments({
 *   status: 'pending',
 *   page: 1,
 *   page_size: 20
 * })
 * ```
 */
export async function getPayments(filters?: PaymentFilters): Promise<PaymentPaginatedResponse> {
  const response = await api.get<PaymentPaginatedResponse>(API_ENDPOINTS.FINANCE.PAYMENTS.LIST, {
    params: filters,
  })
  return response.data
}

/**
 * Get single payment by ID
 *
 * @param paymentId - The payment ID
 * @returns Payment details
 *
 * @throws {AxiosError} 404 if payment not found
 */
export async function getPayment(paymentId: number): Promise<Payment> {
  const response = await api.get<Payment>(API_ENDPOINTS.FINANCE.PAYMENTS.DETAIL(paymentId))
  return response.data
}

/**
 * Get payments by invoice ID
 *
 * @param invoiceId - The invoice ID
 * @returns List of payments for the invoice
 */
export async function getPaymentsByInvoice(invoiceId: number): Promise<Payment[]> {
  const response = await api.get<Payment[]>(API_ENDPOINTS.FINANCE.PAYMENTS.BY_INVOICE(invoiceId))
  return response.data
}

// ============================================================================
// PAYMENT ACTIONS (Maker-Checker Workflow)
// ============================================================================

/**
 * Record a manual payment (Maker action)
 * Creates payment with status "pending" for verification
 *
 * @param data - Payment details
 * @returns Created payment (status = "pending")
 *
 * @throws {AxiosError} 400 if amount exceeds remaining
 * @throws {AxiosError} 403 if no permission
 *
 * @example
 * ```ts
 * const payment = await paymentsApi.createPayment({
 *   invoice_id: 123,
 *   method_id: 1, // Cash
 *   amount: '5000000',
 *   payment_date: '2024-01-15',
 *   reference_code: 'BANK-12345',
 *   payer_name: 'Nguyen Van A'
 * })
 * ```
 */
export async function createPayment(data: PaymentCreateRequest): Promise<Payment> {
  const response = await api.post<Payment>(API_ENDPOINTS.FINANCE.PAYMENTS.CREATE, data)
  return response.data
}

/**
 * Verify a payment (Checker action)
 * Changes status from "pending" to "verified"
 *
 * @param paymentId - The payment ID
 * @returns Updated payment (status = "verified")
 *
 * @throws {AxiosError} 400 if already verified or maker-checker violation
 * @throws {AxiosError} 403 if no permission
 */
export async function verifyPayment(paymentId: number): Promise<Payment> {
  const response = await api.post<Payment>(API_ENDPOINTS.FINANCE.PAYMENTS.VERIFY(paymentId))
  return response.data
}

/**
 * Reject a payment (Checker action)
 * Changes status from "pending" to "rejected"
 *
 * @param paymentId - The payment ID
 * @param data - Rejection reason
 * @returns Updated payment (status = "rejected")
 *
 * @throws {AxiosError} 400 if already verified or maker-checker violation
 * @throws {AxiosError} 403 if no permission
 */
export async function rejectPayment(paymentId: number, data: PaymentRejectRequest): Promise<Payment> {
  const response = await api.post<Payment>(API_ENDPOINTS.FINANCE.PAYMENTS.REJECT(paymentId), data)
  return response.data
}

// ============================================================================
// ONLINE PAYMENT (Payment Intent)
// ============================================================================

/**
 * Create payment intent for online payment
 * Generates pay_url for gateway redirect
 *
 * @param data - Payment intent details with idempotency_key
 * @returns Payment intent with pay_url
 *
 * @example
 * ```ts
 * const intent = await paymentsApi.createPaymentIntent({
 *   invoice_id: 123,
 *   method_id: 2, // VNPay
 *   amount: '5000000',
 *   idempotency_key: crypto.randomUUID(),
 *   return_url: 'https://example.com/finance/payments/return'
 * })
 *
 * // Redirect to gateway
 * window.location.href = intent.pay_url
 * ```
 */
export async function createPaymentIntent(data: PaymentIntentCreateRequest): Promise<PaymentIntent> {
  const response = await api.post<PaymentIntent>(API_ENDPOINTS.FINANCE.PAYMENTS.INTENTS.CREATE, data)
  return response.data
}

/**
 * Get payment intent by ID
 * Used to check payment status after gateway callback
 *
 * @param intentId - The payment intent ID
 * @returns Payment intent with current status
 */
export async function getPaymentIntent(intentId: number): Promise<PaymentIntent> {
  const response = await api.get<PaymentIntent>(API_ENDPOINTS.FINANCE.PAYMENTS.INTENTS.DETAIL(intentId))
  return response.data
}

// ============================================================================
// LOOKUP DATA
// ============================================================================

/**
 * Get list of payment methods
 *
 * @returns List of active payment methods
 */
export async function getPaymentMethods(): Promise<PaymentMethod[]> {
  const response = await api.get<PaymentMethod[]>(API_ENDPOINTS.FINANCE.PAYMENTS.METHODS)
  return response.data
}

/**
 * Get list of installment plans
 *
 * @returns List of active installment plans
 */
export async function getInstallmentPlans(): Promise<InstallmentPlan[]> {
  const response = await api.get<InstallmentPlan[]>(API_ENDPOINTS.FINANCE.INSTALLMENT_PLANS.LIST)
  return response.data
}

/**
 * Get single installment plan by ID
 *
 * @param id - The installment plan ID
 * @returns Installment plan details
 */
export async function getInstallmentPlan(id: number): Promise<InstallmentPlan> {
  const response = await api.get<InstallmentPlan>(API_ENDPOINTS.FINANCE.INSTALLMENT_PLANS.DETAIL(id))
  return response.data
}

// ============================================================================
// DASHBOARD
// ============================================================================

/**
 * Get finance dashboard statistics
 *
 * @returns Dashboard stats (pending counts, amounts, collections)
 */
export async function getFinanceDashboard(): Promise<FinanceDashboardStats> {
  const response = await api.get<FinanceDashboardStats>(API_ENDPOINTS.FINANCE.DASHBOARD)
  return response.data
}

// ============================================================================
// EXPORTED API OBJECT
// ============================================================================

export const paymentsApi = {
  // CRUD
  getPayments,
  getPayment,
  getPaymentsByInvoice,
  // Maker-Checker Actions
  createPayment,
  verifyPayment,
  rejectPayment,
  // Online Payment
  createPaymentIntent,
  getPaymentIntent,
  // Lookup
  getPaymentMethods,
  getInstallmentPlans,
  getInstallmentPlan,
  // Dashboard
  getFinanceDashboard,
}
