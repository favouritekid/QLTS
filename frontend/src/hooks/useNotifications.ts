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

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    MarkAsReadRequest,
    { previousData: [readonly unknown[], unknown][] }
  >({
    mutationFn: async (data: MarkAsReadRequest) => {
      await api.post(API_ENDPOINTS.NOTIFICATIONS.MARK_AS_READ, data);
    },
    onMutate: async (data: MarkAsReadRequest) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });

      // Snapshot previous values
      const previousData = queryClient.getQueriesData({ queryKey: notificationKeys.lists() });

      // Optimistically update all notification queries
      queryClient.setQueriesData<NotificationsPage>(
        { queryKey: notificationKeys.lists() },
        (oldData) => {
          if (!oldData) return oldData;

          // Mark specified notifications as read
          const updatedNotifications = oldData.notifications.map((notification) =>
            data.notification_ids.includes(notification.id)
              ? { ...notification, is_read: true, read_at: new Date().toISOString() }
              : notification
          );

          // Calculate how many unread notifications are being marked as read
          const unreadCountChange = data.notification_ids.filter(
            (id) => oldData.notifications.find((n) => n.id === id && !n.is_read)
          ).length;

          return {
            ...oldData,
            unread_count: Math.max(0, oldData.unread_count - unreadCountChange),
            notifications: updatedNotifications,
          };
        }
      );

      return { previousData };
    },
    onError: (_err, _data, context) => {
      // Rollback on error
      if (context?.previousData) {
        context.previousData.forEach(([queryKey, data]) => {
          queryClient.setQueryData(queryKey, data);
        });
      }
    },
    onSettled: () => {
      // Refetch to ensure sync with server
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
}

// ============================================
// ✅ MARK ALL AS READ MUTATION
// ============================================

export function useMarkAllAsRead() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    void,
    { previousData: [readonly unknown[], unknown][] }
  >({
    mutationFn: async () => {
      await api.post(API_ENDPOINTS.NOTIFICATIONS.MARK_ALL_AS_READ);
    },
    onMutate: async () => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });

      // Snapshot previous values
      const previousData = queryClient.getQueriesData({ queryKey: notificationKeys.lists() });

      // Optimistically update all notification queries
      queryClient.setQueriesData<NotificationsPage>(
        { queryKey: notificationKeys.lists() },
        (oldData) => {
          if (!oldData) return oldData;

          // Mark all notifications as read
          const updatedNotifications = oldData.notifications.map((notification) => ({
            ...notification,
            is_read: true,
            read_at: new Date().toISOString(),
          }));

          return {
            ...oldData,
            unread_count: 0, // All marked as read
            notifications: updatedNotifications,
          };
        }
      );

      return { previousData };
    },
    onError: (_err, _data, context) => {
      // Rollback on error
      if (context?.previousData) {
        context.previousData.forEach(([queryKey, data]) => {
          queryClient.setQueryData(queryKey, data);
        });
      }
    },
    onSettled: () => {
      // Refetch to ensure sync with server
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
}

// ============================================
// 🗑️ DELETE NOTIFICATION MUTATION
// ============================================

export function useDeleteNotification() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    number,
    { previousData: [readonly unknown[], unknown][] }
  >({
    mutationFn: async (id: number) => {
      await api.delete(API_ENDPOINTS.NOTIFICATIONS.DELETE(id));
    },
    onMutate: async (id: number) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });

      // Snapshot previous values
      const previousData = queryClient.getQueriesData({ queryKey: notificationKeys.lists() });

      // Optimistically update all notification queries
      queryClient.setQueriesData<NotificationsPage>(
        { queryKey: notificationKeys.lists() },
        (oldData) => {
          if (!oldData) return oldData;

          // Find the notification being deleted to check if it was unread
          const deletedNotification = oldData.notifications.find((n) => n.id === id);
          const wasUnread = deletedNotification && !deletedNotification.is_read;

          // Remove the notification from the list
          const updatedNotifications = oldData.notifications.filter((n) => n.id !== id);

          return {
            ...oldData,
            total_count: Math.max(0, oldData.total_count - 1),
            unread_count: wasUnread
              ? Math.max(0, oldData.unread_count - 1)
              : oldData.unread_count,
            notifications: updatedNotifications,
          };
        }
      );

      return { previousData };
    },
    onError: (_err, _data, context) => {
      // Rollback on error
      if (context?.previousData) {
        context.previousData.forEach(([queryKey, data]) => {
          queryClient.setQueryData(queryKey, data);
        });
      }
    },
    onSettled: () => {
      // Refetch to ensure sync with server
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
