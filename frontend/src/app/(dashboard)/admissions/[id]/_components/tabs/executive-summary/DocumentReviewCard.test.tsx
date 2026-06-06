/**
 * DocumentReviewCard — compact "Tài liệu" signal tests.
 *
 * Core fix pinned here: the two BE-split failure modes render with the right tone
 *   - missing_count > 0 (chưa nộp)        → ERROR (đỏ)
 *   - unverified_count > 0 (chờ xác minh) → WARNING (KHÔNG đỏ)  ← regression guard
 * unverified_count is optional → falls back to submitted − verified.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { DocumentReviewCard } from "./DocumentReviewCard"

function buildProfile(stats: {
  mandatory_count?: number
  verified_count?: number
  submitted_count?: number
  missing_count?: number
  unverified_count?: number
  missingUt?: string[]
} = {}): AdmissionProfileResponse {
  const { missingUt, ...docStats } = stats
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
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: missingUt ?? [],
    priority_resolution_snapshot: {},
    document_stats: {
      verified_count: docStats.verified_count ?? 0,
      submitted_count: docStats.submitted_count ?? 0,
      mandatory_count: docStats.mandatory_count ?? 0,
      missing_count: docStats.missing_count ?? 0,
      ...(docStats.unverified_count !== undefined ? { unverified_count: docStats.unverified_count } : {}),
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("DocumentReviewCard — tone by failure mode", () => {
  it("no mandatory docs + no UT gap: success tone", () => {
    render(<DocumentReviewCard profile={buildProfile({ mandatory_count: 0 })} />)
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-success-600")).toBeTruthy()
    expect(card.querySelector(".text-error-600")).toBeFalsy()
    expect(screen.getByText("Không yêu cầu tài liệu")).toBeInTheDocument()
  })

  it("missing mandatory docs: ERROR tone + 'Thiếu N tài liệu bắt buộc'", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 5, verified_count: 2, submitted_count: 3, missing_count: 2, unverified_count: 1 })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-error-600")).toBeTruthy()
    expect(screen.getByText("3/5 đã nộp")).toBeInTheDocument()
    expect(screen.getByText(/Thiếu 2 tài liệu bắt buộc/)).toBeInTheDocument()
  })

  it("missing mandatory docs AND missing UT → error tone + both counts in one secondary", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 5, verified_count: 1, submitted_count: 3, missing_count: 2, unverified_count: 0, missingUt: ["UT07"] })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-error-600")).toBeTruthy()
    // The error-branch secondary appends the UT count (no "chờ xác minh" since unverified=0).
    expect(screen.getByText("Thiếu 2 tài liệu bắt buộc · thiếu 1 minh chứng UT")).toBeInTheDocument()
  })

  it("REGRESSION: submitted đủ, chờ xác minh → WARNING (KHÔNG error)", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 3, verified_count: 1, submitted_count: 3, missing_count: 0, unverified_count: 2 })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
    expect(card.querySelector(".text-error-600")).toBeFalsy()
    expect(screen.getByText("Đã nộp đủ, còn 2 tài liệu chờ xác minh")).toBeInTheDocument()
  })

  it("unverified_count absent → falls back to submitted − verified (still WARNING)", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 3, verified_count: 1, submitted_count: 3, missing_count: 0 })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
    expect(card.querySelector(".text-error-600")).toBeFalsy()
    expect(screen.getByText("Đã nộp đủ, còn 2 tài liệu chờ xác minh")).toBeInTheDocument()
  })

  it("all verified, no gap: success tone + 'Đã xác minh đủ'", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 3, verified_count: 3, submitted_count: 3, missing_count: 0, unverified_count: 0 })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-success-600")).toBeTruthy()
    expect(screen.getByText("Đã xác minh đủ")).toBeInTheDocument()
  })

  it("only UT evidence missing: warning tone + UT count", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 2, verified_count: 2, submitted_count: 2, missing_count: 0, unverified_count: 0, missingUt: ["UT07"] })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-warning-600")).toBeTruthy()
    expect(screen.getByText("Thiếu 1 minh chứng UT")).toBeInTheDocument()
  })

  it("no mandatory docs + unverified OPTIONAL uploads → success, no contradictory 'chờ xác minh'", () => {
    render(
      <DocumentReviewCard
        profile={buildProfile({ mandatory_count: 0, submitted_count: 2, verified_count: 0, missing_count: 0, unverified_count: 2 })}
      />,
    )
    const card = screen.getByTestId("document-review-card")
    expect(card.querySelector(".text-success-600")).toBeTruthy()
    expect(screen.getByText("Không yêu cầu tài liệu")).toBeInTheDocument()
    expect(screen.queryByText(/chờ xác minh/)).not.toBeInTheDocument()
  })
})
