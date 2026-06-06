/**
 * SectionReview (table) — anchor tests.
 *
 * Pins: 7 rows (Step 1-7, not 8); Step 7 is info "Tham khảo" (NO success/green,
 * CTA "Xem Step 7" only navigates); error/warning rows say "Sửa", success "Xem";
 * Step 5 detail formats total_score to 2 decimals; CTA buttons deep-link.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent, within } from "@testing-library/react"
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

describe("SectionReview (table)", () => {
  it("renders Step 1-7 rows (not Step 8)", () => {
    render(<SectionReview profile={buildProfile()} onNavigateToStep={vi.fn()} />)
    expect(screen.getByText("Thông tin cá nhân")).toBeInTheDocument()
    expect(screen.getByText("Học phí")).toBeInTheDocument()
    expect(screen.queryByText("Hoàn tất & Nộp")).not.toBeInTheDocument()
  })

  it("Step 7 is info 'Tham khảo' (no success/green), CTA 'Xem Step 7' only navigates", () => {
    const onNavigateToStep = vi.fn()
    render(<SectionReview profile={buildProfile()} onNavigateToStep={onNavigateToStep} />)
    const row = screen.getByText("Học phí").closest("tr")!
    expect(within(row).getByText("Tham khảo")).toBeInTheDocument()
    expect(row.querySelector(".bg-info-100")).toBeTruthy()
    expect(row.querySelector(".bg-success-100")).toBeNull()
    fireEvent.click(within(row).getByRole("button", { name: "Xem Bước 7" }))
    expect(onNavigateToStep).toHaveBeenCalledWith(7)
  })

  it("error/warning rows show 'Sửa'; success rows show 'Xem'", () => {
    render(<SectionReview profile={buildProfile()} onNavigateToStep={vi.fn()} />)
    const row3 = screen.getByText("Học tập").closest("tr")! // error
    expect(within(row3).getByRole("button").textContent).toContain("Sửa")
    const row1 = screen.getByText("Thông tin cá nhân").closest("tr")! // success
    expect(within(row1).getByRole("button").textContent).toContain("Xem")
  })

  it("CTA button deep-links via onNavigateToStep(step)", () => {
    const onNavigateToStep = vi.fn()
    render(<SectionReview profile={buildProfile()} onNavigateToStep={onNavigateToStep} />)
    const row5 = screen.getByText("Điểm & Điều kiện").closest("tr")!
    fireEvent.click(within(row5).getByRole("button"))
    expect(onNavigateToStep).toHaveBeenCalledWith(5)
  })

  it("Step 5 detail formats total_score to 2 decimals (no long float)", () => {
    render(
      <SectionReview
        profile={buildProfile({ total_score: 7.333333333333333 } as Partial<AdmissionProfileResponse>)}
        onNavigateToStep={vi.fn()}
      />,
    )
    expect(screen.getByText("Tổng điểm: 7.33")).toBeInTheDocument()
    expect(screen.queryByText(/7\.3333/)).not.toBeInTheDocument()
  })

  it("Step 5 detail shows 'Tổng điểm: —' when total_score absent", () => {
    render(<SectionReview profile={buildProfile()} onNavigateToStep={vi.fn()} />)
    expect(screen.getByText("Tổng điểm: —")).toBeInTheDocument()
  })

  it("Step 5 detail shows NV completeness for multi-NV (not 'Tổng điểm: —')", () => {
    render(
      <SectionReview
        profile={buildProfile({
          uses_choice_engine: true,
          total_score: null,
          choices: [{ data_complete: true }, { data_complete: false }],
        } as Partial<AdmissionProfileResponse>)}
        onNavigateToStep={vi.fn()}
      />,
    )
    expect(screen.getByText("1/2 NV đủ điểm")).toBeInTheDocument()
    expect(screen.queryByText("Tổng điểm: —")).not.toBeInTheDocument()
  })
})
