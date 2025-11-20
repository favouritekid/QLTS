// src/hooks/usePolicySuggestions.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

interface PolicySuggestionsResponse {
  subjects: string[];
  objects: string[];
  actions: string[];
}

/**
 * Hook to fetch autocomplete suggestions for policy fields
 *
 * Returns unique lists of subjects, objects, and actions from existing policies.
 * Cached for 60 seconds to reduce API calls.
 *
 * @example
 * const { data } = usePolicySuggestions();
 * // data.subjects = ["role:admin", "role:manager", ...]
 * // data.objects = ["/api/leads", "/api/users", ...]
 * // data.actions = ["GET", "POST", ".*", ...]
 */
export function usePolicySuggestions() {
  return useQuery<PolicySuggestionsResponse>({
    queryKey: ["admin", "policies", "suggestions"],
    queryFn: async () => {
      const response = await api.get<PolicySuggestionsResponse>(
        `${API_ENDPOINTS.ADMIN.PERMISSIONS.POLICIES}/suggestions`
      );
      return response.data;
    },
    staleTime: 60000, // Cache for 60 seconds
    gcTime: 300000, // Keep in cache for 5 minutes
  });
}
