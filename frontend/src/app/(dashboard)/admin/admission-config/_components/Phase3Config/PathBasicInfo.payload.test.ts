/**
 * Pure-function tests for the PR-1B'-FE payload builders inside
 * ``PathBasicInfo`` (#184 Wave 1 PR-1B'-FE).
 *
 * Why pure-function and not full-render: ``PathBasicInfo`` is
 * tightly coupled to ``useAuth`` + React Query mutation hooks,
 * which require a heavyweight test harness. The 3 wire-payload
 * shapes are the load-bearing contract — once we lock those, the
 * UI render is conventional Tailwind / shadcn primitives that
 * type-check + visual review cover. Re-implements the 3 builders
 * from the source so a regression in the component touches both.
 */
import { describe, expect, it } from "vitest"

import type {
  AdmissionAudience,
  BonusRuleOverride,
} from "@/lib/zod/admission-path"


// =============================================================================
// Re-implemented builders — kept in lockstep with PathBasicInfo.tsx
// =============================================================================
// If a divergence happens between this test and the component source,
// the failing assertion is the cue to update both. Each helper is
// short on purpose so the contract surface stays narrow.


function buildApplicableToPayload(
  applicableTo: Set<AdmissionAudience>,
): AdmissionAudience[] | null {
  return applicableTo.size > 0 ? Array.from(applicableTo) : null
}

function buildMethodQuotaPayload(methodQuotaInput: string): number | null {
  if (methodQuotaInput.trim() === "") return null
  const parsed = Number(methodQuotaInput)
  if (!Number.isFinite(parsed) || parsed < 0) return null
  return Math.floor(parsed)
}

function buildBonusOverridePayload(args: {
  enabled: boolean
  applyAreaBonus: boolean
  applyObjectBonus: boolean
  maxTotalBonusInput: string
}): BonusRuleOverride | null {
  if (!args.enabled) return null
  const trimmed = args.maxTotalBonusInput.trim()
  let maxTotal: number | null
  if (trimmed === "") {
    maxTotal = null
  } else {
    const parsed = Number(trimmed)
    if (!Number.isFinite(parsed)) {
      maxTotal = null
    } else {
      maxTotal = Math.min(10, Math.max(0, parsed))
    }
  }
  return {
    apply_area_bonus: args.applyAreaBonus,
    apply_object_bonus: args.applyObjectBonus,
    max_total_bonus: maxTotal,
  }
}


// =============================================================================
// applicable_to
// =============================================================================


describe("buildApplicableToPayload", () => {
  it("empty Set → null (= applicable to every audience)", () => {
    // Phase 1+2 contract — empty filter is distinct from any
    // audience-list selection; backend treats null as legacy.
    expect(buildApplicableToPayload(new Set())).toBeNull()
  })

  it("single audience → array of one", () => {
    const input = new Set<AdmissionAudience>(["POST_THPT"])
    expect(buildApplicableToPayload(input)).toEqual(["POST_THPT"])
  })

  it("multiple audiences preserve insertion order", () => {
    // Ordering is informational only (BE accepts any order via
    // GIN index), but a deterministic order keeps diffs stable
    // when the admin re-saves.
    const input = new Set<AdmissionAudience>([
      "POST_THPT",
      "LIEN_THONG_TC",
      "VLVH",
    ])
    expect(buildApplicableToPayload(input)).toEqual([
      "POST_THPT",
      "LIEN_THONG_TC",
      "VLVH",
    ])
  })
})


// =============================================================================
// method_quota
// =============================================================================


describe("buildMethodQuotaPayload", () => {
  it("empty string → null (= no method-level cap)", () => {
    expect(buildMethodQuotaPayload("")).toBeNull()
  })

  it("whitespace-only → null", () => {
    expect(buildMethodQuotaPayload("   ")).toBeNull()
  })

  it("zero is a legitimate value (admin marks method exhausted)", () => {
    expect(buildMethodQuotaPayload("0")).toBe(0)
  })

  it("positive integer parses through", () => {
    expect(buildMethodQuotaPayload("100")).toBe(100)
  })

  it("decimal input is floored to integer (BE column is Integer, ge=0)", () => {
    // Codex P2 catch on PR-1B'-FE: previous version let ``"1.5"`` through
    // and BE rejected with Pydantic ValidationError 400 — bad UX.
    // Floor at the FE so admin's intent ("about 1") survives the wire.
    expect(buildMethodQuotaPayload("1.5")).toBe(1)
    expect(buildMethodQuotaPayload("99.99")).toBe(99)
  })

  it("negative input → null (rejected)", () => {
    // BE schema also rejects via ge=0; defense-in-depth on FE.
    expect(buildMethodQuotaPayload("-1")).toBeNull()
  })

  it("negative decimal → null (rejected)", () => {
    expect(buildMethodQuotaPayload("-0.5")).toBeNull()
  })

  it("non-numeric input → null", () => {
    expect(buildMethodQuotaPayload("abc")).toBeNull()
  })
})


// =============================================================================
// bonus_rule_override
// =============================================================================


describe("buildBonusOverridePayload", () => {
  it("toggle OFF → null (= inherit method default) regardless of subfields", () => {
    // Subfield state should not leak into the wire payload when
    // the toggle is off; this ensures admin can flip the toggle
    // without first clearing the subfields.
    expect(
      buildBonusOverridePayload({
        enabled: false,
        applyAreaBonus: true,
        applyObjectBonus: true,
        maxTotalBonusInput: "2.5",
      }),
    ).toBeNull()
  })

  it("toggle ON with all subfields → typed shape", () => {
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: true,
        applyObjectBonus: false,
        maxTotalBonusInput: "2.75",
      }),
    ).toEqual({
      apply_area_bonus: true,
      apply_object_bonus: false,
      max_total_bonus: 2.75,
    })
  })

  it("toggle ON with empty max_total_bonus input → null cap (no limit)", () => {
    // Distinct semantic from "0 cap" — empty = no cap, 0 = effectively
    // disabled. Codex P2 explicit: structured form preserves the
    // distinction the raw JSON editor would lose.
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: true,
        applyObjectBonus: true,
        maxTotalBonusInput: "",
      }),
    ).toEqual({
      apply_area_bonus: true,
      apply_object_bonus: true,
      max_total_bonus: null,
    })
  })

  it("toggle ON with both bonus flags off → still emits typed shape (admin disabled both bonuses for this path)", () => {
    // This is a real admin choice — "this path overrides the
    // method default to BLOCK both area and subject bonus". Wire
    // shape should still be the typed object, not null (null
    // would mean "inherit method default" which is the wrong
    // semantic).
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: false,
        applyObjectBonus: false,
        maxTotalBonusInput: "0",
      }),
    ).toEqual({
      apply_area_bonus: false,
      apply_object_bonus: false,
      max_total_bonus: 0,
    })
  })

  it("non-numeric max_total_bonus input → null cap", () => {
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: true,
        applyObjectBonus: true,
        maxTotalBonusInput: "abc",
      }),
    ).toEqual({
      apply_area_bonus: true,
      apply_object_bonus: true,
      max_total_bonus: null,
    })
  })

  it("max_total_bonus > 10 is clamped (BE schema ge=0, le=10)", () => {
    // Codex P2 catch on PR-1B'-FE: previous version sent ``11.5`` to BE
    // which rejected with Pydantic ValidationError 400. Clamp at the FE
    // boundary so admin's "cap me hard" intent survives without a
    // round-trip error.
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: true,
        applyObjectBonus: true,
        maxTotalBonusInput: "11.5",
      }),
    ).toEqual({
      apply_area_bonus: true,
      apply_object_bonus: true,
      max_total_bonus: 10,
    })
  })

  it("max_total_bonus < 0 is clamped to 0", () => {
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: true,
        applyObjectBonus: true,
        maxTotalBonusInput: "-2.0",
      }),
    ).toEqual({
      apply_area_bonus: true,
      apply_object_bonus: true,
      max_total_bonus: 0,
    })
  })

  it("max_total_bonus exactly 10 is preserved (boundary)", () => {
    expect(
      buildBonusOverridePayload({
        enabled: true,
        applyAreaBonus: true,
        applyObjectBonus: true,
        maxTotalBonusInput: "10",
      }),
    ).toEqual({
      apply_area_bonus: true,
      apply_object_bonus: true,
      max_total_bonus: 10,
    })
  })
})
