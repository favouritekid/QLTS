/**
 * Zod Validation Schemas for Finance Module
 * Version: 3.0 - FULLY ALIGNED WITH BACKEND (includes can_* permission flags)
 *
 * ⚠️ IMPORTANT: These schemas MUST mirror Backend Pydantic schemas exactly.
 *
 * Mirrors Backend Pydantic schemas for type safety and validation.
 * Used with React Hook Form via @hookform/resolvers/zod
 *
 * Backend schemas: Backend_FastAPI/app/schemas/finance.py
 * Last sync: 2026-02-03
 */

import { z } from "zod"

// ==============================================================================
// ENUMS (match backend exactly)
// ==============================================================================

export const feeTypeSchema = z.enum([
  "application",
  "tuition",
  "enrollment",
  "insurance",
  "dormitory",
  "other",
])

export const feeStatusSchema = z.enum([
  "pending",
  "calculated",
  "invoiced",
  "partial",
  "paid",
  "overdue",
  "waived",
  "cancelled",
])

export const invoiceStatusSchema = z.enum([
  "draft",
  "issued",
  "partial",
  "paid",
  "cancelled",
  "overdue",
])

export const paymentStatusSchema = z.enum([
  "pending",
  "verified",
  "rejected",
  "refunded",
])

export const paymentIntentStatusSchema = z.enum([
  "created",
  "pending",
  "completed",
  "failed",
  "expired",
  "cancelled",
])

export const overpaymentStatusSchema = z.enum([
  "pending",
  "applied",
  "refunded",
  "cancelled",
])

export const refundStatusSchema = z.enum([
  "pending",
  "approved",
  "rejected",
  "refunded",
])

// Origin of a refund — mirrors backend RefundSourceEnum. Only `withdrawal`
// refunds are auto-rejected when a pending withdrawal is cancelled.
export const refundSourceSchema = z.enum([
  "withdrawal",
  "manual",
  "overpayment",
])

export const transactionTypeSchema = z.enum([
  "payment",
  "refund",
  "adjustment",
  "waive",
  "penalty",
  "reversal",
])

export const resolutionTypeSchema = z.enum([
  "apply_to_next",
  "refund",
  "write_off",
])

// ==============================================================================
// HELPERS
// ==============================================================================

/**
 * VND amount string validation
 * Backend returns Decimal as string to preserve precision
 */
const amountString = () =>
  z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, "Số tiền không hợp lệ")

/**
 * Academic year format validation (e.g., "2024-2025")
 */
const academicYearSchema = z
  .string()
  .regex(/^\d{4}-\d{4}$/, "Năm học phải có định dạng YYYY-YYYY")

// ==============================================================================
// INSTALLMENT PLAN (from backend InstallmentPlanResponse)
// ==============================================================================

export const installmentScheduleItemSchema = z.object({
  installment_no: z.number().int().positive(),
  percent: z.number().min(0).max(100), // Decimal in backend, number in JSON
  due_days_offset: z.number().int().min(0),
})

export type InstallmentScheduleItem = z.infer<typeof installmentScheduleItemSchema>

export const installmentPlanSchema = z.object({
  id: z.number().int().positive(),
  code: z.string().min(1).max(50),
  name: z.string().min(1).max(255),
  installment_count: z.number().int().positive(),
  schedule: z.array(installmentScheduleItemSchema),
  penalty_rate: z.string(), // Decimal → string
  is_active: z.boolean(),
  created_at: z.string(),
})

export type InstallmentPlan = z.infer<typeof installmentPlanSchema>

// ==============================================================================
// PAYMENT METHOD (from backend PaymentMethodResponse)
// ==============================================================================

export const paymentMethodSchema = z.object({
  id: z.number().int().positive(),
  code: z.string().min(1).max(50),
  name: z.string().min(1).max(255),
  is_online: z.boolean(),
  requires_verification: z.boolean(),
  gateway_code: z.string().nullable(), // vnpay | momo | zalopay | null
  display_order: z.number().int().min(0),
  is_active: z.boolean(),
  created_at: z.string(),
  description: z.string().nullable(),
})

export type PaymentMethod = z.infer<typeof paymentMethodSchema>

// ==============================================================================
// FEE APPLIED DISCOUNT (from backend FeeAppliedDiscountResponse)
// ==============================================================================

export const feeAppliedDiscountSchema = z.object({
  id: z.number().int().positive(),
  policy_id: z.number().int().positive(),
  policy_name: z.string(),
  discount_type: z.string(),
  discount_value: z.string(), // Decimal → string
  discount_amount: z.string(), // Decimal → string
  application_order: z.number().int().min(0),
})

export type FeeAppliedDiscount = z.infer<typeof feeAppliedDiscountSchema>

// ==============================================================================
// FEE RESPONSE SCHEMAS (from backend FeeResponse)
// ==============================================================================

export const feeSchema = z.object({
  id: z.number().int().positive(),
  admission_profile_id: z.number().int().positive(),
  installment_plan_id: z.number().int().positive().nullable(),
  fee_type: feeTypeSchema,
  academic_year: academicYearSchema,
  base_amount: z.string(),
  total_discount: z.string(),
  final_amount: z.string(),
  paid_amount: z.string(),
  waived_amount: z.string(),
  remaining_amount: z.string(), // Computed property
  status: feeStatusSchema,
  notes: z.string().nullable(),
  version: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
  applied_discounts: z.array(feeAppliedDiscountSchema),
  // Permission flags (computed by backend based on status)
  can_waive: z.boolean(),
  can_cancel: z.boolean(),
  can_recalculate: z.boolean(),
  // Additional metadata
  due_date: z.string().nullable(), // First invoice due date for quick reference
})

export type Fee = z.infer<typeof feeSchema>

// Fee summary for use in InvoiceDetail
export const feeSummarySchema = z.object({
  id: z.number().int().positive(),
  fee_type: feeTypeSchema,
  academic_year: z.string(),
  semester_no: z.number().int().positive().nullable().optional(),
  final_amount: z.string(),
  paid_amount: z.string(),
  remaining_amount: z.string(),
  status: feeStatusSchema,
  // BE-owned: khoản phí có hóa đơn còn thu được (invoice-level, gồm penalty).
  has_payable_invoice: z.boolean(),
})

export type FeeSummary = z.infer<typeof feeSummarySchema>

// Invoice summary for FeeDetail
export const invoiceSummarySchema = z.object({
  id: z.number().int().positive(),
  invoice_number: z.string(),
  installment_no: z.number().int().positive(),
  amount: z.string(),
  paid_amount: z.string(),
  remaining_amount: z.string(),
  due_date: z.string(),
  status: invoiceStatusSchema,
})

export type InvoiceSummary = z.infer<typeof invoiceSummarySchema>

export const feeDetailSchema = feeSchema.extend({
  invoices: z.array(invoiceSummarySchema),
  installment_plan: installmentPlanSchema.nullable(),
  // [TODO_BACKEND] Add: profile nested object for cross-reference
})

export type FeeDetail = z.infer<typeof feeDetailSchema>

// ==============================================================================
// INVOICE RESPONSE SCHEMAS (from backend InvoiceResponse)
// ==============================================================================

export const invoiceSchema = z.object({
  id: z.number().int().positive(),
  fee_id: z.number().int().positive(),
  invoice_number: z.string(),
  installment_no: z.number().int().positive(),
  amount: z.string(),
  due_date: z.string(), // date in backend, ISO string in JSON
  status: invoiceStatusSchema,
  paid_amount: z.string(),
  remaining_amount: z.string(), // Computed (includes penalty)
  penalty_amount: z.string(),
  total_due: z.string(), // Computed (amount + penalty_amount)
  issued_at: z.string().nullable(),
  paid_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  // Permission flags (computed by backend based on status)
  can_issue: z.boolean(),
  can_cancel: z.boolean(),
  can_record_payment: z.boolean(),
  can_apply_penalty: z.boolean(),
})

export type Invoice = z.infer<typeof invoiceSchema>

// Payment summary for InvoiceDetail
export const paymentSummarySchema = z.object({
  id: z.number().int().positive(),
  invoice_id: z.number().int().positive(),
  amount: z.string(),
  status: paymentStatusSchema,
  payment_date: z.string().nullable(),
  created_at: z.string(),
  // [TODO_BACKEND] Add: reference_code, method_name (for display)
})

export type PaymentSummary = z.infer<typeof paymentSummarySchema>

export const invoiceDetailSchema = invoiceSchema.extend({
  payments: z.array(paymentSummarySchema),
  fee: feeSummarySchema.nullable(),
})

export type InvoiceDetail = z.infer<typeof invoiceDetailSchema>

// ==============================================================================
// PAYMENT INTENT RESPONSE SCHEMAS (from backend PaymentIntentResponse)
// ==============================================================================

export const paymentIntentSchema = z.object({
  id: z.number().int().positive(),
  invoice_id: z.number().int().positive(),
  method_id: z.number().int().positive(),
  amount: z.string(),
  currency: z.string().default("VND"),
  status: paymentIntentStatusSchema,
  gateway_ref: z.string().nullable(),
  gateway_status: z.string().nullable(),
  pay_url: z.string().nullable(), // URL to redirect for online payment
  expires_at: z.string(),
  created_at: z.string(),
  // [TODO_BACKEND] Add: updated_at, completed_at, callback_received_at, callback_data, gateway_response, idempotency_key
})

export type PaymentIntent = z.infer<typeof paymentIntentSchema>

// ==============================================================================
// PAYMENT RESPONSE SCHEMAS (from backend PaymentResponse)
// ==============================================================================

export const paymentSchema = z.object({
  id: z.number().int().positive(),
  invoice_id: z.number().int().positive(),
  method_id: z.number().int().positive(),
  intent_id: z.number().int().positive().nullable(),
  amount: z.string(),
  status: paymentStatusSchema,
  reference_code: z.string().nullable(),
  payer_name: z.string().nullable(),
  payment_date: z.string().nullable(),
  verified_at: z.string().nullable(),
  rejected_at: z.string().nullable(),
  created_by_id: z.number().int().positive(),
  verified_by_id: z.number().int().positive().nullable(),
  rejection_reason: z.string().nullable(),
  notes: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  // Permission flags (computed by backend with Maker-Checker enforcement)
  can_verify: z.boolean(),
  can_reject: z.boolean(),
  // Denormalized user names for display
  created_by_name: z.string().nullable(),
  verified_by_name: z.string().nullable(),
})

export type Payment = z.infer<typeof paymentSchema>

// ==============================================================================
// OVERPAYMENT RESPONSE SCHEMAS (from backend OverpaymentRecordResponse)
// ==============================================================================

export const overpaymentRecordSchema = z.object({
  id: z.number().int().positive(),
  payment_id: z.number().int().positive(),
  invoice_id: z.number().int().positive(),
  admission_profile_id: z.number().int().positive(),
  overpayment_amount: z.string(),
  currency: z.string().default("VND"),
  status: overpaymentStatusSchema,
  resolution_type: resolutionTypeSchema.nullable(),
  resolved_at: z.string().nullable(),
  resolved_by_id: z.number().int().positive().nullable(),
  resolution_notes: z.string().nullable(),
  applied_to_invoice_id: z.number().int().positive().nullable(),
  applied_amount: z.string().nullable(),
  refund_request_id: z.number().int().positive().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  can_resolve: z.boolean(),
  can_apply: z.boolean(),
  can_refund: z.boolean(),
  can_write_off: z.boolean(),
})

export type OverpaymentRecord = z.infer<typeof overpaymentRecordSchema>

// ==============================================================================
// REFUND RESPONSE SCHEMAS (from backend RefundRequestResponse)
// ==============================================================================

export const refundRequestSchema = z.object({
  id: z.number().int().positive(),
  payment_id: z.number().int().positive(),
  amount: z.string(),
  reason: z.string(),
  status: refundStatusSchema,
  source: refundSourceSchema,
  requested_at: z.string(),
  requested_by_id: z.number().int().positive(),
  approved_at: z.string().nullable(),
  approved_by_id: z.number().int().positive().nullable(),
  rejected_at: z.string().nullable(),
  rejected_by_id: z.number().int().positive().nullable(),
  rejection_reason: z.string().nullable(),
  refunded_at: z.string().nullable(),
  refund_reference: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  can_approve: z.boolean(),
  can_reject: z.boolean(),
  can_process: z.boolean(),
})

export type RefundRequest = z.infer<typeof refundRequestSchema>

export const vietQRResponseSchema = z.object({
  qr_payload: z.string(),
  qr_image_base64: z.string(),
  bank_account: z.object({
    bank_bin: z.string(),
    account_number: z.string(),
    account_name: z.string(),
    bank_name: z.string(),
  }),
  amount: z.string(),
  content: z.string(),
})

export const debtAgingBucketSchema = z.enum(["0_30", "31_60", "over_60"])

export const debtReportRowSchema = z.object({
  admission_profile_id: z.number().int().positive(),
  profile_code: z.string(),
  profile_name: z.string(),
  unit_id: z.number().int().positive().nullable(),
  unit_name: z.string().nullable(),
  academic_year: z.number().int(),
  admission_round_id: z.number().int().positive().nullable(),
  fee_types: z.array(z.string()),
  invoice_count: z.number().int().min(0),
  total_expected: z.string(),
  total_paid: z.string(),
  total_outstanding: z.string(),
  days_overdue: z.number().int().min(0),
  aging_bucket: debtAgingBucketSchema,
})

export const debtReportResponseSchema = z.object({
  items: z.array(debtReportRowSchema),
  summary: z.object({
    debtor_count: z.number().int().min(0),
    total_expected: z.string(),
    total_paid: z.string(),
    total_outstanding: z.string(),
    bucket_0_30: z.string(),
    bucket_31_60: z.string(),
    bucket_over_60: z.string(),
  }),
})

// ==============================================================================
// ACCOUNTING PERIOD RESPONSE SCHEMAS (from backend AccountingPeriodResponse)
// ==============================================================================

export const accountingPeriodSchema = z.object({
  id: z.number().int().positive(),
  month: z.number().int().min(1).max(12), // Backend uses 'month', not 'period_month'
  year: z.number().int().min(2000).max(2100), // Backend uses 'year', not 'period_year'
  is_closed: z.boolean(),
  closed_at: z.string().nullable(),
  closed_by_id: z.number().int().positive().nullable(),
  total_payments: z.string(), // Decimal → string
  total_refunds: z.string(),
  net_revenue: z.string(),
  created_at: z.string(),
  // [TODO_BACKEND] Add: notes
  // [TODO_BACKEND] Add permission flag: can_close
})

export type AccountingPeriod = z.infer<typeof accountingPeriodSchema>

// ==============================================================================
// PAYMENT TRANSACTION (from backend PaymentTransactionResponse)
// ==============================================================================

export const paymentTransactionSchema = z.object({
  id: z.number().int().positive(),
  payment_id: z.number().int().positive().nullable(),
  fee_id: z.number().int().positive(),
  period_id: z.number().int().positive().nullable(),
  transaction_type: transactionTypeSchema,
  amount: z.string(),
  balance_before: z.string(),
  balance_after: z.string(),
  external_reference: z.string().nullable(),
  performed_by_id: z.number().int().positive().nullable(),
  notes: z.string().nullable(),
  created_at: z.string(),
  // [TODO_BACKEND] Add: performed_by_name (denormalized), gateway_response, idempotency_key
})

export type PaymentTransaction = z.infer<typeof paymentTransactionSchema>

// ==============================================================================
// PROFILE FINANCE SUMMARY (from backend ProfileFinanceSummary)
// ⚠️ NOTE: Field names must match backend exactly!
// ==============================================================================

export const profileFinanceSummarySchema = z.object({
  admission_profile_id: z.number().int().positive(), // Backend uses this, not 'profile_id'
  total_fees: z.string(), // Backend uses this, not 'total_amount'
  total_paid: z.string(), // Backend uses this, not 'paid_amount'
  total_remaining: z.string(), // Backend uses this, not 'remaining_amount'
  fees: z.array(feeSummarySchema),
  pending_invoices: z.number().int().min(0),
  overdue_invoices: z.number().int().min(0),
  // [TODO_BACKEND] Add: has_fee (boolean), fee_status, overdue_amount, last_payment_date
})

export type ProfileFinanceSummary = z.infer<typeof profileFinanceSummarySchema>

// ==============================================================================
// DASHBOARD STATS
// ==============================================================================

export const financeDashboardStatsSchema = z.object({
  pending_fees_count: z.number().int().min(0),
  pending_fees_amount: z.string(),
  pending_payments_count: z.number().int().min(0),
  overdue_invoices_count: z.number().int().min(0),
  overdue_amount: z.string(),
  today_collections: z.string(),
  monthly_collections: z.string(),
  period_collections: z.string(),
  period_start: z.string().nullable().optional(),
  period_end: z.string().nullable().optional(),
  pending_overpayments_count: z.number().int().min(0),
  pending_refunds_count: z.number().int().min(0),
})

export type FinanceDashboardStats = z.infer<typeof financeDashboardStatsSchema>

// ==============================================================================
// PAGINATION RESPONSE SCHEMAS
// ==============================================================================

export const feePaginatedResponseSchema = z.object({
  items: z.array(feeSchema),
  total: z.number().int().min(0),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  pages: z.number().int().min(0),
})

export type FeePaginatedResponse = z.infer<typeof feePaginatedResponseSchema>

export const invoicePaginatedResponseSchema = z.object({
  items: z.array(invoiceSchema),
  total: z.number().int().min(0),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  pages: z.number().int().min(0),
})

export type InvoicePaginatedResponse = z.infer<typeof invoicePaginatedResponseSchema>

export const paymentPaginatedResponseSchema = z.object({
  items: z.array(paymentSchema),
  total: z.number().int().min(0),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  pages: z.number().int().min(0),
})

export type PaymentPaginatedResponse = z.infer<typeof paymentPaginatedResponseSchema>

// ==============================================================================
// REQUEST SCHEMAS (for API calls - match backend request schemas)
// ==============================================================================

export const feeCalculateRequestSchema = z
  .object({
    admission_profile_id: z.number().int().positive("Vui lòng chọn hồ sơ"),
    fee_type: feeTypeSchema.optional(),
    installment_plan_code: z.string().optional(), // defaults to "FULL"
    // PR #7 — HK number for tuition. Optional + nullable mirrors the backend
    // contract (defaults to 1 when omitted for tuition; must be null/unset
    // for non-tuition types). max(12) mirrors backend FeeCalculateRequest
    // (Field le=12) — chặn HK ngoài int32.
    semester_no: z.number().int().positive().max(12).nullable().optional(),
    // Lịch thu "đóng trước" (Pha 1) — GIỮ tổng học phí, chỉ chia 2 đợt. Mirror
    // backend validate_collection_schedule. down_payment là Decimal-as-string;
    // các hạn là chuỗi ISO YYYY-MM-DD.
    collection_schedule_mode: z.enum(["standard", "down_payment"]).optional(),
    down_payment: z
      .string()
      .regex(/^\d+(\.\d{1,2})?$/, "Số đóng trước không hợp lệ")
      .nullable()
      .optional(),
    down_payment_due: z.string().nullable().optional(),
    remainder_due: z.string().nullable().optional(),
    // Miễn/giảm học phí THẬT (Pha 2) — "Học phí áp dụng" = final sau MỌI giảm
    // (Decimal-as-string). Mirror backend validate_manual_tuition.
    target_final_amount: z
      .string()
      .regex(/^\d+(\.\d{1,2})?$/, "Học phí áp dụng không hợp lệ")
      .nullable()
      .optional(),
    manual_discount_reason: z
      .string()
      .max(500, "Lý do không được quá 500 ký tự")
      .nullable()
      .optional(),
  })
  // Mirror backend validate_collection_schedule: mode="down_payment" ⟹
  // fee_type=tuition + đủ số đóng trước & 2 hạn + hạn đợt 2 >= đợt 1.
  .refine(
    (d) =>
      d.collection_schedule_mode !== "down_payment" ||
      (d.fee_type ?? "tuition") === "tuition",
    {
      message: "Lịch 'đóng trước' chỉ áp dụng cho học phí",
      path: ["collection_schedule_mode"],
    }
  )
  .refine(
    (d) =>
      d.collection_schedule_mode !== "down_payment" ||
      (d.down_payment != null && !!d.down_payment_due && !!d.remainder_due),
    {
      message: "Lịch 'đóng trước' cần số đóng trước và hạn cả hai đợt",
      path: ["down_payment"],
    }
  )
  .refine(
    (d) =>
      d.collection_schedule_mode !== "down_payment" ||
      !d.down_payment_due ||
      !d.remainder_due ||
      d.remainder_due >= d.down_payment_due,
    {
      message: "Hạn phần còn lại phải >= hạn đợt đầu",
      path: ["remainder_due"],
    }
  )
  // Mirror backend validate_manual_tuition: có target ⟹ tuition + reason ≥10;
  // có reason ⟹ phải có target. (target < mức nền kiểm ở service — cần canonical.)
  .refine(
    (d) =>
      d.target_final_amount == null || (d.fee_type ?? "tuition") === "tuition",
    {
      message: "Miễn/giảm học phí chỉ áp dụng cho học phí",
      path: ["target_final_amount"],
    }
  )
  .refine(
    (d) =>
      d.target_final_amount == null ||
      (!!d.manual_discount_reason && d.manual_discount_reason.trim().length >= 10),
    {
      message: "Cần lý do miễn/giảm học phí (tối thiểu 10 ký tự)",
      path: ["manual_discount_reason"],
    }
  )
  .refine((d) => !d.manual_discount_reason || d.target_final_amount != null, {
    message: "Có lý do miễn/giảm nhưng thiếu mức học phí áp dụng",
    path: ["target_final_amount"],
  })

export type FeeCalculateRequest = z.infer<typeof feeCalculateRequestSchema>

export const feeWaiveRequestSchema = z.object({
  waive_amount: z
    .string()
    .min(1, "Vui lòng nhập số tiền miễn giảm")
    .regex(/^\d+(\.\d{1,2})?$/, "Số tiền không hợp lệ"),
  reason: z
    .string()
    .min(10, "Lý do miễn giảm phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type FeeWaiveRequest = z.infer<typeof feeWaiveRequestSchema>

export const feeRecalculateRequestSchema = z.object({
  new_base_amount: z
    .string()
    .min(1, "Vui lòng nhập mức phí gốc mới")
    .regex(/^\d+(\.\d{1,2})?$/, "Mức phí gốc không hợp lệ"),
  reason: z
    .string()
    .min(10, "Lý do tính lại phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type FeeRecalculateRequest = z.infer<typeof feeRecalculateRequestSchema>

export const paymentCreateRequestSchema = z.object({
  invoice_id: z.number().int().positive(),
  method_id: z.number().int().positive("Vui lòng chọn phương thức thanh toán"),
  amount: z
    .string()
    .min(1, "Vui lòng nhập số tiền")
    .regex(/^\d+(\.\d{1,2})?$/, "Số tiền không hợp lệ"),
  payment_date: z.string().optional(),
  reference_code: z.string().max(100).optional(),
  payer_name: z.string().max(255).optional(),
  payer_account: z.string().max(100).optional(),
  notes: z.string().max(500).optional(),
})

export type PaymentCreateRequest = z.infer<typeof paymentCreateRequestSchema>

export const paymentIntentCreateRequestSchema = z.object({
  invoice_id: z.number().int().positive(),
  method_id: z.number().int().positive("Vui lòng chọn phương thức thanh toán"),
  amount: z
    .string()
    .min(1, "Vui lòng nhập số tiền")
    .regex(/^\d+(\.\d{1,2})?$/, "Số tiền không hợp lệ"),
  idempotency_key: z.string().uuid("Idempotency key không hợp lệ"),
  return_url: z.string().url().optional(),
})

export type PaymentIntentCreateRequest = z.infer<typeof paymentIntentCreateRequestSchema>

// Backend exposes separate verify/reject actions.
// Frontend maps the reject form payload to the backend query param in the API client.
export const paymentRejectRequestSchema = z.object({
  rejection_reason: z
    .string()
    .min(10, "Lý do từ chối phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type PaymentRejectRequest = z.infer<typeof paymentRejectRequestSchema>

export const invoiceCancelRequestSchema = z.object({
  reason: z
    .string()
    .min(10, "Lý do hủy phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type InvoiceCancelRequest = z.infer<typeof invoiceCancelRequestSchema>

export const invoicePenaltyRequestSchema = z.object({
  penalty_amount: z
    .string()
    .min(1, "Vui lòng nhập số tiền phạt")
    .regex(/^\d+(\.\d{1,2})?$/, "Số tiền không hợp lệ"),
  // Backend route apply-penalty yêu cầu reason (1..500) — mirror để không lệch.
  reason: z
    .string()
    .trim()
    .min(1, "Vui lòng nhập lý do áp phạt")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type InvoicePenaltyRequest = z.infer<typeof invoicePenaltyRequestSchema>

export const overpaymentApplyRequestSchema = z.object({
  overpayment_id: z.number().int().positive(),
  target_invoice_id: z.number().int().positive(),
  amount: z.string().optional(),
  notes: z.string().max(500).optional(),
})

export type OverpaymentApplyRequest = z.infer<typeof overpaymentApplyRequestSchema>

export const overpaymentRefundRequestSchema = z.object({
  overpayment_id: z.number().int().positive(),
  notes: z.string().max(500).optional(),
})

export type OverpaymentRefundRequest = z.infer<typeof overpaymentRefundRequestSchema>

export const overpaymentWriteOffRequestSchema = z.object({
  overpayment_id: z.number().int().positive(),
  reason: z
    .string()
    .min(10, "Lý do ghi giảm phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type OverpaymentWriteOffRequest = z.infer<typeof overpaymentWriteOffRequestSchema>

export const refundCreateRequestSchema = z.object({
  payment_id: z.number().int().positive(),
  amount: z
    .string()
    .min(1, "Vui lòng nhập số tiền hoàn")
    .regex(/^\d+(\.\d{1,2})?$/, "Số tiền không hợp lệ"),
  reason: z
    .string()
    .min(10, "Lý do hoàn tiền phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

export type RefundCreateRequest = z.infer<typeof refundCreateRequestSchema>

export const refundApproveRequestSchema = z.object({
  refund_id: z.number().int().positive(),
  approve: z.boolean(),
  rejection_reason: z.string().max(500).optional(),
})

export type RefundApproveRequest = z.infer<typeof refundApproveRequestSchema>

export const refundProcessRequestSchema = z.object({
  refund_id: z.number().int().positive(),
  refund_reference: z.string().min(1, "Vui lòng nhập mã tham chiếu hoàn tiền"),
})

export type RefundProcessRequest = z.infer<typeof refundProcessRequestSchema>

export const accountingPeriodCloseRequestSchema = z.object({
  period_id: z.number().int().positive(),
  notes: z.string().max(500).optional(),
})

export type AccountingPeriodCloseRequest = z.infer<typeof accountingPeriodCloseRequestSchema>

// ==============================================================================
// FORM SCHEMAS (for React Hook Form)
// Frontend-only, separate from Request Types
// ==============================================================================

export const feeCalculateFormSchema = z.object({
  profile_search: z.string().default(""),
  admission_profile_id: z.number().int().positive().nullable(),
  fee_type: feeTypeSchema.default("tuition"),
  installment_plan_code: z.string().default(""),
})

export type FeeCalculateFormValues = z.infer<typeof feeCalculateFormSchema>

export const feeWaiveFormSchema = z.object({
  waive_amount: z.string().min(1, "Vui lòng nhập số tiền miễn giảm"),
  reason: z.string().min(10, "Lý do miễn giảm phải có ít nhất 10 ký tự"),
})

export type FeeWaiveFormValues = z.infer<typeof feeWaiveFormSchema>

export const paymentRecordFormSchema = z.object({
  invoice_id: z.number().int().positive(),
  method_id: z.number().int().positive().nullable(),
  amount: z.string().min(1, "Vui lòng nhập số tiền"),
  payment_date: z.string().default(""),
  reference_code: z.string().default(""),
  payer_name: z.string().default(""),
  payer_account: z.string().default(""),
  notes: z.string().default(""),
})

export type PaymentRecordFormValues = z.infer<typeof paymentRecordFormSchema>

export const paymentRejectFormSchema = z.object({
  rejection_reason: z.string().min(10, "Lý do từ chối phải có ít nhất 10 ký tự"),
})

export type PaymentRejectFormValues = z.infer<typeof paymentRejectFormSchema>

export const invoicePenaltyFormSchema = z.object({
  penalty_amount: z.string().min(1, "Vui lòng nhập số tiền phạt"),
})

export type InvoicePenaltyFormValues = z.infer<typeof invoicePenaltyFormSchema>

export const onlinePaymentFormSchema = z.object({
  method_id: z.number().int().positive().nullable(),
  amount: z.string().min(1, "Vui lòng nhập số tiền"),
})

export type OnlinePaymentFormValues = z.infer<typeof onlinePaymentFormSchema>

export const overpaymentResolveFormSchema = z.object({
  resolution_type: resolutionTypeSchema.nullable(),
  target_invoice_id: z.number().int().positive().nullable(),
  notes: z.string().default(""),
})

export type OverpaymentResolveFormValues = z.infer<typeof overpaymentResolveFormSchema>

export const refundCreateFormSchema = z.object({
  payment_id: z.number().int().positive(),
  amount: z.string().min(1, "Vui lòng nhập số tiền hoàn"),
  reason: z.string().min(10, "Lý do hoàn tiền phải có ít nhất 10 ký tự"),
})

export type RefundCreateFormValues = z.infer<typeof refundCreateFormSchema>

// ==============================================================================
// FILTER SCHEMAS (for query parameters)
// ==============================================================================

export const feeFiltersSchema = z.object({
  profile_id: z.number().int().positive().optional(),
  status: feeStatusSchema.optional(),
  fee_type: feeTypeSchema.optional(),
  academic_year: academicYearSchema.optional(),
  page: z.number().int().positive().optional().default(1),
  page_size: z.number().int().positive().max(100).optional().default(20),
})

export type FeeFilters = z.infer<typeof feeFiltersSchema>

export const invoiceFiltersSchema = z.object({
  fee_id: z.number().int().positive().optional(),
  status: invoiceStatusSchema.optional(),
  overdue_only: z.boolean().optional(),
  page: z.number().int().positive().optional().default(1),
  page_size: z.number().int().positive().max(100).optional().default(20),
})

export type InvoiceFilters = z.infer<typeof invoiceFiltersSchema>

export const paymentFiltersSchema = z.object({
  invoice_id: z.number().int().positive().optional(),
  status: paymentStatusSchema.optional(),
  method_id: z.number().int().positive().optional(),
  page: z.number().int().positive().optional().default(1),
  page_size: z.number().int().positive().max(100).optional().default(20),
})

export type PaymentFilters = z.infer<typeof paymentFiltersSchema>

// ==============================================================================
// MAPPING FUNCTIONS: Form → Request
// ==============================================================================

/**
 * Convert FeeCalculateFormValues to FeeCalculateRequest
 */
export function toFeeCalculateRequest(form: FeeCalculateFormValues): FeeCalculateRequest {
  return {
    admission_profile_id: form.admission_profile_id!,
    fee_type: form.fee_type,
    installment_plan_code: form.installment_plan_code || undefined,
  }
}

/**
 * Convert PaymentRecordFormValues to PaymentCreateRequest
 */
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

/**
 * Convert RefundCreateFormValues to RefundCreateRequest
 */
export function toRefundCreateRequest(form: RefundCreateFormValues): RefundCreateRequest {
  return {
    payment_id: form.payment_id,
    amount: form.amount,
    reason: form.reason,
  }
}

// ==============================================================================
// VALIDATION HELPERS
// ==============================================================================

/**
 * Format VND currency
 */
export function formatVND(amount: string | number): string {
  const num = typeof amount === "string" ? parseFloat(amount) : amount
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(num)
}

/**
 * Validate VND amount string
 */
export function isValidAmount(amount: string): boolean {
  return /^\d+(\.\d{1,2})?$/.test(amount) && parseFloat(amount) > 0
}

/**
 * Parse amount string to number
 */
export function parseAmount(amount: string): number {
  return parseFloat(amount) || 0
}

/**
 * Parse a formatted VND string like "9.000.000 VND" into a whole-number amount.
 */
export function parseVNDDisplayAmount(amount: string): number {
  const digitsOnly = amount.replace(/[^\d-]/g, "")
  return digitsOnly ? parseInt(digitsOnly, 10) : 0
}

/**
 * Parse an amount that may be RAW from the API ("3000000.00") OR already
 * formatted by formatVND ("3.000.000 ₫") into a number — without the
 * double-format pitfall. A formatted VN string uses '.' as a thousands
 * separator, so feeding "3.000.000" back through parseFloat reads it as the
 * decimal 3. Detect the formatted case (it carries the ₫ suffix) and strip
 * separators with parseVNDDisplayAmount; otherwise parse the raw decimal.
 *
 * Use this anywhere a value might be a *_formatted view-model field OR a raw
 * Decimal string — e.g. AmountDisplay and the finance list color thresholds.
 */
export function parseAmountInput(amount: string | number): number {
  if (typeof amount !== "string") return amount
  if (amount.includes("₫")) return parseVNDDisplayAmount(amount)
  return parseFloat(amount.replace(/[^\d.-]/g, "")) || 0
}

/**
 * Compare two amounts (as strings)
 */
export function compareAmounts(a: string, b: string): number {
  return parseFloat(a) - parseFloat(b)
}

/**
 * Check if amount exceeds limit
 */
export function exceedsLimit(amount: string, limit: string): boolean {
  return parseFloat(amount) > parseFloat(limit)
}
