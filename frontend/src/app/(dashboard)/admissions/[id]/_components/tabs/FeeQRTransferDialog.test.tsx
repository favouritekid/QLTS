import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@/test/utils/test-utils"

import { FeeQRTransferDialog } from "./FeeQRTransferDialog"

const useInvoicesByFee = vi.fn()
const useInvoiceVietQR = vi.fn()

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoicesByFee: (...args: unknown[]) => useInvoicesByFee(...args),
  useInvoiceVietQR: (...args: unknown[]) => useInvoiceVietQR(...args),
}))

const fakeVietQR = {
  qr_payload: "00020101...",
  qr_image_base64: "iVBORw0KGgoAAAANSUhEUg==",
  bank_account: {
    bank_bin: "970436",
    account_number: "123456789",
    account_name: "TRUONG ABC",
  },
  amount: "10000000",
  content: "HS-000178 thanh toan hoc phi",
}

function makeInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: 701,
    fee_id: 501,
    invoice_number: "INV-2026-0001",
    installment_no: 1,
    amount: "10000000",
    due_date: "2026-08-01",
    status: "issued",
    paid_amount: "0",
    remaining_amount: "10000000",
    penalty_amount: "0",
    total_due: "10000000",
    is_overdue: false,
    issued_at: "2026-07-01T00:00:00Z",
    paid_at: null,
    cancelled_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    can_issue: false,
    can_cancel: false,
    can_record_payment: false,
    can_apply_penalty: false,
    ...overrides,
  }
}

describe("FeeQRTransferDialog", () => {
  beforeEach(() => {
    useInvoicesByFee.mockReset()
    useInvoiceVietQR.mockReset()
    useInvoiceVietQR.mockReturnValue({
      data: fakeVietQR,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })
  })

  it("shows the VietQR image for a single payable invoice and selects it", async () => {
    useInvoicesByFee.mockReturnValue({
      data: [makeInvoice()],
      isLoading: false,
      error: null,
    })

    render(
      <FeeQRTransferDialog feeId={501} feeLabel="Học phí — HK1" open onOpenChange={vi.fn()} />
    )

    expect(await screen.findByAltText("VietQR")).toBeInTheDocument()
    // Single installment → no picker.
    expect(screen.queryByText(/chọn đợt thanh toán/i)).not.toBeInTheDocument()
    // Auto-selected the payable invoice id for the QR query.
    await waitFor(() =>
      expect(useInvoiceVietQR).toHaveBeenCalledWith(701, expect.objectContaining({ enabled: true }))
    )
  })

  it("filters out draft / paid / cancelled invoices (no payable → empty notice)", () => {
    useInvoicesByFee.mockReturnValue({
      data: [
        makeInvoice({ id: 1, status: "draft" }),
        makeInvoice({ id: 2, status: "paid", remaining_amount: "0" }),
        makeInvoice({ id: 3, status: "cancelled" }),
        // issued but fully settled → not payable.
        makeInvoice({ id: 4, status: "issued", remaining_amount: "0" }),
      ],
      isLoading: false,
      error: null,
    })

    render(
      <FeeQRTransferDialog feeId={501} feeLabel="Học phí — HK1" open onOpenChange={vi.fn()} />
    )

    expect(screen.getByText(/chưa có hóa đơn cần thanh toán/i)).toBeInTheDocument()
    expect(screen.queryByAltText("VietQR")).not.toBeInTheDocument()
  })

  it("renders an installment picker when there are multiple payable invoices", () => {
    useInvoicesByFee.mockReturnValue({
      data: [
        makeInvoice({ id: 701, installment_no: 1, status: "partial", remaining_amount: "4000000" }),
        makeInvoice({ id: 702, installment_no: 2, status: "overdue", remaining_amount: "6000000" }),
      ],
      isLoading: false,
      error: null,
    })

    render(
      <FeeQRTransferDialog feeId={501} feeLabel="Học phí — HK1" open onOpenChange={vi.fn()} />
    )

    expect(screen.getByText(/chọn đợt thanh toán/i)).toBeInTheDocument()
  })
})
