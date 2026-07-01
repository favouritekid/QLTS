// src/hooks/admissions/filterDefaults.test.ts
import { describe, it, expect } from "vitest"
import {
  parseAdmissionsSearchParamsToApiParams,
  areAdmissionsListParamsEqual,
  buildCoordinationParams,
  parseUnitId,
  ADMISSIONS_INT4_MAX,
} from "./filterDefaults"

// Regression guard for the SSR coordination-filter drift (Admission List v2 #1):
// the SSR parser + equality key-set MUST know the officer/unit_id/reviewer/
// unassigned params, else a ?officer=5 deep-link reuses the UNFILTERED SSR
// initialData (list shows all rows while badges show the filtered count).

describe("parseAdmissionsSearchParamsToApiParams — coordination filters", () => {
  it("parses officer / unit_id / reviewer / unassigned from the URL", () => {
    const p = parseAdmissionsSearchParamsToApiParams({
      officer: "5,7",
      unit_id: "3",
      reviewer: "9",
      unassigned: "1",
    })
    expect(p.assigned_officer_id).toBe("5,7")
    expect(p.unit_id).toBe(3)
    expect(p.assigned_reviewer_id).toBe("9")
    expect(p.unassigned).toBe(true)
  })

  it("omits coordination params when absent", () => {
    const p = parseAdmissionsSearchParamsToApiParams({})
    expect(p.assigned_officer_id).toBeUndefined()
    expect(p.unit_id).toBeUndefined()
    expect(p.assigned_reviewer_id).toBeUndefined()
    expect(p.unassigned).toBeUndefined()
  })

  it("treats unassigned only for '1' / 'true'", () => {
    expect(parseAdmissionsSearchParamsToApiParams({ unassigned: "true" }).unassigned).toBe(true)
    expect(parseAdmissionsSearchParamsToApiParams({ unassigned: "0" }).unassigned).toBeUndefined()
  })
})

describe("areAdmissionsListParamsEqual — coordination keys (SSR-drift guard)", () => {
  const base = parseAdmissionsSearchParamsToApiParams({})

  it("detects an officer-only difference → SSR initialData must NOT be reused", () => {
    const client = parseAdmissionsSearchParamsToApiParams({ officer: "5" })
    expect(areAdmissionsListParamsEqual(client, base)).toBe(false)
  })

  it("detects unit_id / reviewer / unassigned differences", () => {
    expect(
      areAdmissionsListParamsEqual(parseAdmissionsSearchParamsToApiParams({ unit_id: "3" }), base),
    ).toBe(false)
    expect(
      areAdmissionsListParamsEqual(parseAdmissionsSearchParamsToApiParams({ reviewer: "9" }), base),
    ).toBe(false)
    expect(
      areAdmissionsListParamsEqual(parseAdmissionsSearchParamsToApiParams({ unassigned: "1" }), base),
    ).toBe(false)
  })

  it("returns true when coordination params match", () => {
    const a = parseAdmissionsSearchParamsToApiParams({ officer: "5", unit_id: "3" })
    const b = parseAdmissionsSearchParamsToApiParams({ officer: "5", unit_id: "3" })
    expect(areAdmissionsListParamsEqual(a, b)).toBe(true)
  })
})

// int4-guard for unit_id (Admission List v2 review #1): a value beyond int4 must
// be DROPPED, never forwarded to the wire — else `Lead.unit_id == <huge>` makes
// asyncpg raise "integer out of range" → 500 (the #437 incident class).
describe("parseUnitId — int4 range guard", () => {
  it("parses a valid unit id", () => {
    expect(parseUnitId("3")).toBe(3)
    expect(parseUnitId(String(ADMISSIONS_INT4_MAX))).toBe(ADMISSIONS_INT4_MAX)
  })

  it("drops an out-of-int4 / non-positive / non-numeric value", () => {
    expect(parseUnitId("99999999999")).toBeUndefined() // > int4 max
    expect(parseUnitId(String(ADMISSIONS_INT4_MAX + 1))).toBeUndefined()
    expect(parseUnitId("0")).toBeUndefined()
    expect(parseUnitId("-4")).toBeUndefined()
    expect(parseUnitId("abc")).toBeUndefined()
    expect(parseUnitId(undefined)).toBeUndefined()
    expect(parseUnitId("")).toBeUndefined()
  })

  it("SSR parser drops an out-of-int4 unit_id deep-link (no SSR 500)", () => {
    const p = parseAdmissionsSearchParamsToApiParams({ unit_id: "99999999999" })
    expect(p.unit_id).toBeUndefined()
  })
})

// Shared coordination-param builder (apiFilters + countFilters + export) — one
// source so the three never drift (officer XOR unassigned, unit int4-guard).
describe("buildCoordinationParams", () => {
  const empty = { officerFilters: [], unitId: "", reviewerFilters: [], unassigned: false }

  it("maps officer / unit_id / reviewer", () => {
    const p = buildCoordinationParams({
      officerFilters: ["5", "7"],
      unitId: "3",
      reviewerFilters: ["9"],
      unassigned: false,
    })
    expect(p.assigned_officer_id).toBe("5,7")
    expect(p.unit_id).toBe(3)
    expect(p.assigned_reviewer_id).toBe("9")
    expect(p.unassigned).toBeUndefined()
  })

  it("XOR: 'unassigned' drops the officer-IN list (avoids IS NULL AND IN = ∅)", () => {
    const p = buildCoordinationParams({
      officerFilters: ["5"],
      unitId: "",
      reviewerFilters: [],
      unassigned: true,
    })
    expect(p.assigned_officer_id).toBeUndefined()
    expect(p.unassigned).toBe(true)
  })

  it("drops an out-of-int4 unit_id (never 500s the backend)", () => {
    const p = buildCoordinationParams({ ...empty, unitId: "99999999999" })
    expect(p.unit_id).toBeUndefined()
  })

  it("returns an empty object when nothing is set", () => {
    expect(buildCoordinationParams(empty)).toEqual({})
  })
})
