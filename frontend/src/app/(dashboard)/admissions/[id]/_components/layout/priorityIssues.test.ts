import { describe, it, expect } from "vitest"
import { firstAttentionStep, issueTotalCount } from "./priorityIssues"

type StepStatus = "success" | "warning" | "error" | "locked"

/** All 8 steps "success" by default; override the ones a case cares about. */
function steps(overrides: Record<number, StepStatus> = {}): Record<number, StepStatus> {
  const base: Record<number, StepStatus> = { 1: "success", 2: "success", 3: "success", 4: "success", 5: "success", 6: "success", 7: "success", 8: "success" }
  return { ...base, ...overrides }
}

const NONE = { requiredDataCount: 0, priorityIssuesCount: 0 }

describe("firstAttentionStep", () => {
  it("returns the first 'error' step before any warning", () => {
    // step 1 warning + step 5 error → error wins even though it's later.
    const target = firstAttentionStep(steps({ 1: "warning", 5: "error" }), NONE)
    expect(target).toBe(5)
  })

  it("prefers the required-data step (2/3) over an earlier NON-blocking step-1 warning", () => {
    // The exact 'kẹt' bug: step 1 amber for blank OPTIONAL personal fields, while
    // family/academic (the real submit blocker) are step 2/3 warnings.
    const target = firstAttentionStep(steps({ 1: "warning", 2: "warning", 3: "warning" }), {
      requiredDataCount: 2,
      priorityIssuesCount: 0,
    })
    expect(target).toBe(2)
  })

  it("routes to step 3 when family is complete but academic (step 3) is the required-data warning", () => {
    const target = firstAttentionStep(steps({ 1: "warning", 3: "warning" }), {
      requiredDataCount: 1,
      priorityIssuesCount: 0,
    })
    expect(target).toBe(3)
  })

  it("routes priority issues to step 4 even when every step is success/locked (no dead-end)", () => {
    // missing_priority_evidence_codes counts toward the badge but step_status[4]
    // stays 'success' once KV is resolved → must still navigate, not no-op.
    const target = firstAttentionStep(steps({ 8: "locked" }), {
      requiredDataCount: 0,
      priorityIssuesCount: 1,
    })
    expect(target).toBe(4)
  })

  it("falls back to the first remaining 'warning' step when no error/required-data/priority", () => {
    const target = firstAttentionStep(steps({ 6: "warning" }), NONE)
    expect(target).toBe(6)
  })

  it("returns null when nothing needs attention", () => {
    expect(firstAttentionStep(steps({ 8: "locked" }), NONE)).toBeNull()
  })

  it("error still wins over required-data and priority", () => {
    const target = firstAttentionStep(steps({ 1: "error", 2: "warning" }), {
      requiredDataCount: 2,
      priorityIssuesCount: 3,
    })
    expect(target).toBe(1)
  })

  it("required-data count with no step-2/3 warning falls through to priority/warning", () => {
    // Defensive: flag says required-data but steps 2/3 aren't warning (backend
    // desync) → don't get stuck; use priority then generic warning.
    const target = firstAttentionStep(steps({ 5: "warning" }), {
      requiredDataCount: 1,
      priorityIssuesCount: 0,
    })
    expect(target).toBe(5)
  })
})

describe("issueTotalCount", () => {
  it("sums validation + priority + required-data counts", () => {
    expect(issueTotalCount(2, 1, { required_data: { count: 3 } })).toBe(6)
  })

  it("treats missing/null grouped or required_data as 0", () => {
    expect(issueTotalCount(2, 1, null)).toBe(3)
    expect(issueTotalCount(0, 0, {})).toBe(0)
  })
})
