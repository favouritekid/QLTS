// src/components/finance/index.ts
/**
 * Finance Module Components
 *
 * Reusable UI components for the Finance bounded context.
 * Includes amount displays, status badges, and cards.
 */

// Amount display
export {
  AmountDisplay,
  RemainingAmount,
  PaidAmount,
  type AmountDisplayProps,
} from "./AmountDisplay"

// Status badges
export {
  FeeStatusBadge,
  InvoiceStatusBadge,
  PaymentStatusBadge,
  financeBadgeVariants,
  type FeeStatusBadgeProps,
  type InvoiceStatusBadgeProps,
  type PaymentStatusBadgeProps,
} from "./FinanceStatusBadges"

// Fee cards
export {
  FeeCard,
  FeeSummaryCard,
  type FeeCardProps,
  type FeeSummaryCardProps,
} from "./FeeCard"

// Payment cards
export {
  PaymentCard,
  PendingPaymentCard,
  type PaymentCardProps,
  type PendingPaymentCardProps,
} from "./PaymentCard"

// Cross-reference components
export { FeeStatusLink, type FeeStatusLinkProps } from "./FeeStatusLink"
export { VietQRDisplay } from "./VietQRDisplay"
export { InvoiceVietQR } from "./InvoiceVietQR"

// Invoice components
export { InvoiceTable, type InvoiceTableProps } from "./InvoiceTable"

// Payment components
export { PaymentTimeline, type PaymentTimelineProps } from "./PaymentTimeline"

// Form selects
export {
  PaymentMethodSelect,
  type PaymentMethodSelectProps,
} from "./PaymentMethodSelect"
export {
  InstallmentPlanSelect,
  type InstallmentPlanSelectProps,
} from "./InstallmentPlanSelect"
