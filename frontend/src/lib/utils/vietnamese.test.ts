import { describe, it, expect } from "vitest"
import { foldVietnamese } from "./vietnamese"

describe("foldVietnamese", () => {
  it("bỏ dấu nguyên âm + lowercase", () => {
    expect(foldVietnamese("Kế toán")).toBe("ke toan")
    expect(foldVietnamese("Dược")).toBe("duoc")
    expect(foldVietnamese("Điều dưỡng")).toBe("dieu duong")
    expect(foldVietnamese("Y sỹ đa khoa")).toBe("y sy da khoa")
  })

  it("đ/Đ → d/D", () => {
    expect(foldVietnamese("Đắk Lắk")).toBe("dak lak")
    expect(foldVietnamese("đ")).toBe("d")
  })

  it("match substring không dấu (use-case combobox filter)", () => {
    const fold = foldVietnamese
    expect(fold("Công nghệ thông tin").includes(fold("cong nghe"))).toBe(true)
    expect(fold("Kế toán Cao đẳng Xét học bạ").includes(fold("ke toan"))).toBe(true)
    expect(fold("Kỹ thuật chế biến món ăn").includes(fold("ky thuat"))).toBe(true)
  })

  it("chuỗi không dấu giữ nguyên (idempotent-ish)", () => {
    expect(foldVietnamese("ke toan")).toBe("ke toan")
  })
})
