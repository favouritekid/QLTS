/**
 * MSW Handlers for Finance API
 */

import { http, HttpResponse } from "msw";
import {
  mockFees,
  mockInvoices,
  mockPayments,
  mockPaymentMethods,
  mockInstallmentPlans,
  mockAccountingPeriods,
  mockDashboardStats,
} from "../data/finance";
import type {
  FeeCalculateRequest,
  FeeWaiveRequest,
  PaymentCreateRequest,
} from "@/types/finance.types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export const financeHandlers = [
  // =========================================================================
  // DASHBOARD
  // =========================================================================
  http.get(`${API_BASE_URL}/api/finance/dashboard`, async () => {
    return HttpResponse.json(mockDashboardStats);
  }),

  // =========================================================================
  // FEES
  // =========================================================================

  // Get fees list with pagination
  http.get(`${API_BASE_URL}/api/fees`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(url.searchParams.get("page") || "1");
    const pageSize = parseInt(url.searchParams.get("page_size") || "10");
    const status = url.searchParams.get("status");
    const profileId = url.searchParams.get("profile_id");

    let filteredFees = [...mockFees];

    // Apply status filter
    if (status) {
      filteredFees = filteredFees.filter((fee) => fee.status === status);
    }

    // Apply profile filter
    if (profileId) {
      filteredFees = filteredFees.filter(
        (fee) => fee.admission_profile_id === parseInt(profileId)
      );
    }

    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    const paginatedFees = filteredFees.slice(start, end);

    return HttpResponse.json({
      items: paginatedFees,
      total: filteredFees.length,
      page,
      page_size: pageSize,
      pages: Math.ceil(filteredFees.length / pageSize),
    });
  }),

  // Get single fee by ID
  http.get(`${API_BASE_URL}/api/fees/:feeId`, async ({ params }) => {
    const { feeId } = params;
    const fee = mockFees.find((f) => f.id === parseInt(feeId as string));

    if (!fee) {
      return HttpResponse.json({ detail: "Fee not found" }, { status: 404 });
    }

    // Return as FeeDetail with nested data
    return HttpResponse.json({
      ...fee,
      installment_plan: mockInstallmentPlans.find(
        (p) => p.id === fee.installment_plan_id
      ),
      applied_discounts: [],
      invoices: mockInvoices
        .filter((inv) => inv.fee_id === fee.id)
        .map((inv) => ({
          id: inv.id,
          invoice_number: inv.invoice_number,
          installment_no: inv.installment_no,
          amount: inv.amount,
          paid_amount: inv.paid_amount,
          remaining_amount: inv.remaining_amount,
          status: inv.status,
          due_date: inv.due_date,
        })),
    });
  }),

  // Get fees by profile
  http.get(`${API_BASE_URL}/api/fees/by-profile/:profileId`, async ({ params }) => {
    const { profileId } = params;
    const fees = mockFees.filter(
      (f) => f.admission_profile_id === parseInt(profileId as string)
    );
    return HttpResponse.json(fees);
  }),

  // Get profile finance summary
  http.get(
    `${API_BASE_URL}/api/fees/summary/:profileId`,
    async ({ params }) => {
      const { profileId } = params;
      const fees = mockFees.filter(
        (f) => f.admission_profile_id === parseInt(profileId as string)
      );

      if (fees.length === 0) {
        return HttpResponse.json({
          admission_profile_id: parseInt(profileId as string),
          total_fees: "0",
          total_paid: "0",
          total_remaining: "0",
          fees: [],
          pending_invoices: 0,
          overdue_invoices: 0,
        });
      }

      const fee = fees[0];
      return HttpResponse.json({
        admission_profile_id: parseInt(profileId as string),
        total_fees: fee.final_amount,
        total_paid: fee.paid_amount,
        total_remaining: fee.remaining_amount,
        fees: [{
          id: fee.id,
          fee_type: fee.fee_type,
          academic_year: fee.academic_year,
          final_amount: fee.final_amount,
          paid_amount: fee.paid_amount,
          remaining_amount: fee.remaining_amount,
          status: fee.status,
        }],
        pending_invoices: 1,
        overdue_invoices: fee.status === "overdue" ? 1 : 0,
      });
    }
  ),

  // Calculate fee
  http.post(`${API_BASE_URL}/api/fees/calculate`, async ({ request }) => {
    const body = (await request.json()) as FeeCalculateRequest;

    const newFee = {
      id: Math.max(...mockFees.map((f) => f.id)) + 1,
      admission_profile_id: body.admission_profile_id,
      installment_plan_id: 1,
      fee_type: body.fee_type || "tuition",
      academic_year: "2025-2026",
      base_amount: "15000000",
      total_discount: "1500000",
      final_amount: "13500000",
      paid_amount: "0",
      waived_amount: "0",
      remaining_amount: "13500000",
      status: "calculated",
      due_date: "2025-03-01",
      calculated_at: new Date().toISOString(),
      last_payment_at: null,
      calculated_by_id: 1,
      version: 1,
      notes: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      can_waive: true,
      can_cancel: true,
      can_recalculate: true,
      profile: {
        id: body.admission_profile_id,
        full_name: "Test Student",
        lead_id: 1,
      },
      installment_plan: mockInstallmentPlans[0],
      applied_discounts: [],
      invoices: [],
    };

    return HttpResponse.json(newFee, { status: 201 });
  }),

  // Waive fee
  http.post(`${API_BASE_URL}/api/fees/:feeId/waive`, async ({ params, request }) => {
    const { feeId } = params;
    const body = (await request.json()) as FeeWaiveRequest;
    const fee = mockFees.find((f) => f.id === parseInt(feeId as string));

    if (!fee) {
      return HttpResponse.json({ detail: "Fee not found" }, { status: 404 });
    }

    if (!fee.can_waive) {
      return HttpResponse.json(
        { detail: "Fee cannot be waived" },
        { status: 400 }
      );
    }

    const updatedFee = {
      ...fee,
      waived_amount: body.waive_amount,
      remaining_amount: (
        parseFloat(fee.final_amount) -
        parseFloat(fee.paid_amount) -
        parseFloat(body.waive_amount)
      ).toString(),
      updated_at: new Date().toISOString(),
    };

    return HttpResponse.json(updatedFee);
  }),

  // Cancel fee
  http.post(`${API_BASE_URL}/api/fees/:feeId/cancel`, async ({ params, request }) => {
    const { feeId } = params;
    const url = new URL(request.url);
    const reason = url.searchParams.get("reason");
    const fee = mockFees.find((f) => f.id === parseInt(feeId as string));

    if (!fee) {
      return HttpResponse.json({ detail: "Fee not found" }, { status: 404 });
    }

    if (!fee.can_cancel) {
      return HttpResponse.json(
        { detail: "Fee cannot be cancelled" },
        { status: 400 }
      );
    }

    if (!reason) {
      return HttpResponse.json({ detail: "Cancellation reason is required" }, { status: 400 });
    }

    const updatedFee = {
      ...fee,
      status: "cancelled",
      can_waive: false,
      can_cancel: false,
      can_recalculate: false,
      updated_at: new Date().toISOString(),
    };

    return HttpResponse.json(updatedFee);
  }),

  // Recalculate fee
  http.post(`${API_BASE_URL}/api/fees/:feeId/recalculate`, async ({ params, request }) => {
    const { feeId } = params;
    const url = new URL(request.url);
    const newBaseAmount = url.searchParams.get("new_base_amount");
    const reason = url.searchParams.get("reason");
    const fee = mockFees.find((f) => f.id === parseInt(feeId as string));

    if (!fee) {
      return HttpResponse.json({ detail: "Fee not found" }, { status: 404 });
    }

    if (!fee.can_recalculate) {
      return HttpResponse.json(
        { detail: "Fee cannot be recalculated" },
        { status: 400 }
      );
    }

    if (!newBaseAmount || !reason) {
      return HttpResponse.json(
        { detail: "New base amount and reason are required" },
        { status: 400 }
      );
    }

    const recalculatedBaseAmount = parseFloat(newBaseAmount);
    const totalDiscount = parseFloat(fee.total_discount);
    const paidAmount = parseFloat(fee.paid_amount);
    const waivedAmount = parseFloat(fee.waived_amount);
    const recalculatedFinalAmount = Math.max(recalculatedBaseAmount - totalDiscount, 0);
    const recalculatedRemainingAmount = Math.max(recalculatedFinalAmount - paidAmount - waivedAmount, 0);

    const updatedFee = {
      ...fee,
      base_amount: newBaseAmount,
      final_amount: recalculatedFinalAmount.toString(),
      remaining_amount: recalculatedRemainingAmount.toString(),
      calculated_at: new Date().toISOString(),
      version: fee.version + 1,
      updated_at: new Date().toISOString(),
      installment_plan: mockInstallmentPlans.find(
        (p) => p.id === fee.installment_plan_id
      ),
      applied_discounts: [],
      invoices: [],
    };

    return HttpResponse.json(updatedFee);
  }),

  // =========================================================================
  // INVOICES
  // =========================================================================

  // Get invoices list
  http.get(`${API_BASE_URL}/api/invoices`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(url.searchParams.get("page") || "1");
    const pageSize = parseInt(url.searchParams.get("page_size") || "10");
    const status = url.searchParams.get("status");
    const feeId = url.searchParams.get("fee_id");

    let filteredInvoices = [...mockInvoices];

    if (status) {
      filteredInvoices = filteredInvoices.filter((inv) => inv.status === status);
    }

    if (feeId) {
      filteredInvoices = filteredInvoices.filter(
        (inv) => inv.fee_id === parseInt(feeId)
      );
    }

    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    const paginatedInvoices = filteredInvoices.slice(start, end);

    return HttpResponse.json({
      items: paginatedInvoices,
      total: filteredInvoices.length,
      page,
      page_size: pageSize,
      pages: Math.ceil(filteredInvoices.length / pageSize),
    });
  }),

  // Get invoices by fee
  http.get(`${API_BASE_URL}/api/invoices/by-fee/:feeId`, async ({ params }) => {
    const { feeId } = params;
    const invoices = mockInvoices.filter(
      (inv) => inv.fee_id === parseInt(feeId as string)
    );
    return HttpResponse.json(invoices);
  }),

  // Get single invoice
  http.get(`${API_BASE_URL}/api/invoices/:invoiceId`, async ({ params }) => {
    const { invoiceId } = params;
    const invoice = mockInvoices.find(
      (inv) => inv.id === parseInt(invoiceId as string)
    );

    if (!invoice) {
      return HttpResponse.json({ detail: "Invoice not found" }, { status: 404 });
    }

    const fee = mockFees.find((f) => f.id === invoice.fee_id);

    return HttpResponse.json({
      ...invoice,
      fee: fee
        ? {
            id: fee.id,
            fee_type: fee.fee_type,
            final_amount: fee.final_amount,
            status: fee.status,
            profile_id: fee.profile?.id,
            profile_name: fee.profile?.full_name,
          }
        : null,
      payments: mockPayments
        .filter((p) => p.invoice_id === invoice.id)
        .map((p) => ({
          id: p.id,
          amount: p.amount,
          status: p.status,
          payment_date: p.payment_date,
          reference_code: p.reference_code,
          method_name:
            mockPaymentMethods.find((m) => m.id === p.method_id)?.name || "",
        })),
    });
  }),

  // Issue invoice
  http.put(`${API_BASE_URL}/api/invoices/:invoiceId/issue`, async ({ params }) => {
    const { invoiceId } = params;
    const invoice = mockInvoices.find(
      (inv) => inv.id === parseInt(invoiceId as string)
    );

    if (!invoice) {
      return HttpResponse.json({ detail: "Invoice not found" }, { status: 404 });
    }

    if (!invoice.can_issue) {
      return HttpResponse.json(
        { detail: "Invoice cannot be issued" },
        { status: 400 }
      );
    }

    const updatedInvoice = {
      ...invoice,
      status: "issued",
      issued_at: new Date().toISOString(),
      issued_by_id: 1,
      can_issue: false,
      can_cancel: true,
      can_record_payment: true,
    };

    return HttpResponse.json(updatedInvoice);
  }),

  // Cancel invoice
  http.put(`${API_BASE_URL}/api/invoices/:invoiceId/cancel`, async ({ params, request }) => {
    const { invoiceId } = params;
    const url = new URL(request.url);
    const reason = url.searchParams.get("reason");
    const invoice = mockInvoices.find(
      (inv) => inv.id === parseInt(invoiceId as string)
    );

    if (!invoice) {
      return HttpResponse.json({ detail: "Invoice not found" }, { status: 404 });
    }

    if (!invoice.can_cancel) {
      return HttpResponse.json(
        { detail: "Invoice cannot be cancelled" },
        { status: 400 }
      );
    }

    if (!reason) {
      return HttpResponse.json({ detail: "Cancellation reason is required" }, { status: 400 });
    }

    const updatedInvoice = {
      ...invoice,
      status: "cancelled",
      cancelled_at: new Date().toISOString(),
      cancelled_by_id: 1,
      cancelled_reason: reason,
      can_issue: false,
      can_cancel: false,
      can_record_payment: false,
      can_apply_penalty: false,
    };

    return HttpResponse.json(updatedInvoice);
  }),

  // Apply penalty
  http.post(`${API_BASE_URL}/api/invoices/:invoiceId/apply-penalty`, async ({ params, request }) => {
    const { invoiceId } = params;
    const url = new URL(request.url);
    const penaltyAmount = url.searchParams.get("penalty_amount");
    const invoice = mockInvoices.find(
      (inv) => inv.id === parseInt(invoiceId as string)
    );

    if (!invoice) {
      return HttpResponse.json({ detail: "Invoice not found" }, { status: 404 });
    }

    if (!invoice.can_apply_penalty) {
      return HttpResponse.json(
        { detail: "Cannot apply penalty to this invoice" },
        { status: 400 }
      );
    }

    if (!penaltyAmount) {
      return HttpResponse.json({ detail: "Penalty amount is required" }, { status: 400 });
    }

    const updatedInvoice = {
      ...invoice,
      penalty_amount: penaltyAmount,
      total_due: (
        parseFloat(invoice.amount) +
        parseFloat(penaltyAmount) -
        parseFloat(invoice.paid_amount)
      ).toString(),
    };

    return HttpResponse.json(updatedInvoice);
  }),

  // =========================================================================
  // PAYMENTS
  // =========================================================================

  // Get payments list
  http.get(`${API_BASE_URL}/api/payments`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(url.searchParams.get("page") || "1");
    const pageSize = parseInt(url.searchParams.get("page_size") || "10");
    const status = url.searchParams.get("status");

    let filteredPayments = [...mockPayments];

    if (status) {
      filteredPayments = filteredPayments.filter((p) => p.status === status);
    }

    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    const paginatedPayments = filteredPayments.slice(start, end);

    return HttpResponse.json({
      items: paginatedPayments,
      total: filteredPayments.length,
      page,
      page_size: pageSize,
      pages: Math.ceil(filteredPayments.length / pageSize),
    });
  }),

  // Get payments by invoice
  http.get(`${API_BASE_URL}/api/payments/by-invoice/:invoiceId`, async ({ params }) => {
    const { invoiceId } = params;
    const payments = mockPayments.filter(
      (p) => p.invoice_id === parseInt(invoiceId as string)
    );
    return HttpResponse.json(payments);
  }),

  // Get single payment
  http.get(`${API_BASE_URL}/api/payments/:paymentId`, async ({ params }) => {
    const { paymentId } = params;
    const payment = mockPayments.find(
      (p) => p.id === parseInt(paymentId as string)
    );

    if (!payment) {
      return HttpResponse.json({ detail: "Payment not found" }, { status: 404 });
    }

    return HttpResponse.json(payment);
  }),

  // Create payment
  http.post(`${API_BASE_URL}/api/payments`, async ({ request }) => {
    const body = (await request.json()) as PaymentCreateRequest;

    const newPayment = {
      id: Math.max(...mockPayments.map((p) => p.id)) + 1,
      invoice_id: body.invoice_id,
      method_id: body.method_id,
      intent_id: null,
      amount: body.amount,
      reference_code: body.reference_code || null,
      payer_name: body.payer_name || null,
      payer_account: body.payer_account || null,
      status: "pending",
      payment_date: body.payment_date || new Date().toISOString(),
      verified_at: null,
      rejected_at: null,
      created_by_id: 1,
      created_by_name: "Test User",
      verified_by_id: null,
      verified_by_name: null,
      rejected_by_id: null,
      rejection_reason: null,
      notes: body.notes || null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      can_verify: true,
      can_reject: true,
    };

    return HttpResponse.json(newPayment, { status: 201 });
  }),

  // Verify payment
  http.put(`${API_BASE_URL}/api/payments/:paymentId/verify`, async ({ params }) => {
    const { paymentId } = params;
    const payment = mockPayments.find(
      (p) => p.id === parseInt(paymentId as string)
    );

    if (!payment) {
      return HttpResponse.json({ detail: "Payment not found" }, { status: 404 });
    }

    if (!payment.can_verify) {
      return HttpResponse.json(
        { detail: "Payment cannot be verified" },
        { status: 400 }
      );
    }

    const updatedPayment = {
      ...payment,
      status: "verified",
      verified_at: new Date().toISOString(),
      verified_by_id: 2,
      verified_by_name: "Manager",
      can_verify: false,
      can_reject: false,
    };

    return HttpResponse.json(updatedPayment);
  }),

  // Reject payment
  http.put(`${API_BASE_URL}/api/payments/:paymentId/reject`, async ({ params, request }) => {
    const { paymentId } = params;
    const url = new URL(request.url);
    const reason = url.searchParams.get("reason");
    const payment = mockPayments.find(
      (p) => p.id === parseInt(paymentId as string)
    );

    if (!payment) {
      return HttpResponse.json({ detail: "Payment not found" }, { status: 404 });
    }

    if (!payment.can_reject) {
      return HttpResponse.json(
        { detail: "Payment cannot be rejected" },
        { status: 400 }
      );
    }

    if (!reason) {
      return HttpResponse.json({ detail: "Rejection reason is required" }, { status: 400 });
    }

    const updatedPayment = {
      ...payment,
      status: "rejected",
      rejected_at: new Date().toISOString(),
      rejected_by_id: 2,
      rejection_reason: reason,
      can_verify: false,
      can_reject: false,
    };

    return HttpResponse.json(updatedPayment);
  }),

  // Get payment methods
  http.get(`${API_BASE_URL}/api/payments/methods`, async () => {
    return HttpResponse.json(mockPaymentMethods);
  }),

  // Create payment intent
  http.post(`${API_BASE_URL}/api/payments/intents`, async ({ request }) => {
    const body = (await request.json()) as {
      invoice_id: number;
      method_id: number;
      amount: string;
      idempotency_key: string;
      return_url?: string;
    };

    const newIntent = {
      id: 1,
      invoice_id: body.invoice_id,
      method_id: body.method_id,
      amount: body.amount,
      currency: "VND",
      gateway_ref: `GW-${Date.now()}`,
      gateway_status: null,
      gateway_response: null,
      idempotency_key: body.idempotency_key,
      status: "created",
      expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
      completed_at: null,
      callback_received_at: null,
      callback_data: null,
      pay_url: "https://sandbox.vnpay.vn/paymentv2/vpcpay.html?token=test",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    return HttpResponse.json(newIntent, { status: 201 });
  }),

  // =========================================================================
  // INSTALLMENT PLANS
  // =========================================================================

  http.get(`${API_BASE_URL}/api/installment-plans`, async () => {
    return HttpResponse.json(mockInstallmentPlans);
  }),

  http.get(`${API_BASE_URL}/api/installment-plans/:id`, async ({ params }) => {
    const { id } = params;
    const plan = mockInstallmentPlans.find(
      (p) => p.id === parseInt(id as string)
    );

    if (!plan) {
      return HttpResponse.json(
        { detail: "Installment plan not found" },
        { status: 404 }
      );
    }

    return HttpResponse.json(plan);
  }),

  // =========================================================================
  // ACCOUNTING PERIODS
  // =========================================================================

  http.get(`${API_BASE_URL}/api/accounting/periods`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(url.searchParams.get("page") || "1");
    const pageSize = parseInt(url.searchParams.get("page_size") || "10");

    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    const paginatedPeriods = mockAccountingPeriods.slice(start, end);

    return HttpResponse.json({
      items: paginatedPeriods,
      total: mockAccountingPeriods.length,
      page,
      page_size: pageSize,
      pages: Math.ceil(mockAccountingPeriods.length / pageSize),
    });
  }),

  http.get(`${API_BASE_URL}/api/accounting/periods/:id`, async ({ params }) => {
    const { id } = params;
    const period = mockAccountingPeriods.find(
      (p) => p.id === parseInt(id as string)
    );

    if (!period) {
      return HttpResponse.json(
        { detail: "Accounting period not found" },
        { status: 404 }
      );
    }

    return HttpResponse.json(period);
  }),

  http.post(`${API_BASE_URL}/api/accounting/periods/:id/close`, async ({ params }) => {
    const { id } = params;
    const period = mockAccountingPeriods.find(
      (p) => p.id === parseInt(id as string)
    );

    if (!period) {
      return HttpResponse.json(
        { detail: "Accounting period not found" },
        { status: 404 }
      );
    }

    // Check if already closed
    if (period.is_closed) {
      return HttpResponse.json(
        { detail: "Period cannot be closed" },
        { status: 400 }
      );
    }

    const updatedPeriod = {
      ...period,
      is_closed: true,
      closed_at: new Date().toISOString(),
      closed_by_id: 1,
    };

    return HttpResponse.json(updatedPeriod);
  }),
];
