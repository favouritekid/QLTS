// src/hooks/usePermissionExplain.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

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
      const response = await api.get<PermissionExplainResponse>(
        `/api/admin/roles/${roleName}/explain`
      );
      return response.data;
    },
    enabled: !!roleName, // Only fetch if roleName is provided
  });
}
