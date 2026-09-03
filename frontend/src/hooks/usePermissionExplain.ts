// src/hooks/usePermissionExplain.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

interface PolicyRule {
  subject: string;
  object: string;
  action: string;
}

interface PermissionExplainResponse {
  role: string;
  policies_from_template: PolicyRule[];
  policies_from_features: PolicyRule[];
  policies_manual: PolicyRule[];
  policies_inherited?: PolicyRule[];
}

/**
 * Hook to explain where a role's permissions come from
 *
 * Fetches permission explanation showing which policies come from:
 * - System templates
 * - Enabled features
 * - Role inheritance (via grouping policies)
 * - Manual additions
 */
export function usePermissionExplain(roleName: string) {
  return useQuery<PermissionExplainResponse>({
    queryKey: ["admin", "roles", roleName, "explain"],
    queryFn: async () => {
      // Đường thật là `/roles/{role_name}/permissions/explain` (roles.py:1205);
      // bản cũ bỏ mất đoạn `/permissions` nên rơi vào 404. Dùng hằng để đoạn ấy
      // chỉ tồn tại ở MỘT chỗ.
      const response = await api.get<PermissionExplainResponse>(
        API_ENDPOINTS.ADMIN.PERMISSIONS.EXPLAIN(roleName)
      );
      return response.data;
    },
    enabled: !!roleName, // Only fetch if roleName is provided
  });
}
