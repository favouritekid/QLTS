/**
 * Finance Module Hooks
 *
 * Exports all React Query hooks and ViewModels for the Finance Module.
 *
 * @example
 * ```tsx
 * import {
 *   useFees,
 *   useFeeViewModel,
 *   useInvoices,
 *   usePayments,
 *   useFinanceDashboardViewModel,
 * } from '@/hooks/finance'
 * ```
 */

// Fee Hooks
export {
  feesKeys,
  useFees,
  useFeeDetail,
  useFeesByProfile,
  useProfileFinanceSummary,
  useProfileCollection,
  useCalculateFee,
  useWaiveFee,
  useCancelFee,
  useRecalculateFee,
} from "./useFees"

export {
  useFeeViewModel,
  toFeeViewModel,
  toFeeListViewModel,
  type FeeViewModel,
  type FeeListItemViewModel,
} from "./useFeeViewModel"

// Invoice Hooks
export {
  invoicesKeys,
  useInvoices,
  useInvoiceStatusCounts,
  useInvoiceDetail,
  useInvoicesByFee,
  useInvoiceVietQR,
  useIssueInvoice,
  useCancelInvoice,
  useApplyPenalty,
} from "./useInvoices"

export {
  useInvoiceViewModel,
  toInvoiceViewModel,
  toInvoiceListViewModel,
  type InvoiceViewModel,
  type InvoiceListItemViewModel,
} from "./useInvoiceViewModel"

// Payment Hooks
export {
  paymentsKeys,
  usePayments,
  usePendingPayments,
  usePaymentDetail,
  usePaymentsByInvoice,
  usePaymentIntent,
  useCreatePayment,
  useVerifyPayment,
  useRejectPayment,
  useCreatePaymentIntent,
} from "./usePayments"

export {
  usePaymentViewModel,
  toPaymentViewModel,
  toPaymentListViewModel,
  toPendingPaymentListViewModel,
  type PaymentViewModel,
  type PaymentListItemViewModel,
  type PendingPaymentViewModel,
} from "./usePaymentViewModel"

// Payment Methods Hooks
export {
  paymentMethodsKeys,
  usePaymentMethods,
  useOnlinePaymentMethods,
  useManualPaymentMethods,
  usePaymentMethodById,
  usePaymentMethodOptions,
  toPaymentMethodOptions,
  type PaymentMethodOption,
} from "./usePaymentMethods"

// Installment Plans Hooks
export {
  installmentPlansKeys,
  useInstallmentPlans,
  useInstallmentPlan,
  useInstallmentPlanByCode,
  useInstallmentPlanOptions,
  toInstallmentPlanOptions,
  toScheduleDisplay,
  getPenaltyDescription,
  type InstallmentPlanOption,
  type ScheduleDisplayItem,
} from "./useInstallmentPlans"

// Dashboard Hooks
export {
  financeDashboardKeys,
  useFinanceDashboard,
  useFinanceDashboardViewModel,
  useFinanceBadgeCounts,
  type FinanceDashboardViewModel,
  type DashboardCard,
  type FinanceBadgeCounts,
} from "./useFinanceDashboard"

export {
  debtReportKeys,
  useDebtReport,
} from "./useDebtReport"

export {
  refundsKeys,
  useRefunds,
  useRefundDetail,
  useCreateRefund,
  useApproveRefund,
  useRejectRefund,
  useProcessRefund,
} from "./useRefunds"

export {
  overpaymentsKeys,
  useOverpayments,
  useApplyOverpayment,
  useRefundOverpayment,
  useWriteOffOverpayment,
} from "./useOverpayments"
