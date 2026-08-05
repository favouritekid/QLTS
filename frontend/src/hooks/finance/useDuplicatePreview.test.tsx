/**
 * Hợp đồng của nguồn dữ liệu cho cảnh báo trùng SỚM.
 *
 * Test dialog mock hook này, nên nó **miễn nhiễm với mọi lỗi bên trong hook** —
 * đúng lớp lỗi đã để lọt một P1 ở vòng trước (`useInvoiceDetail` giữ
 * `staleTime` 30 giây mà không ca nào thấy). Ở đây gọi hook thật và soi đối số
 * gửi xuống tầng API.
 *
 * ⚠️ `gcTime` dài là CỐ Ý: `createTestQueryClient` dùng `gcTime: 0`, cache bị
 * dọn ngay khi hết người nghe, nên ca "hỏi lại mỗi lần mở" sẽ xanh kể cả khi
 * `staleTime` là 15 giây — một bài kiểm tra không thể đỏ.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { capSoPhienMoi } from "@/lib/finance/duplicate-payment"
import { useDuplicatePreview } from "./usePayments"

const getPayments = vi.fn()

vi.mock("@/lib/api/payments", () => ({
  paymentsApi: {
    getPayments: (...args: unknown[]) => getPayments(...args),
  },
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 5 * 60 * 1000 } },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  Wrapper.displayName = "TestQueryClientWrapper"
  return Wrapper
}

const DU_CAN_CU = {
  feeId: 7,
  amount: 1_000_000,
  paymentDate: "2026-08-05",
  sessionId: 0,
}

beforeEach(() => {
  getPayments.mockReset()
  getPayments.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 0 })
})

describe("useDuplicatePreview", () => {
  it("hỏi máy chủ bằng bộ ba fee_id + số tiền + ngày", async () => {
    const wrapper = createWrapper()
    renderHook(() => useDuplicatePreview(DU_CAN_CU, { enabled: true }), { wrapper })

    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(1))

    const params = getPayments.mock.calls[0][0]
    expect(params).toMatchObject({
      fee_id: 7,
      duplicate_amount: 1_000_000,
      duplicate_date: "2026-08-05",
    })
    // Ca quyết định: `status` có mặt nghĩa là ai đó đã quay về lối tự lọc ở
    // giao diện — luật dò trùng phải sống ở máy chủ, nơi có tổng tiền đã hoàn
    // và múi giờ cố định.
    expect(params).not.toHaveProperty("status")
    expect(params).not.toHaveProperty("pending_manual_only")
  })

  it.each([
    ["chưa có khoản phí", { ...DU_CAN_CU, feeId: undefined }],
    ["chưa gõ số tiền", { ...DU_CAN_CU, amount: null }],
    ["số tiền bằng 0", { ...DU_CAN_CU, amount: 0 }],
    ["chưa có ngày", { ...DU_CAN_CU, paymentDate: null }],
  ])("KHÔNG hỏi khi %s", async (_ten, input) => {
    // Câu hỏi thiếu vế bị máy chủ từ chối 422, và một lỗi đỏ trong lúc người
    // dùng đang gõ dở là nhiễu chứ không phải thông tin.
    const wrapper = createWrapper()
    renderHook(() => useDuplicatePreview(input, { enabled: true }), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(getPayments).not.toHaveBeenCalled()
  })

  it("form đóng thì không hỏi", async () => {
    const wrapper = createWrapper()
    renderHook(() => useDuplicatePreview(DU_CAN_CU, { enabled: false }), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(getPayments).not.toHaveBeenCalled()
  })

  it("đóng rồi mở lại thì hỏi lại máy chủ, không dùng cache", async () => {
    const wrapper = createWrapper()
    const { rerender } = renderHook(
      ({ open }: { open: boolean }) => useDuplicatePreview(DU_CAN_CU, { enabled: open }),
      { wrapper, initialProps: { open: true } },
    )
    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(1))

    rerender({ open: false })
    rerender({ open: true })

    // Người khác vừa ghi một phiếu trong lúc form này đóng là ca trùng kinh
    // điển — cache dù vài giây cũng che mất nó.
    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(2))
  })

  it("đổi số tiền thì hỏi lại bằng số mới", async () => {
    const wrapper = createWrapper()
    const { rerender } = renderHook(
      ({ amount }: { amount: number }) =>
        useDuplicatePreview({ ...DU_CAN_CU, amount }, { enabled: true }),
      { wrapper, initialProps: { amount: 1_000_000 } },
    )
    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(1))

    rerender({ amount: 2_000_000 })
    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(2))
    expect(getPayments.mock.calls[1][0]).toMatchObject({ duplicate_amount: 2_000_000 })
  })

  it("mở lại (phiên mới) thì KHÔNG trả dữ liệu của phiên trước trong lúc chờ", async () => {
    // `staleTime: 0` chỉ buộc HỎI LẠI; nó không xoá dữ liệu cũ. Nếu khoá truy
    // vấn không đổi theo lần mở, React Query trả ngay bản cache của phiên
    // trước trong lúc request mới đang bay — form dựng cảnh báo từ dữ liệu
    // chưa ai kiểm lại, người dùng tick, và cờ xác nhận đi kèm một bộ dữ liệu
    // của lần khác.
    const wrapper = createWrapper()
    getPayments.mockResolvedValueOnce({
      items: [{ id: 91, amount: "1000000", status: "pending", payment_date: null }],
      total: 1,
      page: 1,
      page_size: 1,
    })

    const { result, rerender } = renderHook(
      ({ sessionId, open }: { sessionId: number; open: boolean }) =>
        useDuplicatePreview({ ...DU_CAN_CU, sessionId }, { enabled: open }),
      { wrapper, initialProps: { sessionId: 0, open: true } },
    )
    await waitFor(() => expect(result.current.data?.items).toHaveLength(1))

    // Phản hồi của lần hỏi kế tiếp bị giữ lại — mô phỏng lúc request đang bay.
    let traLoi: (v: unknown) => void = () => {}
    getPayments.mockImplementationOnce(
      () => new Promise((resolve) => { traLoi = resolve }),
    )

    rerender({ sessionId: 0, open: false })
    rerender({ sessionId: 1, open: true }) // đóng rồi mở lại = phiên mới

    // Đang chờ: KHÔNG được có dữ liệu nào.
    expect(result.current.data).toBeUndefined()

    traLoi({ items: [], total: 0, page: 1, page_size: 0 })
    await waitFor(() => expect(result.current.data?.items).toEqual([]))
  })

  it("số thứ tự phiên KHÔNG được gửi lên máy chủ", async () => {
    const wrapper = createWrapper()
    renderHook(
      () => useDuplicatePreview({ ...DU_CAN_CU, sessionId: 7 }, { enabled: true }),
      { wrapper },
    )
    await waitFor(() => expect(getPayments).toHaveBeenCalledTimes(1))
    // Máy chủ không cần biết đây là lần mở thứ mấy; gửi thừa tham số là mời
    // một cuộc tranh luận không cần thiết ở tầng validate.
    expect(getPayments.mock.calls[0][0]).not.toHaveProperty("sessionId")
    expect(JSON.stringify(getPayments.mock.calls[0][0])).not.toContain("phien")
  })
})

describe("useDuplicatePreview — dialog bị UNMOUNT rồi mở lại", () => {
  it("phiên mới sau khi unmount vẫn không thấy dữ liệu cũ", async () => {
    // Đường THẬT ở màn Thu học phí: `WorkspaceActionDialogs` chỉ render form
    // khi `dialog.type === "record"`, nên đóng form là unmount hẳn. Một
    // `useState(0)` sẽ lại là 0 ở lần mở sau, khoá truy vấn trùng khít phiên
    // trước, và bản cache cũ sống dậy — ca rerender trong cùng một hook KHÔNG
    // mô phỏng được chuyện này.
    //
    // Dùng CHUNG một QueryClient qua hai lần mount: đó là điều kiện để cache
    // của phiên trước còn sống mà thử.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 5 * 60 * 1000 } },
    })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    getPayments.mockResolvedValueOnce({
      items: [{ id: 91, amount: "1000000", status: "pending", payment_date: null }],
      total: 1,
      page: 1,
      page_size: 1,
    })

    // Cấp số MỘT lần cho mỗi lần mount — đúng cách component dùng
    // (`useState(capSoPhienMoi)`). Gọi trong thân render sẽ cấp số mới mỗi lần
    // render, khoá truy vấn đổi liên tục và hook không bao giờ có dữ liệu.
    const soPhien1 = capSoPhienMoi()
    const phien1 = renderHook(
      () =>
        useDuplicatePreview({ ...DU_CAN_CU, sessionId: soPhien1 }, { enabled: true }),
      { wrapper },
    )
    await waitFor(() => expect(phien1.result.current.data?.items).toHaveLength(1))
    phien1.unmount()

    // Phản hồi của phiên 2 bị giữ lại: mô phỏng lúc request mới còn đang bay.
    let traLoi: (v: unknown) => void = () => {}
    getPayments.mockImplementationOnce(
      () => new Promise((resolve) => { traLoi = resolve }),
    )

    // Phiên 2 — mount MỚI hoàn toàn, cùng fee/tiền/ngày.
    const soPhien2 = capSoPhienMoi()
    const phien2 = renderHook(
      () =>
        useDuplicatePreview({ ...DU_CAN_CU, sessionId: soPhien2 }, { enabled: true }),
      { wrapper },
    )

    expect(phien2.result.current.data).toBeUndefined()

    traLoi({ items: [], total: 0, page: 1, page_size: 0 })
    await waitFor(() => expect(phien2.result.current.data?.items).toEqual([]))
  })

  it("capSoPhienMoi không bao giờ cấp lại một số đã cấp", () => {
    const day = Array.from({ length: 5 }, () => capSoPhienMoi())
    expect(new Set(day).size).toBe(day.length)
    // Tăng dần: một bộ đếm quay vòng cũng sẽ trùng khoá y như hằng số.
    expect([...day].sort((a, b) => a - b)).toEqual(day)
  })
})
