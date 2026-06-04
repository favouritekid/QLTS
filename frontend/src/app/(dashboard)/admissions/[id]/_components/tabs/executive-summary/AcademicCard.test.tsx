/**
 * AcademicCard — score-display branch tests.
 *
 * P0 hotfix multi-NV: when uses_choice_engine, the profile-level "Tổng Điểm
 * Xét Tuyển" box is replaced by per-NV scores (total_score is null for
 * multi-NV → would otherwise render "N/A"/0.00).
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import { AcademicCard } from "./AcademicCard"

function buildProfile(overrides: Partial<Record<string, unknown>> = {}) {
  const base = {
    id: 1,
    status: "submitted",
    version: 1,
    step_status: { "3": "success", "4": "success" },
    grouped_validation_errors: { scores: { count: 0 } },
    applied_rules: { method_type: "subject_based" },
    total_score: 22.5,
    average_score: 7.5,
    admission_scores: { gpa: null, selected_group: "A00", subject_scores: {} },
    uses_choice_engine: false,
    choices: [],
  }
  return { ...base, ...overrides } as unknown as Parameters<
    typeof AcademicCard
  >[0]["profile"]
}

describe("AcademicCard — legacy single-NV", () => {
  it("subject-based: hiển thị Tổng Điểm Xét Tuyển profile-level", () => {
    render(<AcademicCard profile={buildProfile()} />)
    expect(screen.getByText(/Tổng Điểm Xét Tuyển/)).toBeInTheDocument()
    expect(screen.getByText("22.50")).toBeInTheDocument()
  })
})

describe("AcademicCard — multi-NV (uses_choice_engine)", () => {
  it("render per-NV thay vì Tổng Điểm Xét Tuyển profile-level (KHÔNG N/A/0.00)", () => {
    const profile = buildProfile({
      uses_choice_engine: true,
      total_score: null,
      choices: [
        {
          id: 10,
          admission_profile_id: 1,
          admission_path_id: 5,
          path_subject_group_config_id: 7,
          display_order: 1,
          decision: "pending",
          display_path_name: "Y sỹ đa khoa 2026 - HSA - DOT_2",
          display_program_name: "Y sỹ đa khoa",
          display_degree_level: "Cao đẳng",
          display_subject_group_name: "Toán-Hóa-Sinh",
          scores: [],
          data_complete: true,
          computed_total_score: "24.50",
          admission_threshold_passed: true,
          threshold_failure_reasons: [],
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    })
    render(<AcademicCard profile={profile} />)
    expect(screen.getByTestId("per-nv-score-summary")).toBeInTheDocument()
    expect(screen.getByText("24.50")).toBeInTheDocument()
    expect(screen.getByText("Y sỹ đa khoa")).toBeInTheDocument()
    // profile-level box label must NOT render for multi-NV
    expect(screen.queryByText(/Tổng Điểm Xét Tuyển/)).not.toBeInTheDocument()
    expect(screen.queryByText("N/A")).not.toBeInTheDocument()
  })
})
