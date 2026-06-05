/**
 * InspectionDetails — collapsible anchor tests (plan P1-a).
 *
 * Pins: default CLOSED (heavy content not mounted); trigger is a real button with
 * aria-expanded; opening reveals HealthCheckGrid + ReviewDetails.
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

describe("InspectionDetails", () => {
  it("default CLOSED: content not mounted, trigger aria-expanded=false", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} />)
    expect(screen.queryByTestId("health-check-grid")).not.toBeInTheDocument()
    const trigger = screen.getByRole("button", { name: /Chi tiết kiểm tra/i })
    expect(trigger).toHaveAttribute("aria-expanded", "false")
  })

  it("opening reveals HealthCheckGrid + ReviewDetails and flips aria-expanded", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} />)
    const trigger = screen.getByRole("button", { name: /Chi tiết kiểm tra/i })
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByTestId("health-check-grid")).toBeInTheDocument()
    expect(screen.getByTestId("review-details")).toBeInTheDocument()
  })
})
