// src/hooks/admissions/filterDefaults.test.ts
import { describe, it, expect } from "vitest"
import {
  parseAdmissionsSearchParamsToApiParams,
  areAdmissionsListParamsEqual,
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
