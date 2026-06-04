/**
 * ScoreReviewCard — anchor tests (Commit 8 followup).
 *
 * Pin: GPA-only vs subject-based scoring branches + status (success/warning).
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
  choices?: unknown[]
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
    admission_scores: {
      gpa: opts.gpa ?? null,
      selected_group: opts.selectedGroup ?? null,
      subject_scores: {},
    },
    uses_choice_engine: opts.usesChoiceEngine ?? false,
    choices: opts.choices ?? [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

function buildChoice(opts: {
  id?: number
  displayOrder?: number
  programName?: string
  computedTotalScore?: number | string | null
  dataComplete?: boolean
  thresholdPassed?: boolean | null
} = {}) {
  return {
    id: opts.id ?? 10,
    admission_profile_id: 1,
    admission_path_id: 5,
    path_subject_group_config_id: 7,
    display_order: opts.displayOrder ?? 1,
    decision: "pending",
    display_path_name: "Y sỹ đa khoa 2026 - HSA - DOT_2",
    display_program_name: opts.programName ?? "Y sỹ đa khoa",
    display_degree_level: "Cao đẳng",
    display_subject_group_name: "Toán-Hóa-Sinh",
    scores: [],
    data_complete: opts.dataComplete ?? true,
    // API serializes Pydantic Decimal as a STRING ("24.50") — mirror that so
    // the test catches a string.toFixed() regression in PerNvScoreSummary.
    computed_total_score:
      opts.computedTotalScore === undefined ? "24.50" : opts.computedTotalScore,
    admission_threshold_passed:
      opts.thresholdPassed === undefined ? true : opts.thresholdPassed,
    threshold_failure_reasons: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  }
}

describe("ScoreReviewCard — GPA-only method", () => {
  it("method=gpa_only + GPA 8.5: hiển thị GPA + success icon", () => {
    const profile = buildProfile({ methodType: "gpa_only", gpa: 8.5 })
    render(<ScoreReviewCard profile={profile} />)
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("GPA:")).toBeInTheDocument()
    expect(screen.getByText("8.50")).toBeInTheDocument()
    expect(card.querySelector(".text-success-600")).toBeTruthy()
  })

  it("method=gpa_only + GPA null: hiển thị '—' + warning icon", () => {
    const profile = buildProfile({ methodType: "gpa_only", gpa: null })
    render(<ScoreReviewCard profile={profile} />)
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
  })
})

describe("ScoreReviewCard — subject-based method", () => {
  it("method=subject_groups + total + group: hiển thị tổng điểm + group name", () => {
    const profile = buildProfile({
      methodType: "subject_groups",
      totalScore: 22.5,
      averageScore: 7.5,
      selectedGroup: "A00",
    })
    render(<ScoreReviewCard profile={profile} />)
    expect(screen.getByText(/Tổng điểm.*A00/)).toBeInTheDocument()
    expect(screen.getByText("22.50")).toBeInTheDocument()
    // Trung bình
    expect(screen.getByText(/Trung bình/)).toBeInTheDocument()
    expect(screen.getByText("7.50")).toBeInTheDocument()
  })

  it("method=subject_groups + totalScore null: warning icon", () => {
    const profile = buildProfile({
      methodType: "subject_groups",
      totalScore: null,
    })
    render(<ScoreReviewCard profile={profile} />)
    const card = screen.getByTestId("score-review-card")
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("method=subject_groups + averageScore null: chỉ hiển thị tổng điểm, KHÔNG dòng Trung bình", () => {
    const profile = buildProfile({
      methodType: "subject_groups",
      totalScore: 18,
      averageScore: null,
    })
    render(<ScoreReviewCard profile={profile} />)
    expect(screen.getByText("18.00")).toBeInTheDocument()
    expect(screen.queryByText(/Trung bình/)).not.toBeInTheDocument()
  })
})

describe("ScoreReviewCard — multi-NV (uses_choice_engine)", () => {
  it("render per-NV computed score + 'Đủ điểm', KHÔNG dùng total_score profile-level (KHÔNG 0.00)", () => {
    const profile = buildProfile({
      usesChoiceEngine: true,
      totalScore: null, // BE sets None for multi-NV
      choices: [
        buildChoice({ computedTotalScore: "24.50", dataComplete: true, thresholdPassed: true }),
      ],
    })
    render(<ScoreReviewCard profile={profile} />)
    expect(screen.getByTestId("per-nv-score-summary")).toBeInTheDocument()
    expect(screen.getByText("Y sỹ đa khoa")).toBeInTheDocument()
    expect(screen.getByText("24.50")).toBeInTheDocument()
    expect(screen.getByText("Đủ điểm")).toBeInTheDocument()
    // profile-level "Tổng điểm" block must NOT render for multi-NV
    expect(screen.queryByText(/^Tổng điểm/)).not.toBeInTheDocument()
    expect(screen.queryByText("0.00")).not.toBeInTheDocument()
  })

  it("multi-NV choice thiếu điểm → '—' + 'Thiếu điểm' + warning icon", () => {
    const profile = buildProfile({
      usesChoiceEngine: true,
      totalScore: null,
      choices: [
        buildChoice({ computedTotalScore: null, dataComplete: false, thresholdPassed: null }),
      ],
    })
    render(<ScoreReviewCard profile={profile} />)
    const card = screen.getByTestId("score-review-card")
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.getByText("Thiếu điểm")).toBeInTheDocument()
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
  })

  it("multi-NV dưới sàn vẫn data_complete → 'Đủ điểm' + 'Dưới sàn' (display only, KHÔNG chặn)", () => {
    const profile = buildProfile({
      usesChoiceEngine: true,
      totalScore: null,
      choices: [
        buildChoice({ computedTotalScore: "12.00", dataComplete: true, thresholdPassed: false }),
      ],
    })
    render(<ScoreReviewCard profile={profile} />)
    expect(screen.getByText("12.00")).toBeInTheDocument()
    expect(screen.getByText("Đủ điểm")).toBeInTheDocument()
    expect(screen.getByText("Dưới sàn")).toBeInTheDocument()
  })
})
