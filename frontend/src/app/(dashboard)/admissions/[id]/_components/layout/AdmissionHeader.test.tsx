/**
 * AdmissionHeader chips — Commit 4 cockpit anchor tests.
 *
 * Pin: review signal chips render đúng theo BE field; KHÔNG render
 * khi profile null.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
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
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: {},
    document_stats: { verified_count: 5, submitted_count: 6, mandatory_count: 8, missing_count: 2 },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("AdmissionHeader — Commit 4 review signal chips", () => {
  it("renders completion chip", () => {
    render(<AdmissionHeader profile={buildProfile({ completion_percent: 80 })} />)
    expect(screen.getByTestId("header-chip-completion")).toHaveTextContent("80%")
  })

  it("renders eligibility chip", () => {
    render(<AdmissionHeader profile={buildProfile({ eligibility_status: "eligible" })} />)
    expect(screen.getByTestId("header-chip-eligibility")).toHaveTextContent("Đủ điều kiện")
  })

  it("renders ineligible eligibility chip with warning style", () => {
    render(<AdmissionHeader profile={buildProfile({ eligibility_status: "ineligible" })} />)
    expect(screen.getByTestId("header-chip-eligibility")).toHaveTextContent("Chưa đủ điều kiện")
  })

  it("renders KV chip when snapshot.kv_resolved set", () => {
    const profile = buildProfile({
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    } as Partial<AdmissionProfileResponse>)
    render(<AdmissionHeader profile={profile} />)
    expect(screen.getByTestId("header-chip-kv")).toHaveTextContent("KV1")
  })

  it("renders UT bucket chip when ut_verified_bucket.applied_code set", () => {
    const profile = buildProfile({
      priority_resolution_snapshot: {
        ut_verified_bucket: { applied_code: "07", applied_rate: 1.0 },
      },
    } as Partial<AdmissionProfileResponse>)
    render(<AdmissionHeader profile={profile} />)
    expect(screen.getByTestId("header-chip-ut")).toHaveTextContent("UT07")
  })

  it("renders docs ratio chip when mandatory_count > 0", () => {
    render(<AdmissionHeader profile={buildProfile()} />)
    expect(screen.getByTestId("header-chip-docs")).toHaveTextContent("5/8")
  })

  it("hides docs chip when mandatory_count=0", () => {
    const profile = buildProfile({
      document_stats: { verified_count: 0, submitted_count: 0, mandatory_count: 0, missing_count: 0 },
    } as Partial<AdmissionProfileResponse>)
    render(<AdmissionHeader profile={profile} />)
    expect(screen.queryByTestId("header-chip-docs")).not.toBeInTheDocument()
  })

  it("renders blocker chip when validation_errors > 0", () => {
    const profile = buildProfile({ validation_errors: ["Thiếu CCCD", "Thiếu họ tên"] })
    render(<AdmissionHeader profile={profile} />)
    expect(screen.getByTestId("header-chip-blockers")).toHaveTextContent("2 vấn đề")
  })

  it("hides blocker chip when validation_errors empty", () => {
    render(<AdmissionHeader profile={buildProfile({ validation_errors: [] })} />)
    expect(screen.queryByTestId("header-chip-blockers")).not.toBeInTheDocument()
  })

  it("renders no chips when profile=null", () => {
    render(<AdmissionHeader profile={null} />)
    expect(screen.queryByTestId("header-chip-completion")).not.toBeInTheDocument()
    expect(screen.queryByTestId("header-chip-eligibility")).not.toBeInTheDocument()
    expect(screen.queryByTestId("header-chip-kv")).not.toBeInTheDocument()
  })
})
