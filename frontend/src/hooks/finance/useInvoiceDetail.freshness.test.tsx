/**
 * Độ tươi của số dư hoá đơn khi form ghi tiền mở lại.
 *
 * Khe hở mà bộ test trước bỏ lọt: dialog chỉ đặt `enabled: open`, tưởng thế là
 * đủ để "mở lại thì hỏi lại". Không đủ — trang cha dùng CHUNG query key này với
 * độ tươi mặc định 30 giây, nên đóng rồi mở lại trong 30 giây sẽ đọc lại đúng
 * bản cache cũ. Ghép với hàng đợi chờ duyệt (đã `staleTime: 0`) thì panel nói
 * hai thời điểm khác nhau: "không còn phiếu nào chờ" — đúng — kèm "còn phải
 * thu" của lúc trước khi ai đó duyệt phiếu. Kế toán đọc được đúng cái kết luận
 * sai mà B1 sinh ra để xoá.
 *
 * ⚠️ `gcTime` dài là CỐ Ý, cùng lý do đã ghi ở `usePendingPaymentsByFee.test`:
 * với `gcTime: 0` cache bị dọn ngay khi hết người nghe, nên ca này sẽ xanh kể
 * cả khi `staleTime` là 30 giây — một bài kiểm tra không thể đỏ.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { useInvoiceDetail } from "./useInvoices"

const getInvoice = vi.fn()

vi.mock("@/lib/api/invoices", () => ({
  invoicesApi: {
    getInvoice: (...args: unknown[]) => getInvoice(...args),
  },
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 5 * 60 * 1000 },
    },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  Wrapper.displayName = "TestQueryClientWrapper"
  return Wrapper
}

beforeEach(() => {
  getInvoice.mockReset()
  getInvoice.mockResolvedValue({
    id: 19,
    fee_id: 7,
    total_due: "5000000",
    paid_amount: "1000000",
    remaining_amount: "4000000",
  })
})

describe("useInvoiceDetail — độ tươi", () => {
  it("với staleTime 0: đóng rồi mở lại thì đọc lại số dư từ máy chủ", async () => {
    const wrapper = createWrapper()
    const { rerender } = renderHook(
      ({ open }: { open: boolean }) =>
        useInvoiceDetail(19, { enabled: open, staleTime: 0 }),
      { wrapper, initialProps: { open: true } },
    )

    await waitFor(() => expect(getInvoice).toHaveBeenCalledTimes(1))

    rerender({ open: false })
    rerender({ open: true })

    await waitFor(() => expect(getInvoice).toHaveBeenCalledTimes(2))
  })

  it("đối chứng — mặc định 30 giây thì mở lại vẫn dùng cache cũ", async () => {
    const wrapper = createWrapper()
    const { rerender } = renderHook(
      ({ open }: { open: boolean }) => useInvoiceDetail(19, { enabled: open }),
      { wrapper, initialProps: { open: true } },
    )

    await waitFor(() => expect(getInvoice).toHaveBeenCalledTimes(1))

    rerender({ open: false })
    rerender({ open: true })

    // Ca này khoá lý do tồn tại của tuỳ chọn: nếu nó cũng gọi lần hai thì
    // `staleTime` mặc định đã không còn tác dụng và ca trên chẳng chứng minh
    // được gì — hai ca phải nói ngược nhau thì mới có nội dung.
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(getInvoice).toHaveBeenCalledTimes(1)
  })

  it("màn xem khác không bị ép hỏi lại (mặc định giữ nguyên 30 giây)", async () => {
    const wrapper = createWrapper()
    const { rerender } = renderHook(
      ({ id }: { id: number }) => useInvoiceDetail(id),
      { wrapper, initialProps: { id: 19 } },
    )
    await waitFor(() => expect(getInvoice).toHaveBeenCalledTimes(1))

    rerender({ id: 19 })
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(getInvoice).toHaveBeenCalledTimes(1)
  })
})
