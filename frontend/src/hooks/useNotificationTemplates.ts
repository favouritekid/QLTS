// src/hooks/useNotificationTemplates.ts
/**
 * ✅ PHASE 3.1: React Query hooks for Notification Templates management
 *
 * Provides hooks for admin users to manage reusable notification templates:
 * - List templates with pagination and filtering
 * - Get single template details
 * - Create new templates
 * - Update existing templates
 * - Delete templates (with protection for system templates and templates in use)
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  NotificationTemplate,
  NotificationTemplateCreate,
  NotificationTemplateUpdate,
  NotificationTemplatesPage,
} from "@/types/api.types";

// ============================================
// 📋 QUERY KEYS
// ============================================

export const notificationTemplateKeys = {
  all: ["notification-templates"] as const,
  lists: () => [...notificationTemplateKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...notificationTemplateKeys.lists(), params] as const,
  details: () => [...notificationTemplateKeys.all, "detail"] as const,
  detail: (id: number) => [...notificationTemplateKeys.details(), id] as const,
};

// ============================================
// 📊 NOTIFICATION TEMPLATES LIST QUERY
// ============================================

interface UseNotificationTemplatesParams {
  page?: number;
  page_size?: number;
  category?: string; // Filter by category
  is_system?: boolean; // Filter by system flag
  search?: string; // Search by name or description
  allowed_event?: string; // Filter templates that support this event
  supported_channel?: string; // Filter templates that support this channel
}

/**
 * Hook to fetch paginated list of notification templates (admin only)
 *
 * ✅ PHASE 1 - WEEK 2: Support initialData from Server Components
 */
export function useNotificationTemplates(
  params: UseNotificationTemplatesParams = {},
  options?: { initialData?: NotificationTemplatesPage }
) {
  const { page = 1, page_size = 50, category, is_system, search, allowed_event, supported_channel } = params;

  return useQuery<NotificationTemplatesPage, AxiosError<ApiErrorResponse>>({
    queryKey: notificationTemplateKeys.list({
      page,
      page_size,
      category,
      is_system,
      search,
      allowed_event,
      supported_channel,
    }),
    queryFn: async () => {
      const response = await api.get<NotificationTemplatesPage>(
        API_ENDPOINTS.NOTIFICATION_TEMPLATES.LIST,
        {
          params: { page, page_size, category, is_system, search, allowed_event, supported_channel },
        }
      );
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    initialData: options?.initialData, // ✅ Use initialData from Server Component
  });
}

// ============================================
// 📄 NOTIFICATION TEMPLATE DETAIL QUERY
// ============================================

interface UseNotificationTemplateOptions {
  enabled?: boolean;
}

/**
 * Hook to fetch single notification template by ID (admin only)
 */
export function useNotificationTemplate(
  templateId: number | undefined,
  options?: UseNotificationTemplateOptions
) {
  return useQuery<NotificationTemplate, AxiosError<ApiErrorResponse>>({
    queryKey: notificationTemplateKeys.detail(templateId!),
    queryFn: async () => {
      const response = await api.get<NotificationTemplate>(
        API_ENDPOINTS.NOTIFICATION_TEMPLATES.DETAIL(templateId!)
      );
      return response.data;
    },
    enabled: options?.enabled !== undefined ? options.enabled : !!templateId,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
}

// ============================================
// ➕ CREATE NOTIFICATION TEMPLATE MUTATION
// ============================================

/**
 * Hook to create a new notification template (admin only)
 */
export function useCreateNotificationTemplate() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationTemplate,
    AxiosError<ApiErrorResponse>,
    NotificationTemplateCreate
  >({
    mutationFn: async (data: NotificationTemplateCreate) => {
      const response = await api.post<NotificationTemplate>(
        API_ENDPOINTS.NOTIFICATION_TEMPLATES.CREATE,
        data
      );
      return response.data;
    },
    onSuccess: () => {
      // Invalidate all list queries to refetch
      queryClient.invalidateQueries({
        queryKey: notificationTemplateKeys.lists(),
      });
    },
  });
}

// ============================================
// ✏️ UPDATE NOTIFICATION TEMPLATE MUTATION
// ============================================

interface UpdateNotificationTemplateParams {
  templateId: number;
  data: NotificationTemplateUpdate;
}

/**
 * Hook to update an existing notification template (admin only)
 */
export function useUpdateNotificationTemplate() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationTemplate,
    AxiosError<ApiErrorResponse>,
    UpdateNotificationTemplateParams
  >({
    mutationFn: async ({ templateId, data }: UpdateNotificationTemplateParams) => {
      const response = await api.put<NotificationTemplate>(
        API_ENDPOINTS.NOTIFICATION_TEMPLATES.UPDATE(templateId),
        data
      );
      return response.data;
    },
    onSuccess: (updatedTemplate) => {
      // Invalidate list queries
      queryClient.invalidateQueries({
        queryKey: notificationTemplateKeys.lists(),
      });
      // Update detail query cache
      queryClient.setQueryData(
        notificationTemplateKeys.detail(updatedTemplate.id),
        updatedTemplate
      );
    },
  });
}

// ============================================
// 🗑️ DELETE NOTIFICATION TEMPLATE MUTATION
// ============================================

/**
 * Hook to delete a notification template (admin only)
 *
 * Note: Cannot delete system templates or templates currently in use
 */
export function useDeleteNotificationTemplate() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (templateId: number) => {
      await api.delete(API_ENDPOINTS.NOTIFICATION_TEMPLATES.DELETE(templateId));
    },
    onSuccess: (_data, templateId) => {
      // Remove from cache
      queryClient.removeQueries({
        queryKey: notificationTemplateKeys.detail(templateId),
      });
      // Invalidate list queries
      queryClient.invalidateQueries({
        queryKey: notificationTemplateKeys.lists(),
      });
    },
  });
}
