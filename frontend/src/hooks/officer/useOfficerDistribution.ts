import { useQuery } from "@tanstack/react-query";
import { ZodError } from "zod";
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
    // staleTime khớp refetchInterval: để 60s thì mỗi lần điều hướng lại trong
    // vòng 5 phút sẽ bắn thêm một request mà bản cache vẫn phục vụ được — mỗi
    // request là một fan-out aggregate đa-đơn-vị ở backend.
    staleTime: 300000,
    refetchInterval: 300000, // 5 phút
    enabled: options?.enabled ?? true,
    // Lỗi hợp đồng (zod parse) là DETERMINISTIC — retry chỉ lặp lại đúng lỗi đó
    // và nhân 4 lần fan-out backend. Chỉ retry lỗi mạng/5xx.
    retry: (failureCount, error) => {
      if (error instanceof ZodError) return false;
      return failureCount < 3;
    },
  });
}
