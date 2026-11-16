import { describe, expect, it } from "vitest"

import { VALID_STEPS, readStep } from "./steps"

describe("docBuoc — tên bước trong URL theo danh sách ĐÓNG", () => {
  it.each(VALID_STEPS.map((b) => [b]))("%s hợp lệ", (b) => {
    expect(readStep(b)).toBe(b)
  })

  it.each([
    ["rỗng", ""],
    ["lạ", "bat-ky"],
    ["khác hoa thường", "TAI"],
    ["có khoảng trắng", "tai "],
    ["tiền tố", "tai-ca-bo"],
    ["giống nhưng chèn", "tai&cccd=1"],
  ])("%s ⇒ null (không đoán)", (_t, v) => {
    expect(readStep(v)).toBeNull()
  })

  it("mảng (khoá lặp) hoặc vắng ⇒ null", () => {
    expect(readStep(["tai", "ghi-nhan"])).toBeNull()
    expect(readStep(undefined)).toBeNull()
  })
})
