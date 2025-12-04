// src/hooks/useActivityLogs.ts
import { useQuery } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ActivityLogsPage,
  ApiErrorResponse,
  UserStatistics,
} from "@/types/api.types";

// ============================================
// 📋 QUERY KEYS
// ============================================

export const activityLogsKeys = {
  all: ["admin", "activity-logs"] as const,
  lists: () => [...activityLogsKeys.all, "list"] as const,
  list: (filters: Record<string, unknown>) =>
    [...activityLogsKeys.lists(), filters] as const,
  statistics: () => ["admin", "statistics"] as const,
};

// ============================================
// 📊 ACTIVITY LOGS LIST QUERY
// ============================================

interface UseActivityLogsParams {
  page?: number;
  page_size?: number;
  actor_id?: number;
  target_user_id?: number;
  action?: string;
  resource_type?: string;
}

export function useActivityLogs(params: UseActivityLogsParams = {}) {
  const { page = 1, page_size = 50, ...filters } = params;

  return useQuery<ActivityLogsPage, AxiosError<ApiErrorResponse>>({
    queryKey: activityLogsKeys.list({ page, page_size, ...filters }),
    queryFn: async () => {
      const response = await api.get<ActivityLogsPage>(
        API_ENDPOINTS.ADMIN.ACTIVITY_LOGS,
        {
          params: { page, page_size, ...filters },
        }
      );
      return response.data;
    },
    staleTime: 30000, // 30 seconds
  });
}

// ============================================
// 📈 USER STATISTICS QUERY
// ============================================

/**
 * ✅ PHASE 1 - WEEK 3 - DAY 2: Added initialData support for SSR
 */
interface UseUserStatisticsOptions {
  enabled?: boolean;
  initialData?: UserStatistics;
}

export function useUserStatistics(options: UseUserStatisticsOptions = {}) {
  return useQuery<UserStatistics, AxiosError<ApiErrorResponse>>({
    queryKey: activityLogsKeys.statistics(),
    queryFn: async () => {
      const response = await api.get<UserStatistics>(
        API_ENDPOINTS.ADMIN.STATISTICS
      );
      return response.data;
    },
    initialData: options.initialData, // ✅ PHASE 1 - WEEK 3 - DAY 2: SSR support
    staleTime: 60000, // 1 minute
    enabled: options.enabled !== false, // Default to true, but allow disabling
  });
}
