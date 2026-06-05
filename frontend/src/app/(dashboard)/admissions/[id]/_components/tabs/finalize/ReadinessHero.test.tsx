/**
 * ReadinessHero — presentational anchor tests.
 *
 * Pins: renders both verdict signals + identity + metrics; renders the cta slot
 * when provided (single CTA surface, no card-in-card); document metric fallback.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { ReadinessHero } from "./ReadinessHero"
import type { SubmissionReadiness } from "./useSubmissionReadiness"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1024,
    lead_id: 1,
    status: "draft",
    full_name: "Nguyễn Văn A",
    citizen_id: "0123456789",
    completion_percent: 100,
    eligibility_status: "eligible",
    applied_rules: { admission_method: "HOC_BA" },
    document_stats: {
      submitted_count: 6,
      verified_count: 6,
      mandatory_count: 6,
      missing_count: 0,
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

function buildReadiness(overrides: Partial<SubmissionReadiness> = {}): SubmissionReadiness {
  return {
    eligibilityVerdict: "eligible",
    eligibilityLabel: "Đủ điều kiện xét",
    eligibilityTone: "success",
    primaryAction: "submit",
    readinessLabel: "Có thể nộp ngay",
    readinessTone: "success",
    actionItems: [],
    actionItemCount: 0,
    summaryLine: null,
    hasExecutiveSummary: true,
    ...overrides,
  }
}

describe("ReadinessHero", () => {
  it("renders identity + both verdict signals", () => {
    render(<ReadinessHero profile={buildProfile()} readiness={buildReadiness()} />)
    expect(screen.getByText("Nguyễn Văn A")).toBeInTheDocument()
    expect(screen.getByText("#1024")).toBeInTheDocument()
    // Eligibility label shows in BOTH the verdict badge and metric 3 (by design).
    expect(screen.getAllByText("Đủ điều kiện xét").length).toBeGreaterThan(0)
    expect(screen.getByText("Có thể nộp ngay")).toBeInTheDocument()
  })

  it("renders document metric m/n from document_stats", () => {
    render(<ReadinessHero profile={buildProfile()} readiness={buildReadiness()} />)
    expect(screen.getByText("6/6 đã nộp")).toBeInTheDocument()
  })

  it("document metric falls back to — when document_stats null", () => {
    render(
      <ReadinessHero
        profile={buildProfile({ document_stats: null } as Partial<AdmissionProfileResponse>)}
        readiness={buildReadiness()}
      />
    )
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("renders cta slot when provided (single CTA surface)", () => {
    render(
      <ReadinessHero
        profile={buildProfile()}
        readiness={buildReadiness()}
        cta={<div data-testid="cta-child">PANEL</div>}
      />
    )
    expect(screen.getByTestId("cta-child")).toBeInTheDocument()
  })

  it("renders summaryLine hint when present", () => {
    render(
      <ReadinessHero
        profile={buildProfile()}
        readiness={buildReadiness({ summaryLine: "Kiểm tra và nộp hồ sơ" })}
      />
    )
    expect(screen.getByText("Kiểm tra và nộp hồ sơ")).toBeInTheDocument()
  })
})
