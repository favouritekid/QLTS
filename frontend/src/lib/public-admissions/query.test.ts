import { describe, expect, it } from "vitest"

import { publicAdmissionsCatalogParams } from "./query"

describe("publicAdmissionsCatalogParams", () => {
  // ============================================================
  // Canonical admission_round_id parsing
  // ============================================================
  it("parses canonical admission_round_id (valid integer)", () => {
    expect(publicAdmissionsCatalogParams({ admission_round_id: "5" })).toEqual({
      admission_round_id: 5,
    })
  })

  it("ignores admission_round_id when not provided", () => {
    expect(publicAdmissionsCatalogParams({})).toBeUndefined()
  })

  // ============================================================
  // Alias `round` parsing
  // ============================================================
  it("falls back to alias `round` when canonical missing", () => {
    expect(publicAdmissionsCatalogParams({ round: "7" })).toEqual({
      admission_round_id: 7,
    })
  })

  it("canonical admission_round_id wins over alias round when both present", () => {
    expect(
      publicAdmissionsCatalogParams({
        admission_round_id: "5",
        round: "10",
      }),
    ).toEqual({ admission_round_id: 5 })
  })

  // ============================================================
  // Invalid round ID → strict fail-closed sentinel (post review #2)
  // ============================================================
  it("invalid non-numeric → sentinel 0 (strict fail-closed)", () => {
    // Plan v4 locked contract: explicit intent → strict. Even when
    // user-supplied value is syntactically garbage, we preserve the
    // intent by passing sentinel 0 (non-existent round PK) → BE serves
    // empty 200.
    expect(
      publicAdmissionsCatalogParams({ admission_round_id: "abc" }),
    ).toEqual({ admission_round_id: 0 })
  })

  it("invalid zero → sentinel 0", () => {
    expect(publicAdmissionsCatalogParams({ admission_round_id: "0" })).toEqual({
      admission_round_id: 0,
    })
  })

  it("invalid negative → sentinel 0", () => {
    expect(
      publicAdmissionsCatalogParams({ admission_round_id: "-5" }),
    ).toEqual({ admission_round_id: 0 })
  })

  it("invalid decimal → sentinel 0 (parseInt would strip silently)", () => {
    // parseInt("3.5", 10) === 3 — preserving that as "round 3" would
    // silently corrupt user intent. Match-string guard rejects.
    expect(
      publicAdmissionsCatalogParams({ admission_round_id: "3.5" }),
    ).toEqual({ admission_round_id: 0 })
  })

  it("empty string → no admission_round_id (not sentinel)", () => {
    // Empty string ≈ user didn't enter anything → treat as no intent
    // (omitted) → default eligible-active union, NOT fail-closed sentinel.
    expect(
      publicAdmissionsCatalogParams({ admission_round_id: "" }),
    ).toBeUndefined()
  })

  it("invalid alias round → sentinel via same path", () => {
    expect(publicAdmissionsCatalogParams({ round: "garbage" })).toEqual({
      admission_round_id: 0,
    })
  })

  // ============================================================
  // Audience parsing
  // ============================================================
  it("preserves audience param", () => {
    expect(publicAdmissionsCatalogParams({ audience: "thpt" })).toEqual({
      audience: "thpt",
    })
  })

  it("combines round + audience", () => {
    expect(
      publicAdmissionsCatalogParams({
        admission_round_id: "3",
        audience: "gdtx",
      }),
    ).toEqual({ admission_round_id: 3, audience: "gdtx" })
  })

  // ============================================================
  // Array-form searchParams (Next.js may pass arrays)
  // ============================================================
  it("takes first value when searchParam is an array", () => {
    expect(
      publicAdmissionsCatalogParams({
        admission_round_id: ["5", "10"],
      }),
    ).toEqual({ admission_round_id: 5 })
  })

  it("returns undefined when only undefined-valued keys present", () => {
    expect(
      publicAdmissionsCatalogParams({
        admission_round_id: undefined,
        audience: undefined,
      }),
    ).toBeUndefined()
  })
})
