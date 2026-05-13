/**
 * Phase 3 PR-3D-B FE Wave B Day 9 — EligibilityResultViewer tests.
 *
 * Non-tautological per memory pattern-change-impact-audit:
 * - i18n label mapping from reason code (not raw code in DOM)
 * - Empty state when result=null
 * - Collapsible raw JSON toggles correctly (aria-expanded)
 * - Score card renders only when score !== null
 * - Decision badge reflects backend decision string
 */
import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { EligibilityResultViewer } from "./EligibilityResultViewer"
import type { EligibilityCheckResult } from "@/lib/admission/eligibility"

describe("EligibilityResultViewer", () => {
  it("renders empty state when result is null", () => {
    render(<EligibilityResultViewer result={null} />)
    expect(screen.getByTestId("eligibility-empty")).toBeTruthy()
    expect(screen.queryByTestId("eligibility-viewer")).toBeNull()
  })

  it("renders rejection with localized reason labels (NOT raw codes)", () => {
    const result: EligibilityCheckResult = {
      decision: "rejected",
      reason_codes: ["BELOW_MIN_GPA", "MISSING_REQUIRED_SUBJECTS"],
      score: null,
    }
    render(
      <EligibilityResultViewer
        result={result}
        pathName="CNTT 2026 - HSA"
        displayOrder={1}
      />,
    )
    expect(screen.getByText(/Lý do chưa đạt/)).toBeTruthy()
    // Reason 1 — localized
    expect(
      screen.getByText("Điểm GPA dưới ngưỡng tối thiểu"),
    ).toBeTruthy()
    expect(
      screen.getByText("Thiếu môn bắt buộc trong tổ hợp"),
    ).toBeTruthy()
    // Raw code NOT visible to candidate
    expect(screen.queryByText("BELOW_MIN_GPA")).toBeNull()
    // Display order prefix shown
    expect(screen.getByText(/NV1 — Kết quả xét tuyển/)).toBeTruthy()
    expect(screen.getByText("CNTT 2026 - HSA")).toBeTruthy()
  })

  it("renders admitted with score card showing final_score + passed=Có + subjects", () => {
    const result: EligibilityCheckResult = {
      decision: "admitted",
      reason_codes: [],
      score: {
        final_score: 27.5,
        passed: true,
        selected_subjects: ["TOAN", "LY", "HOA"],
      },
    }
    render(<EligibilityResultViewer result={result} />)
    expect(screen.getByTestId("eligibility-score-card")).toBeTruthy()
    expect(screen.getByText("27.5")).toBeTruthy()
    expect(screen.getByText("Có")).toBeTruthy()
    expect(screen.getByText("TOAN, LY, HOA")).toBeTruthy()
  })

  it("falls back to raw code for unknown reason (forward-compat with BE additions)", () => {
    const result: EligibilityCheckResult = {
      decision: "rejected",
      reason_codes: ["FUTURE_UNKNOWN_RULE"],
      score: null,
    }
    render(<EligibilityResultViewer result={result} />)
    // Unknown code falls back to raw string
    expect(screen.getByText("FUTURE_UNKNOWN_RULE")).toBeTruthy()
  })

  it("toggles raw JSON details via collapsible (aria-expanded reflects state)", () => {
    const result: EligibilityCheckResult = {
      decision: "rejected",
      reason_codes: ["BELOW_MIN_GPA"],
      score: null,
    }
    render(<EligibilityResultViewer result={result} />)
    const toggle = screen.getByTestId("eligibility-raw-toggle")
    // Initially closed
    expect(toggle.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByTestId("eligibility-raw-json")).toBeNull()
    // Click → open
    fireEvent.click(toggle)
    expect(toggle.getAttribute("aria-expanded")).toBe("true")
    const raw = screen.getByTestId("eligibility-raw-json")
    expect(raw.textContent).toContain("BELOW_MIN_GPA")
    expect(raw.textContent).toContain("rejected")
  })

  it("renders admitted reason_codes with success icon path (NOT destructive)", () => {
    // Edge: engine may emit non-fatal codes alongside admitted decision
    const result: EligibilityCheckResult = {
      decision: "admitted",
      reason_codes: ["SOME_NOTICE_CODE"],
      score: { final_score: 28, passed: true, selected_subjects: ["TOAN"] },
    }
    render(<EligibilityResultViewer result={result} />)
    expect(screen.getByText(/Ghi chú/)).toBeTruthy()
    // Should NOT show "Lý do chưa đạt" — that's the failure heading
    expect(screen.queryByText(/Lý do chưa đạt/)).toBeNull()
  })

  it("shows no-details fallback when reason_codes empty AND score null", () => {
    const result: EligibilityCheckResult = {
      decision: "skip",
      reason_codes: [],
      score: null,
    }
    render(<EligibilityResultViewer result={result} />)
    expect(screen.getByTestId("eligibility-no-details")).toBeTruthy()
  })

  it("decision badge reflects backend decision string", () => {
    const result: EligibilityCheckResult = {
      decision: "waitlisted",
      reason_codes: [],
      score: null,
    }
    render(<EligibilityResultViewer result={result} />)
    const viewer = screen.getByTestId("eligibility-viewer")
    // DecisionBadge sets role="status" with localized text
    const badge = within(viewer).getByRole("status")
    expect(badge.textContent).toContain("Chờ ghế")
  })
})
