import { describe, it, expect } from "vitest"
import type { RefundRequest } from "@/types/finance.types"
import { isOverAsking, isPendingPayout } from "./refundWarnings"

/** Phiếu tối thiểu cho phép so; ghi đè đúng thứ mỗi ca quan tâm. */
function refund(overrides: Partial<RefundRequest> = {}): RefundRequest {
  return {
    status: "approved",
    amount: "1000000",
    refundable_amount: "1000000",
    ...overrides,
  } as unknown as RefundRequest
}

describe("isOverAsking", () => {
  it("tô đỏ khi phiếu chờ chi đòi nhiều hơn số còn hoàn được", () => {
    // Đúng ca backend sẽ từ chối, nên cảnh báo có ích: chặn trước khi bấm.
    expect(
      isOverAsking(refund({ amount: "2570000", refundable_amount: "2500000" })),
    ).toBe(true)
  })

  it("không tô đỏ khi đòi vừa đúng số còn hoàn được", () => {
    expect(
      isOverAsking(refund({ amount: "2500000", refundable_amount: "2500000" })),
    ).toBe(false)
  })

  it("KHÔNG tô đỏ phiếu ĐÃ CHI toàn phần — refundable đã trừ chính nó", () => {
    // 🔴 Ca hồi quy: `refundable_amount` trừ mọi phiếu đã chi, kể cả dòng này, nên
    // hoàn toàn phần xong thì refundable = 0 và phép so thô sẽ đỏ oan vĩnh viễn.
    // 7/7 phiếu chờ chi trên prod 30-07 đều toàn phần ⇒ nếu sai, bảng đỏ sạch.
    expect(
      isOverAsking(refund({ status: "refunded", amount: "2500000", refundable_amount: "0" })),
    ).toBe(false)
  })

  it("KHÔNG tô đỏ nhiều phiếu đã chi trên cùng một phiếu thu", () => {
    // Hai phiếu 600k + 400k trên phiếu thu 1tr: chi xong cả hai thì refundable = 0.
    expect(
      isOverAsking(refund({ status: "refunded", amount: "600000", refundable_amount: "0" })),
    ).toBe(false)
    expect(
      isOverAsking(refund({ status: "refunded", amount: "400000", refundable_amount: "0" })),
    ).toBe(false)
  })

  it("KHÔNG tô đỏ phiếu đã từ chối", () => {
    expect(
      isOverAsking(refund({ status: "rejected", amount: "9999999", refundable_amount: "0" })),
    ).toBe(false)
  })

  it("không tô đỏ khi backend không trả số còn hoàn được", () => {
    // Bản ghi cũ / quan hệ đã gỡ: thà không cảnh báo hơn là cảnh báo bừa.
    expect(isOverAsking(refund({ refundable_amount: null }))).toBe(false)
  })
})

describe("isPendingPayout", () => {
  it("chỉ pending và approved là còn chờ chi", () => {
    expect(isPendingPayout({ status: "pending" })).toBe(true)
    expect(isPendingPayout({ status: "approved" })).toBe(true)
    expect(isPendingPayout({ status: "refunded" })).toBe(false)
    expect(isPendingPayout({ status: "rejected" })).toBe(false)
  })
})
