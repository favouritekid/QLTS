// src/hooks/useNotificationRules.ts
/**
 * ✅ PHASE 2.4: React Query hooks for Notification Rules management
 *
 * Provides hooks for admin users to manage notification rules:
 * - List rules with pagination and filtering
 * - Get single rule details
 * - Create new rules
 * - Update existing rules
 * - Toggle enable/disable
 * - Delete rules
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiErrorResponse,
  NotificationRule,
  NotificationRuleCreate,
  NotificationRuleUpdate,
  NotificationRulesPage,
} from "@/types/api.types";

// ============================================
// 📋 QUERY KEYS
// ============================================

export const notificationRuleKeys = {
  all: ["notification-rules"] as const,
  lists: () => [...notificationRuleKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...notificationRuleKeys.lists(), params] as const,
  details: () => [...notificationRuleKeys.all, "detail"] as const,
  detail: (id: number) => [...notificationRuleKeys.details(), id] as const,
};

// ============================================
// 📊 NOTIFICATION RULES LIST QUERY
// ============================================

interface UseNotificationRulesParams {
  page?: number;
  page_size?: number;
  event?: string; // Filter by event type
  enabled?: boolean; // Filter by enabled status
}

/**
 * Hook to fetch paginated list of notification rules (admin only)
 */
export function useNotificationRules(params: UseNotificationRulesParams = {}) {
  const { page = 1, page_size = 50, event, enabled } = params;

  return useQuery<NotificationRulesPage, AxiosError<ApiErrorResponse>>({
    queryKey: notificationRuleKeys.list({ page, page_size, event, enabled }),
    queryFn: async () => {
      const response = await api.get<NotificationRulesPage>(
        API_ENDPOINTS.NOTIFICATION_RULES.LIST,
        {
          params: { page, page_size, event, enabled },
        }
      );
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });
}

// ============================================
// 📄 NOTIFICATION RULE DETAIL QUERY
// ============================================

/**
 * Hook to fetch single notification rule by ID (admin only)
 */
export function useNotificationRule(ruleId: number | undefined) {
  return useQuery<NotificationRule, AxiosError<ApiErrorResponse>>({
    queryKey: notificationRuleKeys.detail(ruleId!),
    queryFn: async () => {
      const response = await api.get<NotificationRule>(
        API_ENDPOINTS.NOTIFICATION_RULES.DETAIL(ruleId!)
      );
      return response.data;
    },
    enabled: !!ruleId, // Only fetch if ruleId is provided
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
}

// ============================================
// ➕ CREATE NOTIFICATION RULE MUTATION
// ============================================

/**
 * Hook to create a new notification rule (admin only)
 */
export function useCreateNotificationRule() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationRule,
    AxiosError<ApiErrorResponse>,
    NotificationRuleCreate
  >({
    mutationFn: async (data: NotificationRuleCreate) => {
      const response = await api.post<NotificationRule>(
        API_ENDPOINTS.NOTIFICATION_RULES.CREATE,
        data
      );
      return response.data;
    },
    onSuccess: () => {
      // Invalidate all list queries to refetch
      queryClient.invalidateQueries({ queryKey: notificationRuleKeys.lists() });
    },
  });
}

// ============================================
// ✏️ UPDATE NOTIFICATION RULE MUTATION
// ============================================

interface UpdateNotificationRuleParams {
  ruleId: number;
  data: NotificationRuleUpdate;
}

/**
 * Hook to update an existing notification rule (admin only)
 */
export function useUpdateNotificationRule() {
  const queryClient = useQueryClient();

  return useMutation<
    NotificationRule,
    AxiosError<ApiErrorResponse>,
    UpdateNotificationRuleParams
  >({
    mutationFn: async ({ ruleId, data }: UpdateNotificationRuleParams) => {
      const response = await api.put<NotificationRule>(
        API_ENDPOINTS.NOTIFICATION_RULES.UPDATE(ruleId),
        data
      );
      return response.data;
    },
    onSuccess: (updatedRule) => {
      // Invalidate list queries
      queryClient.invalidateQueries({ queryKey: notificationRuleKeys.lists() });
      // Update detail query cache
      queryClient.setQueryData(
        notificationRuleKeys.detail(updatedRule.id),
        updatedRule
      );
    },
  });
}

// ============================================
// 🔄 TOGGLE NOTIFICATION RULE MUTATION
// ============================================

/**
 * Hook to toggle enabled/disabled status of a notification rule (admin only)
 */
export function useToggleNotificationRule() {
  const queryClient = useQueryClient();

  return useMutation<NotificationRule, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (ruleId: number) => {
      const response = await api.patch<NotificationRule>(
        API_ENDPOINTS.NOTIFICATION_RULES.TOGGLE(ruleId)
      );
      return response.data;
    },
    onMutate: async (ruleId: number) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({
        queryKey: notificationRuleKeys.detail(ruleId),
      });

      // Snapshot previous value
      const previousRule = queryClient.getQueryData<NotificationRule>(
        notificationRuleKeys.detail(ruleId)
      );

      // Optimistically update
      if (previousRule) {
        queryClient.setQueryData<NotificationRule>(
          notificationRuleKeys.detail(ruleId),
          { ...previousRule, enabled: !previousRule.enabled }
        );
      }

      return { previousRule };
    },
    onError: (_err, ruleId, context) => {
      // Rollback on error
      const ctx = context as { previousRule?: NotificationRule } | undefined;
      if (ctx?.previousRule) {
        queryClient.setQueryData(
          notificationRuleKeys.detail(ruleId),
          ctx.previousRule
        );
      }
    },
    onSuccess: () => {
      // Invalidate list queries to reflect change
      queryClient.invalidateQueries({ queryKey: notificationRuleKeys.lists() });
    },
  });
}

// ============================================
// 🗑️ DELETE NOTIFICATION RULE MUTATION
// ============================================

/**
 * Hook to delete a notification rule (admin only)
 */
export function useDeleteNotificationRule() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (ruleId: number) => {
      await api.delete(API_ENDPOINTS.NOTIFICATION_RULES.DELETE(ruleId));
    },
    onSuccess: (_data, ruleId) => {
      // Remove from cache
      queryClient.removeQueries({
        queryKey: notificationRuleKeys.detail(ruleId),
      });
      // Invalidate list queries
      queryClient.invalidateQueries({ queryKey: notificationRuleKeys.lists() });
    },
  });
}

// ============================================
// ✅ NOTIFICATION 2.0: METADATA QUERY
// ============================================

/**
 * Hook to fetch notification metadata for dynamic rule builder (admin only)
 *
 * Returns:
 * - events: All available system events with metadata (display names, variables, filters)
 * - channels: Available delivery channels (socket, email, zalo, sms)
 * - resolver_types: Available recipient resolver types
 * - operators: Available condition operators
 */
export function useNotificationMetadata() {
  return useQuery<import("@/types/api.types").NotificationMetadata, AxiosError<ApiErrorResponse>>({
    queryKey: [...notificationRuleKeys.all, "metadata"] as const,
    queryFn: async () => {
      const response = await api.get<import("@/types/api.types").NotificationMetadata>(
        API_ENDPOINTS.NOTIFICATION_RULES.METADATA
      );
      return response.data;
    },
    staleTime: 30 * 60 * 1000, // 30 minutes (metadata rarely changes)
    gcTime: 60 * 60 * 1000, // 1 hour
  });
}
