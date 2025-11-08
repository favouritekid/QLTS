// src/hooks/useCasbinPolicies.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { toast } from "sonner";
import type { PolicyCreate, ApiErrorResponse } from "@/types/api.types";
import { AxiosError } from "axios";

// Query key factory
export const casbinPoliciesKeys = {
  all: ["casbin", "policies"] as const,
  lists: () => [...casbinPoliciesKeys.all, "list"] as const,
};

// ============================================
// 📋 GET ALL POLICIES QUERY
// ============================================

export function useCasbinPolicies() {
  return useQuery<string[][], AxiosError<ApiErrorResponse>>({
    queryKey: casbinPoliciesKeys.lists(),
    queryFn: async () => {
      const response = await api.get<string[][]>(API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES);
      return response.data;
    },
    staleTime: 30 * 1000, // 30 seconds
  });
}

// ============================================
// ➕ ADD POLICY MUTATION
// ============================================

export function useAddPolicy() {
  const queryClient = useQueryClient();

  return useMutation<{ detail: string }, AxiosError<ApiErrorResponse>, PolicyCreate>({
    mutationFn: async (data) => {
      const response = await api.post<{ detail: string }>(
        API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES,
        data
      );
      return response.data;
    },
    onSuccess: () => {
      toast.success("Policy added successfully!");
      queryClient.invalidateQueries({ queryKey: casbinPoliciesKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to add policy";
      toast.error(typeof message === "string" ? message : "Failed to add policy");
    },
  });
}

// ============================================
// 🗑️ DELETE POLICY MUTATION
// ============================================

export function useDeletePolicy() {
  const queryClient = useQueryClient();

  return useMutation<{ detail: string }, AxiosError<ApiErrorResponse>, PolicyCreate>({
    mutationFn: async (data) => {
      const response = await api.delete<{ detail: string }>(
        API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES,
        { data }
      );
      return response.data;
    },
    onSuccess: () => {
      toast.success("Policy deleted successfully!");
      queryClient.invalidateQueries({ queryKey: casbinPoliciesKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to delete policy";
      toast.error(typeof message === "string" ? message : "Failed to delete policy");
    },
  });
}
