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

describe("useSubmissionReadiness — verdict + summary", () => {
  it("canSubmit && isEligible (clean) → verdict 'Có thể nộp' (success), no summary", () => {
    const r = run(buildParams({ canSubmit: true, isEligible: true }))
    expect(r.primaryAction).toBe("submit")
    expect(r.verdictLabel).toBe("Có thể nộp")
    expect(r.verdictTone).toBe("success")
    expect(r.decisionSummary).toBeNull()
    expect(r.outstandingLabel).toBe("Mục cần xử lý")
  })

  it("submitted + eligible but NO canSubmit → primaryAction none, verdict never says 'nộp'", () => {
    const r = run(
      buildParams({
        profile: buildProfile({ status: "submitted", eligibility_status: "eligible" }),
        isEligible: true,
        canSubmit: false,
      }),
    )
    expect(r.primaryAction).toBe("none")
    expect(r.verdictLabel).not.toMatch(/nộp/i)
    expect(r.verdictTone).toBe("neutral")
  })

  it("canSubmit && !isEligible + items → verdict 'Chưa thể nộp', summary counts items", () => {
    const profile = buildProfile({
      eligibility_status: "ineligible",
      step_status: { "5": "error" },
      grouped_validation_errors: {
        scores: { category: "Điểm số", errors: ["Điểm chưa đạt"], count: 1 },
      },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canSubmit: true, isEligible: false }))
    expect(r.actionItemCount).toBeGreaterThan(0)
    expect(r.verdictLabel).toBe("Chưa thể nộp")
    expect(r.verdictTone).toBe("warning")
    expect(r.decisionSummary).toBe(`Còn ${r.actionItemCount} mục cần xử lý trước khi nộp.`)
  })

  it("canSubmit && !isEligible + 0 items → verdict 'Chưa thể nộp', summary 'Chưa đủ điều kiện để nộp.'", () => {
    const profile = buildProfile({
      eligibility_status: "ineligible",
      step_status: { "1": "success", "2": "success", "3": "success", "5": "success", "6": "success", "7": "success" },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canSubmit: true, isEligible: false }))
    expect(r.actionItemCount).toBe(0)
    expect(r.verdictLabel).toBe("Chưa thể nộp")
    expect(r.decisionSummary).toBe("Chưa đủ điều kiện để nộp.")
  })

  it("resubmit clean (ineligible) → verdict 'Có thể nộp lại' (success) — NOT gated by eligibility", () => {
    const r = run(
      buildParams({
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
    expect(r.verdictLabel).toBe("Có thể nộp lại")
  })

  it("resubmit + items → verdict 'Cần xử lý', summary counts", () => {
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
    expect(r.verdictLabel).toBe("Cần xử lý")
    expect(r.decisionSummary).toBe(`Còn ${r.actionItemCount} mục cần xử lý trước khi nộp lại.`)
  })
})

describe("useSubmissionReadiness — primaryAction precedence (B5)", () => {
  it("canApprove (eligible clean) → approve / verdict 'Chờ phê duyệt' (info)", () => {
    const r = run(buildParams({ canApprove: true }))
    expect(r.primaryAction).toBe("approve")
    expect(r.verdictLabel).toBe("Chờ phê duyệt")
    expect(r.verdictTone).toBe("info")
    expect(r.outstandingLabel).toBe("Mục cần xử lý")
  })

  it("approve wins over reject + request_revision", () => {
    const r = run(buildParams({ canApprove: true, canReject: true, canRequestRevision: true }))
    expect(r.primaryAction).toBe("approve")
  })

  it("canApprove + bypass_warning → warning tone", () => {
    const r = run(
      buildParams({
        profile: buildProfile({ bypass_warning: true, eligibility_status: "ineligible" }),
        canApprove: true,
        isEligible: false,
      }),
    )
    expect(r.primaryAction).toBe("approve")
    expect(r.verdictTone).toBe("warning")
  })

  it("canApprove + ineligible + NO bypass → verdict NOT positive ('Chưa thể phê duyệt')", () => {
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
    expect(r.verdictTone).not.toBe("info")
    expect(r.verdictTone).not.toBe("success")
    expect(r.verdictLabel).toBe("Chưa thể phê duyệt")
  })

  it("canPublishResult → publish_result / verdict 'Sẵn sàng công bố'", () => {
    const r = run(buildParams({ canPublishResult: true }))
    expect(r.primaryAction).toBe("publish_result")
    expect(r.verdictLabel).toBe("Sẵn sàng công bố")
  })

  it("multi-NV submitted: canApprove + canPublishResult both true → publish_result WINS (BE overlap admission_service.py:1673/1681)", () => {
    const r = run(
      buildParams({
        profile: buildProfile({ status: "submitted", uses_choice_engine: true } as Partial<AdmissionProfileResponse>),
        canApprove: true,
        canPublishResult: true,
        canReject: true,
        canRequestRevision: true,
      }),
    )
    expect(r.primaryAction).toBe("publish_result")
    expect(r.verdictLabel).toBe("Sẵn sàng công bố")
  })

  it("canEnroll → enroll / verdict 'Sẵn sàng ghi danh'", () => {
    const r = run(buildParams({ canEnroll: true }))
    expect(r.primaryAction).toBe("enroll")
    expect(r.verdictLabel).toBe("Sẵn sàng ghi danh")
  })

  it("no flags → none, verdict reflects status (not an action prompt)", () => {
    const r = run(buildParams({ profile: buildProfile({ status: "enrolled" }) }))
    expect(r.primaryAction).toBe("none")
    expect(r.verdictLabel).toBe("Đã nhập học")
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

describe("useSubmissionReadiness — data consistency (eligible but warnings)", () => {
  it("eligible + docs incomplete → approve verdict 'Còn cảnh báo rà soát' (warning) + summary", () => {
    const profile = buildProfile({
      eligibility_status: "eligible",
      document_stats: { submitted_count: 5, verified_count: 5, mandatory_count: 7, missing_count: 2 },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canApprove: true, isEligible: true }))
    expect(r.primaryAction).toBe("approve")
    expect(r.verdictLabel).toBe("Còn cảnh báo rà soát")
    expect(r.verdictTone).toBe("warning")
    expect(r.documentTone).toBe("warning")
    expect(r.hasOutstandingWarnings).toBe(true)
    expect(r.decisionSummary).toMatch(/cần kiểm tra trước khi phê duyệt/)
  })

  it("eligible + docs complete + no warnings → approve verdict 'Chờ phê duyệt' (info), no summary", () => {
    const profile = buildProfile({
      eligibility_status: "eligible",
      document_stats: { submitted_count: 7, verified_count: 7, mandatory_count: 7, missing_count: 0 },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canApprove: true, isEligible: true }))
    expect(r.verdictLabel).toBe("Chờ phê duyệt")
    expect(r.verdictTone).toBe("info")
    expect(r.documentTone).toBe("success")
    expect(r.hasOutstandingWarnings).toBe(false)
    expect(r.decisionSummary).toBeNull()
  })

  it("SUBMIT eligible + docs incomplete → verdict 'Còn cảnh báo' (warning) + summary 'trước khi nộp'", () => {
    const profile = buildProfile({
      eligibility_status: "eligible",
      document_stats: { submitted_count: 5, verified_count: 5, mandatory_count: 7, missing_count: 2 },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canSubmit: true, isEligible: true }))
    expect(r.primaryAction).toBe("submit")
    expect(r.verdictLabel).toBe("Còn cảnh báo")
    expect(r.verdictTone).toBe("warning")
    expect(r.decisionSummary).toMatch(/cần kiểm tra trước khi nộp/)
  })

  it("eligible + docs submitted-but-UNVERIFIED → warning (Hero mirrors the cockpit pending-verify state)", () => {
    const profile = buildProfile({
      eligibility_status: "eligible",
      document_stats: { submitted_count: 7, verified_count: 4, mandatory_count: 7, missing_count: 0, unverified_count: 3 },
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canApprove: true, isEligible: true }))
    expect(r.documentTone).toBe("warning")
    expect(r.hasOutstandingWarnings).toBe(true)
    expect(r.verdictLabel).toBe("Còn cảnh báo rà soát")
  })

  it("eligible + all docs verified but missing UT evidence → documentTone warning (mirror cockpit DocumentReviewCard)", () => {
    const profile = buildProfile({
      eligibility_status: "eligible",
      document_stats: { submitted_count: 5, verified_count: 5, mandatory_count: 5, missing_count: 0, unverified_count: 0 },
      missing_priority_evidence_codes: ["UT07"],
    } as Partial<AdmissionProfileResponse>)
    const r = run(buildParams({ profile, canApprove: true, isEligible: true }))
    // Hero "Tài liệu" metric must not be green while the cockpit shows amber for missing UT.
    expect(r.documentTone).toBe("warning")
  })
})
