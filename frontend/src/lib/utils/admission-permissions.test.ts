import { describe, it, expect } from "vitest"
import { canDecide, isStepNavLocked } from "./admission-permissions"

describe("canDecide", () => {
  it("trusts the BE aggregate has_decision when present", () => {
    expect(canDecide({ has_decision: true })).toBe(true)
    // has_decision present + false → do NOT fall back to the OR-7 (?? only
    // triggers on null/undefined), even if an individual flag is set.
    expect(canDecide({ has_decision: false, approve: true })).toBe(false)
  })

  it("falls back to the OR of the 7 decision flags when has_decision is absent", () => {
    expect(canDecide({ approve: true })).toBe(true)
    expect(canDecide({ enroll: true })).toBe(true)
    expect(canDecide({})).toBe(false)
    expect(canDecide(undefined)).toBe(false)
  })
})

describe("isStepNavLocked", () => {
  it("keeps step 8 reachable for decision-capable users even when backend-locked", () => {
    expect(isStepNavLocked(8, "locked", true)).toBe(false)
  })

  it("locks step 8 when the user cannot decide", () => {
    expect(isStepNavLocked(8, "locked", false)).toBe(true)
  })

  it("never treats a non-locked step 8 as locked", () => {
    expect(isStepNavLocked(8, "success", false)).toBe(false)
  })

  it("only step 8 gets the decide override — other locked steps stay locked", () => {
    expect(isStepNavLocked(5, "locked", true)).toBe(true)
    expect(isStepNavLocked(1, "locked", false)).toBe(true)
  })

  it("non-locked steps are never locked regardless of decide", () => {
    expect(isStepNavLocked(3, "warning", false)).toBe(false)
    expect(isStepNavLocked(6, "success", true)).toBe(false)
  })
})
