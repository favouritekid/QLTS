/**
 * Unit Tests for useFees Hook
 *
 * Tests cover:
 * - Query hooks: useFees, useFeeDetail, useFeesByProfile, useProfileFinanceSummary
 * - Mutation hooks: useCalculateFee, useWaiveFee, useCancelFee, useRecalculateFee
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  useFees,
  useFeeDetail,
  useFeesByProfile,
  useProfileFinanceSummary,
  useCalculateFee,
  useWaiveFee,
  useCancelFee,
  useRecalculateFee,
} from "./useFees";
import type { FeeDetail, FeeCalculateRequest, FeeWaiveRequest } from "@/types/finance.types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Test wrapper
function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

describe("useFees Hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Queries", () => {
    describe("useFees", () => {
      it("should fetch fees list successfully", async () => {
        const { result } = renderHook(() => useFees({ page: 1, page_size: 10 }), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.items).toBeDefined();
        expect(Array.isArray(result.current.data?.items)).toBe(true);
      });

      it("should fetch fees with status filter", async () => {
        const { result } = renderHook(
          () => useFees({ page: 1, page_size: 10, status: "calculated" }),
          { wrapper: createWrapper() }
        );

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => useFees({ page: 1 }, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("useFeeDetail", () => {
      it("should fetch a single fee by ID", async () => {
        const { result } = renderHook(() => useFeeDetail(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.id).toBe(1);
        expect(result.current.data?.fee_type).toBe("tuition");
      });

      it("should include nested data (invoices, installment_plan)", async () => {
        const { result } = renderHook(() => useFeeDetail(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.installment_plan).toBeDefined();
        expect(result.current.data?.invoices).toBeDefined();
        expect(Array.isArray(result.current.data?.invoices)).toBe(true);
      });

      it("should handle 404 error for non-existent fee", async () => {
        server.use(
          http.get(`${API_BASE_URL}/api/fees/:feeId`, () => {
            return HttpResponse.json({ detail: "Fee not found" }, { status: 404 });
          })
        );

        const { result } = renderHook(() => useFeeDetail(99999), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(() => useFeeDetail(1, { enabled: false }), {
          wrapper: createWrapper(),
        });

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("useFeesByProfile", () => {
      it("should fetch fees for a specific profile", async () => {
        const { result } = renderHook(() => useFeesByProfile(100), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(Array.isArray(result.current.data)).toBe(true);
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => useFeesByProfile(100, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("useProfileFinanceSummary", () => {
      it("should fetch finance summary for a profile", async () => {
        const { result } = renderHook(() => useProfileFinanceSummary(100), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.total_fees).toBeDefined();
        expect(result.current.data?.total_paid).toBeDefined();
      });

      it("should return empty fees array for profile without fees", async () => {
        // Profile 999 has no fees in mock data
        const { result } = renderHook(() => useProfileFinanceSummary(999), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data?.fees).toEqual([]);
        expect(result.current.data?.pending_invoices).toBe(0);
      });
    });
  });

  describe("Mutations", () => {
    describe("useCalculateFee", () => {
      it("should calculate fee successfully", async () => {
        const calculateData: FeeCalculateRequest = {
          admission_profile_id: 100,
          fee_type: "tuition",
          installment_plan_code: "FULL",
        };

        const { result } = renderHook(() => useCalculateFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate(calculateData);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.admission_profile_id).toBe(100);
        expect(result.current.data?.fee_type).toBe("tuition");
        expect(result.current.data?.status).toBe("calculated");
      });

      it("should return fee with permission flags", async () => {
        const calculateData: FeeCalculateRequest = {
          admission_profile_id: 100,
          fee_type: "tuition",
        };

        const { result } = renderHook(() => useCalculateFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate(calculateData);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data?.can_waive).toBeDefined();
        expect(result.current.data?.can_cancel).toBeDefined();
        expect(result.current.data?.can_recalculate).toBeDefined();
      });
    });

    describe("useWaiveFee", () => {
      it("should waive fee successfully", async () => {
        const waiveData: FeeWaiveRequest = {
          waive_amount: "1000000",
          reason: "Scholarship",
        };

        const { result } = renderHook(() => useWaiveFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ feeId: 1, data: waiveData });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.waived_amount).toBe(waiveData.waive_amount);
      });

      it("should handle waive error when fee cannot be waived", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/fees/:feeId/waive`, () => {
            return HttpResponse.json(
              { detail: "Fee cannot be waived" },
              { status: 400 }
            );
          })
        );

        const waiveData: FeeWaiveRequest = {
          waive_amount: "1000000",
          reason: "Invalid waive",
        };

        const { result } = renderHook(() => useWaiveFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ feeId: 2, data: waiveData });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });

    describe("useCancelFee", () => {
      it("should cancel fee successfully", async () => {
        const { result } = renderHook(() => useCancelFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ feeId: 1, reason: "Profile withdrawn" });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("cancelled");
      });

      it("should handle cancel error when fee cannot be cancelled", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/fees/:feeId/cancel`, () => {
            return HttpResponse.json(
              { detail: "Fee cannot be cancelled" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useCancelFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ feeId: 2, reason: "Cannot cancel" });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });

    describe("useRecalculateFee", () => {
      it("should recalculate fee successfully", async () => {
        const recalculateData = {
          new_base_amount: "15000000",
          reason: "Recalculate after policy update",
        };

        const { result } = renderHook(() => useRecalculateFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ feeId: 1, data: recalculateData });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.base_amount).toBe(recalculateData.new_base_amount);
        expect(result.current.data?.version).toBeGreaterThan(0);
      });

      it("should handle recalculate error when fee cannot be recalculated", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/fees/:feeId/recalculate`, () => {
            return HttpResponse.json(
              { detail: "Fee cannot be recalculated" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useRecalculateFee(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          feeId: 2,
          data: {
            new_base_amount: "20000000",
            reason: "Cannot recalculate",
          },
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });
  });

  describe("Error Handling", () => {
    it("should handle network error gracefully", async () => {
      server.use(
        http.get(`${API_BASE_URL}/api/fees`, () => {
          return HttpResponse.error();
        })
      );

      const { result } = renderHook(() => useFees({ page: 1 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toBeDefined();
    });

    it("should handle server error (500) gracefully", async () => {
      server.use(
        http.get(`${API_BASE_URL}/api/fees`, () => {
          return HttpResponse.json(
            { detail: "Internal server error" },
            { status: 500 }
          );
        })
      );

      const { result } = renderHook(() => useFees({ page: 1 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toBeDefined();
    });
  });
});
