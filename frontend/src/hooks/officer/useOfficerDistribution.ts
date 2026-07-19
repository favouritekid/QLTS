import { useQuery } from "@tanstack/react-query";
import { officerApi } from "@/lib/api/officer";
import type { OfficerDistributionPanel } from "@/lib/zod/officer";
import { officerKeys } from "./useWeeklyLeaderboard";

export interface UseOfficerDistributionOptions {
  /**
   * Chỉ dùng cho admin chọn một đơn vị cụ thể. CỐ Ý không truyền `scope`:
   * backend tự suy theo role (officer → đơn vị của mình, manager → unit,
   * admin → organization), nên frontend không thể gửi sai scope.
   */
  unitId?: number | null;
  enabled?: boolean;
}

export function useOfficerDistribution(
  options?: UseOfficerDistributionOptions
) {
  const unitId = options?.unitId ?? undefined;

  return useQuery<OfficerDistributionPanel>({
    queryKey: officerKeys.distributionPanel(unitId ?? null),
    queryFn: async () => officerApi.getDistributionPanel({ unitId }),
    staleTime: 60000, // 1 phút
    refetchInterval: 300000, // 5 phút
    enabled: options?.enabled ?? true,
  });
}
