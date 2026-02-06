/**
 * Unit Tests for useInvoices Hook
 *
 * Tests cover:
 * - Query hooks: useInvoices, useInvoiceDetail, useInvoicesByFee
 * - Mutation hooks: useIssueInvoice, useCancelInvoice, useApplyPenalty
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  useInvoices,
  useInvoiceDetail,
  useInvoicesByFee,
  useIssueInvoice,
  useCancelInvoice,
  useApplyPenalty,
} from "./useInvoices";
import type { InvoicePenaltyRequest } from "@/types/finance.types";

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

describe("useInvoices Hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Queries", () => {
    describe("useInvoices", () => {
      it("should fetch invoices list successfully", async () => {
        const { result } = renderHook(() => useInvoices({ page: 1, page_size: 10 }), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.items).toBeDefined();
        expect(Array.isArray(result.current.data?.items)).toBe(true);
      });

      it("should fetch invoices with status filter", async () => {
        const { result } = renderHook(
          () => useInvoices({ page: 1, page_size: 10, status: "issued" }),
          { wrapper: createWrapper() }
        );

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => useInvoices({ page: 1 }, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("useInvoiceDetail", () => {
      it("should fetch a single invoice by ID", async () => {
        const { result } = renderHook(() => useInvoiceDetail(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.id).toBe(1);
        expect(result.current.data?.invoice_number).toBeDefined();
      });

      it("should include nested data (fee, payments)", async () => {
        const { result } = renderHook(() => useInvoiceDetail(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.fee).toBeDefined();
        expect(result.current.data?.payments).toBeDefined();
        expect(Array.isArray(result.current.data?.payments)).toBe(true);
      });

      it("should handle 404 error for non-existent invoice", async () => {
        server.use(
          http.get(`${API_BASE_URL}/api/invoices/:invoiceId`, () => {
            return HttpResponse.json(
              { detail: "Invoice not found" },
              { status: 404 }
            );
          })
        );

        const { result } = renderHook(() => useInvoiceDetail(99999), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => useInvoiceDetail(1, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("useInvoicesByFee", () => {
      it("should fetch invoices for a specific fee", async () => {
        const { result } = renderHook(() => useInvoicesByFee(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(Array.isArray(result.current.data)).toBe(true);
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => useInvoicesByFee(1, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });
  });

  describe("Mutations", () => {
    describe("useIssueInvoice", () => {
      it("should issue invoice successfully", async () => {
        // Override with a draft invoice that can be issued
        server.use(
          http.post(`${API_BASE_URL}/api/invoices/:invoiceId/issue`, () => {
            return HttpResponse.json({
              id: 1,
              fee_id: 1,
              invoice_number: "INV-2025-000001",
              installment_no: 1,
              amount: "13500000",
              paid_amount: "0",
              remaining_amount: "13500000",
              penalty_amount: "0",
              total_due: "13500000",
              due_date: "2025-03-01",
              status: "issued",
              issued_at: new Date().toISOString(),
              issued_by_id: 1,
              can_issue: false,
              can_cancel: true,
              can_record_payment: true,
              can_apply_penalty: false,
            });
          })
        );

        const { result } = renderHook(() => useIssueInvoice(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ invoiceId: 1, feeId: 1 });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("issued");
        expect(result.current.data?.issued_at).toBeDefined();
      });

      it("should handle issue error when invoice cannot be issued", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/invoices/:invoiceId/issue`, () => {
            return HttpResponse.json(
              { detail: "Invoice cannot be issued" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useIssueInvoice(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ invoiceId: 2, feeId: 2 });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });

    describe("useCancelInvoice", () => {
      it("should cancel invoice successfully", async () => {
        const { result } = renderHook(() => useCancelInvoice(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          invoiceId: 1,
          feeId: 1,
          reason: "Data entry error",
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("cancelled");
        expect(result.current.data?.cancelled_at).toBeDefined();
      });

      it("should handle cancel error when invoice cannot be cancelled", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/invoices/:invoiceId/cancel`, () => {
            return HttpResponse.json(
              { detail: "Invoice cannot be cancelled" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useCancelInvoice(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          invoiceId: 2,
          feeId: 2,
          reason: "Cannot cancel",
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });

    describe("useApplyPenalty", () => {
      it("should apply penalty successfully", async () => {
        // Override with an overdue invoice that can have penalty
        server.use(
          http.post(`${API_BASE_URL}/api/invoices/:invoiceId/penalty`, async ({ request }) => {
            const body = (await request.json()) as InvoicePenaltyRequest;
            return HttpResponse.json({
              id: 1,
              fee_id: 1,
              invoice_number: "INV-2025-000001",
              installment_no: 1,
              amount: "13500000",
              paid_amount: "0",
              remaining_amount: "13500000",
              penalty_amount: body.penalty_amount,
              total_due: (13500000 + parseFloat(body.penalty_amount)).toString(),
              due_date: "2025-03-01",
              status: "overdue",
              can_issue: false,
              can_cancel: false,
              can_record_payment: true,
              can_apply_penalty: true,
            });
          })
        );

        const penaltyData: InvoicePenaltyRequest = {
          penalty_amount: "500000",
          reason: "30 days overdue",
        };

        const { result } = renderHook(() => useApplyPenalty(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          invoiceId: 1,
          feeId: 1,
          data: penaltyData,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("overdue");
      });

      it("should handle penalty error when cannot apply penalty", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/invoices/:invoiceId/penalty`, () => {
            return HttpResponse.json(
              { detail: "Cannot apply penalty to this invoice" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useApplyPenalty(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          invoiceId: 2,
          feeId: 2,
          data: { penalty_amount: "100000" },
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });
  });

  describe("Error Handling", () => {
    it("should handle network error gracefully", async () => {
      server.use(
        http.get(`${API_BASE_URL}/api/invoices`, () => {
          return HttpResponse.error();
        })
      );

      const { result } = renderHook(() => useInvoices({ page: 1 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toBeDefined();
    });
  });
});
