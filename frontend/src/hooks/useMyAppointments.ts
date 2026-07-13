// src/hooks/useMyAppointments.ts
import { useQuery } from "@tanstack/react-query";

import {
  getMyAppointments,
  type MyAppointmentsResponse,
} from "@/lib/api/leads";

export const myAppointmentsKey = ["leads", "my-appointments"] as const;

/**
 * Lịch hẹn gọi lại của officer đang login ("Nhịp hẹn").
 *
 * Refetch mỗi 60s để re-bucket overdue/upcoming khi thời gian trôi (BE tính
 * is_overdue realtime). Đồng hồ đếm giây do component tự tick từ `server_time`.
 */
export function useMyAppointments(enabled = true) {
  return useQuery<MyAppointmentsResponse>({
    queryKey: myAppointmentsKey,
    queryFn: getMyAppointments,
    enabled,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });
}
