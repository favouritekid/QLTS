/**
 * AdmissionHeader — "Dải trạng thái hồ sơ" case status header.
 *
 * Pin: the header answers who · nguyện vọng · phụ trách · trạng thái · verdict ·
 * việc cần xử lý, all BE-driven; the CTA jumps to the first blocking step; nothing
 * renders for a null profile.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Mock FeeStatusLink (depends on react-query)
vi.mock("@/components/finance", () => ({
  FeeStatusLink: () => <span data-testid="fee-status-link" />,
}))

import { AdmissionHeader } from "./AdmissionHeader"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 42,
    full_name: "Nguyễn Văn A",
    status: "submitted",
    version: 1,
    academic_year: 2026,
    permissions: {},
    eligibility_status: "eligible",
    validation_errors: [],
    available_actions: [],
    completion_percent: 80,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    choices: [],
    // Neutral priority state so derivePriorityIssues() = 0 by default (tests that
    // want work items set validation_errors / cultural explicitly).
    cultural_education_level: "THPT",
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: { kv_resolved: "KV2" },
    grouped_validation_errors: null,
    document_stats: { verified_count: 5, submitted_count: 6, mandatory_count: 8, missing_count: 2 },
    assigned_officer_name: "Ksor Ho Hơn",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("AdmissionHeader — dải trạng thái", () => {
  it("renders applicant name + #id", () => {
    render(<AdmissionHeader profile={buildProfile()} />)
    expect(screen.getByRole("heading")).toHaveTextContent("Nguyễn Văn A")
    expect(screen.getByRole("heading")).toHaveTextContent("#42")
  })

  it("renders the eligibility verdict", () => {
    render(<AdmissionHeader profile={buildProfile({ eligibility_status: "eligible" })} />)
    expect(screen.getByTestId("header-chip-eligibility")).toHaveTextContent("Đủ điều kiện")
  })

  it("renders ineligible verdict", () => {
    render(<AdmissionHeader profile={buildProfile({ eligibility_status: "ineligible" })} />)
    expect(screen.getByTestId("header-chip-eligibility")).toHaveTextContent("Chưa đủ điều kiện")
  })

  it("renders completion %", () => {
    render(<AdmissionHeader profile={buildProfile({ completion_percent: 80 })} />)
    expect(screen.getByTestId("header-chip-completion")).toHaveTextContent("80%")
  })

  it("renders docs ratio when mandatory_count > 0; hides when 0", () => {
    const { rerender } = render(<AdmissionHeader profile={buildProfile()} />)
    expect(screen.getByTestId("header-chip-docs")).toHaveTextContent("5/8")
    rerender(
      <AdmissionHeader
        profile={buildProfile({
          document_stats: { verified_count: 0, submitted_count: 0, mandatory_count: 0, missing_count: 0 },
        } as Partial<AdmissionProfileResponse>)}
      />,
    )
    expect(screen.queryByTestId("header-chip-docs")).not.toBeInTheDocument()
  })

  it("renders KV ledger item when snapshot.kv_resolved set", () => {
    render(<AdmissionHeader profile={buildProfile({ priority_resolution_snapshot: { kv_resolved: "KV1" } } as Partial<AdmissionProfileResponse>)} />)
    expect(screen.getByTestId("header-chip-kv")).toHaveTextContent("KV1")
  })

  // ----- nguyện vọng (đăng ký ngành gì) -----
  it("renders the registered major (nguyện vọng) from choices", () => {
    const profile = buildProfile({
      choices: [
        {
          id: 1, admission_profile_id: 42, admission_path_id: 7, path_subject_group_config_id: 3,
          display_order: 1, decision: "pending", display_path_name: "Điều dưỡng 2026 – Chính quy – Học bạ",
          display_program_name: "Điều dưỡng", display_degree_level: "Cao đẳng",
          display_subject_group_name: "B00", scores: [], data_complete: false, threshold_failure_reasons: [],
        },
      ],
    } as unknown as Partial<AdmissionProfileResponse>)
    render(<AdmissionHeader profile={profile} />)
    expect(screen.getByText("Điều dưỡng")).toBeInTheDocument()
    expect(screen.getByText("NV1")).toBeInTheDocument()
  })

  it("shows '+N NV' for multi-NV and 'Chưa chọn nguyện vọng' when empty", () => {
    const multi = buildProfile({
      choices: [
        { id: 1, display_order: 1, display_program_name: "Dược", display_degree_level: "Cao đẳng", display_path_name: "Dược", display_subject_group_name: "B00", decision: "pending", scores: [], data_complete: false, threshold_failure_reasons: [], admission_profile_id: 42, admission_path_id: 7, path_subject_group_config_id: 3 },
        { id: 2, display_order: 2, display_program_name: "Điều dưỡng", display_degree_level: "Cao đẳng", display_path_name: "Điều dưỡng", display_subject_group_name: "B00", decision: "pending", scores: [], data_complete: false, threshold_failure_reasons: [], admission_profile_id: 42, admission_path_id: 8, path_subject_group_config_id: 4 },
      ],
    } as unknown as Partial<AdmissionProfileResponse>)
    render(<AdmissionHeader profile={multi} />)
    expect(screen.getByText("+1 NV")).toBeInTheDocument()

    render(<AdmissionHeader profile={buildProfile({ choices: [] })} />)
    expect(screen.getByText("Chưa chọn nguyện vọng")).toBeInTheDocument()
  })

  it("falls back to legacy program_name when choices empty (uses_choice_engine=false)", () => {
    // Legacy single-NV profiles carry no choices[] but still identify the program
    // via program_name — must NOT read "Chưa chọn nguyện vọng".
    render(<AdmissionHeader profile={buildProfile({ uses_choice_engine: false, choices: [], program_name: "Điều dưỡng" } as Partial<AdmissionProfileResponse>)} />)
    expect(screen.getByText("Điều dưỡng")).toBeInTheDocument()
    expect(screen.queryByText("Chưa chọn nguyện vọng")).not.toBeInTheDocument()
  })

  it("does NOT show program_name for a choice-engine profile with empty choices[] (reads 'Chưa chọn nguyện vọng')", () => {
    // uses_choice_engine=true → nguyện vọng comes from choices[]; an empty choices[]
    // genuinely has none yet, and program_name may be a stale lead/offering display
    // value → must not masquerade as a chosen program.
    render(<AdmissionHeader profile={buildProfile({ uses_choice_engine: true, choices: [], program_name: "Điều dưỡng" } as Partial<AdmissionProfileResponse>)} />)
    expect(screen.getByText("Chưa chọn nguyện vọng")).toBeInTheDocument()
    expect(screen.queryByText("Điều dưỡng")).not.toBeInTheDocument()
  })

  // ----- phụ trách -----
  it("renders the assigned officer; 'Chưa phân công' when absent", () => {
    render(<AdmissionHeader profile={buildProfile({ assigned_officer_name: "Ksor Ho Hơn" })} />)
    expect(screen.getByText("Ksor Ho Hơn")).toBeInTheDocument()
    render(<AdmissionHeader profile={buildProfile({ assigned_officer_name: undefined } as Partial<AdmissionProfileResponse>)} />)
    expect(screen.getByText("Chưa phân công")).toBeInTheDocument()
  })

  // ----- việc cần xử lý CTA -----
  it("shows the work-items CTA and jumps to the first blocking step on click", () => {
    const onCheckCondition = vi.fn()
    render(<AdmissionHeader profile={buildProfile({ validation_errors: ["Thiếu CCCD", "Thiếu họ tên"] })} onCheckCondition={onCheckCondition} />)
    const cta = screen.getByTestId("header-chip-blockers")
    expect(cta).toHaveTextContent("việc")
    fireEvent.click(cta)
    expect(onCheckCondition).toHaveBeenCalledTimes(1)
  })

  it("hides the work-items CTA when nothing is blocking", () => {
    // Neutral profile: no validation errors, priority resolved (kv set + cultural
    // set + draft so the post-submit-kv rule doesn't fire), no required-data.
    render(<AdmissionHeader profile={buildProfile({ status: "draft", validation_errors: [], grouped_validation_errors: null })} />)
    expect(screen.queryByTestId("header-chip-blockers")).not.toBeInTheDocument()
  })

  it("renders nothing but a placeholder heading when profile=null", () => {
    render(<AdmissionHeader profile={null} />)
    expect(screen.queryByTestId("header-chip-eligibility")).not.toBeInTheDocument()
    expect(screen.queryByTestId("header-chip-completion")).not.toBeInTheDocument()
    expect(screen.queryByTestId("header-chip-blockers")).not.toBeInTheDocument()
  })
})
