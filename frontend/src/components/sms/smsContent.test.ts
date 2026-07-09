import { describe, expect, it } from "vitest"

import {
  isStrongTuition,
  programTuition,
  tuitionLevelLabel,
  tuitionTier,
} from "./smsContent"

describe("tuitionTier", () => {
  it("suy mức ưu đãi mạnh nhất theo mã (free > 70 > 30)", () => {
    expect(tuitionTier("6720301")).toBe("70") // Điều dưỡng (cd70)
    expect(tuitionTier("6720201")).toBe("70") // Dược (cd70)
    expect(tuitionTier("6720102")).toBe("30") // YHCT (cd30)
    expect(tuitionTier("5510216")).toBe("free") // Ô tô TC (thcsFree)
  })
  it("mã không có dữ liệu → null", () => {
    expect(tuitionTier("0000000")).toBeNull()
  })
})

describe("isStrongTuition", () => {
  it("free/70 = mạnh; 30/null = không", () => {
    expect(isStrongTuition("free")).toBe(true)
    expect(isStrongTuition("70")).toBe(true)
    expect(isStrongTuition("30")).toBe(false)
    expect(isStrongTuition(null)).toBe(false)
  })
})

describe("programTuition", () => {
  it("trả object học phí theo mã; null nếu không có", () => {
    expect(programTuition("6720201")?.total).toBe("48.000.000 đ")
    expect(programTuition("0000000")).toBeNull()
  })
})

describe("tuitionLevelLabel", () => {
  it("nhãn ngắn (card) vs dài (hero) theo mức", () => {
    expect(tuitionLevelLabel("free", "card")).toBe("Miễn 100%")
    expect(tuitionLevelLabel("free", "hero")).toBe("Miễn 100% học phí")
    expect(tuitionLevelLabel("70", "card")).toBe("Giảm 70%")
    expect(tuitionLevelLabel("30", "card")).toBe("Ưu đãi 30%")
    expect(tuitionLevelLabel(null, "card")).toBe("Học bổng")
    expect(tuitionLevelLabel(null, "hero")).toBe("Học bổng đầu vào")
  })
})
