// src/hooks/policies/usePolicySync.test.tsx
/**
 * useSyncPolicies — HTTP 200 KHÔNG phải bằng chứng đã đồng bộ xong.
 *
 * Backend trả `{synced_count, failed_count}`. Bản cũ toast
 * "Sync operation completed" cho MỌI phản hồi 2xx, kể cả khi `failed_count > 0`
 * — cùng một lớp lỗi với hai chỗ kia: báo thành công cho việc chưa xảy ra.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({
  getSyncStatus: vi.fn(),
  syncUsers: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: hoisted.toastSuccess,
    error: hoisted.toastError,
  },
}));

vi.mock("@/lib/api/policies", () => ({
  policiesApi: {
    getSyncStatus: () => hoisted.getSyncStatus(),
    syncUsers: (userIds: number[] | null) => hoisted.syncUsers(userIds),
  },
}));

import { useSyncPolicies } from "./usePolicySync";

function messageOf(call: unknown[] | undefined): string {
  const first = call?.[0];
  return typeof first === "string" ? first : "";
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

async function runSync() {
  const { result } = renderHook(() => useSyncPolicies(), {
    wrapper: makeWrapper(),
  });

  act(() => {
    result.current.mutate(null);
  });

  // Chờ mutation THỰC SỰ settle — `isPending === false` cũng đúng ở thời điểm
  // trước khi mutate kịp chạy, nên nó không phải mốc chờ hợp lệ.
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  return result;
}

describe("useSyncPolicies", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("failed_count > 0 ⇒ KHÔNG toast thành công", async () => {
    hoisted.syncUsers.mockResolvedValue({ synced_count: 3, failed_count: 2 });

    await runSync();

    expect(hoisted.toastSuccess).not.toHaveBeenCalled();
    const message = messageOf(hoisted.toastError.mock.calls[0]);
    expect(message).toContain("MỘT PHẦN");
    expect(message).toContain("3");
    expect(message).toContain("2");
  });

  it("backend không trả số liệu ⇒ KHÔNG toast thành công", async () => {
    hoisted.syncUsers.mockResolvedValue({});

    await runSync();

    expect(hoisted.toastSuccess).not.toHaveBeenCalled();
    expect(hoisted.toastError).toHaveBeenCalledTimes(1);
  });

  it("CA ĐỐI CHỨNG: failed_count = 0 ⇒ mới toast thành công", async () => {
    hoisted.syncUsers.mockResolvedValue({ synced_count: 5, failed_count: 0 });

    await runSync();

    expect(hoisted.toastError).not.toHaveBeenCalled();
    expect(messageOf(hoisted.toastSuccess.mock.calls[0])).toContain(
      "Đã đồng bộ 5 user"
    );
  });
});
