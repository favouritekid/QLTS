/**
 * Hợp đồng của nguồn dữ liệu cho ô "đang chờ duyệt" ở form ghi tiền.
 *
 * Hai điều phải chứng minh, và cả hai đều là NHÂN QUẢ chứ không phải hình
 * thức — test cũ chỉ mock hook rồi kiểm chữ hiện ra, nên nó xanh y hệt nhau
 * dù hook hỏi máy chủ câu gì:
 *
 * 1. **Hỏi đúng câu.** `pending_manual_only` (phiếu TAY chờ duyệt) chứ không
 *    phải `status=pending` — bộ lọc trạng thái chung còn trả về phiếu ONLINE
 *    người học tự bấm rồi bỏ dở, và đếm nó vào ô này là dựng cảnh báo trên
 *    dữ liệu sai loại.
 * 2. **Hỏi lại mỗi lần mở.** Đóng rồi mở lại form phải gọi máy chủ, kể cả khi
 *    mới vài giây. Đó chính là ca trùng kinh điển: kế toán khác vừa tạo phiếu
 *    trong lúc form này đóng. Cache vài giây dựng lại đúng màn hình nói dối
 *    mà tính năng sinh ra để xoá.
 *
 * ⚠️ QueryClient ở đây CỐ Ý đặt `gcTime` dài. `createTestQueryClient` dùng
 * `gcTime: 0`, nghĩa là cache bị dọn ngay khi query không còn người nghe —
 * với client đó thì ca (2) xanh kể cả khi hook đặt `staleTime: 15_000`, tức
 * một bài kiểm tra không thể đỏ. Giữ cache sống mới ép được `staleTime` phải
 * tự chịu trách nhiệm.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { usePendingPaymentsByFee } from "./usePayments"

const getPayments = vi.fn()

vi.mock("@/lib/api/payments", () => ({
  paymentsApi: {
    getPayments: (...args: unknown[]) => getPayments(...args),
  },
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        // Cache PHẢI sống qua lúc dialog đóng — xem ghi chú đầu file.
        gcTime: 5 * 60 * 1000,
      },
    },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  Wrapper.displayName = "TestQueryClientWrapper"
  return Wrapper
}

beforeEach(() => {
  getPayments.mockReset()
  getPayments.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
})

describe("usePendingPaymentsByFee", () => {
  it("hỏi hàng đợi phiếu TAY chờ duyệt của đúng khoản phí", async () => {
    const wrapper = createWrapper()
    renderHook(() => usePendingPaymentsByFee(7, { enabled: true }), { wrapper })

    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(1))

    const params = getPayments.mock.calls[0][0]
    expect(params).toMatchObject({
      fee_id: 7,
      pending_manual_only: true,
      page: 1,
      page_size: 100,
    })
    // Ca quyết định: `status` có mặt là quay lại bộ lọc trạng thái chung, và
    // phiếu online đang treo sẽ được đếm vào ô "kế toán đã nhập chưa duyệt".
    expect(params).not.toHaveProperty("status")
  })

  it("đóng rồi mở lại form thì hỏi lại máy chủ, không dùng cache", async () => {
    const wrapper = createWrapper()
    const { rerender } = renderHook(
      ({ open }: { open: boolean }) => usePendingPaymentsByFee(7, { enabled: open }),
      { wrapper, initialProps: { open: true } },
    )

    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(1))

    // Đóng form: query ngừng chạy nhưng dữ liệu cũ vẫn nằm trong cache.
    rerender({ open: false })
    // Mở lại NGAY — không có độ trễ nào, đúng thao tác thật của kế toán khi
    // nghi mình bấm hụt.
    rerender({ open: true })

    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(2))
  })

  it("không có khoản phí thì không gọi máy chủ", async () => {
    const wrapper = createWrapper()
    renderHook(() => usePendingPaymentsByFee(undefined, { enabled: true }), {
      wrapper,
    })

    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(getPayments).not.toHaveBeenCalled()
  })
})
