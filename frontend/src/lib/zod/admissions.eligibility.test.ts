/**
 * FE Zod tests for the M-1-11 deploy-choreography Stage 1
 * permissive parse + #184 Wave 2 PR-2A 4 eligibility scalar
 * fields (FE-zod-eligibility / phase1_09a wiring).
 *
 * Locks the runtime contract:
 *
 * 1. Permissive status parse — BE deploys M-1-11 (status CHECK
 *    extend 10 → 14) BEFORE the FE container build catches up.
 *    Profile responses with ``status="reviewing"`` /
 *    ``status="admitted"`` MUST parse without throwing so the FE
 *    renders generic gray badge (status-badge.config.ts:380
 *    DEFAULT_BADGE_CONFIG fallback) instead of crashing.
 *
 * 2. Legacy 14 status all still parse strict — Stage 1 widens the
 *    accepted set; doesn't narrow.
 *
 * 3. 4 eligibility scalar fields — gpa_overall, conduct,
 *    health_category, graduation_year. All nullable + optional so
 *    legacy responses (pre-phase1_09a) still parse.
 *
 * 4. Range guards mirror BE Pydantic + alembic migration:
 *    - gpa_overall [0, 10]
 *    - conduct enum {TB, KHA, TOT}
 *    - health_category int [1, 4]
 *    - graduation_year int [1900, 2100]
 */
import { describe, expect, it } from "vitest"

import { admissionProfileResponseSchema } from "./admissions"


/**
 * Minimum profile shape that satisfies all REQUIRED fields in
 * admissionProfileResponseSchema. Each test layers eligibility
 * fields on top of this baseline.
 */
function _baselineProfile(): Record<string, unknown> {
  // The schema declares many ``z.string().nullable()`` fields
  // (NOT optional) — they need an explicit ``null`` rather than
  // being omitted. List them all so each test can override only
  // the field it cares about.
  const isoDate = "2026-05-04T00:00:00Z"
  return {
    id: 1,
    lead_id: 100,
    full_name: null,
    dob: null,
    gender: null,
    email: null,
    phone: null,
    social_insurance_number: null,
    nationality: null,
    ethnicity: null,
    religion: null,
    disability_type: null,
    permanent_province: null,
    permanent_district: null,
    permanent_ward: null,
    permanent_residential_group: null,
    permanent_street_address: null,
    place_of_birth: null,
    native_place: null,
    union_entry_date: null,
    party_entry_date: null,
    party_official_entry_date: null,
    status: "draft",
    applied_rules: {
      schema_version: 1,
      mandatory_docs: [],
      method_type: "gpa_only",
    },
    family_info: [],
    academic_history: [],
    admission_scores: null,
    documents_checklist: [],
    created_at: isoDate,
    updated_at: isoDate,
    permissions: {},
    minor_correction_fields: [],
  }
}


// =============================================================================
// 1. Permissive status — Stage 1 deploy choreography
// =============================================================================


describe("admissionProfileResponseSchema — permissive status parse", () => {
  it("parses all 10 legacy status values strict", () => {
    const legacy = [
      "draft",
      "submitted",
      "resubmitted",
      "approved",
      "rejected",
      "revision_requested",
      "confirmed",
      "overridden",
      "enrolled",
      "withdrawn",
    ]
    for (const status of legacy) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        status,
      })
      expect(result.success, `legacy status ${status} should parse`).toBe(true)
    }
  })

  it("parses unknown status 'reviewing' (M-1-11 future state)", () => {
    // M-1-11 extends the BE CHECK to 14 states. FE permissive
    // catchall lets `reviewing` through during the deploy window.
    const result = admissionProfileResponseSchema.safeParse({
      ..._baselineProfile(),
      status: "reviewing",
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.status).toBe("reviewing")
    }
  })

  it("parses unknown status 'admitted' (M-1-11 future state)", () => {
    const result = admissionProfileResponseSchema.safeParse({
      ..._baselineProfile(),
      status: "admitted",
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.status).toBe("admitted")
    }
  })

  it("parses arbitrary unknown status string without crashing", () => {
    // Defense — even if BE accidentally emits a typo or a state
    // we haven't planned for, FE must not crash. StatusBadge
    // fallback renders the raw string with neutral styling.
    const result = admissionProfileResponseSchema.safeParse({
      ..._baselineProfile(),
      status: "future_state_x",
    })
    expect(result.success).toBe(true)
  })

  it("rejects non-string status (number / object / null)", () => {
    // Permissive only widens to ANY STRING; type itself stays
    // string. A number or null is still a contract violation.
    for (const bad of [42, { state: "draft" }, null, undefined]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        status: bad,
      })
      expect(result.success, `non-string ${typeof bad} should fail`).toBe(false)
    }
  })
})


// =============================================================================
// 2. 4 eligibility scalar fields
// =============================================================================


describe("admissionProfileResponseSchema — gpa_overall", () => {
  it("accepts numeric in range [0, 10]", () => {
    for (const value of [0, 0.5, 5.25, 9.99, 10]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        gpa_overall: value,
      })
      expect(result.success, `gpa ${value} should parse`).toBe(true)
    }
  })

  it("coerces string-numeric (BE Pydantic Numeric → JSON string)", () => {
    const result = admissionProfileResponseSchema.safeParse({
      ..._baselineProfile(),
      gpa_overall: "8.5",
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.gpa_overall).toBe(8.5)
    }
  })

  it("rejects out-of-range gpa", () => {
    for (const value of [-0.1, 10.1, 100]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        gpa_overall: value,
      })
      expect(result.success, `gpa ${value} should fail`).toBe(false)
    }
  })

  it("accepts null + omitted (legacy response)", () => {
    expect(
      admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        gpa_overall: null,
      }).success,
    ).toBe(true)
    // Omit entirely.
    expect(admissionProfileResponseSchema.safeParse(_baselineProfile()).success).toBe(true)
  })
})


describe("admissionProfileResponseSchema — conduct", () => {
  it("accepts the 3 enum values", () => {
    for (const value of ["TB", "KHA", "TOT"]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        conduct: value,
      })
      expect(result.success).toBe(true)
    }
  })

  it("rejects unknown enum value", () => {
    // Conduct is enum-strict (BE CHECK constraint enforces it
    // too); permissive only applies to status field.
    const result = admissionProfileResponseSchema.safeParse({
      ..._baselineProfile(),
      conduct: "EXCELLENT",
    })
    expect(result.success).toBe(false)
  })

  it("accepts null + omitted (admin UI hasn't filled yet)", () => {
    expect(
      admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        conduct: null,
      }).success,
    ).toBe(true)
  })
})


describe("admissionProfileResponseSchema — health_category", () => {
  it("accepts integers 1..4", () => {
    for (const value of [1, 2, 3, 4]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        health_category: value,
      })
      expect(result.success).toBe(true)
    }
  })

  it("rejects out-of-range + non-integer", () => {
    for (const value of [0, 5, 3.5, -1]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        health_category: value,
      })
      expect(result.success, `health_category ${value} should fail`).toBe(false)
    }
  })
})


describe("admissionProfileResponseSchema — graduation_year", () => {
  it("accepts years in [1900, 2100]", () => {
    for (const value of [1900, 1950, 2026, 2100]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        graduation_year: value,
      })
      expect(result.success, `year ${value} should parse`).toBe(true)
    }
  })

  it("rejects years outside the range", () => {
    for (const value of [1899, 2101, 0]) {
      const result = admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        graduation_year: value,
      })
      expect(result.success, `year ${value} should fail`).toBe(false)
    }
  })

  it("accepts null + omitted", () => {
    expect(
      admissionProfileResponseSchema.safeParse({
        ..._baselineProfile(),
        graduation_year: null,
      }).success,
    ).toBe(true)
    expect(admissionProfileResponseSchema.safeParse(_baselineProfile()).success).toBe(true)
  })
})


// =============================================================================
// 3. Combined — eligibility fields + permissive status interplay
// =============================================================================


describe("admissionProfileResponseSchema — combined Wave 2 + M-1-11 deploy", () => {
  it("parses a profile with all 4 eligibility fields + future status", () => {
    // The realistic post-Wave-2-pre-Wave-3 response shape: BE
    // emits the new eligibility fields (Wave 2 shipped) + a new
    // status (Wave 3 ships next). FE Zod must accept both.
    const result = admissionProfileResponseSchema.safeParse({
      ..._baselineProfile(),
      status: "reviewing",
      gpa_overall: 8.75,
      conduct: "TOT",
      health_category: 1,
      graduation_year: 2026,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.status).toBe("reviewing")
      expect(result.data.gpa_overall).toBe(8.75)
      expect(result.data.conduct).toBe("TOT")
      expect(result.data.health_category).toBe(1)
      expect(result.data.graduation_year).toBe(2026)
    }
  })
})
