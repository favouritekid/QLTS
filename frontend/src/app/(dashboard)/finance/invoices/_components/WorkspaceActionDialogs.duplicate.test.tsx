/**
 * Đường THẬT của màn Thu học phí: form ghi tiền bị **unmount hẳn** khi đóng
 * (`WorkspaceActionDialogs` chỉ render nó khi `dialog.type === "record"`).
 *
 * Vì sao cần một ca ở đây thay vì chỉ ở dialog: mọi ca trong
 * `PaymentRecordDialog.test.tsx` giữ component mounted và chỉ đổi prop `open`,
 * nên chúng không thể thấy lớp lỗi "state khởi tạo lại từ đầu ở lần mount
 * sau". Chính caller này làm lộ nó — một số phiên khởi tạo bằng hằng số sẽ lặp
 * lại y hệt phiên trước, khoá truy vấn trùng khít, và bản cache cũ sống dậy.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@/test/utils/test-utils"

import { WorkspaceActionDialogs } from "./WorkspaceActionDialogs"

/** Số phiên mà mỗi lần mount của form đã yêu cầu. */
const soPhienDaCap: number[] = []
const previewCalls: Array<{ sessionId: number }> = []

vi.mock("@/hooks/finance/usePayments", () => ({
  useCreatePayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePendingPaymentsByFee: () => ({
    data: { items: [], total: 0 },
    isLoading: false,
    isError: false,
  }),
  useDuplicatePreview: (input: { sessionId: number }) => {
    previewCalls.push({ sessionId: input.sessionId })
    return { data: undefined }
  },
  useVerifyPayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRejectPayment: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoiceDetail: () => ({
    data: { total_due: "5000000", paid_amount: "0", remaining_amount: "5000000" },
    isLoading: false,
    isError: false,
  }),
  useInvoiceVietQR: () => ({ data: undefined, isLoading: false }),
}))

vi.mock("@/hooks/finance/usePaymentMethods", () => ({
  usePaymentMethods: () => ({
    data: [{ id: 1, code: "cash", name: "Tiền mặt", is_online: false, is_active: true }],
    isLoading: false,
  }),
}))

const DIALOG_GHI_TIEN = {
  type: "record" as const,
  invoiceId: 19,
  feeId: 7,
  maxAmountFormatted: "5.000.000 ₫",
  invoiceNumber: "INV-1",
}

beforeEach(() => {
  soPhienDaCap.length = 0
  previewCalls.length = 0
})

describe("WorkspaceActionDialogs — form ghi tiền bị unmount khi đóng", () => {
  it("mỗi lần MỞ LẠI dùng một số phiên khác, không lặp lại phiên trước", async () => {
    const { rerender } = render(
      <WorkspaceActionDialogs dialog={DIALOG_GHI_TIEN} onClose={vi.fn()} />,
    )
    await waitFor(() => expect(previewCalls.length).toBeGreaterThan(0))
    const phienDau = previewCalls.at(-1)!.sessionId

    // Đóng: caller đặt dialog = null ⇒ form bị gỡ khỏi cây, mọi state biến mất.
    rerender(<WorkspaceActionDialogs dialog={null} onClose={vi.fn()} />)
    expect(screen.queryByTestId("payment-debt-panel")).not.toBeInTheDocument()

    previewCalls.length = 0
    // Mở lại CÙNG hoá đơn, cùng khoản phí.
    rerender(<WorkspaceActionDialogs dialog={DIALOG_GHI_TIEN} onClose={vi.fn()} />)
    await waitFor(() => expect(previewCalls.length).toBeGreaterThan(0))
    const phienSau = previewCalls.at(-1)!.sessionId

    // Đây là toàn bộ nội dung của bài kiểm: hai lần mở phải mang hai số khác
    // nhau. Bằng nhau nghĩa là khoá truy vấn trùng khít phiên trước và React
    // Query sẽ trả lại bản cache cũ ngay khi form vừa hiện.
    expect(phienSau).not.toBe(phienDau)
  })
})
