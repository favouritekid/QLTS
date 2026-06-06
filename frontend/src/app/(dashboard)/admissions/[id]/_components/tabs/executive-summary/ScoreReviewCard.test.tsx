/**
 * ScoreReviewCard — compact "Điểm xét tuyển" signal tests.
 *
 * Pin: GPA-only vs subject-based vs multi-NV branches + tone (success/warning).
 * admission_threshold_passed is display-only (neutral wording), never error.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { ScoreReviewCard } from "./ScoreReviewCard"

function buildProfile(opts: {
  methodType?: string
  gpa?: number | null
  totalScore?: number | null
  averageScore?: number | null
  selectedGroup?: string | null
  usesChoiceEngine?: boolean
  choices?: Array<{ data_complete: boolean; admission_threshold_passed: boolean | null }>
} = {}): AdmissionProfileResponse {
  return {
    id: 1,
    status: "submitted",
    version: 1,
    academic_year: 2026,
    permissions: {},
    eligibility_status: "eligible",
    validation_errors: [],
    available_actions: [],
    completion_percent: 100,
    applied_rules: { method_type: opts.methodType ?? "subject_groups" },
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: {},
    total_score: opts.totalScore ?? null,
    average_score: opts.averageScore ?? null,
    admission_scores: { gpa: opts.gpa ?? null, selected_group: opts.selectedGroup ?? null, subject_scores: {} },
    uses_choice_engine: opts.usesChoiceEngine ?? false,
    choices: opts.choices ?? [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("ScoreReviewCard — GPA-only", () => {
  it("gpa 8.5: shows GPA + success tone", () => {
    render(<ScoreReviewCard profile={buildProfile({ methodType: "gpa_only", gpa: 8.5 })} />)
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("8.50")).toBeInTheDocument()
    expect(screen.getByText(/GPA/)).toBeInTheDocument()
    expect(card.querySelector(".text-success-600")).toBeTruthy()
  })

  it("gpa null: '—' + warning tone", () => {
    render(<ScoreReviewCard profile={buildProfile({ methodType: "gpa_only", gpa: null })} />)
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
  })
})

describe("ScoreReviewCard — subject-based", () => {
  it("total + group: shows '22.50 (A00)' + average + success", () => {
    render(
      <ScoreReviewCard
        profile={buildProfile({ totalScore: 22.5, averageScore: 7.5, selectedGroup: "A00" })}
      />,
    )
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("22.50 (A00)")).toBeInTheDocument()
    expect(screen.getByText(/Trung bình 7\.50/)).toBeInTheDocument()
    expect(card.querySelector(".text-success-600")).toBeTruthy()
  })

  it("total null: '—' + warning tone", () => {
    render(<ScoreReviewCard profile={buildProfile({ totalScore: null })} />)
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
  })
})

describe("ScoreReviewCard — multi-NV", () => {
  it("all complete + passed: '1/1 NV đủ điểm' + '1/1 NV đạt sàn' + success", () => {
    render(
      <ScoreReviewCard
        profile={buildProfile({
          usesChoiceEngine: true,
          totalScore: null,
          choices: [{ data_complete: true, admission_threshold_passed: true }],
        })}
      />,
    )
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("1/1 NV đủ điểm")).toBeInTheDocument()
    expect(screen.getByText("1/1 NV đạt sàn")).toBeInTheDocument()
    expect(card.querySelector(".text-success-600")).toBeTruthy()
  })

  it("incomplete NV: '0/1 NV đủ điểm' + warning + no sàn passed", () => {
    render(
      <ScoreReviewCard
        profile={buildProfile({
          usesChoiceEngine: true,
          totalScore: null,
          choices: [{ data_complete: false, admission_threshold_passed: null }],
        })}
      />,
    )
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("0/1 NV đủ điểm")).toBeInTheDocument()
    expect(screen.getByText("Chưa NV nào đạt sàn")).toBeInTheDocument()
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
  })
})
