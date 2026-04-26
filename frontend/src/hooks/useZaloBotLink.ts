// src/hooks/useZaloBotLink.ts
// v5 Step 21: React Query hooks for the Zalo Bot link flow.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { notificationPreferenceKeys } from "@/hooks/useNotificationPreferences";
import type {
  ApiErrorResponse,
  ZaloBotLinkCode,
  ZaloBotLinkStatus,
  ZaloBotUnlinkResult,
} from "@/types/api.types";

export const zaloBotKeys = {
  all: ["zaloBot"] as const,
  status: () => [...zaloBotKeys.all, "status"] as const,
};

export interface UseZaloBotLinkStatusOptions {
  /**
   * When `true`, refetch status every 5s. The settings UI flips this on
   * after the user clicks "Generate code" so the UI updates as soon as
   * the backend marks the link active. Polling stops once `is_linked`
   * is true (handled by ``refetchInterval`` returning ``false``).
   */
  pollWhileWaiting?: boolean;
}

const POLL_INTERVAL_MS = 5000;

export function useZaloBotLinkStatus(
  options?: UseZaloBotLinkStatusOptions,
) {
  return useQuery<ZaloBotLinkStatus, AxiosError<ApiErrorResponse>>({
    queryKey: zaloBotKeys.status(),
    queryFn: async () => {
      const response = await api.get<ZaloBotLinkStatus>(
        API_ENDPOINTS.ZALO_BOT.LINK_STATUS,
      );
      return response.data;
    },
    // 30s default freshness — plenty for the linked state. While the
    // user is waiting for the bot reply we override via refetchInterval.
    staleTime: 30 * 1000,
    refetchInterval: (query) => {
      if (!options?.pollWhileWaiting) return false;
      // Stop polling once the binding is active.
      const data = query.state.data as ZaloBotLinkStatus | undefined;
      return data?.is_linked ? false : POLL_INTERVAL_MS;
    },
  });
}

/**
 * Generate a fresh 6-char link code (TTL 600s on the backend). Each call
 * supersedes the previous code for this user — the backend revokes the
 * old code via its pointer key.
 */
export function useGenerateLinkCode() {
  const queryClient = useQueryClient();

  return useMutation<ZaloBotLinkCode, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      const response = await api.post<ZaloBotLinkCode>(
        API_ENDPOINTS.ZALO_BOT.LINK_CODE,
      );
      return response.data;
    },
    onSuccess: () => {
      // Status may still be unlinked at this point (the user has only
      // received the code, not typed it into Zalo yet). Invalidate
      // anyway so the polling query picks up immediately.
      queryClient.invalidateQueries({ queryKey: zaloBotKeys.status() });
    },
  });
}

/**
 * Unlink the caller's Zalo Bot binding. Backend POST (not DELETE) —
 * mirrors the link-service contract that flips ``zalo_bot_enabled``
 * alongside the link row. Invalidates both the link status and the
 * generic notification preferences cache so the settings UI re-reads
 * the new ``zalo_bot_enabled=false`` immediately.
 */
export function useUnlinkZaloBot() {
  const queryClient = useQueryClient();

  return useMutation<ZaloBotUnlinkResult, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      const response = await api.post<ZaloBotUnlinkResult>(
        API_ENDPOINTS.ZALO_BOT.UNLINK,
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: zaloBotKeys.status() });
      queryClient.invalidateQueries({
        queryKey: notificationPreferenceKeys.all,
      });
    },
  });
}
