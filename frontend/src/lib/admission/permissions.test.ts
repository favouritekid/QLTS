/**
 * Phase 3 PR-3D-A Sub-4 — hasAction + getActionItem helper tests.
 *
 * Non-tautological per memory `pattern-change-impact-audit`:
 * - Verify v2 typed PREFERRED over legacy
 * - Verify legacy fallback when v2 absent
 * - Verify null-safe behavior
 * - Verify type narrowing extracts target/endpoint metadata
 */
import { describe, it, expect } from "vitest"
import { hasAction, getActionItem } from "./permissions"

describe("hasAction()", () => {
  it("returns false for null profile", () => {
    expect(hasAction(null, "calculate_fee")).toBe(false)
  })

  it("returns false for undefined profile", () => {
    expect(hasAction(undefined, "calculate_fee")).toBe(false)
  })

  it("returns false when neither field present", () => {
    expect(hasAction({}, "calculate_fee")).toBe(false)
  })

  it("returns true when action in legacy list (fallback)", () => {
    const profile = { available_actions: ["calculate_fee", "claim"] }
    expect(hasAction(profile, "calculate_fee")).toBe(true)
    expect(hasAction(profile, "claim")).toBe(true)
    expect(hasAction(profile, "approve")).toBe(false)
  })

  it("returns true when action in v2 typed list (preferred)", () => {
    const profile = {
      available_actions_v2: [
        { action: "calculate_fee" },
        { action: "claim", target: 42 },
      ],
    }
    expect(hasAction(profile, "calculate_fee")).toBe(true)
    expect(hasAction(profile, "claim")).toBe(true)
    expect(hasAction(profile, "approve")).toBe(false)
  })

  it("⭐ v2 takes PRIORITY over legacy when both present", () => {
    // Legacy says "claim" allowed, v2 says NOT allowed
    // Result: v2 wins → false
    const profile = {
      available_actions: ["claim"],
      available_actions_v2: [{ action: "approve" }],
    }
    expect(hasAction(profile, "claim")).toBe(false)
    expect(hasAction(profile, "approve")).toBe(true)
  })

  it("v2 empty array overrides legacy (NOT falls back)", () => {
    // v2 present but empty → explicit no-permissions, NOT fallback signal
    const profile = {
      available_actions: ["claim"],
      available_actions_v2: [],
    }
    expect(hasAction(profile, "claim")).toBe(false)
  })
})

describe("getActionItem()", () => {
  it("returns typed action item with target metadata", () => {
    const profile = {
      available_actions_v2: [
        { action: "promote_choice", target: 5, endpoint: "/api/v2/choices/5/promote" },
      ],
    }
    const item = getActionItem(profile, "promote_choice")
    expect(item).not.toBeNull()
    expect(item?.target).toBe(5)
    expect(item?.endpoint).toBe("/api/v2/choices/5/promote")
  })

  it("returns null if action not found in v2", () => {
    const profile = {
      available_actions_v2: [{ action: "calculate_fee" }],
    }
    expect(getActionItem(profile, "non_existent")).toBeNull()
  })

  it("returns null when v2 absent (legacy doesn't carry metadata)", () => {
    const profile = {
      available_actions: ["calculate_fee"],
    }
    expect(getActionItem(profile, "calculate_fee")).toBeNull()
  })

  it("returns null for null profile", () => {
    expect(getActionItem(null, "any")).toBeNull()
  })
})
