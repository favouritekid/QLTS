/**
 * Regression: the record-payment form prefills the payer name + reference from
 * the collection-drawer context (Quick win A) so the accountant confirms instead
 * of re-typing what the system already knows; without a context it stays blank.
 *
 * Và (B1): bảng công nợ trong dialog, đặc biệt dòng "đang chờ duyệt". Tiền chỉ
 * vào sổ khi phiếu được DUYỆT, nên nếu không nói ra thì màn hình hiện y như
 * chưa ai thu và kế toán nhập lại — prod đã có 9 phiếu nghi trùng theo đúng
 * đường đó.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@/test/utils/test-utils"

import { PaymentRecordDialog } from "./PaymentRecordDialog"

// Trạng thái điều khiển được cho từng ca — khai ở ngoài để `vi.mock` (bị hoist)
// vẫn đọc được giá trị mới nhất.
const state = {
  invoice: {
    total_due: "5000000",
    paid_amount: "1000000",
    remaining_amount: "4000000",
  } as Record<string, string> | undefined,
  invoiceLoading: false,
  pendingItems: [] as Array<{ id: number; amount: string }>,
  pendingLoading: false,
}

vi.mock("@/hooks/finance/usePayments", () => ({
  useCreatePayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePendingPaymentsByFee: () => ({
    data: { items: state.pendingItems, total: state.pendingItems.length },
    isLoading: state.pendingLoading,
  }),
}))

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoiceDetail: () => ({ data: state.invoice, isLoading: state.invoiceLoading }),
}))

vi.mock("@/hooks/finance/usePaymentMethods", () => ({
  usePaymentMethods: () => ({
    data: [
      { id: 1, code: "cash", name: "Tiền mặt", is_online: false, is_active: true },
    ],
    isLoading: false,
  }),
}))

beforeEach(() => {
  state.invoice = {
    total_due: "5000000",
    paid_amount: "1000000",
    remaining_amount: "4000000",
  }
  state.invoiceLoading = false
  state.pendingItems = []
  state.pendingLoading = false
})

describe("PaymentRecordDialog", () => {
  it("prefills payer name + reference from the drawer context", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        maxAmount="4.200.000 ₫"
        defaultPayerName="Nguyễn Thế Đạt"
        defaultReference="HS-000025"
      />,
    )
    expect(screen.getByLabelText(/tên người nộp/i)).toHaveValue("Nguyễn Thế Đạt")
    expect(screen.getByLabelText(/mã tham chiếu/i)).toHaveValue("HS-000025")
  })

  it("leaves payer + reference blank with no context (e.g. detail page)", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        maxAmount="4.200.000 ₫"
      />,
    )
    expect(screen.getByLabelText(/tên người nộp/i)).toHaveValue("")
    expect(screen.getByLabelText(/mã tham chiếu/i)).toHaveValue("")
  })
})

describe("PaymentRecordDialog — bảng công nợ", () => {
  it("hiện dòng 'chờ duyệt' kèm SỐ PHIẾU và TỔNG khi có phiếu chưa duyệt", () => {
    state.pendingItems = [
      { id: 1, amount: "2000000" },
      { id: 2, amount: "500000" },
    ]
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    const row = screen.getByTestId("payment-pending-row")
    expect(row).toHaveTextContent(/2 phiếu/)
    // 2.000.000 + 500.000 — cộng ở FE vì API trả từng phiếu, không trả tổng.
    expect(row).toHaveTextContent(/2\D?500\D?000/)
  })

  it("ẨN dòng 'chờ duyệt' khi không có phiếu nào chờ", () => {
    state.pendingItems = []
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    expect(screen.getByTestId("payment-debt-panel")).toBeInTheDocument()
    expect(screen.queryByTestId("payment-pending-row")).not.toBeInTheDocument()
  })

  it("đang tải thì KHÔNG chặn form — vẫn gõ được", () => {
    state.invoiceLoading = true
    state.pendingLoading = true
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    // Panel có mặt (đang ở trạng thái chờ) nhưng các ô nhập vẫn dùng được.
    expect(screen.getByTestId("payment-debt-panel")).toBeInTheDocument()
    expect(screen.queryByTestId("payment-pending-row")).not.toBeInTheDocument()
    expect(screen.getByLabelText(/tên người nộp/i)).toBeEnabled()
    expect(screen.getByLabelText(/mã tham chiếu/i)).toBeEnabled()
  })

  it("hiện ba dòng công nợ lấy từ SỐ THẬT của máy chủ", () => {
    state.invoice = {
      total_due: "5000000",
      paid_amount: "1000000",
      remaining_amount: "4000000",
    }
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        // Prop hiển thị CỐ TÌNH lệch số thật: panel phải bám máy chủ, không
        // bám chuỗi truyền qua prop.
        maxAmount="9.999.999 ₫"
      />,
    )
    const panel = screen.getByTestId("payment-debt-panel")
    expect(panel).toHaveTextContent(/5\D?000\D?000/)
    expect(panel).toHaveTextContent(/1\D?000\D?000/)
    expect(panel).toHaveTextContent(/4\D?000\D?000/)
    expect(panel).not.toHaveTextContent(/9\D?999\D?999/)
  })
})
