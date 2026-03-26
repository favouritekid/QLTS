// src/hooks/useNotificationDeliveries.ts
/**
 * Phase B8 + C2: React Query hooks for Notification Delivery Ops
 *
 * B8: list + detail (admin read-only)
 * C2: stats, failures, replay (admin actions)
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  NotificationDeliveriesPage,
  NotificationDelivery,
} from "@/types/api.types";

// ============================================
// TYPES (C2)
// ============================================

export interface DeliveryStats {
  total: number;
  by_status: Record<string, number>;
  by_channel: Record<string, number>;
  success_rate: number;
}

export interface FailureReasonCount {
  error_reason: string;
  count: number;
  latest_at: string | null;
}

export interface DeliveryFailureSummary {
  total_failures: number;
  by_reason: FailureReasonCount[];
}

export interface ReplayResponse {
  replayed: boolean;
  delivery_id: number;
  message: string;
}

// ============================================
// QUERY KEYS
// ============================================

export const notificationDeliveryKeys = {
  all: ["notification-deliveries"] as const,
  lists: () => [...notificationDeliveryKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...notificationDeliveryKeys.lists(), params] as const,
  details: () => [...notificationDeliveryKeys.all, "detail"] as const,
  detail: (id: number) => [...notificationDeliveryKeys.details(), id] as const,
  stats: (params?: Record<string, unknown>) =>
    [...notificationDeliveryKeys.all, "stats", params] as const,
  failures: (params?: Record<string, unknown>) =>
    [...notificationDeliveryKeys.all, "failures", params] as const,
};

// ============================================
// LIST DELIVERIES
// ============================================

export interface UseNotificationDeliveriesParams {
  page?: number;
  page_size?: number;
  event?: string;
  channel?: string;
  status?: string;
  user_id?: number;
  source_type?: string;
  source_id?: number;
  date_from?: string;
  date_to?: string;
}

export function useNotificationDeliveries(
  params: UseNotificationDeliveriesParams = {},
  options?: { initialData?: NotificationDeliveriesPage }
) {
  const {
    page = 1,
    page_size = 50,
    event,
    channel,
    status,
    user_id,
    source_type,
    source_id,
    date_from,
    date_to,
  } = params;

  return useQuery<NotificationDeliveriesPage, AxiosError<ApiErrorResponse>>({
    queryKey: notificationDeliveryKeys.list({
      page,
      page_size,
      event,
      channel,
      status,
      user_id,
      source_type,
      source_id,
      date_from,
      date_to,
    }),
    queryFn: async () => {
      const { data } = await api.get<NotificationDeliveriesPage>(
        API_ENDPOINTS.NOTIFICATION_DELIVERIES.LIST,
        {
          params: {
            page,
            page_size,
            event: event || undefined,
            channel: channel || undefined,
            status: status || undefined,
            user_id: user_id || undefined,
            source_type: source_type || undefined,
            source_id: source_id || undefined,
            date_from: date_from || undefined,
            date_to: date_to || undefined,
          },
        }
      );
      return data;
    },
    initialData: options?.initialData,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
}

// ============================================
// DELIVERY DETAIL
// ============================================

export function useNotificationDeliveryDetail(
  id: number,
  options?: { enabled?: boolean }
) {
  return useQuery<NotificationDelivery, AxiosError<ApiErrorResponse>>({
    queryKey: notificationDeliveryKeys.detail(id),
    queryFn: async () => {
      const { data } = await api.get<NotificationDelivery>(
        API_ENDPOINTS.NOTIFICATION_DELIVERIES.DETAIL(id)
      );
      return data;
    },
    enabled: options?.enabled !== false && id > 0,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
}

// ============================================
// STATS (C2-5)
// ============================================

export interface UseDeliveryStatsParams {
  date_from?: string;
  date_to?: string;
  event?: string;
  channel?: string;
}

export function useDeliveryStats(params: UseDeliveryStatsParams = {}) {
  return useQuery<DeliveryStats, AxiosError<ApiErrorResponse>>({
    queryKey: notificationDeliveryKeys.stats(params),
    queryFn: async () => {
      const { data } = await api.get<DeliveryStats>(
        API_ENDPOINTS.NOTIFICATION_DELIVERIES.STATS,
        { params: { ...params } }
      );
      return data;
    },
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });
}

// ============================================
// FAILURES (C2-5)
// ============================================

export interface UseDeliveryFailuresParams {
  date_from?: string;
  date_to?: string;
  channel?: string;
  limit?: number;
}

export function useDeliveryFailures(params: UseDeliveryFailuresParams = {}) {
  return useQuery<DeliveryFailureSummary, AxiosError<ApiErrorResponse>>({
    queryKey: notificationDeliveryKeys.failures(params),
    queryFn: async () => {
      const { data } = await api.get<DeliveryFailureSummary>(
        API_ENDPOINTS.NOTIFICATION_DELIVERIES.FAILURES,
        { params: { ...params } }
      );
      return data;
    },
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });
}

// ============================================
// REPLAY (C2-2)
// ============================================

export function useReplayDelivery() {
  const queryClient = useQueryClient();

  return useMutation<ReplayResponse, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (deliveryId: number) => {
      const { data } = await api.post<ReplayResponse>(
        API_ENDPOINTS.NOTIFICATION_DELIVERIES.REPLAY(deliveryId)
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: notificationDeliveryKeys.all });
    },
  });
}
