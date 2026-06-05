/**
 * SectionReview — anchor tests.
 *
 * Pins (plan B4/I5): renders Step 1-7 (not 8); Step 7 is info/neutral (NO
 * success/green, CTA only navigates); editable rows say "Sửa" when they need
 * work; deep-link via onNavigateToStep.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { SectionReview } from "./SectionReview"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: "draft",
    applied_rules: {},
    step_status: {
      "1": "success",
      "2": "warning",
      "3": "error",
      "4": "success",
      "5": "success",
      "6": "success",
      "7": "success",
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("SectionReview", () => {
  it("renders Step 1-7 rows (not Step 8)", () => {
    render(<SectionReview profile={buildProfile()} onNavigateToStep={vi.fn()} />)
    expect(screen.getByText("Thông tin cá nhân")).toBeInTheDocument()
    expect(screen.getByText("Học phí")).toBeInTheDocument()
    expect(screen.queryByText("Hoàn tất & Nộp")).not.toBeInTheDocument()
  })

  it("Step 7 is info/neutral — no success badge, metric is informational", () => {
    render(<SectionReview profile={buildProfile()} onNavigateToStep={vi.fn()} />)
    const row = screen.getByText("Học phí").closest("button")!
    // metric is the informational copy, not a readiness signal
    expect(screen.getByText("Dữ liệu học phí xem tại Step 7")).toBeInTheDocument()
    // badge uses info variant, NOT success/green — even though step_status[7]="success"
    expect(row.querySelector(".bg-info-100")).toBeTruthy()
    expect(row.querySelector(".bg-success-100")).toBeNull()
  })

  it("Step 7 CTA only navigates ('Xem Step 7'), calls onNavigateToStep(7)", () => {
    const onNavigateToStep = vi.fn()
    render(<SectionReview profile={buildProfile()} onNavigateToStep={onNavigateToStep} />)
    expect(screen.getByText("Xem Step 7")).toBeInTheDocument()
    fireEvent.click(screen.getByText("Học phí").closest("button")!)
    expect(onNavigateToStep).toHaveBeenCalledWith(7)
  })

  it("error/warning rows show 'Sửa'; success rows show 'Xem'", () => {
    render(<SectionReview profile={buildProfile()} onNavigateToStep={vi.fn()} />)
    // Step 3 = error → Sửa
    const row3 = screen.getByText("Học tập").closest("button")!
    expect(row3.textContent).toContain("Sửa")
    // Step 1 = success → Xem
    const row1 = screen.getByText("Thông tin cá nhân").closest("button")!
    expect(row1.textContent).toContain("Xem")
  })

  it("Step 5 metric formats total_score to 2 decimals (no raw long float)", () => {
    render(
      <SectionReview
        profile={buildProfile({
          total_score: 7.333333333333333,
          step_status: { "5": "success" },
        } as Partial<AdmissionProfileResponse>)}
        onNavigateToStep={vi.fn()}
      />,
    )
    expect(screen.getByText("Tổng điểm: 7.33")).toBeInTheDocument()
    expect(screen.queryByText(/7\.3333/)).not.toBeInTheDocument()
  })
})
