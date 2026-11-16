/**
 * Dòng danh sách hồ sơ mang `academic_year` (máy chủ `083a428d`, đặc tả 5.1): `int | null`. Nút "Dựng văn bản Hội đồng"
 * đọc năm học chung từ đây. Khoá RIÊNG trường này: schema chi tiết khai `.optional()` (không nhận `null`) nên
 * `admissionListItemSchema` phải khai lại — nếu quên, một hồ sơ chưa có năm sẽ làm TRẮNG cả bảng hồ sơ.
 */
import { describe, expect, it } from "vitest"

import { admissionListItemSchema } from "./admissions"

const truong = admissionListItemSchema.shape.academic_year

describe("admissionListItemSchema.academic_year", () => {
  it.each([[2026], [2025], [null], [undefined]])("nhận %s", (v) => {
    expect(truong.safeParse(v).success).toBe(true)
  })

  it("giữ nguyên giá trị: số ⇒ số, null ⇒ null (không ép)", () => {
    expect(truong.parse(2026)).toBe(2026)
    expect(truong.parse(null)).toBeNull()
  })

  it.each([["2026"], [2026.5], [true]])("từ chối giá trị sai kiểu %s", (v) => {
    expect(truong.safeParse(v).success).toBe(false)
  })
})
