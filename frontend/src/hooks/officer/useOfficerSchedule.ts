import { useQuery } from "@tanstack/react-query";
import { officerApi, type UpcomingActivitiesResponse } from "@/lib/api/officer";
import { officerKeys } from "./useWeeklyLeaderboard"; // Share keys
export type { ScheduleActivity } from "@/lib/api/officer"; // Re-export for UI


export function useOfficerSchedule(
  month: number,
  year: number,
  scope?: string,
  unitId?: number | null,
  officerId?: number | null,
) {
  return useQuery<UpcomingActivitiesResponse>({
    queryKey: [...officerKeys.upcomingActivities(month, year), scope, unitId, officerId],
    queryFn: async () => {
      return officerApi.getUpcomingActivities(month, year, scope, unitId ?? undefined, officerId ?? undefined);
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}
