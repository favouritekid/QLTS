import { useQuery } from "@tanstack/react-query";
import { officerApi, type WeeklyLeaderboardData, type LeaderboardFilters } from "@/lib/api/officer";

export const officerKeys = {
  all: ["officer"] as const,
  leaderboard: (filters?: LeaderboardFilters) => [
    ...officerKeys.all,
    "leaderboard",
    filters?.startDate,
    filters?.endDate,
    filters?.scope,
    filters?.unitId,
    filters?.officerId,
  ] as const,
  upcomingActivities: (month: number, year: number) => [...officerKeys.all, "upcoming-activities", month, year] as const,
  recommendations: (limit: number, startDate?: string, endDate?: string) =>
    [...officerKeys.all, "recommendations", limit, startDate, endDate] as const,
  workload: () => [...officerKeys.all, "workload"] as const, // Placeholder for workload key if needed separately or part of dashboard
};

export interface UseWeeklyLeaderboardOptions {
  startDate?: string;
  endDate?: string;
  scope?: "personal" | "unit" | "organization";
  unitId?: number | null;
  officerId?: number | null;
}

export function useWeeklyLeaderboard(options?: UseWeeklyLeaderboardOptions) {
  const filters: LeaderboardFilters = {
    startDate: options?.startDate,
    endDate: options?.endDate,
    scope: options?.scope,
    unitId: options?.unitId ?? undefined,
    officerId: options?.officerId ?? undefined,
  };

  return useQuery<WeeklyLeaderboardData>({
    queryKey: officerKeys.leaderboard(filters),
    queryFn: async () => {
      return officerApi.getLeaderboard(filters);
    },
    staleTime: 60000, // 1 minute
    refetchInterval: 300000, // 5 minutes
  });
}
