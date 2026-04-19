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

import { appliedRulesSchema, subjectGroupSnapshotSchema } from "./admissions"

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
