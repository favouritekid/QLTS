/**
 * PriorityReviewCard — anchor tests (Commit 8 followup).
 *
 * Pin: snapshot field shape contract + visual status (success/warning/error)
 * + 4 conditional badges (Bị cap / Cán bộ đã ấn định / Cần ấn định thủ
 * công / Thiếu N minh chứng UT). Anti-regression cho snapshot key drift
 * BE-side.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { PriorityReviewCard } from "./PriorityReviewCard"

type Snapshot = Record<string, unknown>

function buildProfile(opts: {
  snapshot?: Snapshot
  missingUt?: string[]
} = {}): AdmissionProfileResponse {
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
    missing_priority_evidence_codes: opts.missingUt ?? [],
    priority_resolution_snapshot: opts.snapshot ?? {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("PriorityReviewCard — happy path", () => {
  it("KV resolved + UT verified + no cap: success icon, KV + UT + tổng cộng visible", () => {
    const profile = buildProfile({
      snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 },
      },
    })
    render(<PriorityReviewCard profile={profile} />)
    const card = screen.getByTestId("priority-review-card")
    expect(card.querySelector(".text-success-600")).toBeTruthy()
    expect(screen.getByText("KV1")).toBeInTheDocument()
    expect(screen.getByText(/UT04.*\+1\.00đ/)).toBeInTheDocument()
    expect(screen.getByText("+1.75đ")).toBeInTheDocument()
    expect(screen.queryByText(/Bị cap/i)).not.toBeInTheDocument()
  })
})

describe("PriorityReviewCard — cap badge", () => {
  it("totalBonus > max_total_bonus: hiển thị badge 'Bị cap' + appliedBonus = cap", () => {
    const profile = buildProfile({
      snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.5 },
        path_bonus_rule: { max_total_bonus: 2.0 },
      },
    })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.getByText(/Bị cap \(max \+2\.00đ\)/)).toBeInTheDocument()
    // Tổng cộng applied = cap (2.0), không phải total raw (2.25)
    expect(screen.getByText("+2.00đ")).toBeInTheDocument()
  })

  it("totalBonus <= cap: KHÔNG badge 'Bị cap'", () => {
    const profile = buildProfile({
      snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 },
        path_bonus_rule: { max_total_bonus: 3.0 },
      },
    })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.queryByText(/Bị cap/i)).not.toBeInTheDocument()
    expect(screen.getByText("+1.75đ")).toBeInTheDocument()
  })
})

describe("PriorityReviewCard — override badge", () => {
  it("manual_override_reason set: hiển thị 'Cán bộ đã ấn định' badge purple", () => {
    const profile = buildProfile({
      snapshot: {
        kv_resolved: "KV2-NT",
        manual_override_reason: "Cán bộ chuyển KV để khớp lịch sử THPT",
      },
    })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.getByText("Cán bộ đã ấn định")).toBeInTheDocument()
  })
})

describe("PriorityReviewCard — requires_manual_override (error)", () => {
  it("snapshot.requires_manual_override=true: error icon + badge 'Cần ấn định thủ công'", () => {
    const profile = buildProfile({
      snapshot: {
        kv_resolved: null,
        requires_manual_override: true,
      },
    })
    render(<PriorityReviewCard profile={profile} />)
    const card = screen.getByTestId("priority-review-card")
    expect(card.querySelector(".text-error-600")).toBeTruthy()
    expect(screen.getByText("Cần ấn định thủ công")).toBeInTheDocument()
  })
})

describe("PriorityReviewCard — missing UT badges (warning)", () => {
  it("missing_priority_evidence_codes > 0: warning icon + badge với count", () => {
    const profile = buildProfile({
      snapshot: { kv_resolved: "KV1" },
      missingUt: ["UT07", "UT05"],
    })
    render(<PriorityReviewCard profile={profile} />)
    const card = screen.getByTestId("priority-review-card")
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
    expect(screen.getByText(/Thiếu 2 minh chứng UT/)).toBeInTheDocument()
  })
})

describe("PriorityReviewCard — empty/missing snapshot fallback", () => {
  it("snapshot rỗng: render '—' cho KV + UT, totalBonus=+0.00đ, warning icon (no KV)", () => {
    const profile = buildProfile({ snapshot: {} })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2) // KV + UT
    expect(screen.getByText("+0.00đ")).toBeInTheDocument()
  })
})
