/**
 * Đường THẬT của màn Thu học phí: form ghi tiền bị **unmount hẳn** khi đóng
 * (`WorkspaceActionDialogs` chỉ render nó khi `dialog.type === "record"`).
 *
 * Vì sao cần một ca ở đây thay vì chỉ ở dialog: mọi ca trong
 * `PaymentRecordDialog.test.tsx` giữ component mounted và chỉ đổi prop `open`,
 * nên chúng không thể thấy lớp lỗi "thứ gì đó sống sót qua một lần mount mới".
 * Chính caller này làm lộ nó.
 *
 * Thứ phải chết ở đây là PHIẾU XÁC NHẬN. Nó nói về một tập ứng viên tại một
 * thời điểm; mang nó sang lần mở sau là xin xác nhận cho một câu hỏi khác.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import userEvent from "@testing-library/user-event"
import { render, screen, waitFor } from "@/test/utils/test-utils"

import { WorkspaceActionDialogs } from "./WorkspaceActionDialogs"

const createPayment = vi.fn()

vi.mock("@/hooks/finance/usePayments", () => ({
  useCreatePayment: () => ({
    mutateAsync: createPayment,
    isPending: false,
  }),
  usePendingPaymentsByFee: () => ({
    data: { items: [], total: 0 },
    isLoading: false,
    isError: false,
  }),
  useVerifyPayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRejectPayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoiceDetail: () => ({
    data: { total_due: "5000000", paid_amount: "0", remaining_amount: "5000000" },
    isLoading: false,
    isError: false,
  }),
}))

vi.mock("@/hooks/finance/usePaymentMethods", () => ({
  usePaymentMethods: () => ({
    data: [{ id: 3, code: "cash", name: "Tiền mặt", is_online: false, is_active: true }],
    isLoading: false,
  }),
}))

const THAN_409 = {
  response: {
    status: 409,
    data: {
      detail: "trùng",
      error_code: "PAYMENT_DUPLICATE_SUSPECTED",
      duplicates: [
        {
          payment_id: 91,
          amount: "1000000",
          payment_date: null,
          status: "pending",
          invoice_number: "INV-A",
        },
      ],
      duplicates_truncated: false,
      duplicates_total: 1,
      review_token: "phieu.cua.lan.truoc",
    },
  },
}

function veMan(mo: boolean) {
  return (
    <WorkspaceActionDialogs
      dialog={
        mo
          ? {
              type: "record" as const,
              invoiceId: 19,
              feeId: 7,
              maxAmountFormatted: "5.000.000 ₫",
              invoiceNumber: "INV-19",
            }
          : null
      }
      onClose={vi.fn()}
    />
  )
}

describe("Thu học phí — phiếu xác nhận không sống qua một lần mở mới", () => {
  beforeEach(() => {
    createPayment.mockReset()
    // Radix Select dùng Pointer Capture và `scrollIntoView`, cả hai đều không
    // có trong jsdom. Gán hàm THƯỜNG (không phải `vi.fn`) vì vitest config bật
    // `mockReset`/`restoreMocks`, sẽ xoá sạch thân mock giữa các ca.
    Element.prototype.scrollIntoView = function scrollIntoView() {}
    Element.prototype.hasPointerCapture = function hasPointerCapture() {
      return false
    }
    Element.prototype.setPointerCapture = function setPointerCapture() {}
    Element.prototype.releasePointerCapture = function releasePointerCapture() {}
  })

  it("đóng rồi mở lại ⇒ lượt gửi mới KHÔNG mang phiếu của lần trước", async () => {
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(THAN_409)
    const { rerender } = render(veMan(true))

    async function dien() {
      await user.click(
        screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
      )
      await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
      await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "1000000")
    }

    await dien()
    await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))
    await screen.findByTestId("payment-duplicate-warning")
    await user.click(screen.getByTestId("payment-duplicate-confirm"))

    // Đóng — form unmount hẳn.
    rerender(veMan(false))
    await waitFor(() =>
      expect(screen.queryByPlaceholderText(/nhập số tiền/i)).not.toBeInTheDocument(),
    )

    // Mở lại và gửi CÙNG bộ dữ liệu. Nếu phiếu sống sót ở đâu đó — module
    // state, React Query, storage — nó sẽ đi kèm ngay lượt đầu tiên này, và
    // người ghi bỏ qua một cảnh báo họ chưa từng thấy trong phiên hiện tại.
    createPayment.mockResolvedValueOnce({ id: 1 })
    rerender(veMan(true))
    await dien()
    await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))

    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(2))
    expect(
      createPayment.mock.calls[1][0].data.review_token,
      "phiếu của lần mở trước sống sót sang lần mở mới",
    ).toBeUndefined()
    // Và không có khối cảnh báo nào được vẽ sẵn lúc mở.
    expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument()
  })
})
