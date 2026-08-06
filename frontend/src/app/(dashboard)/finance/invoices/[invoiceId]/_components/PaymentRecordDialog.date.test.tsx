/**
 * Ngày thu gửi lên máy chủ phải là ngày kế toán bấm trên lịch.
 *
 * Triệu chứng đã gặp thật: ghi một khoản thu, lưu xong thì ngày hiển thị lùi
 * một ngày. Nguyên nhân là `toISOString()`: lịch trả `Date` 00:00 GIỜ ĐỊA
 * PHƯƠNG, còn `toISOString()` quy về UTC, nên ở Việt Nam (UTC+7) ngày rơi lùi.
 * Sau khi lưu, màn hình hiện đúng cái đã lưu — nên người ghi thấy chính ngày
 * mình vừa chọn bị lùi.
 *
 * 🔴 File này chạy ở `TZ=Asia/Ho_Chi_Minh`. Ở UTC mặc định của Vitest, bản cũ
 * và bản mới cho cùng kết quả — bài kiểm sẽ xanh với cả bản sai.
 */
const TZ_GOC = process.env.TZ
process.env.TZ = "Asia/Ho_Chi_Minh"

import { afterAll, describe, it, expect, vi, beforeEach } from "vitest"
import userEvent from "@testing-library/user-event"
import { render, screen, waitFor } from "@/test/utils/test-utils"

import { PaymentRecordDialog } from "./PaymentRecordDialog"

const createPayment = vi.fn()

// Khối cảnh báo trùng (nhánh PR B) gọi thêm hai hook cùng module — mock thiếu
// một cái là component ném "not a function" trước khi tới được phần ngày.
vi.mock("@/hooks/finance/usePayments", () => ({
  useCreatePayment: () => ({
    mutateAsync: (...args: unknown[]) => createPayment(...args),
    isPending: false,
  }),
  usePendingPaymentsByFee: () => ({
    data: { items: [], total: 0 },
    isLoading: false,
    isError: false,
  }),
  useDuplicatePreview: () => ({ data: undefined }),
}))

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoiceDetail: () => ({
    data: { total_due: "9999999", paid_amount: "0", remaining_amount: "9999999" },
    isLoading: false,
    isError: false,
  }),
  useInvoiceVietQR: () => ({ data: undefined, isLoading: false }),
}))

vi.mock("@/hooks/finance/usePaymentMethods", () => ({
  usePaymentMethods: () => ({
    data: [
      { id: 1, code: "cash", name: "Tiền mặt", is_online: false, is_active: true },
    ],
    isLoading: false,
  }),
}))

/** Radix + react-day-picker cần Pointer Capture và `scrollIntoView` — jsdom
 *  không có. Gán hàm THƯỜNG vì vitest config bật `mockReset`/`restoreMocks`. */
function installPointerStubs() {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
  Element.prototype.hasPointerCapture = function hasPointerCapture() {
    return false
  }
  Element.prototype.setPointerCapture = function setPointerCapture() {}
  Element.prototype.releasePointerCapture = function releasePointerCapture() {}
}

afterAll(() => {
  if (TZ_GOC === undefined) delete process.env.TZ
  else process.env.TZ = TZ_GOC
})

beforeEach(() => {
  installPointerStubs()
})

describe("PaymentRecordDialog — ngày thu", () => {
  it("guard: bộ test chạy ở múi giờ Việt Nam", () => {
    // Ở UTC (offset 0) hai cách tính trùng nhau và ca dưới mất khả năng phân biệt.
    expect(new Date(2026, 7, 5).getTimezoneOffset()).toBe(-420)
  })

  it("bấm một ngày trên lịch thì gửi đúng ngày đó", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date("2026-08-12T09:00:00+07:00"))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    try {
      render(
        <PaymentRecordDialog
          open
          onOpenChange={vi.fn()}
          invoiceId={19}
          feeId={7}
          maxAmount="9.999.999 ₫"
        />,
      )

      await user.click(
        screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
      )
      await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
      await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "1000000")

      // Mở lịch (combobox thứ hai) và bấm ngày 05 — thao tác thật của kế toán
      // ghi một khoản thu mấy hôm trước.
      const nutLich = screen.getAllByRole("combobox")[1]
      await user.click(nutLich)
      const lich = await screen.findByRole("grid")
      const oNgay5 = lich.querySelector<HTMLElement>('[data-day="2026-08-05"] button')
      expect(oNgay5).not.toBeNull()
      await user.click(oNgay5!)

      await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))
      await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))

      expect(createPayment.mock.calls[0][0].data.payment_date).toBe("2026-08-05")
    } finally {
      vi.useRealTimers()
    }
  })
})
