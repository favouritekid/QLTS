import { useQuery } from "@tanstack/react-query";
import { officerApi, type RecommendationsResponse } from "@/lib/api/officer";
import { officerKeys } from "./useWeeklyLeaderboard";
export type { Recommendation } from "@/lib/api/officer"; // Re-export for UI


export function useOfficerRecommendations(limit: number = 5) {
  return useQuery<RecommendationsResponse>({
    queryKey: officerKeys.recommendations(limit),
    queryFn: async () => {
      return officerApi.getRecommendations(limit);
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}
