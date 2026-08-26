/**
 * Nút "Đóng kỳ" chỉ được hiện khi backend nói được đóng.
 *
 * Vì sao tệp này tồn tại: bản trước của PR kill-switch đã gate đúng nút bằng
 * `currentPeriod.can_close`, nhưng **không test nào import component này**.
 * Nghĩa là xoá điều kiện đi thì cả 2.345 ca Vitest vẫn xanh — chỉ có type-check
 * biết `can_close` tồn tại, còn không ai canh việc nó được DÙNG.
 *
 * Bộ này canh nhân quả, không canh sự hiện diện của trường:
 *   - `can_close: false` ⇒ không có nút;
 *   - `can_close: true`  ⇒ có nút;
 *   - backend cũ không trả trường ⇒ Zod hạ về `false` (fail-closed), không ném.
 *
 * Hook được `vi.mock` thay vì đi qua MSW: bài toán ở đây là điều kiện render,
 * và một ca test chỉ nên vi phạm một bất biến.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@/test/utils/test-utils"
import { AccountingPeriodClient } from "./AccountingPeriodClient"
import * as UseAccountingPeriods from "@/hooks/finance/useAccountingPeriods"
import { accountingPeriodSchema } from "@/lib/zod/finance"
import type { AccountingPeriod } from "@/types/finance.types"

vi.mock("@/hooks/finance/useAccountingPeriods", () => ({
  useAccountingPeriods: vi.fn(),
  useCurrentPeriod: vi.fn(),
  useCreatePeriod: vi.fn(),
  useClosePeriod: vi.fn(),
}))

const KY_DANG_MO: AccountingPeriod = {
  id: 7,
  month: 6,
  year: 2099,
  is_closed: false,
  closed_at: null,
  closed_by_id: null,
  total_payments: "0",
  total_refunds: "0",
  net_revenue: "0",
  created_at: "2099-06-01T00:00:00Z",
  can_close: false,
}

function dungHook(currentPeriod: AccountingPeriod | null) {
  ;(UseAccountingPeriods.useCurrentPeriod as any).mockReturnValue({
    data: currentPeriod,
    isLoading: false,
    isError: false,
  })
  ;(UseAccountingPeriods.useAccountingPeriods as any).mockReturnValue({
    data: currentPeriod ? [currentPeriod] : [],
    isLoading: false,
    isError: false,
  })
  ;(UseAccountingPeriods.useCreatePeriod as any).mockReturnValue({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  })
  ;(UseAccountingPeriods.useClosePeriod as any).mockReturnValue({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  })
}

describe("AccountingPeriodClient — nút Đóng kỳ", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("can_close=false ⇒ KHÔNG hiện nút Đóng kỳ", () => {
    dungHook({ ...KY_DANG_MO, can_close: false })

    render(<AccountingPeriodClient />)

    // Kỳ vẫn phải hiện ra — nếu component không render gì thì ca này xanh vì
    // lý do sai, và ca dưới cũng sẽ đỏ để lộ chuyện đó.
    // `getAllByText`: nhãn kỳ xuất hiện cả ở thẻ "kỳ hiện tại" lẫn ở hàng bảng.
    expect(screen.getAllByText(/Tháng 6 2099/).length).toBeGreaterThan(0)
    expect(
      screen.queryByRole("button", { name: /Đóng kỳ/ })
    ).not.toBeInTheDocument()
  })

  it("can_close=true ⇒ CÓ nút Đóng kỳ", () => {
    dungHook({ ...KY_DANG_MO, can_close: true })

    render(<AccountingPeriodClient />)

    expect(screen.getByRole("button", { name: /Đóng kỳ/ })).toBeInTheDocument()
  })

  it("backend cũ không trả can_close ⇒ Zod hạ về false, không ném", () => {
    const { can_close: _bo, ...thieuTruong } = KY_DANG_MO

    const ket_qua = accountingPeriodSchema.parse(thieuTruong)

    expect(ket_qua.can_close).toBe(false)
  })
})
