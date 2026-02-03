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
