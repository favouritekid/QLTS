/**
 * DecisionActionsPanel — extraction + composition anchor tests (STEP8 plan D2/R4).
 *
 * Pins:
 *   - Multi-action cluster preserved (canApprove+canReject → both; 3-way review).
 *   - Root is NOT a Card and carries NO sticky/bottom-4/shadow-lg (Hero owns shell).
 *   - bypass_warning guard preserved (warning class + AlertDialog).
 *   - submit disabled when !isEligible; resubmit NEVER gated by isEligible.
 *   - No send-link inside the panel (stays on sticky AdmissionActions).
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Pass-through AlertDialog mock (no Radix portal) — mirrors FinalizeTab.test.
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogTrigger: ({ children }: { children: React.ReactNode; asChild?: boolean }) => <>{children}</>,
  AlertDialogContent: ({ children }: { children: React.ReactNode }) => <div data-testid="dialog-content">{children}</div>,
  AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  AlertDialogAction: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void; className?: string }) => (
    <button onClick={(e) => onClick?.(e as unknown as React.MouseEvent)}>{children}</button>
  ),
}))

import { DecisionActionsPanel } from "./DecisionActionsPanel"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: "draft",
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
    bypass_warning: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

function renderPanel(
  profile: AdmissionProfileResponse,
  overrides: Partial<React.ComponentProps<typeof DecisionActionsPanel>> = {},
) {
  const spies = {
    onSubmit: vi.fn(),
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onResubmit: vi.fn(),
    onRequestRevision: vi.fn(),
    onPublishResult: vi.fn(),
    onEnroll: vi.fn(),
  }
  const utils = render(
    <DecisionActionsPanel
      profile={profile}
      isEligible={profile.eligibility_status === "eligible"}
      onSubmit={spies.onSubmit}
      isSubmitting={false}
      canSubmit={false}
      onResubmit={spies.onResubmit}
      isResubmitting={false}
      canResubmit={false}
      onApprove={spies.onApprove}
      isApproving={false}
      canApprove={false}
      onReject={spies.onReject}
      isRejecting={false}
      canReject={false}
      onRequestRevision={spies.onRequestRevision}
      isRequestingRevision={false}
      canRequestRevision={false}
      onPublishResult={spies.onPublishResult}
      isPublishingResult={false}
      canPublishResult={false}
      onEnroll={spies.onEnroll}
      isEnrolling={false}
      canEnroll={false}
      {...overrides}
    />
  )
  return { ...utils, spies }
}

describe("DecisionActionsPanel — multi-action cluster (B5/I3)", () => {
  beforeEach(() => vi.clearAllMocks())

  it("canApprove + canReject → renders BOTH", () => {
    renderPanel(buildProfile(), { canApprove: true, canReject: true })
    expect(screen.getByText("Phê duyệt")).toBeInTheDocument()
    expect(screen.getByText("Từ chối hồ sơ")).toBeInTheDocument()
  })

  it("canRequestRevision + canReject + canApprove → renders ALL THREE", () => {
    renderPanel(buildProfile(), {
      canRequestRevision: true,
      canReject: true,
      canApprove: true,
    })
    // "Yêu cầu sửa" appears twice (trigger + dialog confirm via passthrough mock).
    expect(screen.getAllByText("Yêu cầu sửa").length).toBeGreaterThan(0)
    expect(screen.getByText("Từ chối hồ sơ")).toBeInTheDocument()
    expect(screen.getByText("Phê duyệt")).toBeInTheDocument()
  })
})

describe("DecisionActionsPanel — composition (R4: no Card/sticky shell)", () => {
  it("root is a plain div, NOT a Card, with no sticky/bottom/shadow classes", () => {
    const { container } = renderPanel(buildProfile(), { canSubmit: true })
    const root = container.firstChild as HTMLElement
    expect(root.tagName).toBe("DIV")
    expect(root.className).not.toMatch(/lg:sticky/)
    expect(root.className).not.toMatch(/bottom-4/)
    expect(root.className).not.toMatch(/lg:shadow-lg/)
    // Not the Card primitive (rounded-xl bg-card shadow border).
    expect(root.className).not.toMatch(/rounded-xl/)
    expect(root.className).not.toMatch(/bg-card/)
  })
})

describe("DecisionActionsPanel — bypass_warning guard (I4)", () => {
  it("bypass_warning=true → Approve trigger has warning class + AlertDialog", () => {
    const profile = buildProfile({ bypass_warning: true, eligibility_status: "ineligible", validation_errors: ["Thiếu CCCD"] })
    renderPanel(profile, { canApprove: true })
    const trigger = screen.getByText("Phê duyệt (vượt điều kiện)").closest("button")
    expect(trigger?.className).toMatch(/bg-warning-600/)
    expect(screen.getByText("⚠️ Hồ sơ chưa đủ điều kiện")).toBeInTheDocument()
  })
})

describe("DecisionActionsPanel — submit vs resubmit gate (I1/I2)", () => {
  beforeEach(() => vi.clearAllMocks())

  it("canSubmit + !isEligible → 'Nộp hồ sơ chính thức' DISABLED", () => {
    renderPanel(buildProfile({ eligibility_status: "ineligible" }), {
      canSubmit: true,
      isEligible: false,
    })
    expect(screen.getByText("Nộp hồ sơ chính thức").closest("button")).toBeDisabled()
  })

  it("canResubmit + !isEligible → 'Nộp lại hồ sơ' ENABLED and actionable", () => {
    const { spies } = renderPanel(buildProfile({ eligibility_status: "ineligible", status: "rejected" }), {
      canResubmit: true,
      isEligible: false,
    })
    expect(screen.getByText("Nộp lại hồ sơ").closest("button")).not.toBeDisabled()
    // Confirm action is wired (AlertDialogAction "Nộp lại").
    fireEvent.click(screen.getByText("Nộp lại"))
    expect(spies.onResubmit).toHaveBeenCalled()
  })
})

describe("DecisionActionsPanel — no send-link (D1/D3)", () => {
  it("does not render any 'Gửi link' utility action", () => {
    renderPanel(buildProfile(), { canSubmit: true, canApprove: true })
    expect(screen.queryByText(/Gửi link/i)).not.toBeInTheDocument()
  })
})
