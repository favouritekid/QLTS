/**
 * FeeReviewCard — compact "Học phí" mini-row tests.
 *
 * Pin: cross-module FeeStatusLink mounted with the profile id + badge variant +
 * an `unavailableFallback` (so finance-unavailable doesn't silently disappear).
 * FeeStatusLink is mocked (it owns the react-query hook + fallback rendering).
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

let lastProps: { profileId?: number; variant?: string; hasFallback?: boolean } = {}

vi.mock("@/components/finance", () => ({
  FeeStatusLink: ({
    profileId,
    variant,
    unavailableFallback,
  }: {
    profileId: number
    variant: string
    unavailableFallback?: React.ReactNode
  }) => {
    lastProps = { profileId, variant, hasFallback: unavailableFallback != null }
    return (
      <span data-testid="fee-status-link" data-profile-id={profileId} data-variant={variant}>
        Chưa tính phí
      </span>
    )
  },
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

describe("FeeReviewCard — mini-row", () => {
  it("renders the row with 'Học phí' label", () => {
    render(<FeeReviewCard profile={buildProfile(39)} />)
    expect(screen.getByTestId("fee-review-card")).toBeInTheDocument()
    expect(screen.getByText("Học phí")).toBeInTheDocument()
  })

  it("mounts FeeStatusLink with profile.id, variant='badge', and an unavailable fallback", () => {
    render(<FeeReviewCard profile={buildProfile(42)} />)
    const link = screen.getByTestId("fee-status-link")
    expect(link).toHaveAttribute("data-profile-id", "42")
    expect(link).toHaveAttribute("data-variant", "badge")
    expect(lastProps.hasFallback).toBe(true)
  })
})
