import { useQuery } from "@tanstack/react-query";
import { officerApi, type UpcomingActivitiesResponse } from "@/lib/api/officer";
import { officerKeys } from "./useWeeklyLeaderboard"; // Share keys
export type { ScheduleActivity } from "@/lib/api/officer"; // Re-export for UI


export function useOfficerSchedule(
  month: number,
  year: number,
  scope?: string,
  unitId?: number | null,
) {
  return useQuery<UpcomingActivitiesResponse>({
    queryKey: [...officerKeys.upcomingActivities(month, year), scope, unitId],
    queryFn: async () => {
      return officerApi.getUpcomingActivities(month, year, scope, unitId ?? undefined);
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}
