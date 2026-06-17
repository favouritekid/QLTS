/**
 * useAdmissions Hook Tests
 *
 * BUG-14: useSubmitAdmission must invalidate lists() alongside detail().
 * BUG-16: All state-changing mutations must invalidate status-counts and stats
 *         using prefix keys [...all, "status-counts"] / [...all, "stats"]
 *         (not admissionsKeys.statusCounts() which adds trailing `undefined`).
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  useSubmitAdmission,
  useDeleteAdmission,
  useApproveAdmission,
  useEnrollStudent,
  useRecordApplicationFeePayment,
  admissionsKeys,
} from "./useAdmissions";
import { feesKeys } from "@/hooks/finance/useFees";
import { handleApiError } from "@/lib/error-handler";

// Mock next/navigation (required by hooks using useRouter)
const pushMock = vi.fn();
const replaceMock = vi.fn();
const backMock = vi.fn();
const prefetchMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: replaceMock,
    back: backMock,
    prefetch: prefetchMock,
  }),
  usePathname: () => "/admissions",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock status-config (used in onSuccess)
vi.mock("@/lib/status-config", () => ({
  getStatusConfig: (status: string) => ({
    label: status,
    bannerMessage: `Banner: ${status}`,
  }),
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

// Mock error handler
vi.mock("@/lib/error-handler", () => ({
  handleApiError: vi.fn(),
}));

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const MOCK_ADMISSION_ID = 99;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapperWithClient() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return { queryClient, Wrapper };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useAdmissions – BUG-14 & BUG-16 invalidation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  describe("useSubmitAdmission (BUG-14)", () => {
    it("should invalidate lists() on success", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/submit`,
          () =>
            HttpResponse.json({
              id: MOCK_ADMISSION_ID,
              status: "submitted",
              validation_errors: [],
            })
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useSubmitAdmission(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      act(() => {
        result.current.mutate(undefined);
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // BUG-14: lists() MUST be invalidated
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionsKeys.lists(),
        })
      );

      invalidateSpy.mockRestore();
    });

    it("should invalidate detail(id) on success", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/submit`,
          () =>
            HttpResponse.json({
              id: MOCK_ADMISSION_ID,
              status: "submitted",
              validation_errors: [],
            })
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useSubmitAdmission(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      act(() => {
        result.current.mutate(undefined);
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionsKeys.detail(MOCK_ADMISSION_ID),
        })
      );

      invalidateSpy.mockRestore();
    });
  });

  describe("BUG-16: status-counts and stats prefix invalidation", () => {
    it("useSubmitAdmission should invalidate status-counts with prefix key", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/submit`,
          () =>
            HttpResponse.json({
              id: MOCK_ADMISSION_ID,
              status: "submitted",
              validation_errors: [],
            })
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useSubmitAdmission(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      act(() => {
        result.current.mutate(undefined);
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // Must use prefix key ["admissions", "status-counts"] (no trailing undefined)
      const statusCountsCalls = invalidateSpy.mock.calls.filter(
        ([opts]) => {
          const key = (opts as { queryKey: readonly unknown[] }).queryKey;
          return (
            Array.isArray(key) &&
            key.length === 2 &&
            key[0] === "admissions" &&
            key[1] === "status-counts"
          );
        }
      );
      expect(statusCountsCalls.length).toBeGreaterThanOrEqual(1);

      invalidateSpy.mockRestore();
    });

    it("useSubmitAdmission should invalidate stats with prefix key", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/submit`,
          () =>
            HttpResponse.json({
              id: MOCK_ADMISSION_ID,
              status: "submitted",
              validation_errors: [],
            })
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useSubmitAdmission(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      act(() => {
        result.current.mutate(undefined);
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // Must use prefix key ["admissions", "stats"] (no trailing undefined)
      const statsCalls = invalidateSpy.mock.calls.filter(
        ([opts]) => {
          const key = (opts as { queryKey: readonly unknown[] }).queryKey;
          return (
            Array.isArray(key) &&
            key.length === 2 &&
            key[0] === "admissions" &&
            key[1] === "stats"
          );
        }
      );
      expect(statsCalls.length).toBeGreaterThanOrEqual(1);

      invalidateSpy.mockRestore();
    });

    it("useDeleteAdmission should invalidate status-counts and stats", async () => {
      server.use(
        http.delete(
          `${API_BASE_URL}/api/admissions/:id`,
          () => new HttpResponse(null, { status: 204 })
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useDeleteAdmission(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      act(() => {
        result.current.mutate();
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      const allKeys = invalidateSpy.mock.calls.map(
        ([opts]) => (opts as { queryKey: readonly unknown[] }).queryKey
      );

      // status-counts prefix
      expect(allKeys).toContainEqual(
        expect.arrayContaining(["admissions", "status-counts"])
      );

      // stats prefix
      expect(allKeys).toContainEqual(
        expect.arrayContaining(["admissions", "stats"])
      );

      invalidateSpy.mockRestore();
    });

    it("useApproveAdmission should invalidate status-counts and stats", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/approve`,
          () =>
            HttpResponse.json({
              id: MOCK_ADMISSION_ID,
              status: "approved",
            })
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useApproveAdmission(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      act(() => {
        result.current.mutate({ notes: "LGTM", version: 1 });
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      const allKeys = invalidateSpy.mock.calls.map(
        ([opts]) => (opts as { queryKey: readonly unknown[] }).queryKey
      );

      // status-counts prefix
      expect(allKeys).toContainEqual(
        expect.arrayContaining(["admissions", "status-counts"])
      );

      // stats prefix
      expect(allKeys).toContainEqual(
        expect.arrayContaining(["admissions", "stats"])
      );

      invalidateSpy.mockRestore();
    });
  });

  describe("application fee collection", () => {
    it("posts query params and invalidates admission plus finance caches", async () => {
      const captured: { url?: URL } = {};
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/record-fee-payment`,
          ({ request }) => {
            captured.url = new URL(request.url);
            return HttpResponse.json({
              id: MOCK_ADMISSION_ID,
              status: "submitted",
              applied_rules: {
                application_fee: 100000,
                requires_application_fee: true,
                fee_status: "paid",
                fee_paid_at: "2026-06-07T08:30:00Z",
                fee_payment_data: {
                  transaction_id: "RCPT-001",
                  amount: "100000",
                  payment_method_code: "cash",
                },
              },
            });
          }
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(
        () => useRecordApplicationFeePayment(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      await act(async () => {
        await result.current.mutateAsync({
          transaction_id: "RCPT-001",
          amount: 100000,
        });
      });

      expect(captured.url).toBeDefined();
      expect(captured.url?.searchParams.get("transaction_id")).toBe("RCPT-001");
      expect(captured.url?.searchParams.get("amount")).toBe("100000");
      expect(captured.url?.searchParams.get("payment_method_code")).toBe("cash");
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionsKeys.detail(MOCK_ADMISSION_ID),
        })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.lists() })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: feesKeys.profileSummary(MOCK_ADMISSION_ID),
        })
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: feesKeys.byProfile(MOCK_ADMISSION_ID),
        })
      );

      invalidateSpy.mockRestore();
    });

    it("routes backend errors through handleApiError", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/record-fee-payment`,
          () => HttpResponse.json({ detail: "Receipt already used" }, { status: 409 })
        )
      );

      const { Wrapper } = createWrapperWithClient();
      const { result } = renderHook(
        () => useRecordApplicationFeePayment(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      await act(async () => {
        await expect(
          result.current.mutateAsync({
            transaction_id: "RCPT-ERR",
            amount: 100000,
          })
        ).rejects.toBeTruthy();
      });

      expect(handleApiError).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          context: "thu lệ phí xét tuyển",
        })
      );
    });
  });

  describe("BUG-003: enroll redirect", () => {
    it("useEnrollStudent should redirect back to the admission detail route after enroll", async () => {
      vi.useFakeTimers();

      server.use(
        http.post(
          `${API_BASE_URL}/api/admissions/:id/enroll`,
          () =>
            HttpResponse.json({
              student_id: 321,
              student_code: "SV20260001",
              enrollment_date: new Date().toISOString(),
            })
        )
      );

      const { Wrapper } = createWrapperWithClient();

      const { result } = renderHook(
        () => useEnrollStudent(MOCK_ADMISSION_ID),
        { wrapper: Wrapper }
      );

      await act(async () => {
        await result.current.mutateAsync();
      });

      act(() => {
        vi.advanceTimersByTime(1500);
      });

      expect(replaceMock).toHaveBeenCalledWith(`/admissions/${MOCK_ADMISSION_ID}`);
      expect(pushMock).not.toHaveBeenCalledWith("/students/321");
    });
  });
});
