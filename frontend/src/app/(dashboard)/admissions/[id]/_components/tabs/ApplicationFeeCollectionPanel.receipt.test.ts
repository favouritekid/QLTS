/**
 * Mã biên lai gợi ý mang NGÀY LỊCH VIỆT NAM.
 *
 * Ràng buộc chống trùng biên lai ở máy chủ là theo (hồ sơ, ngày), nên mã sinh
 * từ ngày UTC sẽ mang ngày hôm trước với mọi giao dịch trước 07:00 sáng — và
 * đụng đúng biên lai của hôm qua.
 *
 * 🔴 Ca này phải chạy ở múi giờ dương mới phân biệt được: ở UTC thì hai cách
 * tính cho cùng kết quả và bài kiểm không thể đỏ.
 */
const TZ_GOC = process.env.TZ
process.env.TZ = "Asia/Ho_Chi_Minh"

import { afterAll, describe, it, expect } from "vitest"

import { suggestReceiptCode } from "./ApplicationFeeCollectionPanel"

afterAll(() => {
  if (TZ_GOC === undefined) delete process.env.TZ
  else process.env.TZ = TZ_GOC
})

describe("suggestReceiptCode", () => {
  it("guard: bộ test chạy ở múi giờ Việt Nam", () => {
    expect(new Date(2026, 7, 5).getTimezoneOffset()).toBe(-420)
  })

  it("thu lúc rạng sáng vẫn mang ngày Việt Nam hôm đó", () => {
    // 05/08 03:00 giờ VN = 04/08 20:00Z. `toISOString()` cho "2026-08-04".
    const luc3hSang = new Date("2026-08-04T20:00:00Z")
    expect(suggestReceiptCode(131, luc3hSang)).toBe("PT-131-20260805")
  })

  it("thu giữa ngày cũng đúng ngày đó", () => {
    const luc14h = new Date("2026-08-05T07:00:00Z") // 14:00 VN
    expect(suggestReceiptCode(131, luc14h)).toBe("PT-131-20260805")
  })

  it("sát nửa đêm VN vẫn thuộc ngày đang diễn ra", () => {
    const luc2350 = new Date("2026-08-05T16:50:00Z") // 23:50 VN ngày 05
    expect(suggestReceiptCode(7, luc2350)).toBe("PT-7-20260805")
  })
})
