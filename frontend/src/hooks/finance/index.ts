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
  useInvoiceDetail,
  useInvoicesByFee,
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
