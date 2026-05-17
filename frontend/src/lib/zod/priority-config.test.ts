/**
 * Zod contract tests for priority-config schemas — Q9 #07 PR3.
 *
 * Pins FE parity with the BE Pydantic schema + PG CHECK regex in
 * `phase1_08b_priority_demographics_gdnn`. If admin types a typo in
 * the area_code field ("KV2_NT" with an underscore, or lowercase
 * "kv1"), Zod must reject BEFORE the round-trip so the user never
 * sees a 500 from PostgreSQL.
 */

import { describe, expect, it } from "vitest"

import {
  AREA_CODE_REGEX,
  GROUP_CODE_REGEX,
  SUB_CODE_REGEX,
  priorityAreaConfigCreateSchema,
  priorityAreaConfigUpdateSchema,
  priorityConfigCloneRequestSchema,
  priorityConfigSeedDefaultsRequestSchema,
  priorityObjectConfigCreateSchema,
  priorityObjectConfigUpdateSchema,
} from "./priority-config"

// ============================================================================
// Regex sanity (pinned to TT 05/2021 Phụ lục 01 canonical code shape)
// ============================================================================

describe("AREA_CODE_REGEX", () => {
  it.each(["KV1", "KV2", "KV3", "KV2-NT", "KV9"])("accepts %s", (code) => {
    expect(AREA_CODE_REGEX.test(code)).toBe(true)
  })

  it.each([
    "KV2_NT", // underscore — common typo, must fail
    "kv1", // lowercase
    "KV2-nt", // lowercase suffix
    "KV1NT", // missing hyphen
    "KV-1", // hyphen in wrong place
    "KV0", // zero is not allowed
    "KV10", // two digits not allowed
    "", // empty
  ])("rejects %s", (code) => {
    expect(AREA_CODE_REGEX.test(code)).toBe(false)
  })
})

describe("GROUP_CODE_REGEX", () => {
  it.each(["UT1", "UT2", "UT9"])("accepts %s", (code) => {
    expect(GROUP_CODE_REGEX.test(code)).toBe(true)
  })

  it.each(["UT", "UT0", "UT10", "ut1", "U1", "V1", "UT1-A"])(
    "rejects %s",
    (code) => {
      expect(GROUP_CODE_REGEX.test(code)).toBe(false)
    },
  )
})

describe("SUB_CODE_REGEX", () => {
  it.each(["01", "04", "07", "99", "00"])("accepts %s", (code) => {
    expect(SUB_CODE_REGEX.test(code)).toBe(true)
  })

  it.each(["1", "100", "0A", "", "AB"])("rejects %s", (code) => {
    expect(SUB_CODE_REGEX.test(code)).toBe(false)
  })
})

// ============================================================================
// PriorityAreaConfigCreate — happy path + typical typos
// ============================================================================

describe("priorityAreaConfigCreateSchema", () => {
  it("parses a valid TT 05/2021 KV1 row", () => {
    const parsed = priorityAreaConfigCreateSchema.parse({
      academic_year: 2026,
      area_code: "KV1",
      area_name: "Khu vực 1",
      bonus_points: 0.75,
      description: "Vùng đặc biệt khó khăn",
    })
    expect(parsed.area_code).toBe("KV1")
    expect(parsed.bonus_points).toBe(0.75)
  })

  it("rejects the canonical underscore typo (KV2_NT)", () => {
    const result = priorityAreaConfigCreateSchema.safeParse({
      academic_year: 2026,
      area_code: "KV2_NT",
      area_name: "Khu vực 2 nông thôn",
      bonus_points: 0.5,
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const codeIssue = result.error.issues.find((i) =>
        i.path.includes("area_code"),
      )
      expect(codeIssue).toBeDefined()
    }
  })

  it("rejects bonus_points > 99.99", () => {
    const result = priorityAreaConfigCreateSchema.safeParse({
      academic_year: 2026,
      area_code: "KV1",
      area_name: "Khu vực 1",
      bonus_points: 100,
    })
    expect(result.success).toBe(false)
  })

  it("rejects bonus_points with > 2 decimal places", () => {
    const result = priorityAreaConfigCreateSchema.safeParse({
      academic_year: 2026,
      area_code: "KV1",
      area_name: "Khu vực 1",
      bonus_points: 0.123,
    })
    expect(result.success).toBe(false)
  })

  it("rejects academic_year < 2020", () => {
    const result = priorityAreaConfigCreateSchema.safeParse({
      academic_year: 2019,
      area_code: "KV1",
      area_name: "Khu vực 1",
      bonus_points: 0.75,
    })
    expect(result.success).toBe(false)
  })

  it("accepts integer bonus_points (0)", () => {
    const result = priorityAreaConfigCreateSchema.safeParse({
      academic_year: 2026,
      area_code: "KV3",
      area_name: "Khu vực 3",
      bonus_points: 0,
    })
    expect(result.success).toBe(true)
  })

  it("rejects malformed date string", () => {
    const result = priorityAreaConfigCreateSchema.safeParse({
      academic_year: 2026,
      area_code: "KV1",
      area_name: "Khu vực 1",
      bonus_points: 0.75,
      effective_from: "2026/01/01", // slashes not allowed
    })
    expect(result.success).toBe(false)
  })
})

describe("priorityAreaConfigUpdateSchema", () => {
  it("accepts empty body (no-op update)", () => {
    const result = priorityAreaConfigUpdateSchema.safeParse({})
    expect(result.success).toBe(true)
  })

  it("accepts partial body — bonus_points only", () => {
    const result = priorityAreaConfigUpdateSchema.safeParse({
      bonus_points: 1.0,
    })
    expect(result.success).toBe(true)
  })

  it("does not allow area_code on update (immutable identity)", () => {
    // Update schema deliberately omits area_code — extra keys are
    // stripped by default, not rejected. Confirm the parsed output
    // is empty when only area_code is sent.
    const result = priorityAreaConfigUpdateSchema.safeParse({
      area_code: "KV9",
    } as Record<string, unknown>)
    expect(result.success).toBe(true)
    if (result.success) {
      expect((result.data as Record<string, unknown>).area_code).toBeUndefined()
    }
  })
})

// ============================================================================
// PriorityObjectConfigCreate
// ============================================================================

describe("priorityObjectConfigCreateSchema", () => {
  it("parses a valid TT 05/2021 UT1/04 row", () => {
    const parsed = priorityObjectConfigCreateSchema.parse({
      academic_year: 2026,
      group_code: "UT1",
      sub_code: "04",
      description: "Con liệt sĩ",
      bonus_points: 2.0,
    })
    expect(parsed.sub_code).toBe("04")
    expect(parsed.bonus_points).toBe(2.0)
  })

  it("rejects single-digit sub_code (must be 2 digits)", () => {
    const result = priorityObjectConfigCreateSchema.safeParse({
      academic_year: 2026,
      group_code: "UT1",
      sub_code: "4",
      description: "Con liệt sĩ",
      bonus_points: 2.0,
    })
    expect(result.success).toBe(false)
  })

  it("rejects 3-digit sub_code", () => {
    const result = priorityObjectConfigCreateSchema.safeParse({
      academic_year: 2026,
      group_code: "UT1",
      sub_code: "004",
      description: "Anh hùng",
      bonus_points: 2.0,
    })
    expect(result.success).toBe(false)
  })

  it("rejects empty description", () => {
    const result = priorityObjectConfigCreateSchema.safeParse({
      academic_year: 2026,
      group_code: "UT1",
      sub_code: "04",
      description: "",
      bonus_points: 2.0,
    })
    expect(result.success).toBe(false)
  })

  it("rejects lowercase group_code", () => {
    const result = priorityObjectConfigCreateSchema.safeParse({
      academic_year: 2026,
      group_code: "ut1",
      sub_code: "04",
      description: "Con liệt sĩ",
      bonus_points: 2.0,
    })
    expect(result.success).toBe(false)
  })
})

describe("priorityObjectConfigUpdateSchema", () => {
  it("accepts partial body — bonus_points + description only", () => {
    const result = priorityObjectConfigUpdateSchema.safeParse({
      bonus_points: 1.5,
      description: "Mô tả mới",
    })
    expect(result.success).toBe(true)
  })

  it("accepts evidence_doc_type=null (clear field)", () => {
    const result = priorityObjectConfigUpdateSchema.safeParse({
      evidence_doc_type: null,
    })
    expect(result.success).toBe(true)
  })
})

// ============================================================================
// Clone + seed requests
// ============================================================================

describe("priorityConfigCloneRequestSchema", () => {
  it("accepts from_year != to_year", () => {
    const parsed = priorityConfigCloneRequestSchema.parse({
      from_year: 2026,
      to_year: 2027,
    })
    expect(parsed.to_year).toBe(2027)
  })

  it("rejects from_year === to_year", () => {
    const result = priorityConfigCloneRequestSchema.safeParse({
      from_year: 2026,
      to_year: 2026,
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      // Refine attaches the error to to_year per schema config.
      const issue = result.error.issues.find((i) => i.path.includes("to_year"))
      expect(issue).toBeDefined()
    }
  })

  it("rejects year < 2020", () => {
    const result = priorityConfigCloneRequestSchema.safeParse({
      from_year: 2019,
      to_year: 2026,
    })
    expect(result.success).toBe(false)
  })
})

describe("priorityConfigSeedDefaultsRequestSchema", () => {
  it("accepts year in range", () => {
    const parsed = priorityConfigSeedDefaultsRequestSchema.parse({
      academic_year: 2026,
    })
    expect(parsed.academic_year).toBe(2026)
  })

  it("rejects year > 2100", () => {
    const result = priorityConfigSeedDefaultsRequestSchema.safeParse({
      academic_year: 2101,
    })
    expect(result.success).toBe(false)
  })
})
