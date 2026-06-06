/**
 * ReadinessHero — presentational anchor tests (decision-surface redesign).
 *
 * Pins: identity + ONE verdict badge; one-line decision summary only when set;
 * metrics WITHOUT a duplicate eligibility metric; cta slot renders; no sticky
 * utility actions in the Hero.
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
    verdictLabel: "Có thể nộp",
    verdictTone: "success",
    decisionSummary: null,
    actionItems: [],
    actionItemCount: 0,
    outstandingLabel: "Mục cần xử lý",
    summaryLine: null,
    hasExecutiveSummary: true,
    documentTone: "success",
    hasOutstandingWarnings: false,
    ...overrides,
  }
}

describe("ReadinessHero", () => {
  it("renders identity + the SINGLE verdict badge", () => {
    render(<ReadinessHero profile={buildProfile()} readiness={buildReadiness()} />)
    expect(screen.getByText("Nguyễn Văn A")).toBeInTheDocument()
    expect(screen.getByText("#1024")).toBeInTheDocument()
    expect(screen.getByText("Có thể nộp")).toBeInTheDocument()
  })

  it("'Nguyện vọng' shows the choice (program/degree); 'Phương thức' shows the humanized method, never the raw code", () => {
    const { container } = render(
      <ReadinessHero
        profile={buildProfile({
          applied_rules: { admission_method: "201", method_type: "subject_based" },
          choices: [{ display_program_name: "Công nghệ ô tô", display_degree_level: "Trung cấp" }],
        } as Partial<AdmissionProfileResponse>)}
        readiness={buildReadiness()}
      />,
    )
    expect(screen.getByText("Công nghệ ô tô — Trung cấp")).toBeInTheDocument()
    expect(screen.getByText("Xét theo tổ hợp môn")).toBeInTheDocument()
    expect(container.textContent).not.toContain("Nguyện vọng: 201")
    expect(screen.queryByText("201")).not.toBeInTheDocument()
  })

  it("does NOT render a separate eligibility badge or eligibility metric (one verdict only)", () => {
    const { container } = render(
      <ReadinessHero profile={buildProfile()} readiness={buildReadiness()} />,
    )
    expect(container.textContent).not.toContain("Việc của bạn")
    expect(container.textContent).not.toContain("Điều kiện xét")
  })

  it("renders the one-line decision summary only when present", () => {
    const { rerender, container } = render(
      <ReadinessHero profile={buildProfile()} readiness={buildReadiness()} />,
    )
    // null summary → not rendered
    expect(container.textContent).not.toMatch(/Còn .* mục cần xử lý/)
    rerender(
      <ReadinessHero
        profile={buildProfile()}
        readiness={buildReadiness({ decisionSummary: "Còn 3 mục cần xử lý trước khi nộp." })}
      />,
    )
    expect(screen.getByText("Còn 3 mục cần xử lý trước khi nộp.")).toBeInTheDocument()
  })

  it("renders document metric m/n from document_stats", () => {
    render(<ReadinessHero profile={buildProfile()} readiness={buildReadiness()} />)
    expect(screen.getByText("6/6 đã nộp")).toBeInTheDocument()
  })

  it("document metric falls back to — when document_stats null", () => {
    render(
      <ReadinessHero
        profile={buildProfile({
          document_stats: null,
          // Give a choice so the "Nguyện vọng" field isn't also "—" (which would
          // make the bare getByText("—") ambiguous) — isolate the doc metric.
          choices: [{ display_program_name: "X", display_degree_level: "Y" }],
        } as Partial<AdmissionProfileResponse>)}
        readiness={buildReadiness()}
      />,
    )
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("renders the outstanding metric with the hook's label when count > 0", () => {
    render(
      <ReadinessHero
        profile={buildProfile()}
        readiness={buildReadiness({ actionItemCount: 3, outstandingLabel: "Mục cần xử lý" })}
      />,
    )
    expect(screen.getByText("Mục cần xử lý")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
  })

  it("hides the outstanding metric when count is 0 (no noisy 'Mục cần xử lý: 0')", () => {
    const { container } = render(
      <ReadinessHero
        profile={buildProfile()}
        readiness={buildReadiness({ actionItemCount: 0, outstandingLabel: "Mục cần xử lý" })}
      />,
    )
    expect(container.textContent).not.toContain("Mục cần xử lý")
  })

  it("renders cta slot when provided (single CTA surface)", () => {
    render(
      <ReadinessHero
        profile={buildProfile()}
        readiness={buildReadiness()}
        cta={<div data-testid="cta-child">PANEL</div>}
      />,
    )
    expect(screen.getByTestId("cta-child")).toBeInTheDocument()
  })

  it("does NOT render any sticky utility action in the Hero", () => {
    const { container } = render(
      <ReadinessHero profile={buildProfile()} readiness={buildReadiness()} cta={<div>cta</div>} />,
    )
    expect(container.textContent).not.toContain("Lưu nháp")
    expect(container.textContent).not.toContain("Lưu thay đổi")
    expect(container.textContent).not.toContain("Kiểm tra toàn bộ")
    expect(container.textContent).not.toContain("Gửi link")
  })
})
