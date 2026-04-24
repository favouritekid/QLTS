// types/finance.types.ts
// Finance Module TypeScript Types
// Version: 3.0 - FULLY ALIGNED WITH BACKEND (includes can_* permission flags)
//
// ⚠️ IMPORTANT: These types MUST mirror Backend Pydantic schemas exactly.
// DO NOT add fields that don't exist in backend without marking as [FRONTEND_ONLY]
//
// Backend schemas: Backend_FastAPI/app/schemas/finance.py
// Last sync: 2026-02-03

// ============================================================================
// ENUMS (match backend exactly)
// ============================================================================
export type FeeType = "application" | "tuition" | "enrollment" | "insurance" | "dormitory" | "other"
export type FeeStatus = "pending" | "calculated" | "invoiced" | "partial" | "paid" | "overdue" | "waived" | "cancelled"
export type InvoiceStatus = "draft" | "issued" | "partial" | "paid" | "cancelled" | "overdue"
export type PaymentStatus = "pending" | "verified" | "rejected" | "refunded"
export type PaymentIntentStatus = "created" | "pending" | "completed" | "failed" | "expired" | "cancelled"
export type OverpaymentStatus = "pending" | "applied" | "refunded" | "cancelled"
export type RefundStatus = "pending" | "approved" | "rejected" | "refunded"
export type TransactionType = "payment" | "refund" | "adjustment" | "waive" | "penalty" | "reversal"
export type ResolutionType = "apply_to_next" | "refund" | "write_off"

// ============================================================================
// INSTALLMENT PLAN (from backend InstallmentPlanResponse)
// ============================================================================
export interface InstallmentScheduleItem {
  installment_no: number
  percent: number // Decimal in backend, but JSON serializes to number
  due_days_offset: number
}

export interface InstallmentPlan {
  id: number
  code: string
  name: string
  description: string | null
  installment_count: number
  schedule: InstallmentScheduleItem[]
  penalty_type: string
  penalty_rate: string // Decimal → string
  grace_period_days: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface InstallmentPlanCreateRequest {
  code: string
  name: string
  description?: string | null
  installment_count: number
  schedule: InstallmentScheduleItem[]
  penalty_type?: string
  penalty_rate?: string
  grace_period_days?: number
  is_active?: boolean
}

export interface InstallmentPlanUpdateRequest {
  name?: string
  description?: string | null
  installment_count?: number
  schedule?: InstallmentScheduleItem[]
  penalty_type?: string
  penalty_rate?: string
  grace_period_days?: number
  is_active?: boolean
}

// ============================================================================
// PAYMENT METHOD (from backend PaymentMethodResponse)
// ============================================================================
export interface PaymentMethod {
  id: number
  code: string
  name: string
  is_online: boolean
  requires_verification: boolean
  gateway_code: string | null
  display_order: number
  is_active: boolean
  created_at: string
  // [TODO_BACKEND] Add: description
}

// ============================================================================
// FEE APPLIED DISCOUNT (from backend FeeAppliedDiscountResponse)
// ============================================================================
export interface FeeAppliedDiscount {
  id: number
  policy_id: number
  policy_name: string
  discount_type: string // Backend has this
  discount_value: string // Decimal → string
  discount_amount: string // Decimal → string
  application_order: number
}

// ============================================================================
// FEE (from backend FeeResponse)
// ============================================================================
export interface Fee {
  id: number
  admission_profile_id: number
  installment_plan_id: number | null
  fee_type: FeeType
  academic_year: string // Format: "2024-2025"
  base_amount: string
  total_discount: string
  final_amount: string
  paid_amount: string
  waived_amount: string
  remaining_amount: string // Computed property
  status: FeeStatus
  notes: string | null
  version: number
  created_at: string
  updated_at: string
  applied_discounts: FeeAppliedDiscount[]
  // Permission flags (computed by backend based on status)
  can_waive: boolean
  can_cancel: boolean
  can_recalculate: boolean
  // Additional metadata
  due_date: string | null // First invoice due date for quick reference
}

export interface FeeSummary {
  id: number
  fee_type: FeeType
  academic_year: string
  semester_no?: number | null
  final_amount: string
  paid_amount: string
  remaining_amount: string
  status: FeeStatus
}

export interface FeeDetail extends Fee {
  invoices: InvoiceSummary[]
  installment_plan: InstallmentPlan | null
  // [TODO_BACKEND] Add: profile nested object for cross-reference
}

// ============================================================================
// INVOICE (from backend InvoiceResponse & InvoiceSummaryResponse)
// ============================================================================
export interface Invoice {
  id: number
  fee_id: number
  invoice_number: string
  installment_no: number
  amount: string
  due_date: string // date in backend, ISO string in JSON
  status: InvoiceStatus
  paid_amount: string
  remaining_amount: string // Computed
  issued_at: string | null
  paid_at: string | null
  cancelled_at: string | null
  created_at: string
  updated_at: string
  // Permission flags (computed by backend based on status)
  can_issue: boolean
  can_cancel: boolean
  can_record_payment: boolean
  can_apply_penalty: boolean
}

export interface InvoiceSummary {
  id: number
  invoice_number: string
  installment_no: number
  amount: string
  paid_amount: string
  remaining_amount: string
  due_date: string
  status: InvoiceStatus
}

export interface InvoiceDetail extends Invoice {
  payments: PaymentSummary[]
  fee: FeeSummary | null
}

// ============================================================================
// PAYMENT INTENT (from backend PaymentIntentResponse)
// ============================================================================
export interface PaymentIntent {
  id: number
  invoice_id: number
  method_id: number
  amount: string
  currency: string
  status: PaymentIntentStatus
  gateway_ref: string | null
  gateway_status: string | null
  pay_url: string | null
  expires_at: string
  created_at: string
  // [TODO_BACKEND] Add: updated_at, completed_at, callback_received_at, callback_data, gateway_response, idempotency_key
}

// ============================================================================
// PAYMENT (from backend PaymentResponse & PaymentSummaryResponse)
// ============================================================================
export interface Payment {
  id: number
  invoice_id: number
  method_id: number
  intent_id: number | null
  amount: string
  status: PaymentStatus
  reference_code: string | null
  payer_name: string | null
  payment_date: string | null
  verified_at: string | null
  rejected_at: string | null
  created_by_id: number
  verified_by_id: number | null
  rejection_reason: string | null
  notes: string | null
  created_at: string
  updated_at: string
  // Permission flags (computed by backend with Maker-Checker enforcement)
  can_verify: boolean
  can_reject: boolean
  // Denormalized user names for display
  created_by_name: string | null
  verified_by_name: string | null
}

export interface PaymentSummary {
  id: number
  invoice_id: number
  amount: string
  status: PaymentStatus
  payment_date: string | null
  created_at: string
  // [TODO_BACKEND] Add: reference_code, method_name (for display)
}

// ============================================================================
// OVERPAYMENT (from backend OverpaymentRecordResponse)
// ============================================================================
export interface OverpaymentRecord {
  id: number
  payment_id: number
  invoice_id: number
  admission_profile_id: number
  overpayment_amount: string
  currency: string
  status: OverpaymentStatus
  resolution_type: ResolutionType | null
  resolved_at: string | null
  resolved_by_id: number | null
  resolution_notes: string | null
  applied_to_invoice_id: number | null
  applied_amount: string | null
  refund_request_id: number | null
  created_at: string
  updated_at: string
  // [TODO_BACKEND] Add permission flag: can_resolve
}

// ============================================================================
// REFUND (from backend RefundRequestResponse)
// ============================================================================
export interface RefundRequest {
  id: number
  payment_id: number
  amount: string
  reason: string
  status: RefundStatus
  requested_at: string
  requested_by_id: number
  approved_at: string | null
  approved_by_id: number | null
  rejected_at: string | null
  rejected_by_id: number | null
  rejection_reason: string | null
  refunded_at: string | null
  refund_reference: string | null
  created_at: string
  updated_at: string
  // [TODO_BACKEND] Add: requested_by_name (denormalized)
  // [TODO_BACKEND] Add permission flags: can_approve, can_reject, can_process
}

// ============================================================================
// ACCOUNTING PERIOD (from backend AccountingPeriodResponse)
// ============================================================================
export interface AccountingPeriod {
  id: number
  month: number // Backend uses 'month', not 'period_month'
  year: number // Backend uses 'year', not 'period_year'
  is_closed: boolean
  closed_at: string | null
  closed_by_id: number | null
  total_payments: string // Decimal → string
  total_refunds: string
  net_revenue: string
  created_at: string
  // [TODO_BACKEND] Add: notes
  // [TODO_BACKEND] Add permission flag: can_close
}

// ============================================================================
// PAYMENT TRANSACTION (from backend PaymentTransactionResponse)
// ============================================================================
export interface PaymentTransaction {
  id: number
  payment_id: number | null
  fee_id: number
  period_id: number | null
  transaction_type: TransactionType
  amount: string
  balance_before: string
  balance_after: string
  external_reference: string | null
  performed_by_id: number | null
  notes: string | null
  created_at: string
  // [TODO_BACKEND] Add: performed_by_name (denormalized), gateway_response, idempotency_key
}

// ============================================================================
// PROFILE FINANCE SUMMARY (from backend ProfileFinanceSummary)
// ⚠️ NOTE: Field names differ from frontend design!
// ============================================================================
export interface ProfileFinanceSummary {
  admission_profile_id: number // Backend uses this, not 'profile_id'
  total_fees: string // Backend uses this, not 'total_amount'
  total_paid: string // Backend uses this, not 'paid_amount'
  total_remaining: string // Backend uses this, not 'remaining_amount'
  fees: FeeSummary[]
  pending_invoices: number
  overdue_invoices: number
  // [TODO_BACKEND] Add: has_fee (boolean), fee_status, overdue_amount, last_payment_date
}

// ============================================================================
// DASHBOARD STATS
// ============================================================================
export interface FinanceDashboardStats {
  pending_fees_count: number
  pending_fees_amount: string
  pending_payments_count: number
  overdue_invoices_count: number
  overdue_amount: string
  today_collections: string
  monthly_collections: string
  period_collections: string
  period_start: string | null
  period_end: string | null
  pending_overpayments_count: number
  pending_refunds_count: number
}

// ============================================================================
// REQUEST TYPES (match backend request schemas)
// ============================================================================

export interface FeeCalculateRequest {
  admission_profile_id: number
  fee_type?: FeeType
  installment_plan_code?: string // defaults to "FULL"
  // PR #7 — semester number for tuition fees. Defaults to 1 (HK1) on the
  // backend when omitted; must stay null/undefined for non-tuition types.
  semester_no?: number | null
}

export interface FeeWaiveRequest {
  waive_amount: string // Decimal as string
  reason: string
}

export interface FeeRecalculateRequest {
  new_base_amount: string // Decimal as string
  reason: string
}

export interface PaymentCreateRequest {
  invoice_id: number
  method_id: number
  amount: string
  payment_date?: string
  reference_code?: string
  payer_name?: string
  payer_account?: string
  notes?: string
}

export interface PaymentIntentCreateRequest {
  invoice_id: number
  method_id: number
  amount: string
  idempotency_key: string
  return_url?: string
}

export interface PaymentVerifyRequest {
  payment_id: number
  approve: boolean
  rejection_reason?: string
}

// [FRONTEND_ONLY] Simplified reject request for form handling
export interface PaymentRejectRequest {
  rejection_reason: string
}

export interface InvoicePenaltyRequest {
  penalty_amount: string
}

export interface OverpaymentApplyRequest {
  overpayment_id: number
  target_invoice_id: number
  amount?: string
  notes?: string
}

export interface OverpaymentRefundRequest {
  overpayment_id: number
  notes?: string
}

export interface OverpaymentWriteOffRequest {
  overpayment_id: number
  reason: string
}

export interface RefundCreateRequest {
  payment_id: number
  amount: string
  reason: string
}

export interface RefundApproveRequest {
  refund_id: number
  approve: boolean
  rejection_reason?: string
}

export interface RefundProcessRequest {
  refund_id: number
  refund_reference: string
}

export interface AccountingPeriodCloseRequest {
  period_id: number
  notes?: string
}

// ============================================================================
// FORM VALUE TYPES (Frontend-only, for React Hook Form)
// ============================================================================
export interface FeeCalculateFormValues {
  profile_search: string
  admission_profile_id: number | null
  fee_type: FeeType
  installment_plan_code: string
}

export interface FeeWaiveFormValues {
  waive_amount: string
  reason: string
}

export interface PaymentRecordFormValues {
  invoice_id: number
  method_id: number | null
  amount: string
  payment_date: string
  reference_code: string
  payer_name: string
  payer_account: string
  notes: string
}

export interface PaymentRejectFormValues {
  rejection_reason: string
}

export interface InvoicePenaltyFormValues {
  penalty_amount: string
}

export interface OnlinePaymentFormValues {
  method_id: number | null
  amount: string
}

// ============================================================================
// MAPPING FUNCTIONS: Form → Request
// ============================================================================
export function toFeeCalculateRequest(form: FeeCalculateFormValues): FeeCalculateRequest {
  return {
    admission_profile_id: form.admission_profile_id!,
    fee_type: form.fee_type,
    installment_plan_code: form.installment_plan_code || undefined,
  }
}

export function toPaymentCreateRequest(form: PaymentRecordFormValues): PaymentCreateRequest {
  return {
    invoice_id: form.invoice_id,
    method_id: form.method_id!,
    amount: form.amount,
    payment_date: form.payment_date || undefined,
    reference_code: form.reference_code || undefined,
    payer_name: form.payer_name || undefined,
    payer_account: form.payer_account || undefined,
    notes: form.notes || undefined,
  }
}

// ============================================================================
// ERROR RESPONSE TYPES
// ============================================================================
export interface FinanceError {
  code: string
  message: string
  field?: string
  details?: Record<string, unknown>
}

export interface FinanceValidationError {
  loc: (string | number)[]
  msg: string
  type: string
}

export const FINANCE_ERROR_CODES = {
  FEE_ALREADY_EXISTS: "FEE_ALREADY_EXISTS",
  FEE_NOT_CALCULABLE: "FEE_NOT_CALCULABLE",
  INVOICE_ALREADY_ISSUED: "INVOICE_ALREADY_ISSUED",
  INVOICE_ALREADY_PAID: "INVOICE_ALREADY_PAID",
  PAYMENT_AMOUNT_EXCEEDS: "PAYMENT_AMOUNT_EXCEEDS",
  PAYMENT_ALREADY_VERIFIED: "PAYMENT_ALREADY_VERIFIED",
  MAKER_CHECKER_VIOLATION: "MAKER_CHECKER_VIOLATION",
  INSUFFICIENT_PERMISSION: "INSUFFICIENT_PERMISSION",
  ACCOUNTING_PERIOD_CLOSED: "ACCOUNTING_PERIOD_CLOSED",
} as const

// ============================================================================
// UI LABELS (Frontend-only display mappings)
// ============================================================================
export const FEE_TYPE_LABELS: Record<FeeType, string> = {
  application: "Lệ phí hồ sơ",
  tuition: "Học phí",
  enrollment: "Phí nhập học",
  insurance: "Bảo hiểm",
  dormitory: "Ký túc xá",
  other: "Khác",
}

export const FEE_STATUS_LABELS: Record<FeeStatus, string> = {
  pending: "Chờ tính phí",
  calculated: "Đã tính phí",
  invoiced: "Đã xuất hóa đơn",
  partial: "Thanh toán một phần",
  paid: "Đã thanh toán",
  overdue: "Quá hạn",
  waived: "Đã miễn giảm",
  cancelled: "Đã hủy",
}

export const FEE_STATUS_VARIANTS: Record<FeeStatus, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "secondary",
  calculated: "outline",
  invoiced: "outline",
  partial: "default",
  paid: "default",
  overdue: "destructive",
  waived: "secondary",
  cancelled: "secondary",
}

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  draft: "Nháp",
  issued: "Đã xuất",
  partial: "Thanh toán một phần",
  paid: "Đã thanh toán",
  cancelled: "Đã hủy",
  overdue: "Quá hạn",
}

export const INVOICE_STATUS_VARIANTS: Record<InvoiceStatus, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "secondary",
  issued: "outline",
  partial: "default",
  paid: "default",
  cancelled: "secondary",
  overdue: "destructive",
}

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  pending: "Chờ xác minh",
  verified: "Đã xác minh",
  rejected: "Từ chối",
  refunded: "Đã hoàn tiền",
}

export const PAYMENT_STATUS_VARIANTS: Record<PaymentStatus, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "secondary",
  verified: "default",
  rejected: "destructive",
  refunded: "outline",
}

export const OVERPAYMENT_STATUS_LABELS: Record<OverpaymentStatus, string> = {
  pending: "Chờ xử lý",
  applied: "Đã áp dụng",
  refunded: "Đã hoàn tiền",
  cancelled: "Đã hủy",
}

export const REFUND_STATUS_LABELS: Record<RefundStatus, string> = {
  pending: "Chờ duyệt",
  approved: "Đã duyệt",
  rejected: "Từ chối",
  refunded: "Đã hoàn tiền",
}

// ============================================================================
// PAGINATION TYPES
// ============================================================================
export interface FeePaginatedResponse {
  items: Fee[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface InvoicePaginatedResponse {
  items: Invoice[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface PaymentPaginatedResponse {
  items: Payment[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ============================================================================
// FILTER TYPES
// ============================================================================
export interface FeeFilters {
  profile_id?: number
  status?: FeeStatus
  fee_type?: FeeType
  academic_year?: string
  page?: number
  page_size?: number
}

export interface InvoiceFilters {
  fee_id?: number
  status?: InvoiceStatus
  overdue_only?: boolean
  page?: number
  page_size?: number
}

export interface PaymentFilters {
  invoice_id?: number
  status?: PaymentStatus
  method_id?: number
  page?: number
  page_size?: number
}
