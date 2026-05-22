/**
 * IssueSummary + derivePriorityIssues contract tests
 *
 * Anchors:
 *   - Priority issues from BE-set flags appear even when
 *     validationErrors=[] (mobile drawer / sidebar must not hide them).
 *   - kv_resolved=null alone (no requires_manual_override flag) does NOT
 *     produce a phantom issue.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { IssueSummary } from "./IssueSummary"
import { derivePriorityIssues } from "./priorityIssues"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: "draft",
    version: 1,
    academic_year: 2026,
    permissions: {},
    eligibility_status: "pending",
    validation_errors: [],
    available_actions: [],
    completion_percent: 50,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: {},
    // Round 2B #4 — default cultural_education_level non-null để các test
    // cũ không trigger flag "Chưa khai trình độ văn hóa". Test riêng cho
    // thiếu cultural set explicit null.
    cultural_education_level: "graduated_thpt",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("derivePriorityIssues", () => {
  it("returns empty list when profile is null", () => {
    expect(derivePriorityIssues(null)).toEqual([])
  })

  it("does NOT flag when kv_resolved === null alone (chưa preview)", () => {
    const profile = buildProfile({
      priority_resolution_snapshot: { kv_resolved: null },
    } as Partial<AdmissionProfileResponse>)
    expect(derivePriorityIssues(profile)).toEqual([])
  })

  it("flags requires_manual_override === true", () => {
    const profile = buildProfile({
      priority_resolution_snapshot: { requires_manual_override: true },
    } as Partial<AdmissionProfileResponse>)
    const issues = derivePriorityIssues(profile)
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatch(/Khu vực ưu tiên/i)
  })

  it("flags missing_priority_evidence_codes with code list (prefix UT auto)", () => {
    const profile = buildProfile({
      missing_priority_evidence_codes: ["07"],
    })
    const issues = derivePriorityIssues(profile)
    expect(issues).toHaveLength(1)
    expect(issues[0]).toContain("UT07")
  })

  it("flags missing_priority_evidence_codes — preserve existing UT prefix", () => {
    const profile = buildProfile({
      missing_priority_evidence_codes: ["UT07"],
    })
    const issues = derivePriorityIssues(profile)
    expect(issues[0]).toContain("UT07")
    // Không duplicate prefix → "UTUT07"
    expect(issues[0]).not.toContain("UTUT07")
  })

  it("combines both flags", () => {
    const profile = buildProfile({
      priority_resolution_snapshot: { requires_manual_override: true },
      missing_priority_evidence_codes: ["UT07", "UT05"],
      cultural_education_level: "graduated_thpt",
    } as Partial<AdmissionProfileResponse>)
    expect(derivePriorityIssues(profile)).toHaveLength(2)
  })

  it("Round 2B #4: thiếu cultural_education_level → flag 'Chưa khai trình độ văn hóa'", () => {
    const profile = buildProfile({
      cultural_education_level: null,
    } as Partial<AdmissionProfileResponse>)
    const issues = derivePriorityIssues(profile)
    expect(issues.some((s) => /Chưa khai trình độ văn hóa/i.test(s))).toBe(true)
  })

  it("Round 2B #4: post-submit + kv_resolved=null + !requires_manual_override → defensive flag", () => {
    const profile = buildProfile({
      status: "submitted",
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: { kv_resolved: null },
    } as Partial<AdmissionProfileResponse>)
    const issues = derivePriorityIssues(profile)
    expect(issues.some((s) => /chưa resolve được KV/i.test(s))).toBe(true)
  })

  it("Round 2B #4: draft + kv_resolved=null → KHÔNG flag (chưa preview)", () => {
    const profile = buildProfile({
      status: "draft",
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: { kv_resolved: null },
    } as Partial<AdmissionProfileResponse>)
    const issues = derivePriorityIssues(profile)
    expect(issues.some((s) => /chưa resolve được KV/i.test(s))).toBe(false)
  })
})

describe("IssueSummary", () => {
  it("renders nothing when validationErrors=[] and no priority issues", () => {
    const { container } = render(
      <IssueSummary profile={buildProfile()} validationErrors={[]} />
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders when ONLY priority issue exists (missing UT) even with empty validationErrors", () => {
    const profile = buildProfile({
      missing_priority_evidence_codes: ["UT07"],
    })
    render(<IssueSummary profile={profile} validationErrors={[]} />)
    expect(screen.getByText(/Vấn đề cần sửa \(1\)/)).toBeInTheDocument()
  })

  it("renders combined count when both validationErrors and priority issues exist", () => {
    const profile = buildProfile({
      priority_resolution_snapshot: { requires_manual_override: true },
    } as Partial<AdmissionProfileResponse>)
    render(
      <IssueSummary
        profile={profile}
        validationErrors={["Tên không hợp lệ", "CCCD trống"]}
      />
    )
    expect(screen.getByText(/Vấn đề cần sửa \(3\)/)).toBeInTheDocument()
  })
})
