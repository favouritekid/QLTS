// src/hooks/useSessions.ts
/**
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Sessions hooks for Server Components
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";

import {
  getActiveSessions,
  revokeSession,
  revokeAllOtherSessions,
  type UserSessionListResponse,
} from "@/lib/api/sessions";
import type { ApiErrorResponse } from "@/types/api.types";

// Query keys
export const sessionKeys = {
  all: ["sessions"] as const,
  list: () => [...sessionKeys.all, "list"] as const,
};

/**
 * Hook to fetch active sessions
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Added initialData support for SSR
 */
export function useSessions(options?: {
  initialData?: UserSessionListResponse;
}) {
  return useQuery<UserSessionListResponse, AxiosError<ApiErrorResponse>>({
    queryKey: sessionKeys.list(),
    queryFn: async () => {
      return await getActiveSessions();
    },
    initialData: options?.initialData,
    staleTime: 30 * 1000, // 30 seconds - sessions don't change often
  });
}

/**
 * Hook to revoke a specific session
 */
export function useRevokeSession() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (sessionId: number) => {
      await revokeSession(sessionId);
    },
    onSuccess: () => {
      // Invalidate sessions list to refetch
      queryClient.invalidateQueries({ queryKey: sessionKeys.all });
    },
  });
}

/**
 * Hook to revoke all other sessions
 */
export function useRevokeAllOtherSessions() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    { currentSessionId?: number }
  >({
    mutationFn: async ({ currentSessionId }) => {
      await revokeAllOtherSessions(currentSessionId);
    },
    onSuccess: () => {
      // Invalidate sessions list to refetch
      queryClient.invalidateQueries({ queryKey: sessionKeys.all });
    },
  });
}
