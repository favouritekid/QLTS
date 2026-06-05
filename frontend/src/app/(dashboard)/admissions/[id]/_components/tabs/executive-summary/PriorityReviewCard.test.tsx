/**
 * PriorityReviewCard — compact "Ưu tiên / KV" signal tests.
 *
 * Pin: tone (success/warning/error) + KV primary + secondary status line.
 * Detail badges (cap / override reason / bonus breakdown) moved to
 * InspectionDetails — no longer asserted here.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { PriorityReviewCard } from "./PriorityReviewCard"

type Snapshot = Record<string, unknown>

function buildProfile(opts: { snapshot?: Snapshot; missingUt?: string[] } = {}): AdmissionProfileResponse {
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

describe("PriorityReviewCard — compact signal", () => {
  it("KV resolved + UT verified: success tone, KV primary + UT secondary", () => {
    const profile = buildProfile({
      snapshot: { kv_resolved: "KV1", ut_verified_bucket: { applied_code: "04", applied_rate: 1.0 } },
    })
    render(<PriorityReviewCard profile={profile} />)
    const card = screen.getByTestId("priority-review-card")
    expect(card.querySelector(".text-success-600")).toBeTruthy()
    expect(screen.getByText("KV1")).toBeInTheDocument()
    expect(screen.getByText(/UT04 hợp lệ \(\+1\.00đ\)/)).toBeInTheDocument()
  })

  it("requires_manual_override: error tone + 'Cần ấn định KV thủ công'", () => {
    const profile = buildProfile({ snapshot: { kv_resolved: null, requires_manual_override: true } })
    render(<PriorityReviewCard profile={profile} />)
    const card = screen.getByTestId("priority-review-card")
    expect(card.querySelector(".text-error-600")).toBeTruthy()
    expect(screen.getByText("Cần ấn định KV thủ công")).toBeInTheDocument()
  })

  it("missing UT evidence: warning tone + count", () => {
    const profile = buildProfile({ snapshot: { kv_resolved: "KV1" }, missingUt: ["UT07", "UT05"] })
    render(<PriorityReviewCard profile={profile} />)
    const card = screen.getByTestId("priority-review-card")
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
    expect(screen.getByText("Thiếu 2 minh chứng UT")).toBeInTheDocument()
  })

  it("empty snapshot: 'Chưa xác định KV' + warning tone", () => {
    render(<PriorityReviewCard profile={buildProfile({ snapshot: {} })} />)
    const card = screen.getByTestId("priority-review-card")
    expect(screen.getByText("Chưa xác định KV")).toBeInTheDocument()
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
  })

  it("manual_override_reason set → suffix 'KV cán bộ ấn định' (override-applied signal)", () => {
    const profile = buildProfile({
      snapshot: { kv_resolved: "KV2-NT", manual_override_reason: "Cán bộ chuyển KV để khớp lịch sử THPT" },
    })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.getByText(/KV cán bộ ấn định/)).toBeInTheDocument()
  })

  it("REGRESSION: missing UT + manual override → cell shows BOTH the UT issue AND the override provenance (audit line is not durable)", () => {
    const profile = buildProfile({
      snapshot: { kv_resolved: "KV2-NT", manual_override_reason: "Cán bộ ấn định KV" },
      missingUt: ["UT07", "UT05"],
    })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.getByText(/Thiếu 2 minh chứng UT · KV cán bộ ấn định/)).toBeInTheDocument()
  })

  it("bonus exceeds path max_total_bonus → '· bị cap' suffix surfaced", () => {
    const profile = buildProfile({
      snapshot: {
        kv_resolved: "KV1",
        breakdown: { area_bonus: 0.75 },
        ut_verified_bucket: { applied_code: "04", applied_rate: 1.5 },
        path_bonus_rule: { max_total_bonus: 2.0 },
      },
    })
    render(<PriorityReviewCard profile={profile} />)
    expect(screen.getByText(/bị cap/)).toBeInTheDocument()
  })
})
