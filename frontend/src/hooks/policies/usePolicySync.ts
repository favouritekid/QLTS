import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { policiesApi, type SyncStatus } from "@/lib/api/policies";
import { toast } from "sonner";
export type { SyncStatus } from "@/lib/api/policies"; // Re-export for UI


export const syncKeys = {
  status: ["policies", "sync-status"] as const,
};

export function usePolicySyncStatus() {
  return useQuery<SyncStatus>({
    queryKey: syncKeys.status,
    queryFn: async () => {
      return policiesApi.getSyncStatus();
    },
  });
}

export function useSyncPolicies() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (userIds: number[] | null) => {
      // If userIds is provided, sync specific users. Otherwise, full sync (if backend supports it via this endpoint or separate).
      // Based on SyncDashboard logic, it seems we want syncUsers here.
      return policiesApi.syncUsers(userIds);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: syncKeys.status });
      toast.success("Sync operation completed");
    },
    onError: () => {
      toast.error("Failed to synchronize");
    },
  });
}
