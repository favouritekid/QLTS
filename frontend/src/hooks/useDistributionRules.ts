// src/hooks/useDistributionRules.ts
/**
 * React Query hooks for Distribution Rules Management
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api/client";

// Type definitions
export interface DistributionRule {
  id: number;
  offering_id: number;
  unit_id: number;
  weight: number;
  priority: number;
  is_active: boolean;
  offering_name?: string;
  unit_name?: string;
}

// =============================================================================
// QUERY KEYS
// =============================================================================

export const distributionRuleKeys = {
  all: ["distribution-rules"] as const,
  lists: () => [...distributionRuleKeys.all, "list"] as const,
};

// =============================================================================
// QUERIES
// =============================================================================

/**
 * Hook to fetch distribution rules list
 */
export function useDistributionRules(options?: { initialData?: DistributionRule[] }) {
  return useQuery({
    queryKey: distributionRuleKeys.lists(),
    queryFn: async () => {
      const res = await api.get<DistributionRule[]>("/api/admin/distribution-rules");
      return res.data;
    },
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 3: Support SSR
  });
}

// =============================================================================
// MUTATIONS
// =============================================================================

/**
 * Delete single rule mutation
 */
export function useDeleteDistributionRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: number) => {
      return api.delete(`/api/admin/distribution-rules/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: distributionRuleKeys.lists() });
      toast.success("Đã xóa luật phân phối thành công");
    },
    onError: () => {
      toast.error("Không thể xóa luật phân phối");
    },
  });
}

/**
 * Bulk delete mutation
 */
export function useBulkDeleteDistributionRules() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (ids: number[]) => {
      await Promise.all(ids.map(id => api.delete(`/api/admin/distribution-rules/${id}`)));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: distributionRuleKeys.lists() });
      toast.success("Đã xóa các luật phân phối đã chọn");
    },
    onError: () => {
      toast.error("Không thể xóa các luật phân phối");
    },
  });
}

/**
 * Toggle active status mutation
 */
export function useToggleDistributionRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, isActive }: { id: number; isActive: boolean }) => {
      return api.put(`/api/admin/distribution-rules/${id}`, { is_active: isActive });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: distributionRuleKeys.lists() });
      toast.success("Đã cập nhật trạng thái thành công");
    },
    onError: () => toast.error("Không thể cập nhật trạng thái"),
  });
}
