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

export function useNotifications(
  params: UseNotificationsParams = {},
  options?: { initialData?: NotificationsPage }
) {
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
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 6: Support SSR
    // ✅ PERFORMANCE FIX (v17): Remove polling - rely on Socket.IO for real-time updates
    // refetchInterval: 30000, // ❌ REMOVED - Socket.IO pushes notifications in real-time
    staleTime: Infinity, // Never mark as stale - Socket.IO will invalidate when needed
    gcTime: 10 * 60 * 1000, // Garbage collect after 10 minutes of inactivity

    // ✅ PHASE 1.1.2: Exponential backoff with jitter (Thundering Herd protection)
    // Retries with increasing delays: 1s → 2s → 4s (+ random 0-1s jitter)
    // Prevents synchronized retries when backend restarts or has issues
    retry: 3, // Retry up to 3 times on failure
    retryDelay: (attemptIndex) => {
      // Exponential backoff: 1s, 2s, 4s, capped at 30s
      const exponentialDelay = Math.min(1000 * 2 ** attemptIndex, 30000);
      // Add jitter (0-1000ms random) to avoid synchronized retries
      const jitter = Math.random() * 1000;
      return exponentialDelay + jitter;
    },
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
// 🗑️ BULK DELETE NOTIFICATIONS MUTATION
// ✅ TECHNICAL DEBT FIX: Single API call for multiple deletes
// ============================================

interface BulkDeleteRequest {
  notification_ids: number[];
}

interface BulkDeleteResponse {
  deleted: number;
}

export function useBulkDeleteNotifications() {
  const queryClient = useQueryClient();

  return useMutation<
    BulkDeleteResponse,
    AxiosError<ApiErrorResponse>,
    BulkDeleteRequest,
    { previousData: [readonly unknown[], unknown][] }
  >({
    mutationFn: async (data: BulkDeleteRequest) => {
      const response = await api.delete<BulkDeleteResponse>(
        API_ENDPOINTS.NOTIFICATIONS.BULK_DELETE,
        { data }
      );
      return response.data;
    },
    onMutate: async (data: BulkDeleteRequest) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });

      // Snapshot previous values
      const previousData = queryClient.getQueriesData({ queryKey: notificationKeys.lists() });

      // Optimistically update all notification queries
      queryClient.setQueriesData<NotificationsPage>(
        { queryKey: notificationKeys.lists() },
        (oldData) => {
          if (!oldData) return oldData;

          // Count unread notifications being deleted
          const unreadBeingDeleted = oldData.notifications.filter(
            (n) => data.notification_ids.includes(n.id) && !n.is_read
          ).length;

          // Remove deleted notifications from the list
          const updatedNotifications = oldData.notifications.filter(
            (n) => !data.notification_ids.includes(n.id)
          );

          return {
            ...oldData,
            total_count: Math.max(0, oldData.total_count - data.notification_ids.length),
            unread_count: Math.max(0, oldData.unread_count - unreadBeingDeleted),
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
