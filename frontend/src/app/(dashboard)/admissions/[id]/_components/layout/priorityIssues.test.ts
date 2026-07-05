import { describe, it, expect } from "vitest"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { firstAttentionStep, issueTotalCount, missingRequiredDataSteps } from "./priorityIssues"

type StepStatus = "success" | "warning" | "error" | "locked"

/** All 8 steps "success" by default; override the ones a case cares about. */
function steps(overrides: Record<number, StepStatus> = {}): Record<number, StepStatus> {
  const base: Record<number, StepStatus> = { 1: "success", 2: "success", 3: "success", 4: "success", 5: "success", 6: "success", 7: "success", 8: "success" }
  return { ...base, ...overrides }
}

/** Minimal profile with both required-data groups present by default. */
function profile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return { family_info: [{}], academic_history: [{}], ...overrides } as unknown as AdmissionProfileResponse
}

const NONE = { requiredDataSteps: [] as number[], priorityIssuesCount: 0 }

describe("firstAttentionStep", () => {
  it("returns the first 'error' step before any warning", () => {
    // step 1 warning + step 5 error → error wins even though it's later.
    expect(firstAttentionStep(steps({ 1: "warning", 5: "error" }), NONE)).toBe(5)
  })

  it("jumps to the earliest missing required-data step, past an earlier step-1 warning", () => {
    // The 'kẹt' bug: step 1 amber for blank OPTIONAL personal fields, while
    // family(2)/academic(3) are the real submit blockers → land on step 2.
    expect(
      firstAttentionStep(steps({ 1: "warning" }), { requiredDataSteps: [2, 3], priorityIssuesCount: 0 }),
    ).toBe(2)
  })

  it("routes to academic (step 3) when only academic is the blocker — even if step 2 is amber for an unrelated reason", () => {
    // The exact edge the count-based version got wrong: step 2 warning (family
    // present but incomplete, NOT a submit blocker) while academic is empty.
    expect(
      firstAttentionStep(steps({ 2: "warning", 3: "warning" }), { requiredDataSteps: [3], priorityIssuesCount: 0 }),
    ).toBe(3)
  })

  it("routes priority issues to step 4 even when every step is success/locked (no dead-end)", () => {
    // missing_priority_evidence_codes counts toward the badge but step_status[4]
    // stays 'success' once KV is resolved → must still navigate, not no-op.
    expect(firstAttentionStep(steps({ 8: "locked" }), { requiredDataSteps: [], priorityIssuesCount: 1 })).toBe(4)
  })

  it("falls back to the first remaining 'warning' step when no error/required-data/priority", () => {
    expect(firstAttentionStep(steps({ 6: "warning" }), NONE)).toBe(6)
  })

  it("returns null when nothing needs attention", () => {
    expect(firstAttentionStep(steps({ 8: "locked" }), NONE)).toBeNull()
  })

  it("error still wins over required-data and priority", () => {
    expect(
      firstAttentionStep(steps({ 1: "error", 2: "warning" }), { requiredDataSteps: [2, 3], priorityIssuesCount: 3 }),
    ).toBe(1)
  })

  it("routes straight to the missing required-data step regardless of its displayed status", () => {
    // Direct routing means a step_status desync (flag says missing but the step
    // isn't amber) still lands on the right tab instead of a generic warning.
    expect(
      firstAttentionStep(steps({ 5: "warning" }), { requiredDataSteps: [3], priorityIssuesCount: 0 }),
    ).toBe(3)
  })
})

describe("missingRequiredDataSteps", () => {
  it("flags family (2) + academic (3) when both empty", () => {
    expect(
      missingRequiredDataSteps(profile({ family_info: [], academic_history: [] } as Partial<AdmissionProfileResponse>)),
    ).toEqual([2, 3])
  })

  it("flags only academic (3) when family is present", () => {
    expect(
      missingRequiredDataSteps(profile({ academic_history: [] } as Partial<AdmissionProfileResponse>)),
    ).toEqual([3])
  })

  it("flags only family (2) when academic is present", () => {
    expect(
      missingRequiredDataSteps(profile({ family_info: [] } as Partial<AdmissionProfileResponse>)),
    ).toEqual([2])
  })

  it("returns [] when both present, and [] for null", () => {
    expect(missingRequiredDataSteps(profile())).toEqual([])
    expect(missingRequiredDataSteps(null)).toEqual([])
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
