/**
 * ReviewerCockpit — decision-cockpit composition tests.
 *
 * Pins: default OPEN renders DecisionSummaryGrid + IssueLocator + fee row + audit
 * line; trigger is a real <button> with aria-expanded; readiness badge + summary
 * line reflect the readiness verdict; collapsible. Children are mocked (own suites
 * cover them; keeps the finance react-query hook out of this test).
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { SubmissionReadiness } from "./useSubmissionReadiness"

vi.mock("./DecisionSummaryGrid", () => ({
  DecisionSummaryGrid: () => <div data-testid="decision-summary-grid" />,
}))
vi.mock("./IssueLocator", () => ({
  IssueLocator: () => <div data-testid="issue-locator" />,
}))
vi.mock("../executive-summary/FeeReviewCard", () => ({
  FeeReviewCard: () => <div data-testid="fee-review-card" />,
}))
vi.mock("../executive-summary/AuditReviewCard", () => ({
  AuditReviewCard: () => <div data-testid="audit-review-card" />,
}))

import { ReviewerCockpit } from "./ReviewerCockpit"

const profile = { id: 1 } as unknown as AdmissionProfileResponse

function buildReadiness(overrides: Partial<SubmissionReadiness> = {}): SubmissionReadiness {
  return {
    eligibilityVerdict: "eligible",
    eligibilityLabel: "Đủ điều kiện xét",
    eligibilityTone: "success",
    primaryAction: "approve",
    verdictLabel: "Chờ phê duyệt",
    verdictTone: "info",
    decisionSummary: null,
    actionItems: [],
    actionItemCount: 0,
    outstandingLabel: "Mục cần xử lý",
    summaryLine: null,
    hasExecutiveSummary: false,
    documentTone: "success",
    hasOutstandingWarnings: false,
    ...overrides,
  }
}

function renderCockpit(readiness: SubmissionReadiness) {
  return render(
    <ReviewerCockpit profile={profile} readiness={readiness} onNavigateToStep={() => {}} />,
  )
}

describe("ReviewerCockpit", () => {
  it("default OPEN: shows decision grid + issue locator + fee row + audit line; aria-expanded=true", () => {
    renderCockpit(buildReadiness())
    const trigger = screen.getByRole("button", { name: /Bảng duyệt/i })
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByTestId("decision-summary-grid")).toBeInTheDocument()
    expect(screen.getByTestId("issue-locator")).toBeInTheDocument()
    expect(screen.getByTestId("fee-review-card")).toBeInTheDocument()
    expect(screen.getByTestId("audit-review-card")).toBeInTheDocument()
  })

  it("renders the readiness badge label in the header", () => {
    renderCockpit(buildReadiness({ verdictLabel: "Còn cảnh báo rà soát", verdictTone: "warning" }))
    expect(screen.getByText("Còn cảnh báo rà soát")).toBeInTheDocument()
  })

  it("summary line reflects an ineligible verdict", () => {
    renderCockpit(
      buildReadiness({
        eligibilityVerdict: "ineligible",
        eligibilityLabel: "Chưa đủ điều kiện",
        eligibilityTone: "error",
        verdictLabel: "Chưa thể phê duyệt",
        verdictTone: "warning",
      }),
    )
    expect(screen.getByText(/Hồ sơ chưa đủ điều kiện — chưa thể phê duyệt/)).toBeInTheDocument()
  })

  it("can collapse: hides the decision grid + flips aria-expanded", () => {
    renderCockpit(buildReadiness())
    const trigger = screen.getByRole("button", { name: /Bảng duyệt/i })
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByTestId("decision-summary-grid")).not.toBeInTheDocument()
  })
})
