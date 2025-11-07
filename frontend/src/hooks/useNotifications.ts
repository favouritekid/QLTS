// src/hooks/useNotifications.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  MarkAsReadRequest,
  Notification,
  NotificationsPage,
} from "@/types/api.types";

// ============================================
// 📋 QUERY KEYS
// ============================================

export const notificationKeys = {
  all: ["notifications"] as const,
  lists: () => [...notificationKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...notificationKeys.lists(), params] as const,
};

// ============================================
// 📊 NOTIFICATIONS LIST QUERY
// ============================================

interface UseNotificationsParams {
  page?: number;
  page_size?: number;
  unread_only?: boolean;
}

export function useNotifications(params: UseNotificationsParams = {}) {
  const { page = 1, page_size = 20, unread_only = false } = params;

  return useQuery<NotificationsPage, AxiosError<ApiErrorResponse>>({
    queryKey: notificationKeys.list({ page, page_size, unread_only }),
    queryFn: async () => {
      const response = await api.get<NotificationsPage>(
        API_ENDPOINTS.NOTIFICATIONS.LIST,
        {
          params: { page, page_size, unread_only },
        }
      );
      return response.data;
    },
    refetchInterval: 30000, // Refetch every 30 seconds
    staleTime: 10000, // Consider data stale after 10 seconds
  });
}

// ============================================
// ✅ MARK AS READ MUTATION
// ============================================

export function useMarkAsRead() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, MarkAsReadRequest>({
    mutationFn: async (data: MarkAsReadRequest) => {
      await api.post(API_ENDPOINTS.NOTIFICATIONS.MARK_AS_READ, data);
    },
    onSuccess: () => {
      // Invalidate all notification queries to refetch
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
}

// ============================================
// ✅ MARK ALL AS READ MUTATION
// ============================================

export function useMarkAllAsRead() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      await api.post(API_ENDPOINTS.NOTIFICATIONS.MARK_ALL_AS_READ);
    },
    onSuccess: () => {
      // Invalidate all notification queries to refetch
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
}

// ============================================
// 🗑️ DELETE NOTIFICATION MUTATION
// ============================================

export function useDeleteNotification() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id: number) => {
      await api.delete(API_ENDPOINTS.NOTIFICATIONS.DELETE(id));
    },
    onSuccess: () => {
      // Invalidate all notification queries to refetch
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
}

// ============================================
// 📡 ADD NEW NOTIFICATION (for real-time updates)
// ============================================

export function useAddNotification() {
  const queryClient = useQueryClient();

  return (notification: Notification) => {
    // Update all notification queries by adding the new notification
    queryClient.setQueriesData<NotificationsPage>(
      { queryKey: notificationKeys.lists() },
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          total_count: oldData.total_count + 1,
          unread_count: oldData.unread_count + 1,
          notifications: [notification, ...oldData.notifications],
        };
      }
    );
  };
}
