/**
 * React Query Hooks for Payment Methods Lookup
 *
 * @see lib/api/payments.ts
 */

import { useQuery } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { paymentsApi } from "@/lib/api/payments"
import type { ApiErrorResponse } from "@/types/api.types"
import type { PaymentMethod } from "@/types/finance.types"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const paymentMethodsKeys = {
  all: ["paymentMethods"] as const,
  list: () => [...paymentMethodsKeys.all, "list"] as const,
}

// =====================================================================
// QUERIES
// =====================================================================

/**
 * Get list of active payment methods
 *
 * @example
 * ```tsx
 * const { data: methods, isLoading } = usePaymentMethods()
 *
 * // Filter for online methods
 * const onlineMethods = methods?.filter(m => m.is_online)
 *
 * // Filter for manual (offline) methods
 * const manualMethods = methods?.filter(m => !m.is_online)
 * ```
 */
export function usePaymentMethods(options?: { enabled?: boolean }) {
  return useQuery<PaymentMethod[], AxiosError<ApiErrorResponse>>({
    queryKey: paymentMethodsKeys.list(),
    queryFn: () => paymentsApi.getPaymentMethods(),
    staleTime: 1000 * 60 * 30, // 30 minutes - rarely changes
    gcTime: 1000 * 60 * 60, // 1 hour
    enabled: options?.enabled ?? true,
  })
}

// =====================================================================
// DERIVED HOOKS
// =====================================================================

/**
 * Get only online payment methods
 */
export function useOnlinePaymentMethods(options?: { enabled?: boolean }) {
  const query = usePaymentMethods(options)

  return {
    ...query,
    data: query.data?.filter((m) => m.is_online && m.is_active),
  }
}

/**
 * Get only manual (offline) payment methods
 */
export function useManualPaymentMethods(options?: { enabled?: boolean }) {
  const query = usePaymentMethods(options)

  return {
    ...query,
    data: query.data?.filter((m) => !m.is_online && m.is_active),
  }
}

/**
 * Get payment method by ID
 */
export function usePaymentMethodById(
  methodId: number | null,
  options?: { enabled?: boolean }
) {
  const query = usePaymentMethods({
    enabled: (options?.enabled ?? true) && methodId !== null,
  })

  return {
    ...query,
    data: query.data?.find((m) => m.id === methodId) ?? null,
  }
}

// =====================================================================
// SELECT OPTIONS
// =====================================================================

export interface PaymentMethodOption {
  value: number
  label: string
  // [TODO_BACKEND] Add description to PaymentMethodResponse
  is_online: boolean
  gateway_code: string | null
  disabled: boolean
}

/**
 * Transform payment methods to select options
 */
export function toPaymentMethodOptions(
  methods: PaymentMethod[] | undefined,
  filter?: "all" | "online" | "manual"
): PaymentMethodOption[] {
  if (!methods) return []

  let filtered = methods
  if (filter === "online") {
    filtered = methods.filter((m) => m.is_online)
  } else if (filter === "manual") {
    filtered = methods.filter((m) => !m.is_online)
  }

  return filtered
    .sort((a, b) => a.display_order - b.display_order)
    .map((m) => ({
      value: m.id,
      label: m.name,
      is_online: m.is_online,
      gateway_code: m.gateway_code,
      disabled: !m.is_active,
    }))
}

/**
 * Hook that returns payment method select options
 */
export function usePaymentMethodOptions(
  filter?: "all" | "online" | "manual",
  options?: { enabled?: boolean }
) {
  const query = usePaymentMethods(options)

  return {
    ...query,
    options: toPaymentMethodOptions(query.data, filter),
  }
}
