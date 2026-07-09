import { describe, expect, it } from "vitest"

import type { SmsLandingProgram } from "@/lib/zod/sms"

import { dedupeByName, groupPrograms } from "./smsPrograms"

function mk(
  id: number,
  name: string,
  code: string,
  degree_level: string,
): SmsLandingProgram {
  return { id, name, code, degree_level, is_heavy: false }
}

describe("groupPrograms", () => {
  it("gộp biến thể CÙNG TÊN thành 1 card + chọn mức ưu đãi mạnh nhất", () => {
    const groups = groupPrograms([
      mk(1, "Ô tô", "6510216", "Cao đẳng"), // cd70 → "70"
      mk(2, "Ô tô", "5510216", "Trung cấp"), // thcsFree → "free"
    ])
    const cards = groups.flatMap((g) => g.items)
    const oto = cards.find((c) => c.name === "Ô tô")
    expect(oto?.variants).toHaveLength(2) // 2 biến thể trong 1 card
    expect(oto?.level).toBe("free") // free > 70
  })

  it("ngành khác tên → card riêng", () => {
    const groups = groupPrograms([
      mk(1, "Dược", "6720201", "Cao đẳng"),
      mk(2, "Điều dưỡng", "6720301", "Cao đẳng"),
    ])
    const names = groups.flatMap((g) => g.items).map((c) => c.name)
    expect(names).toContain("Dược")
    expect(names).toContain("Điều dưỡng")
  })
})

describe("dedupeByName", () => {
  it("giữ mục ĐẦU của mỗi tên", () => {
    const out = dedupeByName([
      mk(1, "A", "c1", "Cao đẳng"),
      mk(2, "A", "c2", "Trung cấp"),
      mk(3, "B", "c3", "Cao đẳng"),
    ])
    expect(out.map((p) => p.id)).toEqual([1, 3])
  })

  it("loại các tên trong exclude", () => {
    const out = dedupeByName(
      [mk(1, "A", "c1", "Cao đẳng"), mk(2, "B", "c2", "Cao đẳng")],
      ["A"],
    )
    expect(out.map((p) => p.name)).toEqual(["B"])
  })
})
