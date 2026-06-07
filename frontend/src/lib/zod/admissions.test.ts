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
import { z } from "zod"

import {
  admissionProfileCreateSchema,
  admissionProfileUpdateSchema,
  appliedRulesSchema,
  priorityObjectEvidenceEntrySchema,
  subjectGroupSnapshotSchema,
  executiveSummaryItemSchema,
} from "./admissions"

describe("executiveSummaryItemSchema — Phase 3 union (legacy string | structured object)", () => {
  it("parses a legacy string item", () => {
    expect(executiveSummaryItemSchema.parse("Thiếu 2 tài liệu bắt buộc")).toBe(
      "Thiếu 2 tài liệu bắt buộc",
    )
  })

  it("parses a structured object item with all fields", () => {
    const obj = {
      code: "documents_missing",
      message: "Thiếu 2 tài liệu bắt buộc",
      step: 6,
      section: "documents",
      severity: "blocker" as const,
    }
    expect(executiveSummaryItemSchema.parse(obj)).toEqual(obj)
  })

  it("parses a structured object with optional step/section/severity omitted", () => {
    const obj = { code: "x", message: "y" }
    expect(executiveSummaryItemSchema.parse(obj)).toEqual(obj)
  })

  it("tolerates an unknown severity → coerces to undefined (does NOT throw)", () => {
    const parsed = executiveSummaryItemSchema.parse({
      code: "x",
      message: "y",
      severity: "fatal",
    }) as { code: string; message: string; severity?: string }
    expect(parsed.code).toBe("x")
    expect(parsed.message).toBe("y")
    expect(parsed.severity).toBeUndefined()
  })

  it("an array with an unknown severity does NOT fail the whole parse", () => {
    expect(() =>
      z.array(executiveSummaryItemSchema).parse([
        { code: "c1", message: "m1", step: 6, severity: "blocker" },
        { code: "c2", message: "m2", step: 5, severity: "info" },
      ]),
    ).not.toThrow()
  })

  it("parses a legacy string[] array (old responses)", () => {
    const arr = ["a", "b"]
    expect(z.array(executiveSummaryItemSchema).parse(arr)).toEqual(arr)
  })

  it("parses a structured object[] array (new responses)", () => {
    const arr = [
      { code: "c1", message: "m1", step: 1, section: "personal_info", severity: "blocker" as const },
      { code: "c2", message: "m2", step: 6, section: "documents", severity: "warning" as const },
    ]
    expect(z.array(executiveSummaryItemSchema).parse(arr)).toEqual(arr)
  })

  it("parses a MIXED array (string + object) — soft-cutover tolerance", () => {
    const arr = ["legacy", { code: "c", message: "m", step: 2 }]
    expect(z.array(executiveSummaryItemSchema).parse(arr)).toEqual(arr)
  })
})

describe("admissionProfileCreateSchema — round contract hardening (plan v4)", () => {
  const base = {
    lead_id: 1,
    admission_method_id: 2,
    admission_round_id: 3,
    academic_year: 2026,
  }

  it("parses a complete payload with admission_round_id + academic_year", () => {
    const parsed = admissionProfileCreateSchema.parse(base)
    expect(parsed.admission_round_id).toBe(3)
    expect(parsed.academic_year).toBe(2026)
  })

  it("rejects a payload missing admission_round_id (now REQUIRED)", () => {
    const { admission_round_id: _omit, ...withoutRound } = base
    void _omit
    expect(() => admissionProfileCreateSchema.parse(withoutRound)).toThrow()
  })

  it("rejects a payload missing academic_year (fallback removed, REQUIRED)", () => {
    const { academic_year: _omit, ...withoutYear } = base
    void _omit
    expect(() => admissionProfileCreateSchema.parse(withoutYear)).toThrow()
  })

  it("rejects a non-positive admission_round_id", () => {
    expect(() =>
      admissionProfileCreateSchema.parse({ ...base, admission_round_id: 0 }),
    ).toThrow()
  })
})

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

  it("preserves application fee payment snapshot fields", () => {
    const parsed = appliedRulesSchema.parse({
      scoring_method: "sum" as const,
      allowed_subject_codes: ["math"],
      subject_groups: [],
      method_type: "subject_based" as const,
      application_fee: 100000,
      requires_application_fee: true,
      fee_status: "paid",
      fee_paid_at: "2026-06-07T08:30:00Z",
      fee_payment_data: {
        transaction_id: "RCPT-001",
        amount: "100000",
        payment_method_code: "cash",
        paid_at: "2026-06-07T08:30:00Z",
        recorded_by: 7,
      },
    })

    expect(parsed.application_fee).toBe(100000)
    expect(parsed.requires_application_fee).toBe(true)
    expect(parsed.fee_status).toBe("paid")
    expect(parsed.fee_paid_at).toBe("2026-06-07T08:30:00Z")
    expect(parsed.fee_payment_data?.transaction_id).toBe("RCPT-001")
    expect(parsed.fee_payment_data?.recorded_by).toBe(7)
  })

  it("accepts legacy snapshots without application fee payment fields", () => {
    const parsed = appliedRulesSchema.parse({
      min_gpa: 6.5,
      scoring_method: "sum" as const,
      allowed_subject_codes: ["math"],
      subject_groups: [],
      method_type: "subject_based" as const,
    })

    expect(parsed.fee_paid_at).toBeUndefined()
    expect(parsed.fee_payment_data).toBeUndefined()
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

/**
 * priorityObjectEvidenceEntrySchema — rejected_by / rejected_at parity.
 *
 * BE schema (Backend_FastAPI/app/schemas/admission.py:515) persists
 * `rejected_by` (officer id) + `rejected_at` (ISO timestamp) vào evidence
 * JSONB entry sau khi PATCH reject. FE strict schema phải accept cả 2 —
 * trước khi thêm vào schema, mọi GET profile sau reject bị
 * ResponseValidationError extra_forbidden ở client parse layer.
 *
 * Anchor cứng để bất kỳ refactor schema nào về sau cũng buộc giữ contract.
 */
describe("priorityObjectEvidenceEntrySchema — rejected fields parity", () => {
  it("parses rejected entry kèm rejected_by + rejected_at + reject_reason", () => {
    const parsed = priorityObjectEvidenceEntrySchema.parse({
      status: "rejected",
      document_id: 1234,
      rejected_by: 42,
      rejected_at: "2026-05-22T10:30:00+07:00",
      reject_reason: "Giấy tờ mờ — yêu cầu nộp lại",
      requested_at: "2026-05-22T09:00:00+07:00",
    })

    expect(parsed.status).toBe("rejected")
    expect(parsed.rejected_by).toBe(42)
    expect(parsed.rejected_at).toBe("2026-05-22T10:30:00+07:00")
    expect(parsed.reject_reason).toBe("Giấy tờ mờ — yêu cầu nộp lại")
  })

  it("accepts rejected entry với rejected_by/rejected_at = null (BE shape khi reject chưa propagate)", () => {
    const parsed = priorityObjectEvidenceEntrySchema.parse({
      status: "rejected",
      rejected_by: null,
      rejected_at: null,
      reject_reason: "TBD",
    })

    expect(parsed.rejected_by).toBeNull()
    expect(parsed.rejected_at).toBeNull()
  })

  it("strict mode rejects khi có extra field (anchor cho schema drift)", () => {
    expect(() =>
      priorityObjectEvidenceEntrySchema.parse({
        status: "verified",
        verified_by: 7,
        verified_at: "2026-05-22T08:00:00+07:00",
        extraneous_field: "should fail",
      }),
    ).toThrow()
  })
})
