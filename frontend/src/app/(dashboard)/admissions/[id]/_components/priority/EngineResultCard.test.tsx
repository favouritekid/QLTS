/**
 * Q9 #07 Phase E.4 — EngineResultCard.deriveEngineState pure-function tests.
 *
 * Pins P1 contract (PR-3 Step D audit cycle): preview-precedence rules
 * trong deriveEngineState. Mirror PriorityHeaderBanner contract.
 *
 * Critical regression: draft + preview present + kv_resolved=null +
 * snapshot.kv_resolved !=null → MUST return "ambiguous", NOT fallback
 * stale snapshot.
 */
import { describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { EngineResultCard, deriveEngineState } from "./EngineResultCard"

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
  path_bonus_rule: null,
}

const AMBIGUOUS_PREVIEW: PreviewPriorityKvResponse = {
  ...HAPPY_PREVIEW,
  kv_resolved: null,
  rule_applied: "ambiguous_requires_manual",
  requires_manual_override: true,
  reason: "tied_graduation_year_and_grade",
  area_bonus: null,
  total_bonus_potential: null,
  rule_law_citation: null,
}

describe("deriveEngineState — manual override always wins", () => {
  it("returns 'override' when snapshot.manual_override_reason present", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: {
        manual_override_reason: "Admin chỉnh KV vì lớp tạo nguồn",
        kv_resolved: "KV1",
      },
    }
    expect(deriveEngineState(profile, HAPPY_PREVIEW)).toBe("override")
    expect(deriveEngineState(profile, null)).toBe("override")
  })
})

describe("deriveEngineState — frozen post-submit", () => {
  it("returns 'frozen' when status='submitted' and snapshot.kv_resolved set", () => {
    const profile = {
      status: "submitted" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveEngineState(profile, AMBIGUOUS_PREVIEW)).toBe("frozen")
    expect(deriveEngineState(profile, null)).toBe("frozen")
  })
})

describe("deriveEngineState — missing cultural input", () => {
  it("returns 'missing' when cultural_education_level null", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: null,
      priority_resolution_snapshot: {},
    }
    expect(deriveEngineState(profile, HAPPY_PREVIEW)).toBe("missing")
    expect(deriveEngineState(profile, null)).toBe("missing")
  })
})

describe("deriveEngineState — draft + preview precedence (P1 fix)", () => {
  const baseProfile = {
    status: "draft" as const,
    cultural_education_level: "graduated_thpt",
  }

  it("draft + preview happy → 'happy'", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {},
    }
    expect(deriveEngineState(profile, HAPPY_PREVIEW)).toBe("happy")
  })

  it("draft + preview requires_manual_override → 'ambiguous'", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveEngineState(profile, AMBIGUOUS_PREVIEW)).toBe("ambiguous")
  })

  it("draft + preview kv_resolved=null + snapshot.kv stale → 'ambiguous' (NO snapshot fallback)", () => {
    // Critical regression — exact stale-snapshot bug user identified.
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      kv_resolved: null,
      area_bonus: null,
      requires_manual_override: false,
    }
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" }, // stale
    }
    expect(deriveEngineState(profile, preview)).toBe("ambiguous")
  })
})

describe("deriveEngineState — draft + no preview (initial load fallback)", () => {
  const baseProfile = {
    status: "draft" as const,
    cultural_education_level: "graduated_thpt",
  }

  it("returns 'happy' when snapshot.kv_resolved exists (no preview yet)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveEngineState(profile, null)).toBe("happy")
  })

  it("returns 'ambiguous' when snapshot.requires_manual_override (no preview)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { requires_manual_override: true },
    }
    expect(deriveEngineState(profile, null)).toBe("ambiguous")
  })

  it("returns 'ambiguous' when snapshot empty + no preview", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {},
    }
    expect(deriveEngineState(profile, null)).toBe("ambiguous")
  })
})

// ---------------------------------------------------------------------------
// Commit 3 — BE-first contract + officer hard-deny CTA (render tests)
// ---------------------------------------------------------------------------

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
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
    cultural_education_level: "graduated_thpt",
    priority_object_codes: [],
    priority_audit_log: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("EngineResultCard — BE-first lawCitation (Commit 3)", () => {
  it("post-draft: ưu tiên snapshot.rule_law_citation nếu BE trả về", () => {
    const profile = buildProfile({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        rule_applied: "longest_duration",
        rule_law_citation: "TT 05/2021 — Phụ lục 01 (BE-canonical)",
      },
    } as Partial<AdmissionProfileResponse>)

    render(
      <EngineResultCard
        profile={profile}
        preview={null}
        canOverride={false}
        onOpenOverride={vi.fn()}
      />
    )
    // BE citation rendered in disclosure; expand it
    const lawToggle = screen.getByTestId("engine-result-citation-disclosure")
    fireEvent.click(lawToggle)
    expect(screen.getByText(/TT 05\/2021 — Phụ lục 01 \(BE-canonical\)/)).toBeInTheDocument()
  })

  it("post-draft: KHÔNG có rule_law_citation → fallback deriveLawCitationFallback(rule_applied)", () => {
    const profile = buildProfile({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        rule_applied: "longest_duration",
        // rule_law_citation intentionally absent (legacy snapshot)
      },
    } as Partial<AdmissionProfileResponse>)

    render(
      <EngineResultCard
        profile={profile}
        preview={null}
        canOverride={false}
        onOpenOverride={vi.fn()}
      />
    )
    // Fallback chain should NOT crash — citation toggle still renders
    expect(screen.getByText(/Khu vực ưu tiên \(đã chốt\)/)).toBeInTheDocument()
  })
})

describe("EngineResultCard — BE-first reason (Commit 3)", () => {
  it("post-draft: ưu tiên snapshot.basis_reason hơn snapshot.reason", () => {
    const profile = buildProfile({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        basis_reason: "Tốt nghiệp THPT 2024 tại trường KV1 (BE canonical)",
        reason: "legacy error reason (FE fallback only)",
      },
    } as Partial<AdmissionProfileResponse>)

    render(
      <EngineResultCard
        profile={profile}
        preview={null}
        canOverride={false}
        onOpenOverride={vi.fn()}
      />
    )
    expect(screen.getByText(/Tốt nghiệp THPT 2024 tại trường KV1 \(BE canonical\)/)).toBeInTheDocument()
    expect(screen.queryByText(/legacy error reason/)).not.toBeInTheDocument()
  })

  it("post-draft: basis_reason missing → fallback reason", () => {
    const profile = buildProfile({
      status: "submitted",
      priority_resolution_snapshot: {
        kv_resolved: "KV1",
        reason: "Fallback reason chỉ khi basis_reason null",
      },
    } as Partial<AdmissionProfileResponse>)

    render(
      <EngineResultCard
        profile={profile}
        preview={null}
        canOverride={false}
        onOpenOverride={vi.fn()}
      />
    )
    expect(screen.getByText(/Fallback reason chỉ khi basis_reason null/)).toBeInTheDocument()
  })
})

describe("EngineResultCard — officer hard-deny CTA (Commit 3)", () => {
  it("ambiguous + !canOverride: render hint 'đề nghị quản lý' + link 'Sửa dữ liệu nguồn' nếu onNavigateToAcademic có", () => {
    const profile = buildProfile({
      status: "draft",
      priority_resolution_snapshot: {
        requires_manual_override: true,
      },
    } as Partial<AdmissionProfileResponse>)

    const onNavigate = vi.fn()
    render(
      <EngineResultCard
        profile={profile}
        preview={null}
        canOverride={false}
        onOpenOverride={vi.fn()}
        onNavigateToAcademic={onNavigate}
      />
    )
    expect(screen.getByTestId("engine-result-officer-deny-cta")).toBeInTheDocument()
    expect(screen.getByText(/đề nghị quản lý/i)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("engine-result-officer-navigate-academic"))
    expect(onNavigate).toHaveBeenCalled()
  })

  it("ambiguous + canOverride=true: render primary CTA 'Chọn KV thủ công', KHÔNG render officer-deny hint", () => {
    const profile = buildProfile({
      status: "draft",
      priority_resolution_snapshot: {
        requires_manual_override: true,
      },
    } as Partial<AdmissionProfileResponse>)

    const onOpen = vi.fn()
    render(
      <EngineResultCard
        profile={profile}
        preview={null}
        canOverride={true}
        onOpenOverride={onOpen}
      />
    )
    expect(screen.queryByTestId("engine-result-officer-deny-cta")).not.toBeInTheDocument()
    expect(screen.getByTestId("engine-result-ambiguous-cta")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("engine-result-ambiguous-cta"))
    expect(onOpen).toHaveBeenCalled()
  })
})
