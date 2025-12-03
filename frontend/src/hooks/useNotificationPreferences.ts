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

// ============================================================================
// TYPES FOR EVENT GROUPS (NEW)
// ============================================================================

export interface EventGroupInfo {
  id: string;
  name_en: string;
  name_vi: string;
  description_en: string;
  description_vi: string;
}

export interface EventGroupPreferencesResponse {
  groups: EventGroupInfo[];
  preferences: Record<string, Record<string, boolean>>;
}

export interface UpdateGroupPreferenceRequest {
  event_group: string;
  channel: string;
  enabled: boolean;
}

// Query keys
export const notificationPreferenceKeys = {
  all: ["notificationPreferences"] as const,
  detail: () => [...notificationPreferenceKeys.all, "detail"] as const,
  eventGroups: () => [...notificationPreferenceKeys.all, "eventGroups"] as const,
};

/**
 * Hook to fetch user's notification preferences
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Added initialData support for SSR
 */
export function useNotificationPreferences(options?: {
  initialData?: NotificationPreference;
}) {
  return useQuery<NotificationPreference, AxiosError<ApiErrorResponse>>({
    queryKey: notificationPreferenceKeys.detail(),
    queryFn: async () => {
      const response = await api.get<NotificationPreference>(
        API_ENDPOINTS.NOTIFICATIONS.PREFERENCES
      );
      return response.data;
    },
    initialData: options?.initialData,
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

// ============================================================================
// EVENT GROUPS HOOKS (NEW - Event-Driven Architecture)
// ============================================================================

/**
 * Hook to fetch event group preferences
 * Returns both group metadata and user's preferences
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Added initialData support for SSR
 */
export function useEventGroupPreferences(options?: {
  initialData?: EventGroupPreferencesResponse;
}) {
  return useQuery<EventGroupPreferencesResponse, AxiosError<ApiErrorResponse>>({
    queryKey: notificationPreferenceKeys.eventGroups(),
    queryFn: async () => {
      const response = await api.get<EventGroupPreferencesResponse>(
        API_ENDPOINTS.NOTIFICATIONS.EVENT_GROUPS
      );
      return response.data;
    },
    initialData: options?.initialData,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to update a single event group/channel preference
 */
export function useUpdateEventGroupPreference() {
  const queryClient = useQueryClient();

  return useMutation<
    { success: boolean; group: string; channel: string; enabled: boolean },
    AxiosError<ApiErrorResponse>,
    UpdateGroupPreferenceRequest
  >({
    mutationFn: async (data: UpdateGroupPreferenceRequest) => {
      const response = await api.patch(
        API_ENDPOINTS.NOTIFICATIONS.EVENT_GROUPS,
        data
      );
      return response.data;
    },
    onSuccess: (data) => {
      // Optimistically update the cache
      queryClient.setQueryData<EventGroupPreferencesResponse>(
        notificationPreferenceKeys.eventGroups(),
        (old) => {
          if (!old) return old;
          return {
            ...old,
            preferences: {
              ...old.preferences,
              [data.group]: {
                ...old.preferences[data.group],
                [data.channel]: data.enabled,
              },
            },
          };
        }
      );
    },
  });
}
