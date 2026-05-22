/**
 * DocumentReviewCard — Commit 7 follow-up anchor.
 *
 * Pin logic `noMandatoryRequired`:
 *   - mandatoryCount=0 + missingUt=0 → isComplete=true (success icon)
 *     (trước fix: rơi vào AlertTriangle đỏ vì isComplete yêu cầu
 *      mandatoryCount > 0).
 *   - mandatoryCount=0 + missingUt > 0 → isComplete=false (warning).
 *   - mandatoryCount > 0 + verified < mandatory → warning.
 *   - mandatoryCount > 0 + verified === mandatory + missingUt=0 → success.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { DocumentReviewCard } from "./DocumentReviewCard"

function buildProfile(overrides: {
  mandatoryCount?: number
  verifiedCount?: number
  submittedCount?: number
  missingCount?: number
  missingUt?: string[]
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
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: overrides.missingUt ?? [],
    priority_evidence_documents: [],
    priority_resolution_snapshot: {},
    document_stats: {
      verified_count: overrides.verifiedCount ?? 0,
      submitted_count: overrides.submittedCount ?? 0,
      mandatory_count: overrides.mandatoryCount ?? 0,
      missing_count: overrides.missingCount ?? 0,
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("DocumentReviewCard — noMandatoryRequired logic (Commit 7 fix-up)", () => {
  it("mandatoryCount=0 + missingUt=[]: render success icon (KHÔNG false-error)", () => {
    const profile = buildProfile({ mandatoryCount: 0, missingUt: [] })
    render(<DocumentReviewCard profile={profile} />)
    const card = screen.getByTestId("document-review-card")
    // Success icon (CheckCircle2) có class text-success-600
    const successIcon = card.querySelector(".text-success-600")
    expect(successIcon).toBeTruthy()
    // KHÔNG có error icon (text-error-600)
    const errorIcon = card.querySelector(".text-error-600")
    expect(errorIcon).toBeFalsy()
  })

  it("mandatoryCount=0 + missingUt=['UT07']: warning icon (Clock) — không phải error", () => {
    const profile = buildProfile({ mandatoryCount: 0, missingUt: ["UT07"] })
    render(<DocumentReviewCard profile={profile} />)
    const card = screen.getByTestId("document-review-card")
    const warningIcon = card.querySelector(".text-warning-600")
    expect(warningIcon).toBeTruthy()
    // Badge thiếu UT
    expect(screen.getByText(/Thiếu 1 minh chứng UT/i)).toBeInTheDocument()
  })

  it("mandatoryCount=5 + verified=2 + submitted=3: warning Clock icon + 'cần X nữa' implicit", () => {
    const profile = buildProfile({
      mandatoryCount: 5,
      verifiedCount: 2,
      submittedCount: 3,
      missingCount: 2,
    })
    render(<DocumentReviewCard profile={profile} />)
    const card = screen.getByTestId("document-review-card")
    const warningIcon = card.querySelector(".text-warning-600")
    expect(warningIcon).toBeTruthy()
    // Badge thiếu mandatory
    expect(screen.getByText(/Thiếu 2 tài liệu bắt buộc/i)).toBeInTheDocument()
    // Ratio hiển thị
    expect(screen.getByText("2/5")).toBeInTheDocument()
  })

  it("mandatoryCount=3 + verified=3 + missingUt=[]: success icon, KHÔNG badge", () => {
    const profile = buildProfile({
      mandatoryCount: 3,
      verifiedCount: 3,
      submittedCount: 3,
      missingCount: 0,
      missingUt: [],
    })
    render(<DocumentReviewCard profile={profile} />)
    const card = screen.getByTestId("document-review-card")
    const successIcon = card.querySelector(".text-success-600")
    expect(successIcon).toBeTruthy()
    expect(screen.queryByText(/Thiếu.*tài liệu/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Thiếu.*minh chứng UT/i)).not.toBeInTheDocument()
  })

  it("mandatoryCount > 0 + verified < mandatory + missingUt=[]: error icon if no pending submit", () => {
    // Edge case: 5 mandatory, 0 verified, 0 submitted → hasPending = false (0 < 5 = true actually)
    // Let me re-check: submitted=0, mandatory=5, 0 < 5 = true → hasPending=true → warning
    // Actually for error icon ta cần !hasPending: missingUt=0 AND submitted>=mandatory AND verified<mandatory.
    // This case khó tạo trừ khi submitted=mandatory but verified<mandatory (đã nộp nhưng chưa duyệt hết).
    const profile = buildProfile({
      mandatoryCount: 3,
      verifiedCount: 1,
      submittedCount: 3, // >= mandatory: hasPending = false
      missingCount: 0,
      missingUt: [],
    })
    render(<DocumentReviewCard profile={profile} />)
    const card = screen.getByTestId("document-review-card")
    // hasPending = (3 < 3) || (0 > 0) = false → falls to error icon
    const errorIcon = card.querySelector(".text-error-600")
    expect(errorIcon).toBeTruthy()
  })
})
