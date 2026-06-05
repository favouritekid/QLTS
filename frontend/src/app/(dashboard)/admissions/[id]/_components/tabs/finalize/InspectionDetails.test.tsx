/**
 * InspectionDetails — collapsible + reviewer-gate anchor tests (plan P1-a, Phase 2).
 *
 * Pins:
 *   - Both sections default CLOSED; triggers are real <button> with aria-expanded.
 *   - Reviewer (isReviewer=true): "Cockpit duyệt" present; opening reveals
 *     HealthCheckGrid. "Chi tiết kiểm tra" reveals ReviewDetails.
 *   - Officer (isReviewer=false): NO "Cockpit duyệt"; HealthCheckGrid NEVER in the
 *     DOM even after opening; ReviewDetails self-check still available.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Stub heavy children — parity tested in their own suites.
vi.mock("../executive-summary/HealthCheckGrid", () => ({
  HealthCheckGrid: () => <div data-testid="health-check-grid" />,
}))
vi.mock("../executive-summary/ReviewDetails", () => ({
  ReviewDetails: () => <div data-testid="review-details" />,
}))

import { InspectionDetails } from "./InspectionDetails"

const profile = { id: 1 } as unknown as AdmissionProfileResponse

describe("InspectionDetails — reviewer cockpit gate (Phase 2)", () => {
  it("reviewer: 'Cockpit duyệt' present, default closed, aria-expanded=false", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} isReviewer={true} />)
    const cockpit = screen.getByRole("button", { name: /Cockpit duyệt/i })
    expect(cockpit).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByTestId("health-check-grid")).not.toBeInTheDocument()
  })

  it("reviewer: opening 'Cockpit duyệt' reveals HealthCheckGrid", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} isReviewer={true} />)
    const cockpit = screen.getByRole("button", { name: /Cockpit duyệt/i })
    fireEvent.click(cockpit)
    expect(cockpit).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByTestId("health-check-grid")).toBeInTheDocument()
  })

  it("officer (no decision perm): NO 'Cockpit duyệt' and HealthCheckGrid NEVER in DOM", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} isReviewer={false} />)
    expect(screen.queryByRole("button", { name: /Cockpit duyệt/i })).not.toBeInTheDocument()
    // Open the self-check section — HealthCheckGrid still must not appear.
    fireEvent.click(screen.getByRole("button", { name: /Chi tiết kiểm tra/i }))
    expect(screen.getByTestId("review-details")).toBeInTheDocument()
    expect(screen.queryByTestId("health-check-grid")).not.toBeInTheDocument()
  })
})

describe("InspectionDetails — self-check section (all roles)", () => {
  it.each([true, false])("isReviewer=%s: 'Chi tiết kiểm tra' opens to ReviewDetails", (isReviewer) => {
    render(
      <InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} isReviewer={isReviewer} />
    )
    const trigger = screen.getByRole("button", { name: /Chi tiết kiểm tra/i })
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByTestId("review-details")).not.toBeInTheDocument()
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByTestId("review-details")).toBeInTheDocument()
  })
})
