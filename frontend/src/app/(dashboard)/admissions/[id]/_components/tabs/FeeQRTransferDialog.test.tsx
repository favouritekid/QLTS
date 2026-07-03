import { describe, it, expect, vi, beforeEach } from "vitest"
import { fireEvent, render, screen, waitFor } from "@/test/utils/test-utils"

import { FeeQRTransferDialog } from "./FeeQRTransferDialog"

// vi.hoisted khởi tạo 2 mock fn TRƯỚC khi vi.mock factory (bị hoist lên trên các
// static import) chạy → khử mọi rủi ro TDZ, không phụ thuộc thứ tự khai báo.
const { useInvoicesByFee, useInvoiceVietQR } = vi.hoisted(() => ({
  useInvoicesByFee: vi.fn(),
  useInvoiceVietQR: vi.fn(),
}))

// FeeQRTransferDialog resolve hóa đơn qua useInvoicesByFee; khối hiển thị QR
// (InvoiceVietQR) gọi useInvoiceVietQR(invoiceId). Mock chung 1 module.
vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoicesByFee,
  useInvoiceVietQR,
}))

// Thẻ QR vẽ bằng canvas (không chạy trong jsdom) → mock trả blob giả để test
// luồng chia sẻ / tải ảnh mà không phụ thuộc canvas thật.
vi.mock("@/lib/finance/qr-card", () => ({
  renderVietQRCard: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
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
    // Defaults so a test that only cares about one hook doesn't crash on the
    // other's destructure (both return the loaded/empty shape unless overridden).
    useInvoicesByFee.mockReturnValue({ data: [], isLoading: false, error: null })
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
    // The QR block is queried for the single payable invoice (id 701).
    await waitFor(() => expect(useInvoiceVietQR).toHaveBeenCalledWith(701))
    // Officer can share the QR to the student.
    expect(
      screen.getByRole("button", { name: /chia sẻ mã qr/i })
    ).toBeInTheDocument()
  })

  it("falls back to downloading the QR image when Web Share is unavailable", async () => {
    useInvoicesByFee.mockReturnValue({
      data: [makeInvoice()],
      isLoading: false,
      error: null,
    })
    // jsdom has no Web Share (navigator.canShare), so ShareQRButton hits the
    // download fallback: it must create (and revoke) a blob URL for the PNG.
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:mock")
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {})

    render(
      <FeeQRTransferDialog feeId={501} feeLabel="Học phí — HK1" open onOpenChange={vi.fn()} />
    )

    fireEvent.click(await screen.findByRole("button", { name: /chia sẻ mã qr/i }))

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
    expect(revokeObjectURL).toHaveBeenCalled()

    createObjectURL.mockRestore()
    revokeObjectURL.mockRestore()
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
    // No payable → QR block never renders → its query is never fired.
    expect(useInvoiceVietQR).not.toHaveBeenCalledWith(expect.any(Number))
  })

  it("renders the installment picker and defaults to the first payable installment", async () => {
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

    // Picker present. Radix Select options render in a portal (unreliable in
    // JSDOM), so per project convention we assert the trigger + the default
    // selection instead of opening the dropdown and clicking an option.
    expect(screen.getByText(/chọn đợt thanh toán/i)).toBeInTheDocument()
    expect(screen.getByRole("combobox")).toBeInTheDocument()
    // Defaults to the FIRST payable installment (701) for the QR, not 702.
    await waitFor(() => expect(useInvoiceVietQR).toHaveBeenCalledWith(701))
    expect(useInvoiceVietQR).not.toHaveBeenCalledWith(702)
  })

  it("shows a distinct error notice (not the empty state) when the by-fee request fails", () => {
    useInvoicesByFee.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("boom"),
    })

    render(
      <FeeQRTransferDialog feeId={501} feeLabel="Học phí — HK1" open onOpenChange={vi.fn()} />
    )

    expect(screen.getByText(/không thể tải hóa đơn/i)).toBeInTheDocument()
    // Must NOT collapse into the "settled/not issued" empty message.
    expect(screen.queryByText(/chưa có hóa đơn cần thanh toán/i)).not.toBeInTheDocument()
    expect(screen.queryByAltText("VietQR")).not.toBeInTheDocument()
  })

  it("shows the loading skeleton while invoices are being fetched", () => {
    useInvoicesByFee.mockReturnValue({ data: undefined, isLoading: true, error: null })

    render(
      <FeeQRTransferDialog feeId={501} feeLabel="Học phí — HK1" open onOpenChange={vi.fn()} />
    )

    // Neither terminal state renders during load.
    expect(screen.queryByText(/chưa có hóa đơn cần thanh toán/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/không thể tải hóa đơn/i)).not.toBeInTheDocument()
    expect(screen.queryByAltText("VietQR")).not.toBeInTheDocument()
  })
})
