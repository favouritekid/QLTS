/**
 * FeeReviewCard — anchor tests (Commit 8 followup).
 *
 * Pin: cross-module FeeStatusLink mounting với đúng profileId; helper
 * copy text + accessibility.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Mock FeeStatusLink — cross-module dependency với react-query.
vi.mock("@/components/finance", () => ({
  FeeStatusLink: ({ profileId, variant }: { profileId: number; variant: string }) => (
    <span data-testid="fee-status-link" data-profile-id={profileId} data-variant={variant}>
      Chưa tính phí
    </span>
  ),
}))

import { FeeReviewCard } from "./FeeReviewCard"

function buildProfile(id: number): AdmissionProfileResponse {
  return {
    id,
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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("FeeReviewCard", () => {
  it("renders card với title 'Học phí'", () => {
    render(<FeeReviewCard profile={buildProfile(39)} />)
    const card = screen.getByTestId("fee-review-card")
    expect(card).toBeInTheDocument()
    expect(screen.getByText("Học phí")).toBeInTheDocument()
  })

  it("mount FeeStatusLink với đúng profile.id + variant='badge'", () => {
    render(<FeeReviewCard profile={buildProfile(42)} />)
    const link = screen.getByTestId("fee-status-link")
    expect(link).toHaveAttribute("data-profile-id", "42")
    expect(link).toHaveAttribute("data-variant", "badge")
  })

  it("hiển thị helper copy 'Trạng thái học phí từ module tài chính'", () => {
    render(<FeeReviewCard profile={buildProfile(1)} />)
    expect(screen.getByText(/Trạng thái học phí từ module tài chính/)).toBeInTheDocument()
  })
})
