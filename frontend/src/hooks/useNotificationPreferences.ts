// src/hooks/useNotificationPreferences.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  NotificationPreference,
  NotificationPreferenceUpdate,
} from "@/types/api.types";

// Query keys
export const notificationPreferenceKeys = {
  all: ["notificationPreferences"] as const,
  detail: () => [...notificationPreferenceKeys.all, "detail"] as const,
};

/**
 * Hook to fetch user's notification preferences
 */
export function useNotificationPreferences() {
  return useQuery<NotificationPreference, AxiosError<ApiErrorResponse>>({
    queryKey: notificationPreferenceKeys.detail(),
    queryFn: async () => {
      const response = await api.get<NotificationPreference>(
        API_ENDPOINTS.NOTIFICATIONS.PREFERENCES
      );
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to update user's notification preferences
 */
export function useUpdateNotificationPreferences() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationPreference,
    AxiosError<ApiErrorResponse>,
    NotificationPreferenceUpdate
  >({
    mutationFn: async (data: NotificationPreferenceUpdate) => {
      const response = await api.put<NotificationPreference>(
        API_ENDPOINTS.NOTIFICATIONS.PREFERENCES,
        data
      );
      return response.data;
    },
    onSuccess: (data) => {
      // Update the cached preferences
      queryClient.setQueryData(notificationPreferenceKeys.detail(), data);

      // Invalidate to refetch
      queryClient.invalidateQueries({
        queryKey: notificationPreferenceKeys.all,
      });
    },
  });
}
