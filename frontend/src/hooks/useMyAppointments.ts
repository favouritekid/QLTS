// src/hooks/useMyAppointments.ts
import { useQuery } from "@tanstack/react-query";

import {
  getMyAppointments,
  type MyAppointmentsResponse,
} from "@/lib/api/leads";

export const myAppointmentsKey = ["leads", "my-appointments"] as const;

/** 403 = role bị Casbin deny (accountant/user) → ẩn widget + ngừng poll.
 *  Duck-typed để khỏi phụ thuộc kiểu AxiosError. */
export function isForbiddenError(err: unknown): boolean {
  return (
    (err as { response?: { status?: number } } | null | undefined)?.response
      ?.status === 403
  );
}

/**
 * Lịch hẹn gọi lại của officer đang login ("Nhịp hẹn").
 *
 * Refetch mỗi 60s để re-bucket overdue/upcoming khi thời gian trôi. Đồng hồ đếm
 * giây do component tự tick từ `server_time`.
 *
 * Role bị Casbin deny (accountant/user) → API trả 403: KHÔNG retry, KHÔNG poll
 * lại, KHÔNG refetch-on-focus (widget tự ẩn qua isForbiddenError) → tránh spam
 * 403 vô hạn + log noise.
 */
export function useMyAppointments(enabled = true) {
  return useQuery<MyAppointmentsResponse>({
    queryKey: myAppointmentsKey,
    queryFn: getMyAppointments,
    enabled,
    refetchInterval: (query) =>
      isForbiddenError(query.state.error) ? false : 60_000,
    refetchOnWindowFocus: (query) => !isForbiddenError(query.state.error),
    staleTime: 30_000,
    retry: (count, err) => !isForbiddenError(err) && count < 3,
  });
}
