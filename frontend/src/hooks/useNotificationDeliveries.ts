// src/hooks/useNotificationDeliveries.ts
/**
 * Phase B8: React Query hooks for Notification Delivery Ops (admin read-only)
 */
import { useQuery } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  NotificationDeliveriesPage,
  NotificationDelivery,
} from "@/types/api.types";

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
