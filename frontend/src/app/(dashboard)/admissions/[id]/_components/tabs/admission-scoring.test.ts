import { describe, it, expect } from "vitest"
import { calculateAdmissionTotal } from "./admission-scoring"

describe("calculateAdmissionTotal — weighted scoring parity with backend", () => {
  it("full weights: Σ score * weight (plain weighted sum, no division)", () => {
    const total = calculateAdmissionTotal({
      subjectScores: { math: 8, lit: 6 },
      scoringMethod: "weighted",
      subjectWeights: { math: 2, lit: 1 },
    })
    // 8*2 + 6*1 = 22 (NOT normalized to 22/3 ≈ 7.33)
    expect(total).toBe(22)
  })

  it("partial weights: missing key defaults to 1.0, NOT fallback", () => {
    const total = calculateAdmissionTotal({
      subjectScores: { math: 8, lit: 6 },
      scoringMethod: "weighted",
      subjectWeights: { math: 2 },
    })
    // lit has no weight → treated as 1.0 (matches backend DB NUMERIC DEFAULT 1.0)
    // 8*2 + 6*1.0 = 22
    expect(total).toBe(22)
  })

  it("empty weights: full fallback to plain sum", () => {
    const total = calculateAdmissionTotal({
      subjectScores: { math: 8, lit: 6 },
      scoringMethod: "weighted",
      subjectWeights: {},
    })
    // Empty object → fallback triggered → 8 + 6 = 14
    expect(total).toBe(14)
  })
})
