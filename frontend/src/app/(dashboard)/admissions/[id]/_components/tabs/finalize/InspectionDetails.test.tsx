/**
 * InspectionDetails — single collapsible "Chi tiết kiểm tra" (default CLOSED, all roles).
 *
 * Pins: ReviewDetails not mounted until opened; trigger is a real <button> with
 * aria-expanded; opening reveals ReviewDetails. (HealthCheckGrid is NOT here — it
 * lives in ReviewerCockpit.)
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

vi.mock("../executive-summary/ReviewDetails", () => ({
  ReviewDetails: () => <div data-testid="review-details" />,
}))

import { InspectionDetails } from "./InspectionDetails"

const profile = { id: 1 } as unknown as AdmissionProfileResponse

describe("InspectionDetails", () => {
  it("default CLOSED: content not mounted, trigger aria-expanded=false", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} />)
    expect(screen.queryByTestId("review-details")).not.toBeInTheDocument()
    const trigger = screen.getByRole("button", { name: /Chi tiết kiểm tra/i })
    expect(trigger).toHaveAttribute("aria-expanded", "false")
  })

  it("opening reveals ReviewDetails and flips aria-expanded", () => {
    render(<InspectionDetails profile={profile} onNavigateToDocuments={vi.fn()} />)
    const trigger = screen.getByRole("button", { name: /Chi tiết kiểm tra/i })
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByTestId("review-details")).toBeInTheDocument()
  })
})
