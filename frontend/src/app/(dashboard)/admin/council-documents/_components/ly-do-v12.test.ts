/**
 * GĐ1b luật in v1.2 — mã lỗi dữ liệu MỚI `verified_format_invalid` (giấy đã duyệt mà hình thức đã xác nhận trống / lạ):
 * máy chủ chưa có câu cho mã này ở bản xem trước (`ROW_DATA_ERROR_REASONS.get(m, m)` trả chính mã) ⇒ giao diện hiện câu
 * tiếng Việt, không để mã tiếng Anh lộ ra. Câu máy chủ có thật ⇒ vẫn hiện NGUYÊN VĂN.
 */
import { describe, expect, it } from "vitest"

import { VERIFIED_FORMAT_INVALID_MESSAGE } from "@/lib/document-review/messages"

import { checkReasonText } from "./display"

describe("checkReasonText — luật in v1.2", () => {
  it("cau = mã ⇒ câu tiếng Việt", () => {
    const t = checkReasonText({ ma: "verified_format_invalid", cau: "verified_format_invalid" })
    expect(t).toBe(VERIFIED_FORMAT_INVALID_MESSAGE)
    expect(t).not.toContain("verified_format_invalid")
    expect(t).toMatch(/hình thức đã xác nhận/)
  })

  it("cau rỗng ⇒ câu tiếng Việt", () => {
    expect(checkReasonText({ ma: "verified_format_invalid", cau: "" })).toBe(VERIFIED_FORMAT_INVALID_MESSAGE)
  })

  it("máy chủ có câu thật ⇒ hiện nguyên văn", () => {
    expect(checkReasonText({ ma: "verified_format_invalid", cau: "Câu của máy chủ" })).toBe("Câu của máy chủ")
  })

  it("mã GĐ1 khác ⇒ nguyên văn cau (không đổi hành vi cũ)", () => {
    expect(checkReasonText({ ma: "du_lieu_van_hoa_la", cau: "trình độ văn hoá rỗng" })).toBe("trình độ văn hoá rỗng")
  })
})
