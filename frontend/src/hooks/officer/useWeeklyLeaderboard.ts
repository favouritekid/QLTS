import { useQuery } from "@tanstack/react-query";
import { officerApi, type WeeklyLeaderboardData } from "@/lib/api/officer";

export const officerKeys = {
  all: ["officer"] as const,
  leaderboard: () => [...officerKeys.all, "leaderboard"] as const,
  upcomingActivities: (month: number, year: number) => [...officerKeys.all, "upcoming-activities", month, year] as const,
  recommendations: (limit: number) => [...officerKeys.all, "recommendations", limit] as const,
  workload: () => [...officerKeys.all, "workload"] as const, // Placeholder for workload key if needed separately or part of dashboard
};

export function useWeeklyLeaderboard() {
  return useQuery<WeeklyLeaderboardData>({
    queryKey: officerKeys.leaderboard(),
    queryFn: async () => {
      return officerApi.getLeaderboard();
    },
    staleTime: 60000, // 1 minute
    refetchInterval: 300000, // 5 minutes
  });
}
