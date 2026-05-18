// src/lib/zod/admissions.test.ts
/**
 * Zod contract tests for admission schemas — scoped to PR6 Step 1.
 *
 * Guards the backend-to-frontend contract for per-subject weights.
 * Backend freezes `subject_weights` at two levels inside applied_rules:
 *   1. Top-level: `applied_rules.subject_weights` (generate_snapshot)
 *   2. Nested:    `applied_rules.subject_groups[*].weights`
 *                 (_serialize_subject_groups)
 *
 * Without these tests, an accidental omission in `appliedRulesSchema`
 * (zod strips unknown keys by default) would silently drop the weight
 * map at runtime — which is exactly the regression flagged in PR-A
 * review.
 */

import { describe, it, expect } from "vitest"

import {
  admissionProfileUpdateSchema,
  appliedRulesSchema,
  subjectGroupSnapshotSchema,
} from "./admissions"

describe("subjectGroupSnapshotSchema (nested weights)", () => {
  it("parses a group with weights", () => {
    const parsed = subjectGroupSnapshotSchema.parse({
      code: "A00",
      name: "Toán - Lý - Hóa",
      subjects: ["math", "physics", "chemistry"],
      weights: { math: 2, physics: 1, chemistry: 1 },
    })

    expect(parsed.weights).toEqual({ math: 2, physics: 1, chemistry: 1 })
  })

  it("parses a pre-migration group without weights (backward-compat)", () => {
    const parsed = subjectGroupSnapshotSchema.parse({
      code: "D01",
      name: "Toán - Văn - Anh",
      subjects: ["math", "literature", "english"],
    })

    expect(parsed.weights).toBeUndefined()
    // `subjects` flat list still parses — pre-existing clients unaffected.
    expect(parsed.subjects).toEqual(["math", "literature", "english"])
  })

  it("rejects zero or negative weights", () => {
    expect(() =>
      subjectGroupSnapshotSchema.parse({
        code: "A00",
        name: "x",
        subjects: ["math"],
        weights: { math: 0 },
      }),
    ).toThrow()

    expect(() =>
      subjectGroupSnapshotSchema.parse({
        code: "A00",
        name: "x",
        subjects: ["math"],
        weights: { math: -1 },
      }),
    ).toThrow()
  })
})

describe("appliedRulesSchema (top-level subject_weights)", () => {
  it("preserves top-level subject_weights emitted by generate_snapshot()", () => {
    // Backend emits subject_weights at the snapshot root. Without the
    // top-level field in the Zod schema, z.object() would strip it and
    // the frontend would silently lose the weight map.
    const raw = {
      min_gpa: 6.5,
      scoring_method: "weighted" as const,
      allowed_subject_codes: ["math", "physics", "chemistry"],
      subject_weights: { math: 2, physics: 1, chemistry: 1 },
      subject_groups: [
        {
          code: "A00",
          name: "Toán - Lý - Hóa",
          subjects: ["math", "physics", "chemistry"],
          weights: { math: 2, physics: 1, chemistry: 1 },
        },
      ],
      method_type: "subject_based" as const,
    }

    const parsed = appliedRulesSchema.parse(raw)

    expect(parsed.subject_weights).toEqual({
      math: 2,
      physics: 1,
      chemistry: 1,
    })
    // Nested weights flow through intact too — regression guard for the
    // two fields being independently mirrored.
    expect(parsed.subject_groups?.[0]?.weights).toEqual({
      math: 2,
      physics: 1,
      chemistry: 1,
    })
  })

  it("accepts pre-migration snapshots without subject_weights", () => {
    // Matches the no-retroactive-backfill decision: old profiles parse
    // fine; consumers treat missing weights as 1.0 (plain sum).
    const raw = {
      min_gpa: 6.5,
      scoring_method: "sum" as const,
      allowed_subject_codes: ["math"],
      subject_groups: [],
      method_type: "subject_based" as const,
    }

    const parsed = appliedRulesSchema.parse(raw)

    expect(parsed.subject_weights).toBeUndefined()
  })

  it("rejects zero or negative top-level weights", () => {
    expect(() =>
      appliedRulesSchema.parse({
        scoring_method: "weighted" as const,
        allowed_subject_codes: [],
        subject_weights: { math: 0 },
        subject_groups: [],
        method_type: "subject_based" as const,
      }),
    ).toThrow()
  })
})


// =============================================================================
// Q9 #07 PR5/A — Priority bonus Zod schemas (review-3 m-FE-3 fix)
// =============================================================================
//
// Lock the FE Zod parity with BE Pydantic for the 7 priority fields.
// Without these tests, a future refactor could silently relax / drop
// validation and the FE would accept garbage that BE then 400s on,
// degrading UX to "click submit then see red".

describe("admissionProfileUpdateSchema priority fields (Q9 #07)", () => {
  const baseline = { version: 1 }

  it("accepts canonical sub_codes + verified evidence", () => {
    const parsed = admissionProfileUpdateSchema.parse({
      ...baseline,
      priority_object_codes: ["04", "06"],
      priority_object_evidence: {
        "04": { status: "verified" },
        "06": { status: "pending", document_id: 123 },
      },
    })
    expect(parsed.priority_object_codes).toEqual(["04", "06"])
    expect(parsed.priority_object_evidence?.["04"].status).toBe("verified")
  })

  it("rejects garbage UT code (per-item regex from prioritySubCodeSchema)", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        priority_object_codes: ["INVALID_99"],
      }),
    ).toThrow()
  })

  it("rejects evidence with bad status enum", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        priority_object_evidence: {
          "04": { status: "approved_typo" },
        },
      }),
    ).toThrow()
  })

  it("rejects evidence with extra unknown keys (.strict mirror of BE extra=forbid)", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        priority_object_evidence: {
          "04": { status: "verified", random_extra: "x" },
        },
      }),
    ).toThrow()
  })

  it("rejects evidence dict keyed by non-canonical sub_code", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        priority_object_evidence: {
          "INVALID_KEY": { status: "verified" },
        },
      }),
    ).toThrow()
  })

  it("rejects invalid area_resolution_basis enum value", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        area_resolution_basis: "highschool",
      }),
    ).toThrow()
  })

  // ==========================================================================
  // Q9 #07 PR5 v1.3 phase1_09 — cultural + vocational 2-field parallel
  // ==========================================================================

  it("accepts cultural_education_level enum values (5 options)", () => {
    const values = [
      "completed_thcs", "graduated_thcs",
      "completed_thpt", "graduated_thpt", "graduated_gdtx",
    ]
    for (const v of values) {
      const parsed = admissionProfileUpdateSchema.parse({
        ...baseline,
        cultural_education_level: v,
      })
      expect(parsed.cultural_education_level).toBe(v)
    }
  })

  it("rejects invalid cultural_education_level value", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        cultural_education_level: "tot_nghiep_thpt",  // wrong format
      }),
    ).toThrow()
  })

  it("accepts vocational_qualification enum values (4 options)", () => {
    const values = ["none", "so_cap", "trung_cap", "cao_dang"]
    for (const v of values) {
      const parsed = admissionProfileUpdateSchema.parse({
        ...baseline,
        vocational_qualification: v,
      })
      expect(parsed.vocational_qualification).toBe(v)
    }
  })

  it("rejects invalid vocational_qualification value", () => {
    expect(() =>
      admissionProfileUpdateSchema.parse({
        ...baseline,
        vocational_qualification: "trung_cap_nghe",  // wrong key
      }),
    ).toThrow()
  })

  it("accepts both fields parallel (Tốt nghiệp THPT + TC)", () => {
    const parsed = admissionProfileUpdateSchema.parse({
      ...baseline,
      cultural_education_level: "graduated_thpt",
      vocational_qualification: "trung_cap",
    })
    expect(parsed.cultural_education_level).toBe("graduated_thpt")
    expect(parsed.vocational_qualification).toBe("trung_cap")
  })

  it("dropped fields no longer in schema (high_school_id, kv_resolved, reason)", () => {
    // Strict schema would reject extras, but admissionProfileUpdateSchema
    // uses default Zod behavior (strip unknown). Verify by checking parsed
    // shape doesn't contain dropped fields.
    const probePayload: Record<string, unknown> = {
      ...baseline,
      high_school_id: 42,  // dropped in phase1_09
      high_school_kv_resolved: "KV1",  // dropped
      area_resolution_reason: "Legacy reason",  // dropped
    }
    const parsed = admissionProfileUpdateSchema.parse(probePayload)
    expect("high_school_id" in parsed).toBe(false)
    expect("high_school_kv_resolved" in parsed).toBe(false)
    expect("area_resolution_reason" in parsed).toBe(false)
  })
})
