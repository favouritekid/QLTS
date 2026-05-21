/**
 * Q9 #07 Phase E.4 — PrioritySummaryPanel.resolveSummaryDisplay tests.
 *
 * Pins P1 contract (PR-3 Step D audit cycle): summary precedence rules
 * mirror PriorityHeaderBanner / EngineResultCard. Without these, §4 tổng
 * có thể lệch với header + engine card khi officer đổi §1.
 *
 * Critical regressions:
 *   1. draft + preview kv=null + snapshot kv stale → kv=null (no fallback)
 *   2. draft + preview ut_breakdown.applied_code_verified live → bucket
 *      reflects live result, ignores stale snapshot.ut_verified_bucket
 */
import { describe, expect, it } from "vitest"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"

import { resolveSummaryDisplay } from "./PrioritySummaryPanel"

const HAPPY_PREVIEW: PreviewPriorityKvResponse = {
  kv_resolved: "KV1",
  pathway: "thpt_multi_school",
  rule_applied: "longest_duration",
  requires_manual_override: false,
  reason: null,
  breakdown: null,
  area_bonus: 0.75,
  object_bonus_potential: null,
  object_bonus_verified: null,
  ut_breakdown: null,
  total_bonus_potential: 0.75,
  rule_law_citation: "TT 05/2021 Phụ lục 01 Mục 5.b",
}

describe("resolveSummaryDisplay — kv precedence", () => {
  it("draft + preview happy → preview wins", () => {
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: { kv_resolved: "KV3" }, // stale
    }
    expect(resolveSummaryDisplay(profile, HAPPY_PREVIEW).kv).toBe("KV1")
  })

  it("draft + preview kv=null + snapshot stale → kv=null (NO fallback)", () => {
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      kv_resolved: null,
      area_bonus: null,
    }
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: { kv_resolved: "KV1" }, // stale
    }
    expect(resolveSummaryDisplay(profile, preview).kv).toBeNull()
  })

  it("post-submit + snapshot kv → snapshot WINS even if preview disagrees (frozen contract)", () => {
    // P1 fix (PR-3 Step D audit cycle 2): frozen contract — snapshot
    // AUTHORITATIVE post-submit. Even if preview accidentally fired (e.g.,
    // race condition before query gate kicks in), snapshot truth wins.
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      kv_resolved: "KV3", // disagreement — snapshot must win
    }
    const profile = {
      status: "submitted" as const,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(resolveSummaryDisplay(profile, preview).kv).toBe("KV1")
  })

  it("post-submit + no preview → snapshot wins", () => {
    const profile = {
      status: "submitted" as const,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(resolveSummaryDisplay(profile, null).kv).toBe("KV1")
  })

  it("draft + no preview + snapshot kv → snapshot defensive fallback", () => {
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(resolveSummaryDisplay(profile, null).kv).toBe("KV1")
  })
})

describe("resolveSummaryDisplay — areaBonus precedence", () => {
  it("draft + preview area_bonus → preview wins", () => {
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: { breakdown: { area_bonus: 0.25 } }, // stale
    }
    expect(resolveSummaryDisplay(profile, HAPPY_PREVIEW).areaBonus).toBe(0.75)
  })

  it("draft + preview area_bonus=null + snapshot stale → 0 (no fallback)", () => {
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      area_bonus: null,
    }
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: { breakdown: { area_bonus: 0.75 } },
    }
    expect(resolveSummaryDisplay(profile, preview).areaBonus).toBe(0)
  })

  it("post-submit + no preview → snapshot.breakdown.area_bonus", () => {
    const profile = {
      status: "submitted" as const,
      priority_resolution_snapshot: { breakdown: { area_bonus: 0.5 } },
    }
    expect(resolveSummaryDisplay(profile, null).areaBonus).toBe(0.5)
  })

  it("post-submit + preview disagrees → snapshot WINS (frozen contract)", () => {
    // Defensive: query gate ngăn preview post-submit, nhưng nếu race
    // condition khiến preview xuất hiện, snapshot truth phải thắng.
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      area_bonus: 1.0, // disagrees with snapshot 0.5
    }
    const profile = {
      status: "submitted" as const,
      priority_resolution_snapshot: { breakdown: { area_bonus: 0.5 } },
    }
    expect(resolveSummaryDisplay(profile, preview).areaBonus).toBe(0.5)
  })
})

describe("resolveSummaryDisplay — verifiedBucket precedence (P1 fix)", () => {
  it("draft + preview ut_breakdown.applied_code_verified live → preview wins", () => {
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      object_bonus_verified: 1.0,
      ut_breakdown: {
        codes_submitted: ["04"],
        applied_code_potential: "04",
        applied_rate_potential: "1.00",
        verified_codes: ["04"],
        applied_code_verified: "04",
        applied_rate_verified: "1.00",
      },
    }
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: {
        ut_verified_bucket: { applied_code: "07", applied_rate: 0.5 }, // stale
      },
    }
    const result = resolveSummaryDisplay(profile, preview).verifiedBucket
    expect(result).toEqual({ code: "04", rate: 1.0 })
  })

  it("draft + preview no verified → bucket null (NO snapshot fallback)", () => {
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      object_bonus_verified: 0,
      ut_breakdown: {
        codes_submitted: ["04"],
        applied_code_potential: "04",
        applied_rate_potential: "1.00",
        verified_codes: [],
        applied_code_verified: null,
        applied_rate_verified: null,
      },
    }
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: {
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 }, // stale
      },
    }
    expect(resolveSummaryDisplay(profile, preview).verifiedBucket).toBeNull()
  })

  it("post-submit + no preview → snapshot.ut_verified_bucket", () => {
    const profile = {
      status: "submitted" as const,
      priority_resolution_snapshot: {
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 },
      },
    }
    expect(resolveSummaryDisplay(profile, null).verifiedBucket).toEqual({
      code: "04",
      rate: 1.0,
    })
  })

  it("draft + no preview → snapshot defensive fallback", () => {
    const profile = {
      status: "draft" as const,
      priority_resolution_snapshot: {
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 },
      },
    }
    expect(resolveSummaryDisplay(profile, null).verifiedBucket).toEqual({
      code: "04",
      rate: 1.0,
    })
  })

  it("post-submit + preview disagrees on verified bucket → snapshot WINS", () => {
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      object_bonus_verified: 0.5,
      ut_breakdown: {
        codes_submitted: ["07"],
        applied_code_potential: "07",
        applied_rate_potential: "0.50",
        verified_codes: ["07"],
        applied_code_verified: "07",
        applied_rate_verified: "0.50",
      },
    }
    const profile = {
      status: "submitted" as const,
      priority_resolution_snapshot: {
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 },
      },
    }
    // Snapshot UT04 wins, preview UT07 ignored
    expect(resolveSummaryDisplay(profile, preview).verifiedBucket).toEqual({
      code: "04",
      rate: 1.0,
    })
  })
})

// ---------------------------------------------------------------------------
// Commit 3 — Cap display from snapshot.path_bonus_rule.max_total_bonus
// ---------------------------------------------------------------------------

import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { PrioritySummaryPanel } from "./PrioritySummaryPanel"

function buildProfileForCap(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    status: "submitted",
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
    priority_resolution_snapshot: {},
    priority_object_codes: [],
    priority_audit_log: [],
    cultural_education_level: "graduated_thpt",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("PrioritySummaryPanel — cap display (Commit 3)", () => {
  it("post-submit + max_total_bonus < total: render cap dòng + badge 'Bị cap' + applied = cap", () => {
    const profile = buildProfileForCap({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.5 },
        path_bonus_rule: { max_total_bonus: 2.0 },
      },
    } as Partial<AdmissionProfileResponse>)

    render(<PrioritySummaryPanel profile={profile} preview={null} />)

    expect(screen.getByTestId("priority-summary-cap")).toBeInTheDocument()
    expect(screen.getByTestId("priority-summary-cap-badge")).toHaveTextContent(/Bị cap/i)
    expect(screen.getByTestId("priority-summary-applied")).toHaveTextContent("+2.00đ")
  })

  it("post-submit + max_total_bonus >= total: render cap dòng + KHÔNG badge + applied = total", () => {
    const profile = buildProfileForCap({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 },
        path_bonus_rule: { max_total_bonus: 3.0 },
      },
    } as Partial<AdmissionProfileResponse>)

    render(<PrioritySummaryPanel profile={profile} preview={null} />)

    expect(screen.getByTestId("priority-summary-cap")).toBeInTheDocument()
    expect(screen.queryByTestId("priority-summary-cap-badge")).not.toBeInTheDocument()
    expect(screen.getByTestId("priority-summary-applied")).toHaveTextContent("+1.75đ")
  })

  it("post-submit + KHÔNG có path_bonus_rule: KHÔNG render cap section", () => {
    const profile = buildProfileForCap({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
      },
    } as Partial<AdmissionProfileResponse>)

    render(<PrioritySummaryPanel profile={profile} preview={null} />)

    expect(screen.queryByTestId("priority-summary-cap")).not.toBeInTheDocument()
  })

  it("draft preview (status='draft' + path_bonus_rule trong snapshot): KHÔNG render cap (frozen-only display)", () => {
    const profile = buildProfileForCap({
      status: "draft",
      priority_resolution_snapshot: {
        path_bonus_rule: { max_total_bonus: 2.0 },
      },
    } as Partial<AdmissionProfileResponse>)

    render(<PrioritySummaryPanel profile={profile} preview={null} />)

    expect(screen.queryByTestId("priority-summary-cap")).not.toBeInTheDocument()
  })
})
