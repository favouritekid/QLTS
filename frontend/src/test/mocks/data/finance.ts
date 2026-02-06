/**
 * Mock data for Finance module tests
 */

import type {
  Fee,
  Invoice,
  Payment,
  PaymentMethod,
  InstallmentPlan,
  AccountingPeriod,
  FinanceDashboardStats,
} from "@/types/finance.types";

// Extended type for mock data with profile info (not exported from main types)
export interface FeeWithProfile extends Fee {
  profile: {
    id: number;
    full_name: string;
    lead_id: number;
  };
}

// =============================================================================
// MOCK PAYMENT METHODS
// =============================================================================

export const mockPaymentMethods: PaymentMethod[] = [
  {
    id: 1,
    code: "cash",
    name: "Tiền mặt",
    is_online: false,
    requires_verification: true,
    gateway_code: null,
    is_active: true,
    display_order: 1,
    created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: 2,
    code: "bank_transfer",
    name: "Chuyển khoản ngân hàng",
    is_online: false,
    requires_verification: true,
    gateway_code: null,
    is_active: true,
    display_order: 2,
    created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: 3,
    code: "vnpay",
    name: "VNPay",
    is_online: true,
    requires_verification: false,
    gateway_code: "vnpay",
    is_active: true,
    display_order: 3,
    created_at: "2025-01-01T00:00:00Z",
  },
];

// =============================================================================
// MOCK INSTALLMENT PLANS
// =============================================================================

export const mockInstallmentPlans: InstallmentPlan[] = [
  {
    id: 1,
    code: "FULL",
    name: "Thanh toán một lần",
    installment_count: 1,
    schedule: [
      { installment_no: 1, percent: 100, due_days_offset: 0 },
    ],
    penalty_rate: "0.05",
    is_active: true,
    created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: 2,
    code: "THREE_MONTH",
    name: "Trả góp 3 đợt",
    installment_count: 3,
    schedule: [
      { installment_no: 1, percent: 34, due_days_offset: 0 },
      { installment_no: 2, percent: 33, due_days_offset: 30 },
      { installment_no: 3, percent: 33, due_days_offset: 60 },
    ],
    penalty_rate: "0.05",
    is_active: true,
    created_at: "2025-01-01T00:00:00Z",
  },
];

// =============================================================================
// MOCK FEES
// =============================================================================

export const mockFees: FeeWithProfile[] = [
  {
    id: 1,
    admission_profile_id: 100,
    installment_plan_id: 1,
    fee_type: "tuition",
    academic_year: "2025-2026",
    base_amount: "15000000",
    total_discount: "1500000",
    final_amount: "13500000",
    paid_amount: "0",
    waived_amount: "0",
    remaining_amount: "13500000",
    status: "calculated",
    due_date: "2025-03-01",
    version: 1,
    notes: null,
    created_at: "2025-02-01T10:00:00Z",
    updated_at: "2025-02-01T10:00:00Z",
    applied_discounts: [],
    can_waive: true,
    can_cancel: true,
    can_recalculate: true,
    profile: {
      id: 100,
      full_name: "Nguyen Van A",
      lead_id: 1,
    },
  },
  {
    id: 2,
    admission_profile_id: 101,
    installment_plan_id: 2,
    fee_type: "tuition",
    academic_year: "2025-2026",
    base_amount: "20000000",
    total_discount: "0",
    final_amount: "20000000",
    paid_amount: "10000000",
    waived_amount: "0",
    remaining_amount: "10000000",
    status: "partial",
    due_date: "2025-03-01",
    version: 1,
    notes: null,
    created_at: "2025-02-01T10:00:00Z",
    updated_at: "2025-02-15T10:00:00Z",
    applied_discounts: [],
    can_waive: true,
    can_cancel: false,
    can_recalculate: false,
    profile: {
      id: 101,
      full_name: "Tran Thi B",
      lead_id: 2,
    },
  },
];

// =============================================================================
// MOCK INVOICES
// =============================================================================

export const mockInvoices: Invoice[] = [
  {
    id: 1,
    fee_id: 1,
    invoice_number: "INV-2025-000001",
    installment_no: 1,
    amount: "13500000",
    paid_amount: "0",
    remaining_amount: "13500000",
    due_date: "2025-03-01",
    status: "issued",
    issued_at: "2025-02-01T10:00:00Z",
    paid_at: null,
    cancelled_at: null,
    created_at: "2025-02-01T10:00:00Z",
    updated_at: "2025-02-01T10:00:00Z",
    can_issue: false,
    can_cancel: true,
    can_record_payment: true,
    can_apply_penalty: false,
  },
  {
    id: 2,
    fee_id: 2,
    invoice_number: "INV-2025-000002",
    installment_no: 1,
    amount: "6800000",
    paid_amount: "6800000",
    remaining_amount: "0",
    due_date: "2025-03-01",
    status: "paid",
    issued_at: "2025-02-01T10:00:00Z",
    paid_at: "2025-02-15T10:00:00Z",
    cancelled_at: null,
    created_at: "2025-02-01T10:00:00Z",
    updated_at: "2025-02-15T10:00:00Z",
    can_issue: false,
    can_cancel: false,
    can_record_payment: false,
    can_apply_penalty: false,
  },
];

// =============================================================================
// MOCK PAYMENTS
// =============================================================================

export const mockPayments: Payment[] = [
  {
    id: 1,
    invoice_id: 2,
    method_id: 1,
    intent_id: null,
    amount: "6800000",
    reference_code: "REF-001",
    payer_name: "Tran Thi B",
    status: "verified",
    payment_date: "2025-02-15T10:00:00Z",
    verified_at: "2025-02-15T11:00:00Z",
    rejected_at: null,
    created_by_id: 2,
    created_by_name: "Finance Officer",
    verified_by_id: 3,
    verified_by_name: "Finance Manager",
    rejection_reason: null,
    notes: null,
    created_at: "2025-02-15T10:00:00Z",
    updated_at: "2025-02-15T11:00:00Z",
    can_verify: false,
    can_reject: false,
  },
  {
    id: 2,
    invoice_id: 1,
    method_id: 2,
    intent_id: null,
    amount: "5000000",
    reference_code: "REF-002",
    payer_name: "Nguyen Van A",
    status: "pending",
    payment_date: "2025-02-20T10:00:00Z",
    verified_at: null,
    rejected_at: null,
    created_by_id: 2,
    created_by_name: "Finance Officer",
    verified_by_id: null,
    verified_by_name: null,
    rejection_reason: null,
    notes: "Pending verification",
    created_at: "2025-02-20T10:00:00Z",
    updated_at: "2025-02-20T10:00:00Z",
    can_verify: true,
    can_reject: true,
  },
];

// =============================================================================
// MOCK ACCOUNTING PERIODS
// =============================================================================

export const mockAccountingPeriods: AccountingPeriod[] = [
  {
    id: 1,
    month: 1,
    year: 2025,
    is_closed: true,
    closed_at: "2025-02-01T00:00:00Z",
    closed_by_id: 1,
    total_payments: "50000000",
    total_refunds: "0",
    net_revenue: "50000000",
    created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: 2,
    month: 2,
    year: 2025,
    is_closed: false,
    closed_at: null,
    closed_by_id: null,
    total_payments: "30000000",
    total_refunds: "0",
    net_revenue: "30000000",
    created_at: "2025-02-01T00:00:00Z",
  },
];

// =============================================================================
// MOCK DASHBOARD STATS
// =============================================================================

export const mockDashboardStats: FinanceDashboardStats = {
  pending_fees_count: 5,
  pending_fees_amount: "75000000",
  pending_payments_count: 3,
  overdue_invoices_count: 2,
  overdue_amount: "20000000",
  today_collections: "15000000",
  monthly_collections: "150000000",
  period_collections: "45000000",
  period_start: "2026-01-29",
  period_end: "2026-02-04",
  pending_overpayments_count: 1,
  pending_refunds_count: 0,
};
