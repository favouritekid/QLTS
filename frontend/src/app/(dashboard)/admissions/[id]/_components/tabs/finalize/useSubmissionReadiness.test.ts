/**
 * useSubmissionReadiness — readiness derivation anchor tests.
 *
 * Pins (STEP8 plan acceptance):
 *   - eligibility verdict tracks eligibility_status (eligible/ineligible/pending).
 *   - "Có thể nộp ngay" ONLY when canSubmit && isEligible; submitted+eligible (none)
 *     never implies "nộp được" (anti-B1 regression).
 *   - resubmit does NOT depend on eligibility (invariant I2).
 *   - primaryAction precedence (B5): approve beats reject+request_revision; publish
 *     / enroll / none mapped correctly.
 *   - ActionItems from grouped_validation_errors + derivePriorityIssues + step_status
 *     {2,3}; NOT routed by critical_blockers; Step 7 never produces an item (B4).
 *   - fallback: executive_summary null → summaryLine null; !isEligible & 0 items →
 *     "Chưa đủ điều kiện nộp" (never "0 mục").
 */

import { describe, it, expect } from "vitest"
import { renderHook } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import {
  useSubmissionReadiness,
  type UseSubmissionReadinessParams,
} from "./useSubmissionReadiness"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: "draft",
    version: 1,
    academic_year: 2026,
    permissions: {},
    eligibility_status: "eligible",
    validation_errors: [],
    available_actions: [],
    completion_percent: 100,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: [],
    // Clean priority → derivePriorityIssues returns [] (cultural set, no override).
    priority_resolution_snapshot: { requires_manual_override: false },
    cultural_education_level: "GDPT",
    bypass_warning: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

function buildParams(
  overrides: Partial<UseSubmissionReadinessParams> = {},
): UseSubmissionReadinessParams {
  return {
    profile: buildProfile(),
    isEligible: true,
    canSubmit: false,
    canResubmit: false,
    canApprove: false,
    canReject: false,
    canRequestRevision: false,
    canPublishResult: false,
    canEnroll: false,
    ...overrides,
  }
}

function run(params: UseSubmissionReadinessParams) {
  return renderHook(() => useSubmissionReadiness(params)).result.current
}

describe("useSubmissionReadiness — eligibility verdict", () => {
  it.each([
    ["eligible", "Đủ điều kiện xét", "success"],
    ["ineligible", "Chưa đủ điều kiện", "error"],
    ["pending", "Chưa xét điều kiện", "neutral"],
  ] as const)("%s → label %s tone %s", (status, label, tone) => {
    const r = run(buildParams({ profile: buildProfile({ eligibility_status: status }) }))
    expect(r.eligibilityVerdict).toBe(status)
    expect(r.eligibilityLabel).toBe(label)
    expect(r.eligibilityTone).toBe(tone)
  })
})

describe("useSubmissionReadiness — action readiness", () => {
  it("canSubmit && isEligible → 'Có thể nộp ngay' (success)", () => {
    const r = run(buildParams({ canSubmit: true, isEligible: true }))
    expect(r.primaryAction).toBe("submit")
    expect(r.readinessLabel).toBe("Có thể nộp ngay")
    expect(r.readinessTone).toBe("success")
  })

  it("submitted + eligible but NO canSubmit → primaryAction none, never says 'nộp'", () => {
    const r = run(
      buildParams({
        profile: buildProfile({ status: "submitted", eligibility_status: "eligible" }),
        isEligible: true,
        canSubmit: false,
      }),
    )
    expect(r.primaryAction).toBe("none")
    expect(r.readinessLabel).not.toMatch(/nộp/i)
    expect(r.readinessTone).toBe("neutral")
  })

  it("canSubmit && !isEligible with action items → 'N mục cần xử lý'", () => {
    const profile = buildProfile({
      eligibility_status: "ineligible",
      step_status: { "5": "error" },
      grouped_validation_errors: {
        scores: { category: "Điểm số", errors: ["Điểm chưa đạt"], count: 1 },
      },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canSubmit: true, isEligible: false }))
    expect(r.actionItemCount).toBeGreaterThan(0)
    expect(r.readinessLabel).toBe(`${r.actionItemCount} mục cần xử lý`)
  })

  it("FALLBACK: canSubmit && !isEligible but 0 action items → 'Chưa đủ điều kiện nộp' (never 0 mục)", () => {
    const profile = buildProfile({
      eligibility_status: "ineligible",
      step_status: { "1": "success", "2": "success", "3": "success", "5": "success", "6": "success", "7": "success" },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canSubmit: true, isEligible: false }))
    expect(r.actionItemCount).toBe(0)
    expect(r.readinessLabel).toBe("Chưa đủ điều kiện nộp")
    expect(r.readinessLabel).not.toMatch(/0 mục/)
  })

  it("resubmit does NOT depend on eligibility: canResubmit + ineligible (clean) → 'Có thể nộp lại'", () => {
    const r = run(
      buildParams({
        // Clean profile (KV resolved so the non-draft defensive priority check
        // does not fire) → N=0; resubmit label is positive despite ineligible.
        profile: buildProfile({
          status: "rejected",
          eligibility_status: "ineligible",
          priority_resolution_snapshot: { requires_manual_override: false, kv_resolved: "KV2" },
        } as Partial<AdmissionProfileResponse>),
        canResubmit: true,
        isEligible: false,
      }),
    )
    expect(r.primaryAction).toBe("resubmit")
    expect(r.actionItemCount).toBe(0)
    expect(r.readinessLabel).toBe("Có thể nộp lại")
  })

  it("resubmit + ineligible + items → 'Nộp lại — N mục cần xử lý'", () => {
    const profile = buildProfile({
      status: "rejected",
      eligibility_status: "ineligible",
      step_status: { "6": "error" },
      grouped_validation_errors: {
        documents: { category: "Tài liệu", errors: ["Thiếu học bạ"], count: 1 },
      },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canResubmit: true, isEligible: false }))
    expect(r.primaryAction).toBe("resubmit")
    expect(r.readinessLabel).toBe(`Nộp lại — ${r.actionItemCount} mục cần xử lý`)
  })
})

describe("useSubmissionReadiness — primaryAction precedence (B5)", () => {
  it("canApprove → approve / 'Chờ bạn phê duyệt'", () => {
    const r = run(buildParams({ canApprove: true }))
    expect(r.primaryAction).toBe("approve")
    expect(r.readinessLabel).toBe("Chờ bạn phê duyệt")
  })

  it("approve wins over reject + request_revision (cluster preserved elsewhere)", () => {
    const r = run(buildParams({ canApprove: true, canReject: true, canRequestRevision: true }))
    expect(r.primaryAction).toBe("approve")
  })

  it("canApprove + bypass_warning → warning tone label", () => {
    const r = run(
      buildParams({
        profile: buildProfile({ bypass_warning: true, eligibility_status: "ineligible" }),
        canApprove: true,
        isEligible: false,
      }),
    )
    expect(r.primaryAction).toBe("approve")
    expect(r.readinessTone).toBe("warning")
  })

  it("canApprove + ineligible + NO bypass → label/tone NOT positive (mirrors disabled approve button)", () => {
    const r = run(
      buildParams({
        profile: buildProfile({
          status: "submitted",
          eligibility_status: "ineligible",
          bypass_warning: false,
        }),
        canApprove: true,
        isEligible: false,
      }),
    )
    expect(r.primaryAction).toBe("approve")
    expect(r.readinessTone).not.toBe("info")
    expect(r.readinessTone).not.toBe("success")
    expect(r.readinessLabel).toMatch(/Chưa thể phê duyệt/)
  })

  it("canPublishResult → publish_result / 'Sẵn sàng công bố kết quả'", () => {
    const r = run(buildParams({ canPublishResult: true }))
    expect(r.primaryAction).toBe("publish_result")
    expect(r.readinessLabel).toBe("Sẵn sàng công bố kết quả")
  })

  it("canEnroll → enroll / 'Sẵn sàng ghi danh'", () => {
    const r = run(buildParams({ canEnroll: true }))
    expect(r.primaryAction).toBe("enroll")
    expect(r.readinessLabel).toBe("Sẵn sàng ghi danh")
  })

  it("no flags → none, label reflects status (not an action prompt)", () => {
    const r = run(buildParams({ profile: buildProfile({ status: "enrolled" }) }))
    expect(r.primaryAction).toBe("none")
    expect(r.readinessLabel).toBe("Đã nhập học")
  })
})

describe("useSubmissionReadiness — action items", () => {
  it("message-level from grouped + priority; section-level from step_status {2,3}; NOT critical_blockers", () => {
    const profile = buildProfile({
      // priority issue (missing cultural) → Step 4
      cultural_education_level: null,
      step_status: { "2": "warning", "3": "error" },
      grouped_validation_errors: {
        personal_info: { category: "Thông tin cá nhân", errors: ["Thiếu CCCD"], count: 1 },
        scores: { category: "Điểm số", errors: ["Điểm chưa đạt"], count: 1 },
        documents: { category: "Tài liệu", errors: ["Thiếu học bạ"], count: 1 },
      },
      executive_summary: {
        overall_status: "incomplete",
        completion_percent: 50,
        step_summary: {},
        critical_blockers: ["MỘT BLOCKER KHÔNG ĐƯỢC ROUTE"],
        warnings: [],
        next_action: "Hoàn thiện hồ sơ",
        can_submit: false,
      },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    const steps = r.actionItems.map((i) => i.step).sort((a, b) => a - b)
    expect(steps).toEqual([1, 2, 3, 4, 5, 6])
    // critical_blockers text must NOT appear as a routed item
    expect(r.actionItems.some((i) => i.message.includes("MỘT BLOCKER"))).toBe(false)
    // summaryLine uses executive_summary.next_action (hint only)
    expect(r.summaryLine).toBe("Hoàn thiện hồ sơ")
  })

  it("errors sort before warnings", () => {
    const profile = buildProfile({
      step_status: { "2": "warning", "3": "error" },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    // step 3 (error) before step 2 (warning)
    const idx3 = r.actionItems.findIndex((i) => i.step === 3)
    const idx2 = r.actionItems.findIndex((i) => i.step === 2)
    expect(idx3).toBeGreaterThanOrEqual(0)
    expect(idx2).toBeGreaterThan(idx3)
  })

  it("Step 7 NEVER produces an action item even when step_status[7]=success", () => {
    const profile = buildProfile({
      step_status: { "7": "success" },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.actionItems.some((i) => i.step === 7)).toBe(false)
  })

  it("FALLBACK: executive_summary null → summaryLine null, still builds items", () => {
    const profile = buildProfile({
      executive_summary: null,
      step_status: { "3": "error" },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.hasExecutiveSummary).toBe(false)
    expect(r.summaryLine).toBeNull()
    expect(r.actionItems.some((i) => i.step === 3)).toBe(true)
  })
})

// Phase 3 — structured executive_summary blocker/warning items.
type ExecutiveSummary = NonNullable<AdmissionProfileResponse["executive_summary"]>
function es(overrides: Partial<ExecutiveSummary> = {}): ExecutiveSummary {
  return {
    overall_status: "incomplete",
    completion_percent: 50,
    step_summary: {},
    critical_blockers: [],
    warnings: [],
    next_action: "Hoàn thiện hồ sơ",
    can_submit: false,
    ...overrides,
  }
}

describe("useSubmissionReadiness — Phase 3 structured blockers routing", () => {
  it("(a) structured blockers route ActionItems by .step with item severity", () => {
    const profile = buildProfile({
      executive_summary: es({
        critical_blockers: [
          { code: "score_below_threshold", message: "Điểm chưa đạt", step: 5, section: "scores", severity: "blocker" },
          { code: "documents_missing", message: "Thiếu tài liệu", step: 6, section: "documents", severity: "blocker" },
        ],
        warnings: [
          { code: "family_missing", message: "Chưa điền gia đình", step: 2, section: "family", severity: "warning" },
        ],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    const byStep = Object.fromEntries(r.actionItems.map((i) => [i.step, i]))
    expect(r.actionItems.map((i) => i.step).sort((a, b) => a - b)).toEqual([2, 5, 6])
    expect(byStep[5].severity).toBe("error")
    expect(byStep[2].severity).toBe("warning")
    expect(byStep[6].message).toBe("Thiếu tài liệu")
  })

  it("(mixed) structured object + legacy string item → heuristic recovers the un-routable section (no blocker dropped)", () => {
    const profile = buildProfile({
      step_status: { "5": "error" },
      grouped_validation_errors: { scores: { category: "Điểm", errors: ["Điểm chưa đạt"], count: 1 } },
      executive_summary: es({
        critical_blockers: [
          { code: "documents_missing", message: "Thiếu tài liệu", step: 6, section: "documents", severity: "blocker" },
          // legacy string item (no step) — must NOT be lost; its section is
          // recovered by the heuristic (grouped.scores → Step 5).
          "legacy điểm blocker không có step",
        ],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    const steps = r.actionItems.map((i) => i.step).sort((a, b) => a - b)
    expect(steps).toContain(6) // structured routed
    expect(steps).toContain(5) // recovered via grouped heuristic — NOT dropped
    expect(r.actionItems.some((i) => i.message.includes("legacy điểm blocker"))).toBe(false)
  })

  it("(b) legacy string blockers → fallback heuristic (string NOT routed)", () => {
    const profile = buildProfile({
      step_status: { "3": "error" },
      grouped_validation_errors: { scores: { category: "Điểm", errors: ["x"], count: 1 } },
      executive_summary: es({ critical_blockers: ["legacy string blocker"] }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.actionItems.map((i) => i.step).sort((a, b) => a - b)).toEqual([3, 5])
    expect(r.actionItems.some((i) => i.message.includes("legacy string blocker"))).toBe(false)
  })

  it("(c) dedupes structured items with the same code", () => {
    const profile = buildProfile({
      executive_summary: es({
        critical_blockers: [
          { code: "documents_missing", message: "Thiếu", step: 6, severity: "blocker" },
          { code: "documents_missing", message: "Thiếu", step: 6, severity: "blocker" },
        ],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.actionItems.filter((i) => i.id === "documents_missing").length).toBe(1)
  })

  it("(c2) keeps DISTINCT blockers on the same step (per-blocker rows)", () => {
    const profile = buildProfile({
      executive_summary: es({
        critical_blockers: [
          { code: "documents_missing", message: "Thiếu", step: 6, severity: "blocker" },
          { code: "documents_unverified", message: "Chờ xác minh", step: 6, severity: "blocker" },
        ],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.actionItems.filter((i) => i.step === 6).length).toBe(2)
  })

  it("structured present → grouped heuristic NOT used (structured wins on step 6)", () => {
    const profile = buildProfile({
      grouped_validation_errors: { documents: { category: "Tài liệu", errors: ["heuristic doc"], count: 1 } },
      executive_summary: es({
        critical_blockers: [{ code: "documents_missing", message: "structured doc", step: 6, severity: "blocker" }],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    const step6 = r.actionItems.filter((i) => i.step === 6)
    expect(step6.length).toBe(1)
    expect(step6[0].message).toBe("structured doc")
  })

  it("priority (Step 4) still added alongside structured items", () => {
    const profile = buildProfile({
      cultural_education_level: null,
      executive_summary: es({
        critical_blockers: [{ code: "score_below_threshold", message: "Điểm", step: 5, severity: "blocker" }],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.actionItems.some((i) => i.step === 4)).toBe(true)
    expect(r.actionItems.some((i) => i.step === 5)).toBe(true)
  })

  it("summaryLine falls back to first structured blocker message when next_action empty", () => {
    const profile = buildProfile({
      executive_summary: es({
        next_action: "",
        critical_blockers: [{ code: "c", message: "Xử lý tài liệu", step: 6, severity: "blocker" }],
      }),
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile }))
    expect(r.summaryLine).toBe("Xử lý tài liệu")
  })
})
