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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
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
