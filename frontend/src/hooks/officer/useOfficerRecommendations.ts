import { useQuery } from "@tanstack/react-query";
import { officerApi, type RecommendationsResponse } from "@/lib/api/officer";
import { officerKeys } from "./useWeeklyLeaderboard";
export type { Recommendation } from "@/lib/api/officer"; // Re-export for UI


export interface UseOfficerRecommendationsOptions {
  startDate?: string;
  endDate?: string;
  /** Disable query (e.g. when scope is not personal) */
  enabled?: boolean;
  /** Drill-down target officer (admin/manager only) */
  officerId?: number | null;
}

export function useOfficerRecommendations(
  limit: number = 5,
  options?: UseOfficerRecommendationsOptions,
) {
  return useQuery<RecommendationsResponse>({
    queryKey: [...officerKeys.recommendations(limit, options?.startDate, options?.endDate), options?.officerId],
    queryFn: async () => {
      return officerApi.getRecommendations(limit, options?.startDate, options?.endDate, options?.officerId ?? undefined);
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
    enabled: options?.enabled ?? true,
  });
}
