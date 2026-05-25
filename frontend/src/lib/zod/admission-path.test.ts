// src/lib/zod/admission-path.test.ts
import { describe, it, expect } from "vitest"

import {
  admissionPathCreateSchema,
  admissionPathResponseSchema,
} from "./admission-path"

// Round contract hardening (plan v4): flat round_* metadata on the path
// response (Section D) + required admission_round_id on create (Section B).
describe("admissionPathResponseSchema — flat round metadata (plan v4 Section D)", () => {
  const ROUND_FIELDS = [
    "round_code",
    "round_name",
    "round_start_date",
    "round_end_date",
    "round_archived_at",
    "round_is_active",
    "round_allow_multi_nv",
  ] as const

  it("declares all 7 flat round_* fields", () => {
    const shape = admissionPathResponseSchema.shape
    for (const key of ROUND_FIELDS) {
      expect(key in shape).toBe(true)
    }
  })

  it("treats round fields as nullable + optional (None when not eager-loaded)", () => {
    const shape = admissionPathResponseSchema.shape
    // Each round field must accept both undefined (absent) and null (BE
    // emitted null because the relationship wasn't eager-loaded).
    for (const key of ROUND_FIELDS) {
      expect(shape[key].safeParse(undefined).success).toBe(true)
      expect(shape[key].safeParse(null).success).toBe(true)
    }
  })

  it("parses concrete round values of the right types", () => {
    const shape = admissionPathResponseSchema.shape
    expect(shape.round_code.safeParse("DOT_2").success).toBe(true)
    expect(shape.round_start_date.safeParse("2026-04-01").success).toBe(true)
    expect(
      shape.round_archived_at.safeParse("2026-05-14T00:00:00+07:00").success,
    ).toBe(true)
    expect(shape.round_is_active.safeParse(true).success).toBe(true)
    expect(shape.round_allow_multi_nv.safeParse(false).success).toBe(true)
  })
})

describe("admissionPathCreateSchema — admission_round_id REQUIRED (plan v4 Section B)", () => {
  const base = { academic_info_id: 1, admission_method_id: 2, admission_round_id: 3 }

  it("parses a payload with admission_round_id", () => {
    const parsed = admissionPathCreateSchema.parse(base)
    expect(parsed.admission_round_id).toBe(3)
  })

  it("rejects a payload missing admission_round_id (auto-DOT_1 shim removed)", () => {
    const { admission_round_id: _omit, ...withoutRound } = base
    void _omit
    expect(() => admissionPathCreateSchema.parse(withoutRound)).toThrow()
  })

  it("rejects a non-positive admission_round_id", () => {
    expect(() =>
      admissionPathCreateSchema.parse({ ...base, admission_round_id: 0 }),
    ).toThrow()
  })
})
