/**
 * ReviewDetails — Commit 4 fix-up anchor.
 *
 * Pin: `onNavigateToDocuments` truyền xuống UtEvidenceCards. Khi user
 * click "Mở tab Giấy tờ" trong UT card, callback fire — KHÔNG noop.
 *
 * Strategy: mock các child component nặng (PrioritySummaryPanel,
 * UtEvidenceCards, ScoreSnapshot, DocumentChecklist) bằng probe expose
 * prop để assert mức composition. Real UtEvidenceCards button test
 * đã có ở priority/UtEvidenceCards.test.tsx.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

vi.mock("../../priority/PrioritySummaryPanel", () => ({
  PrioritySummaryPanel: () => <div data-testid="probe-priority-summary" />,
}))

vi.mock("../../priority/UtEvidenceCards", () => ({
  UtEvidenceCards: ({ onNavigateToDocuments, canVerify, isEditable }: {
    onNavigateToDocuments: () => void
    canVerify: boolean
    isEditable: boolean
  }) => (
    <button
      data-testid="probe-ut-evidence-navigate"
      data-can-verify={String(canVerify)}
      data-is-editable={String(isEditable)}
      onClick={onNavigateToDocuments}
    >
      probe-navigate
    </button>
  ),
}))

vi.mock("./ScoreSnapshot", () => ({
  ScoreSnapshot: () => <div data-testid="probe-score-snapshot" />,
}))

vi.mock("./DocumentChecklist", () => ({
  DocumentChecklist: () => <div data-testid="probe-document-checklist" />,
}))

import { ReviewDetails } from "./ReviewDetails"

function buildProfile(): AdmissionProfileResponse {
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
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("ReviewDetails — Commit 4 fix-up: onNavigateToDocuments wiring", () => {
  it("renders all 4 sections", () => {
    render(<ReviewDetails profile={buildProfile()} onNavigateToDocuments={vi.fn()} />)
    expect(screen.getByTestId("probe-priority-summary")).toBeInTheDocument()
    expect(screen.getByTestId("probe-ut-evidence-navigate")).toBeInTheDocument()
    expect(screen.getByTestId("probe-score-snapshot")).toBeInTheDocument()
    expect(screen.getByTestId("probe-document-checklist")).toBeInTheDocument()
  })

  it("UtEvidenceCards nhận canVerify=false + isEditable=false (read-only ở Step 8)", () => {
    render(<ReviewDetails profile={buildProfile()} onNavigateToDocuments={vi.fn()} />)
    const probe = screen.getByTestId("probe-ut-evidence-navigate")
    expect(probe).toHaveAttribute("data-can-verify", "false")
    expect(probe).toHaveAttribute("data-is-editable", "false")
  })

  it("click probe navigate button fires onNavigateToDocuments (KHÔNG noop)", () => {
    const onNavigate = vi.fn()
    render(<ReviewDetails profile={buildProfile()} onNavigateToDocuments={onNavigate} />)
    fireEvent.click(screen.getByTestId("probe-ut-evidence-navigate"))
    expect(onNavigate).toHaveBeenCalledTimes(1)
  })
})
