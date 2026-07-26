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
// Mirrors backend RefundSourceEnum. Only `withdrawal` refunds are auto-rejected
// when a pending withdrawal is cancelled.
export type RefundSource = "withdrawal" | "manual" | "overpayment"
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
  description: string | null
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
  // Đổi ngành có khấu trừ phiếu thu (BE-owned). Optional cho backward-compat
  // trong lúc rollout (cờ BE MAJOR_CHANGE_REPRICE_ENABLED).
  awaiting_accountant_confirmation?: boolean
  can_confirm_major_change?: boolean
  major_change_from_major_name?: string | null
  major_change_to_major_name?: string | null
  major_change_delta_amount?: string | null
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
  // Backend-owned: có ≥1 hóa đơn của khoản phí này còn THU ĐƯỢC (invoice-level,
  // remaining GỒM penalty). Nguồn DUY NHẤT để quyết hiện nút "Mã QR chuyển khoản"
  // — KHÔNG suy luận từ fee.status/remaining ở FE (bỏ sót penalty-only + lệch
  // hóa đơn đợt draft). Mọi builder FeeSummaryResponse serialize (default false).
  has_payable_invoice: boolean
  // Role-aware capability flags (backend-owned, each mirrors its route gate).
  // Optional: only the collection drawer populates them; other FeeSummary
  // sources leave them falsy → no action button (safe default).
  can_waive?: boolean
  can_recalculate?: boolean
  can_cancel?: boolean
  // Current base amount — only the drawer sets it (prefills the "Tính lại"
  // dialog). Absent elsewhere (no recalculate button there).
  base_amount?: string
  // Đổi ngành: cờ để worklist kế toán + drawer đánh dấu "chờ xác nhận".
  awaiting_accountant_confirmation?: boolean
  can_confirm_major_change?: boolean
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
  remaining_amount: string // Computed (includes penalty)
  penalty_amount: string
  total_due: string // Computed (amount + penalty_amount)
  // Backend-owned derived overdue flag (issued/partial AND due_date < today).
  // Single source of truth — FE never recomputes overdue from status/due_date.
  is_overdue?: boolean
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
  // List-only enrichment (present on GET /api/invoices items, absent on detail)
  profile_name?: string | null
  fee_type?: FeeType | null
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

/**
 * InvoiceListItem — the EXACT contract returned by `GET /api/invoices` items
 * (backend `InvoiceListItem(InvoiceSummaryResponse)`). This is a LIST-only type;
 * the detail page keeps using `Invoice`. Reusing the detail `Invoice` type for
 * the list is the root of the "fields always undefined" bug (list never returns
 * penalty/total_due/issued_at, and detail never returns the enrichment below).
 */
export interface InvoiceListItem {
  id: number
  invoice_number: string
  installment_no: number
  amount: string
  paid_amount: string
  remaining_amount: string
  // Penalty accrued on this invoice + total due (amount + penalty). When penalty
  // > 0, `remaining_amount` already includes it, so the row shows `total_due` as
  // the headline figure (otherwise "Còn" would exceed the displayed amount).
  penalty_amount: string
  total_due: string
  due_date: string
  status: InvoiceStatus
  // List enrichment (who + what), batch-safe from lead/offering/program/officer
  fee_id: number
  profile_id: number | null
  profile_name: string | null
  profile_code: string | null
  // Ngành/trình độ từ snapshot Fee.resolved_* (BE-owned, đúng NV admitted).
  program_name: string | null
  degree_level: string | null
  officer_name: string | null
  fee_type: FeeType | null
  semester_no: number | null
  // Backend-owned derived overdue flag (issued/partial AND due_date < today).
  // Single source of truth — FE never recomputes overdue from due_date.
  is_overdue: boolean
  // Permission flags (role-aware, computed by backend)
  can_issue: boolean
  can_cancel: boolean
  can_record_payment: boolean
  can_apply_penalty: boolean
}

/**
 * Status counts for the invoice list tabs (`GET /api/invoices/status-counts`).
 * `counts` is grouped by the enum `Invoice.status`; `overdue_derived` is the
 * DERIVED count (issued/partial AND due<today) used by the "Quá hạn" tab/chip so
 * it always matches the red-spine rows, regardless of the enum `overdue` lag.
 */
export interface InvoiceStatusCounts {
  counts: {
    draft: number
    issued: number
    partial: number
    paid: number
    cancelled: number
    overdue: number
  }
  overdue_derived: number
  /** Count cho tab "Chờ xác nhận đổi ngành" (0 nếu BE chưa trả). */
  awaiting_major_change?: number
  total: number
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

/**
 * Payment row for the workspace payment list / maker-checker queue / drawer
 * (from backend `PaymentListItem`). DISTINCT from the detail `Payment`: the
 * list endpoint returns only these enriched columns, so the queue card reads
 * fields that actually exist (no `undefined` from reading detail-only fields).
 * `is_online` (= intent_id is not None) is backend-owned — never recompute it
 * from a missing `intent_id`. `pages` is NOT returned; derive from total/size.
 */
export interface PaymentListItem {
  id: number
  invoice_id: number
  amount: string
  status: PaymentStatus
  payment_date: string | null
  created_at: string
  // Reconciliation + grain (enriched by backend list builder)
  reference_code: string | null
  payer_name: string | null
  is_online: boolean
  // True when the viewer is the maker (own payment) → queue shows the
  // maker-checker reason rather than a hidden verify button.
  is_own: boolean
  profile_name: string | null
  method_name: string | null
  created_by_name: string | null
  // Người duyệt (checker) + thời điểm duyệt (drawer chi tiết).
  verified_by_name: string | null
  verified_at: string | null
  // Nguồn thu (BE-owned): "online" | "import" | "manual".
  source: PaymentSource
  // Role-aware maker-checker flags (computed by backend)
  can_verify: boolean
  can_reject: boolean
}

/** Nguồn thu của 1 payment (BE-owned, suy ra lúc đọc). */
export type PaymentSource = "online" | "import" | "manual"

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
  can_resolve: boolean
  can_apply: boolean
  can_refund: boolean
  can_write_off: boolean
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
  source: RefundSource
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
  can_approve: boolean
  can_reject: boolean
  can_process: boolean
}

export interface VietQRBankAccount {
  bank_bin: string
  account_number: string
  account_name: string
  bank_name: string
}

export interface VietQRResponse {
  qr_payload: string
  qr_image_base64: string
  bank_account: VietQRBankAccount
  amount: string
  content: string
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
// PROFILE COLLECTION (workspace drawer — from backend ProfileCollectionResponse)
// The three finance tiers for ONE profile. `summary.fees` is the canonical fee
// list (the "Phí" section); `invoices`/`payments` are flat cross-fee
// projections reusing the SAME list-item contracts (NOT detail types).
// ============================================================================
export interface ProfileCollectionIdentity {
  profile_id: number
  profile_code: string
  student_name: string | null
  // CCCD đã che giữa (PII-safe, dùng để HIỂN THỊ). Ngành/trình độ từ snapshot
  // Fee.resolved_*.
  citizen_id_masked: string | null
  // CCCD đầy đủ — CHỈ cho nút copy (kế toán cần để xuất hóa đơn GTGT; lộ PII có
  // chủ đích cho nhân viên tài chính). Hiển thị vẫn dùng bản che bên trên.
  citizen_id_full: string | null
  program_name: string | null
  degree_level: string | null
  officer_name: string | null
  phone: string | null
  // Địa chỉ thường trú đã ghép 1 dòng (BE-owned). Null khi chưa có.
  permanent_address: string | null
}

export interface ProfileCollection {
  identity: ProfileCollectionIdentity
  summary: ProfileFinanceSummary
  invoices: InvoiceListItem[]
  payments: PaymentListItem[]
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
  // Σ invoice.remaining over issued/partial invoices (unit-scoped). Drives the
  // "Còn phải thu" money metric in the collection workspace rail.
  outstanding_total: string
}

export type DebtAgingBucket = "0_30" | "31_60" | "over_60"

export interface DebtReportRow {
  admission_profile_id: number
  profile_code: string
  profile_name: string
  unit_id: number | null
  unit_name: string | null
  academic_year: number
  admission_round_id: number | null
  fee_types: string[]
  invoice_count: number
  total_expected: string
  total_paid: string
  total_outstanding: string
  days_overdue: number
  aging_bucket: DebtAgingBucket
}

export interface DebtReportSummary {
  debtor_count: number
  total_expected: string
  total_paid: string
  total_outstanding: string
  bucket_0_30: string
  bucket_31_60: string
  bucket_over_60: string
}

export interface DebtReportResponse {
  items: DebtReportRow[]
  summary: DebtReportSummary
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
  // Lịch thu "đóng trước" (Pha 1) — GIỮ nguyên tổng học phí, chỉ chia số phải
  // thu thành đợt đầu + phần còn lại (2 hóa đơn). "down_payment" CHỈ cho tuition;
  // cần down_payment + cả 2 hạn (mirror backend validate_collection_schedule).
  // Bỏ hết khi mode "standard" (theo kế hoạch trả góp như cũ).
  collection_schedule_mode?: "standard" | "down_payment"
  down_payment?: string | null // Decimal as string
  down_payment_due?: string | null // YYYY-MM-DD
  remainder_due?: string | null // YYYY-MM-DD
  // Miễn/giảm học phí THẬT (Pha 2) — GIẢM nghĩa vụ. "Học phí áp dụng" = final sau
  // MỌI giảm (Decimal as string). CHỈ tuition + reason ≥10 + quyền
  // admin/manager/accountant (backend enforce 403). Bỏ khi không miễn/giảm.
  target_final_amount?: string | null
  manual_discount_reason?: string | null
  // Ưu đãi theo CHÍNH SÁCH người dùng tích chọn. Phải là tập con của cấu hình
  // ngành (backend từ chối id ngoài tập đó — 400, không lọc im lặng).
  // undefined = không nêu ý kiến ⇒ áp toàn bộ cấu hình; [] = không áp ưu đãi nào.
  discount_policy_ids?: number[]
}

/** Một chính sách ưu đãi đã cấu hình cho ngành của hồ sơ. */
export interface DiscountPolicyOption {
  id: number
  name: string
  discount_type: string
  discount_value: string
  /** Số tiền giảm khi áp MỘT MÌNH trên giá chuẩn học kỳ (Decimal as string). */
  amount: string
  selectable: boolean
  /** Mã lý do không chọn được (máy đọc). */
  reason: string | null
  /** Lý do bằng tiếng Việt để hiển thị. */
  reason_text: string | null
  selected: boolean
}

/** Giá chuẩn học phí (GET /api/fees/tuition-preview) — Decimal as string. */
export interface TuitionPreviewResponse {
  base_amount: string
  total_discount: string
  final_amount: string
  semester_no: number
  /** Ưu đãi đã cấu hình cho ngành — nguồn DUY NHẤT cho ô tích của dialog. */
  discount_policies: DiscountPolicyOption[]
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
  reason: string // bắt buộc — backend route apply-penalty yêu cầu lý do
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

/**
 * Trạng thái hóa đơn "còn thu được" (đã phát hành, chưa tất toán/hủy) — mirror
 * backend PAYABLE_INVOICE_STATUSES. Chỉ các trạng thái này mới ghi nhận thanh
 * toán / sinh được VietQR. Nguồn DUY NHẤT cho mọi nơi FE lọc hóa đơn payable
 * (thay vì mỗi chỗ khai báo lại một literal set).
 */
export const PAYABLE_INVOICE_STATUSES: readonly InvoiceStatus[] = [
  "issued",
  "partial",
  "overdue",
]

/** Hóa đơn còn phải thu: đã phát hành (issued/partial/overdue) VÀ còn dư nợ > 0. */
export function isInvoicePayable(
  invoice: Pick<Invoice, "status" | "remaining_amount">,
): boolean {
  return (
    PAYABLE_INVOICE_STATUSES.includes(invoice.status) &&
    parseFloat(invoice.remaining_amount) > 0
  )
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
  items: InvoiceListItem[]
  total: number
  page: number
  page_size: number
  // NOTE: backend `InvoicesPage` does NOT return `pages`. Pagination derives
  // total pages from total/page_size (see common Pagination component).
}

export interface PaymentPaginatedResponse {
  items: Payment[]
  total: number
  page: number
  page_size: number
  pages: number
}

/**
 * Paginated payment LIST response (`PaymentListItem` rows). The backend does
 * NOT return `pages` — derive it from `Math.ceil(total / page_size)`.
 */
export interface PaymentListPaginatedResponse {
  items: PaymentListItem[]
  total: number
  page: number
  page_size: number
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

/**
 * Filter ngành/trình độ/năm-HK/TVV/đơn vị/hạn — BE đọc Fee.resolved_* (snapshot)
 * cho ngành/trình độ. PHẢI đồng bộ với InvoiceStatusCountFilters để badge tab khớp.
 */
export interface InvoiceWorkspaceFilters {
  major_id?: number
  /** Trình độ: TEXT name khớp Fee.resolved_degree_level (vd "Cao đẳng"). */
  degree_level?: string
  academic_year?: number
  semester_no?: number
  officer_id?: number
  /** Đơn vị: INTERSECT với scope IDOR (officer vẫn bị clamp). */
  unit_id?: number
  /** Hạn thanh toán: "due_soon_7d" (đến hạn ≤7 ngày, chưa thu) | "overdue". */
  due_window?: "due_soon_7d" | "overdue"
}

export interface InvoiceFilters extends InvoiceWorkspaceFilters {
  page?: number
  page_size?: number
  /** Comma-separated status enum values (e.g. "issued,partial"). */
  status?: string
  fee_id?: number
  /** Deep-link scope: only invoices of this admission profile (TuitionTab). */
  profile_id?: number
  fee_type?: FeeType
  /** Derived overdue (issued/partial/overdue AND due<today). Use for "Quá hạn" tab. */
  overdue_only?: boolean
  /** Lens "Chờ xác nhận đổi ngành" (cờ trên khoản phí cha). */
  awaiting_major_change?: boolean
  search?: string
  sort_by?:
    | "priority"
    | "due_date"
    | "amount"
    | "paid"
    | "remaining"
    | "status"
    | "created_at"
  sort_order?: "asc" | "desc"
}

/**
 * Query params for `GET /api/invoices/status-counts`. PARITY: mọi filter
 * workspace (ngành/trình độ/năm-HK/TVV/đơn vị/hạn) phải có Ở ĐÂY y hệt list,
 * nếu không badge tab đếm lệch.
 */
export interface InvoiceStatusCountFilters extends InvoiceWorkspaceFilters {
  fee_id?: number
  profile_id?: number
  fee_type?: FeeType
  search?: string
}

export interface PaymentFilters {
  invoice_id?: number
  status?: PaymentStatus
  method_id?: number
  page?: number
  page_size?: number
  // Maker-checker queue: manual payments (intent_id IS NULL) awaiting
  // verification. When true the backend ignores status/method_id. Online
  // (auto-verified) payments never appear here.
  pending_manual_only?: boolean
}

export interface DebtReportFilters {
  unit_id?: number
  academic_year?: number
  round_id?: number
  fee_type?: FeeType
  aging?: DebtAgingBucket
}

export interface RefundFilters {
  payment_id?: number
  status?: RefundStatus
  page?: number
  page_size?: number
}

export interface OverpaymentFilters {
  profile_id?: number
  status?: OverpaymentStatus
  page?: number
  page_size?: number
}
