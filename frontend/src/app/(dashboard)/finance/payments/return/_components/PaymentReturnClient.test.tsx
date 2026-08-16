/**
 * Trạng thái trên trang trả về CHỈ được lấy từ máy chủ.
 *
 * Bản trước ưu tiên `?status=` trong URL hơn `intent.status` do máy chủ trả về
 * (`// Priority: query param > intent status`). Người xem sửa được URL, nên mở
 * `/finance/payments/return?intent_id=<intent PENDING có thật>&status=success`
 * là thấy thẻ xanh "Thanh toán thành công" kèm SỐ TIỀN THẬT lấy từ máy chủ.
 *
 * Ba ca đầu khoá đúng lỗ ấy. Hai ca sau khoá phần fail-closed: chưa xác minh
 * được thì không khẳng định gì, và nút "Thử lại" chỉ mọc theo trạng thái server.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { PaymentReturnClient } from "./PaymentReturnClient"

let thamSo = new URLSearchParams()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => thamSo,
  usePathname: () => "/finance/payments/return",
}))

let ketQuaIntent: { data?: unknown; isLoading: boolean; error?: unknown } = {
  data: undefined,
  isLoading: false,
  error: undefined,
}
vi.mock("@/hooks/finance/usePayments", () => ({
  usePaymentIntent: () => ketQuaIntent,
}))

function dung(url: string, intent: typeof ketQuaIntent) {
  thamSo = new URLSearchParams(url)
  ketQuaIntent = intent
  render(<PaymentReturnClient />)
}

const KHONG_TAI = { data: undefined, isLoading: false, error: undefined }

describe("PaymentReturnClient — trạng thái chỉ đến từ máy chủ", () => {
  it("URL nói success + máy chủ nói pending ⇒ KHÔNG hiện thành công", () => {
    dung("intent_id=7&status=success", {
      data: { id: 7, status: "pending", amount: "1000000", invoice_id: 3 },
      isLoading: false,
      error: undefined,
    })
    expect(screen.queryByText("Thanh toán thành công")).not.toBeInTheDocument()
    expect(screen.getByText("Đang xử lý")).toBeInTheDocument()
  })

  it("URL nói success mà KHÔNG có intent_id ⇒ không khẳng định, có cảnh báo", () => {
    dung("status=success&reference=GIA-MAO-123", KHONG_TAI)
    expect(screen.queryByText("Thanh toán thành công")).not.toBeInTheDocument()
    expect(screen.getByTestId("canh-bao-chua-xac-minh")).toBeInTheDocument()
  })

  it("intent_id có nhưng máy chủ lỗi/không thấy ⇒ KHÔNG rơi về success của URL", () => {
    dung("intent_id=999&status=success", {
      data: undefined,
      isLoading: false,
      error: new Error("404"),
    })
    expect(screen.queryByText("Thanh toán thành công")).not.toBeInTheDocument()
    expect(screen.getByTestId("canh-bao-chua-xac-minh")).toBeInTheDocument()
  })

  it("máy chủ nói completed ⇒ hiện thành công, không cần tham số URL", () => {
    dung("intent_id=7", {
      data: { id: 7, status: "completed", amount: "1000000", invoice_id: 3 },
      isLoading: false,
      error: undefined,
    })
    expect(screen.getByText("Thanh toán thành công")).toBeInTheDocument()
    expect(screen.queryByTestId("canh-bao-chua-xac-minh")).not.toBeInTheDocument()
  })

  it("URL đổi invoice_id ⇒ link vẫn trỏ hoá đơn THẬT của intent", () => {
    dung("intent_id=7&invoice_id=999", {
      data: { id: 7, status: "completed", amount: "1000000", invoice_id: 3 },
      isLoading: false,
      error: undefined,
    })
    const link = screen.getByRole("link", { name: /Xem hóa đơn/i })
    expect(link).toHaveAttribute("href", "/finance/invoices/3")
    expect(screen.queryByRole("link", { name: /999/ })).not.toBeInTheDocument()
  })

  it("chưa xác minh mà URL có invoice_id ⇒ KHÔNG mọc nút tới hoá đơn đó", () => {
    dung("invoice_id=999&status=failed", KHONG_TAI)
    expect(screen.queryByText("Xem hóa đơn")).not.toBeInTheDocument()
    expect(screen.queryByText("Thử lại")).not.toBeInTheDocument()
    expect(screen.getByTestId("canh-bao-chua-xac-minh")).toBeInTheDocument()
  })

  it("nút 'Thử lại' chỉ mọc khi MÁY CHỦ nói failed, không phải khi URL nói", () => {
    dung("intent_id=7&status=failed", {
      data: { id: 7, status: "pending", amount: "1000000", invoice_id: 3 },
      isLoading: false,
      error: undefined,
    })
    expect(screen.queryByText("Thử lại")).not.toBeInTheDocument()
  })
})
