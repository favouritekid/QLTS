// src/hooks/usePolicies.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { activityLogsKeys } from "@/hooks/useActivityLogs";
import type {
  RolesListResponse,
  TemplatesListResponse,
  PolicyRule,
  PolicyCreateRequest,
  PolicyBatchRequest,
  PolicyBatchResult,
  PolicyValidationRequest,
  PolicyValidationResult,
  TemplateApplicationRequest,
  PolicyStatistics,
} from "@/types/policy.types";

// MỘT đường phục vụ cả POST (roles.py:558) lẫn DELETE (roles.py:639) grouping
// policy. Bí danh cục bộ để hai hook bên dưới KHÔNG THỂ trôi lệch nhau — bản cũ
// hardcode chuỗi ở cả hai chỗ và cả hai cùng thiếu `/roles`.
const GROUPING_POLICIES = API_ENDPOINTS.ADMIN.PERMISSIONS.GROUPING_POLICIES;

// Query keys
export const policyKeys = {
  all: ["policies"] as const,
  lists: () => [...policyKeys.all, "list"] as const,
  list: () => [...policyKeys.lists()] as const,
  roles: () => [...policyKeys.all, "roles"] as const,
  templates: () => [...policyKeys.all, "templates"] as const,
  statistics: () => [...policyKeys.all, "statistics"] as const,
};

// Get all policies
export function usePolicies() {
  return useQuery<PolicyRule[]>({
    queryKey: policyKeys.list(),
    queryFn: async () => {
      const response = await api.get<string[][]>(API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES);
      // Convert from Casbin format [[subject, object, action]] to PolicyRule[]
      return response.data.map((p) => ({
        subject: p[0],
        object: p[1],
        action: p[2],
      })) as PolicyRule[];
    },
  });
}

// Get all roles
export function useRoles() {
  return useQuery<RolesListResponse>({
    queryKey: policyKeys.roles(),
    queryFn: async () => {
      const response = await api.get<RolesListResponse>(API_ENDPOINTS.ADMIN.PERMISSIONS.ROLES);
      return response.data;
    },
  });
}

// Get all templates
export function useTemplates() {
  return useQuery<TemplatesListResponse>({
    queryKey: policyKeys.templates(),
    queryFn: async () => {
      const response = await api.get<TemplatesListResponse>(API_ENDPOINTS.ADMIN.PERMISSIONS.TEMPLATES);
      return response.data;
    },
  });
}

// Get policy statistics
export function usePolicyStatistics(options?: { initialData?: PolicyStatistics }) {
  return useQuery<PolicyStatistics>({
    queryKey: policyKeys.statistics(),
    queryFn: async () => {
      const response = await api.get<PolicyStatistics>(API_ENDPOINTS.ADMIN.PERMISSIONS.STATISTICS);
      return response.data;
    },
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 4: Support SSR
  });
}

// Add single policy
export function useAddPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (policy: PolicyCreateRequest) => {
      const response = await api.post(API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES, policy);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: policyKeys.all });
      queryClient.invalidateQueries({ queryKey: activityLogsKeys.all });
    },
  });
}

// Delete policy
export function useDeletePolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (policy: PolicyCreateRequest) => {
      const response = await api.delete(API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES, {
        data: policy,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: policyKeys.all });
      queryClient.invalidateQueries({ queryKey: activityLogsKeys.all });
    },
  });
}

// Batch add policies
export function useBatchAddPolicies() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: PolicyBatchRequest) => {
      const response = await api.post<PolicyBatchResult>(
        API_ENDPOINTS.ADMIN.PERMISSIONS.BATCH,
        request
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: policyKeys.all });
      queryClient.invalidateQueries({ queryKey: activityLogsKeys.all });
    },
  });
}

// Validate policy operation
export function useValidatePolicy() {
  return useMutation({
    mutationFn: async (request: PolicyValidationRequest) => {
      const response = await api.post<PolicyValidationResult>(
        API_ENDPOINTS.ADMIN.PERMISSIONS.VALIDATE,
        request
      );
      return response.data;
    },
  });
}

// Apply template to role
export function useApplyTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: TemplateApplicationRequest) => {
      const response = await api.post<PolicyBatchResult>(
        API_ENDPOINTS.ADMIN.PERMISSIONS.APPLY_TEMPLATE,
        request
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: policyKeys.all });
      queryClient.invalidateQueries({ queryKey: activityLogsKeys.all });
    },
  });
}

// Add grouping policy (role inheritance or user-role assignment)
//
// Cả hai hook dưới đây đọc CÙNG hằng `GROUPING_POLICIES`. Backend phục vụ POST
// (roles.py:558) và DELETE (roles.py:639) trên đúng MỘT đường, nên tách thành
// hai chuỗi chỉ tạo cơ hội cho một nửa trôi đi mà nửa kia vẫn xanh.
// Bản cũ hardcode `/api/admin/grouping-policies` ở CẢ HAI — thiếu `/roles` ⇒ 404.
export function useAddGroupingPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: { subject: string; parent_role: string }) => {
      const response = await api.post(GROUPING_POLICIES, request);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: policyKeys.all });
      queryClient.invalidateQueries({ queryKey: activityLogsKeys.all });
    },
  });
}

// Remove grouping policy
//
// Chưa có caller ở thời điểm sửa, nhưng vẫn vá cùng lượt: nó mắc ĐÚNG lỗi thiếu
// `/roles` như bản POST, và để lại một nửa là tái diễn cái bẫy đã ghi ở `0b87ac4e`
// (sửa một hằng, bỏ hằng anh em, rồi lỗi quay lại qua đường còn sót).
export function useDeleteGroupingPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: { subject: string; parent_role: string }) => {
      // Axios: `delete(url, config)` — payload BẮT BUỘC đi trong `config.data`,
      // truyền như đối số vị trí thứ hai thì backend nhận body rỗng và trả 422.
      const response = await api.delete(GROUPING_POLICIES, { data: request });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: policyKeys.all });
      queryClient.invalidateQueries({ queryKey: activityLogsKeys.all });
    },
  });
}
