/**
 * Regression: the record-payment form prefills the payer name + reference from
 * the collection-drawer context (Quick win A) so the accountant confirms instead
 * of re-typing what the system already knows; without a context it stays blank.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@/test/utils/test-utils"

import { PaymentRecordDialog } from "./PaymentRecordDialog"

vi.mock("@/hooks/finance/usePayments", () => ({
  useCreatePayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock("@/hooks/finance/usePaymentMethods", () => ({
  usePaymentMethods: () => ({
    data: [
      { id: 1, code: "cash", name: "Tiền mặt", is_online: false, is_active: true },
    ],
    isLoading: false,
  }),
}))

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
