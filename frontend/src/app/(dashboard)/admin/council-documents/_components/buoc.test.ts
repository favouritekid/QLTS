import { describe, expect, it } from "vitest"

import { BUOC_HOP_LE, docBuoc } from "./buoc"

describe("docBuoc — tên bước trong URL theo danh sách ĐÓNG", () => {
  it.each(BUOC_HOP_LE.map((b) => [b]))("%s hợp lệ", (b) => {
    expect(docBuoc(b)).toBe(b)
  })

  it.each([
    ["rỗng", ""],
    ["lạ", "bat-ky"],
    ["khác hoa thường", "TAI"],
    ["có khoảng trắng", "tai "],
    ["tiền tố", "tai-ca-bo"],
    ["giống nhưng chèn", "tai&cccd=1"],
  ])("%s ⇒ null (không đoán)", (_t, v) => {
    expect(docBuoc(v)).toBeNull()
  })

  it("mảng (khoá lặp) hoặc vắng ⇒ null", () => {
    expect(docBuoc(["tai", "ghi-nhan"])).toBeNull()
    expect(docBuoc(undefined)).toBeNull()
  })
})
