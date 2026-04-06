/**
 * Unit Tests for usePayments Hook
 *
 * Tests cover:
 * - Query hooks: usePayments, usePaymentDetail, usePaymentsByInvoice, usePaymentIntent
 * - Mutation hooks (Maker-Checker): useCreatePayment, useVerifyPayment, useRejectPayment
 * - Online Payment: useCreatePaymentIntent
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  usePayments,
  usePaymentDetail,
  usePaymentsByInvoice,
  usePaymentIntent,
  useCreatePayment,
  useVerifyPayment,
  useRejectPayment,
  useCreatePaymentIntent,
} from "./usePayments";
import type {
  PaymentCreateRequest,
  PaymentRejectRequest,
  PaymentIntentCreateRequest,
} from "@/types/finance.types";

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

describe("usePayments Hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Queries", () => {
    describe("usePayments", () => {
      it("should fetch payments list successfully", async () => {
        const { result } = renderHook(() => usePayments({ page: 1, page_size: 10 }), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.items).toBeDefined();
        expect(Array.isArray(result.current.data?.items)).toBe(true);
      });

      it("should fetch pending payments for verification queue", async () => {
        const { result } = renderHook(
          () => usePayments({ page: 1, page_size: 10, status: "pending" }),
          { wrapper: createWrapper() }
        );

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => usePayments({ page: 1 }, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("usePaymentDetail", () => {
      it("should fetch a single payment by ID", async () => {
        const { result } = renderHook(() => usePaymentDetail(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.id).toBe(1);
        expect(result.current.data?.status).toBeDefined();
      });

      it("should include permission flags (can_verify, can_reject)", async () => {
        const { result } = renderHook(() => usePaymentDetail(2), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(typeof result.current.data?.can_verify).toBe("boolean");
        expect(typeof result.current.data?.can_reject).toBe("boolean");
      });

      it("should handle 404 error for non-existent payment", async () => {
        server.use(
          http.get(`${API_BASE_URL}/api/payments/:paymentId`, () => {
            return HttpResponse.json(
              { detail: "Payment not found" },
              { status: 404 }
            );
          })
        );

        const { result } = renderHook(() => usePaymentDetail(99999), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => usePaymentDetail(1, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("usePaymentsByInvoice", () => {
      it("should fetch payments for a specific invoice", async () => {
        const { result } = renderHook(() => usePaymentsByInvoice(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(Array.isArray(result.current.data)).toBe(true);
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => usePaymentsByInvoice(1, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("usePaymentIntent", () => {
      it("should fetch payment intent by ID", async () => {
        server.use(
          http.get(`${API_BASE_URL}/api/payments/intents/:intentId`, () => {
            return HttpResponse.json({
              id: 1,
              invoice_id: 1,
              method_id: 3,
              amount: "5000000",
              currency: "VND",
              gateway_ref: "GW-123",
              idempotency_key: "test-key",
              status: "pending",
              expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
              pay_url: "https://vnpay.vn/pay?token=test",
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            });
          })
        );

        const { result } = renderHook(() => usePaymentIntent(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.id).toBe(1);
        expect(result.current.data?.pay_url).toBeDefined();
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(
          () => usePaymentIntent(1, { enabled: false }),
          { wrapper: createWrapper() }
        );

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });
  });

  describe("Mutations - Maker-Checker Workflow", () => {
    describe("useCreatePayment (Maker)", () => {
      it("should create payment with pending status", async () => {
        const paymentData: PaymentCreateRequest = {
          invoice_id: 1,
          method_id: 1,
          amount: "5000000",
          reference_code: "BANK-12345",
          payer_name: "Nguyen Van A",
        };

        const { result } = renderHook(() => useCreatePayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          data: paymentData,
          invoiceId: 1,
          feeId: 1,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("pending");
        expect(result.current.data?.can_verify).toBe(true);
        expect(result.current.data?.can_reject).toBe(true);
      });

      it("should handle error when payment amount exceeds remaining", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/payments`, () => {
            return HttpResponse.json(
              { detail: "Payment amount exceeds remaining amount" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useCreatePayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          data: {
            invoice_id: 1,
            method_id: 1,
            amount: "99999999999",
          },
          invoiceId: 1,
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });

    describe("useVerifyPayment (Checker)", () => {
      it("should verify payment successfully", async () => {
        const { result } = renderHook(() => useVerifyPayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          paymentId: 2,
          invoiceId: 1,
          feeId: 1,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("verified");
        expect(result.current.data?.verified_at).toBeDefined();
        expect(result.current.data?.verified_by_id).toBeDefined();
      });

      it("should handle maker-checker violation (same user cannot verify)", async () => {
        server.use(
          http.put(`${API_BASE_URL}/api/payments/:paymentId/verify`, () => {
            return HttpResponse.json(
              { detail: "Maker cannot verify own payment" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useVerifyPayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          paymentId: 1,
          invoiceId: 1,
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });

      it("should handle error when payment cannot be verified", async () => {
        server.use(
          http.put(`${API_BASE_URL}/api/payments/:paymentId/verify`, () => {
            return HttpResponse.json(
              { detail: "Payment cannot be verified" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useVerifyPayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          paymentId: 1,
          invoiceId: 1,
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });

    describe("useRejectPayment (Checker)", () => {
      it("should reject payment successfully with reason", async () => {
        const rejectData: PaymentRejectRequest = {
          rejection_reason: "Amount does not match bank statement",
        };

        const { result } = renderHook(() => useRejectPayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          paymentId: 2,
          invoiceId: 1,
          feeId: 1,
          data: rejectData,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("rejected");
        expect(result.current.data?.rejected_at).toBeDefined();
        expect(result.current.data?.rejection_reason).toBe(rejectData.rejection_reason);
      });

      it("should handle error when payment cannot be rejected", async () => {
        server.use(
          http.put(`${API_BASE_URL}/api/payments/:paymentId/reject`, () => {
            return HttpResponse.json(
              { detail: "Payment cannot be rejected" },
              { status: 400 }
            );
          })
        );

        const { result } = renderHook(() => useRejectPayment(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          paymentId: 1,
          invoiceId: 1,
          data: { rejection_reason: "Test" },
        });

        await waitFor(() => expect(result.current.isError).toBe(true));

        expect(result.current.error).toBeDefined();
      });
    });
  });

  describe("Mutations - Online Payment", () => {
    describe("useCreatePaymentIntent", () => {
      it("should create payment intent successfully", async () => {
        const intentData: PaymentIntentCreateRequest = {
          invoice_id: 1,
          method_id: 3, // VNPay
          amount: "5000000",
          idempotency_key: "test-uuid-123",
          return_url: "http://localhost:3000/finance/payments/return",
        };

        const mockOnPayUrl = vi.fn();

        const { result } = renderHook(() => useCreatePaymentIntent(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          data: intentData,
          onPayUrl: mockOnPayUrl,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.pay_url).toBeDefined();
        expect(result.current.data?.status).toBe("created");

        // Verify onPayUrl callback was called with the pay_url
        expect(mockOnPayUrl).toHaveBeenCalledWith(expect.stringContaining("https://"));
      });

      it("should include gateway reference in response", async () => {
        const intentData: PaymentIntentCreateRequest = {
          invoice_id: 1,
          method_id: 3,
          amount: "5000000",
          idempotency_key: "test-uuid-456",
        };

        const { result } = renderHook(() => useCreatePaymentIntent(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          data: intentData,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.gateway_ref).toBeDefined();
        expect(result.current.data?.status).toBe("created");
      });

      it("should handle idempotency conflict", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/payments/intents`, () => {
            return HttpResponse.json(
              { detail: "Idempotency key already used" },
              { status: 409 }
            );
          })
        );

        const { result } = renderHook(() => useCreatePaymentIntent(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          data: {
            invoice_id: 1,
            method_id: 3,
            amount: "5000000",
            idempotency_key: "duplicate-key",
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
        http.get(`${API_BASE_URL}/api/payments`, () => {
          return HttpResponse.error();
        })
      );

      const { result } = renderHook(() => usePayments({ page: 1 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toBeDefined();
    });

    it("should handle server error (500) gracefully", async () => {
      server.use(
        http.get(`${API_BASE_URL}/api/payments`, () => {
          return HttpResponse.json(
            { detail: "Internal server error" },
            { status: 500 }
          );
        })
      );

      const { result } = renderHook(() => usePayments({ page: 1 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toBeDefined();
    });

    it("should handle unauthorized error (401)", async () => {
      server.use(
        http.get(`${API_BASE_URL}/api/payments`, () => {
          return HttpResponse.json(
            { detail: "Not authenticated" },
            { status: 401 }
          );
        })
      );

      const { result } = renderHook(() => usePayments({ page: 1 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toBeDefined();
    });
  });
});
