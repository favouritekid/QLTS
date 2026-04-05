// src/hooks/useNotificationConsents.ts
/**
 * Phase B7: React Query hooks for Notification Consent management (admin)
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  NotificationConsent,
  NotificationConsentImportResult,
  NotificationConsentsPage,
  NotificationConsentUpsert,
} from "@/types/api.types";

// ============================================
// QUERY KEYS
// ============================================

export const notificationConsentKeys = {
  all: ["notification-consents"] as const,
  lists: () => [...notificationConsentKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...notificationConsentKeys.lists(), params] as const,
};

// ============================================
// LIST CONSENTS
// ============================================

export interface UseNotificationConsentsParams {
  page?: number;
  page_size?: number;
  channel?: string;
  source_type?: string;
  consent_status?: string;
}

export function useNotificationConsents(
  params: UseNotificationConsentsParams = {},
  options?: { initialData?: NotificationConsentsPage }
) {
  const {
    page = 1,
    page_size = 50,
    channel,
    source_type,
    consent_status,
  } = params;

  return useQuery<NotificationConsentsPage, AxiosError<ApiErrorResponse>>({
    queryKey: notificationConsentKeys.list({
      page,
      page_size,
      channel,
      source_type,
      consent_status,
    }),
    queryFn: async () => {
      const { data } = await api.get<NotificationConsentsPage>(
        API_ENDPOINTS.NOTIFICATION_CONSENTS.LIST,
        {
          params: {
            page,
            page_size,
            channel: channel || undefined,
            source_type: source_type || undefined,
            consent_status: consent_status || undefined,
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
// UPSERT CONSENT
// ============================================

export function useUpsertConsent() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationConsent,
    AxiosError<ApiErrorResponse>,
    NotificationConsentUpsert
  >({
    mutationFn: async (body) => {
      const { data } = await api.post<NotificationConsent>(
        API_ENDPOINTS.NOTIFICATION_CONSENTS.UPSERT,
        body
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: notificationConsentKeys.lists(),
      });
    },
  });
}

// ============================================
// BULK IMPORT CONSENTS (CSV)
// ============================================

export function useBulkImportConsents() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationConsentImportResult,
    AxiosError<ApiErrorResponse>,
    File
  >({
    mutationFn: async (file) => {
      const formData = new FormData();
      formData.append("file", file);
      const { data } = await api.post<NotificationConsentImportResult>(
        API_ENDPOINTS.NOTIFICATION_CONSENTS.BULK_IMPORT,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: notificationConsentKeys.lists(),
      });
    },
  });
}
