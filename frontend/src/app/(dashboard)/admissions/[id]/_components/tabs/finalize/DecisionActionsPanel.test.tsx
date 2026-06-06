/**
 * DecisionActionsPanel — decision CTA hierarchy tests (plan Hero redesign).
 *
 * Pins:
 *   - Reviewer cluster prominence: eligible → Phê duyệt primary + Yêu cầu sửa /
 *     Từ chối secondary; ineligible & no bypass → Yêu cầu sửa primary, Phê duyệt
 *     disabled tertiary (no success green) + reason line.
 *   - Single-action states: enroll/submit/resubmit show ONLY their own action;
 *     publish_result shows "Công bố" + "Yêu cầu sửa" (secondary, when permitted) but
 *     still hides approve/reject.
 *   - bypass_warning guard preserved (warning class + AlertDialog).
 *   - submit disabled + reason when !isEligible; resubmit NEVER gated by isEligible.
 *   - Root is NOT a Card / sticky (Hero owns shell). No send-link inside the panel.
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
      primaryAction="approve"
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

describe("DecisionActionsPanel — reviewer cluster hierarchy", () => {
  beforeEach(() => vi.clearAllMocks())

  it("eligible + canApprove + canReject → both render (approve primary, reject secondary)", () => {
    renderPanel(buildProfile(), { canApprove: true, canReject: true })
    expect(screen.getByText("Phê duyệt")).toBeInTheDocument()
    expect(screen.getByText("Từ chối hồ sơ")).toBeInTheDocument()
  })

  it("eligible + 3-way → Phê duyệt + Yêu cầu sửa + Từ chối all render", () => {
    renderPanel(buildProfile(), { canApprove: true, canReject: true, canRequestRevision: true })
    expect(screen.getAllByText("Yêu cầu sửa").length).toBeGreaterThan(0)
    expect(screen.getByText("Từ chối hồ sơ")).toBeInTheDocument()
    expect(screen.getByText("Phê duyệt")).toBeInTheDocument()
  })

  it("ineligible + no bypass → Yêu cầu sửa primary; Phê duyệt disabled tertiary + reason; Từ chối present", () => {
    renderPanel(buildProfile({ eligibility_status: "ineligible", bypass_warning: false }), {
      canApprove: true,
      canReject: true,
      canRequestRevision: true,
      isEligible: false,
    })
    expect(screen.getAllByText("Yêu cầu sửa").length).toBeGreaterThan(0)
    expect(screen.getByText("Từ chối hồ sơ")).toBeInTheDocument()
    const approve = screen.getByText("Phê duyệt").closest("button")
    expect(approve).toBeDisabled()
    expect(approve?.className).not.toMatch(/bg-success-600/)
    expect(screen.getByText("Chưa đủ điều kiện để phê duyệt.")).toBeInTheDocument()
  })
})

describe("DecisionActionsPanel — single-action states hide off-state actions", () => {
  beforeEach(() => vi.clearAllMocks())

  it("publish_result → 'Công bố kết quả' (primary) + 'Yêu cầu sửa' (secondary); hides Phê duyệt/Từ chối", () => {
    renderPanel(buildProfile(), {
      primaryAction: "publish_result",
      canPublishResult: true,
      canApprove: true,
      canReject: true,
      canRequestRevision: true,
    })
    expect(screen.getAllByText("Công bố kết quả").length).toBeGreaterThan(0)
    // Reviewer giữ được đường trả hồ sơ multi-NV lỗi về officer trước khi công bố.
    expect(screen.getAllByText("Yêu cầu sửa").length).toBeGreaterThan(0)
    expect(screen.queryByText("Phê duyệt")).not.toBeInTheDocument()
    expect(screen.queryByText("Từ chối hồ sơ")).not.toBeInTheDocument()
  })

  it("publish_result without request_revision perm → ONLY 'Công bố kết quả'", () => {
    renderPanel(buildProfile(), { primaryAction: "publish_result", canPublishResult: true })
    expect(screen.getAllByText("Công bố kết quả").length).toBeGreaterThan(0)
    expect(screen.queryByText("Yêu cầu sửa")).not.toBeInTheDocument()
    expect(screen.queryByText("Từ chối hồ sơ")).not.toBeInTheDocument()
  })

  it("enroll → ONLY 'Ghi danh'", () => {
    renderPanel(buildProfile(), { primaryAction: "enroll", canEnroll: true, canReject: true })
    expect(screen.getByText("Ghi danh")).toBeInTheDocument()
    expect(screen.queryByText("Từ chối hồ sơ")).not.toBeInTheDocument()
  })
})

describe("DecisionActionsPanel — composition (R4: no Card/sticky shell)", () => {
  it("root is a plain div, NOT a Card, with no sticky/bottom/shadow classes", () => {
    const { container } = renderPanel(buildProfile(), { primaryAction: "submit", canSubmit: true })
    const root = container.firstChild as HTMLElement
    expect(root.tagName).toBe("DIV")
    expect(root.className).not.toMatch(/lg:sticky/)
    expect(root.className).not.toMatch(/bottom-4/)
    expect(root.className).not.toMatch(/lg:shadow-lg/)
    expect(root.className).not.toMatch(/rounded-xl/)
    expect(root.className).not.toMatch(/bg-card/)
  })
})

describe("DecisionActionsPanel — approve tone", () => {
  beforeEach(() => vi.clearAllMocks())

  it("bypass_warning=true → 'Phê duyệt (vượt điều kiện)' warning class + AlertDialog", () => {
    const profile = buildProfile({ bypass_warning: true, eligibility_status: "ineligible", validation_errors: ["Thiếu CCCD"] })
    renderPanel(profile, { canApprove: true, isEligible: false })
    const trigger = screen.getByText("Phê duyệt (vượt điều kiện)").closest("button")
    expect(trigger?.className).toMatch(/bg-warning-600/)
    expect(screen.getByText("⚠️ Hồ sơ chưa đủ điều kiện")).toBeInTheDocument()
  })

  it("eligible → Phê duyệt enabled with success tone", () => {
    renderPanel(buildProfile({ eligibility_status: "eligible" }), { canApprove: true, isEligible: true })
    const btn = screen.getByText("Phê duyệt").closest("button")
    expect(btn).not.toBeDisabled()
    expect(btn?.className).toMatch(/bg-success-600/)
  })

  it("ineligible + no bypass (only approve perm) → disabled, neutral (no green), reason line", () => {
    renderPanel(buildProfile({ eligibility_status: "ineligible", bypass_warning: false }), {
      canApprove: true,
      isEligible: false,
    })
    const btn = screen.getByText("Phê duyệt").closest("button")
    expect(btn).toBeDisabled()
    expect(btn?.className).not.toMatch(/bg-success-600/)
    expect(screen.queryByText("Phê duyệt (vượt điều kiện)")).not.toBeInTheDocument()
    expect(screen.getByText("Chưa đủ điều kiện để phê duyệt.")).toBeInTheDocument()
  })
})

describe("DecisionActionsPanel — submit / resubmit gate (I1/I2)", () => {
  beforeEach(() => vi.clearAllMocks())

  it("submit + !isEligible → 'Nộp hồ sơ chính thức' DISABLED + reason line", () => {
    renderPanel(buildProfile({ eligibility_status: "ineligible" }), {
      primaryAction: "submit",
      canSubmit: true,
      isEligible: false,
    })
    expect(screen.getByText("Nộp hồ sơ chính thức").closest("button")).toBeDisabled()
    expect(screen.getByText("Chưa đủ điều kiện để nộp.")).toBeInTheDocument()
  })

  it("submit + eligible → enabled, no reason line", () => {
    renderPanel(buildProfile({ eligibility_status: "eligible" }), {
      primaryAction: "submit",
      canSubmit: true,
      isEligible: true,
    })
    expect(screen.getByText("Nộp hồ sơ chính thức").closest("button")).not.toBeDisabled()
    expect(screen.queryByText("Chưa đủ điều kiện để nộp.")).not.toBeInTheDocument()
  })

  it("resubmit + !isEligible → 'Nộp lại hồ sơ' ENABLED and actionable", () => {
    const { spies } = renderPanel(buildProfile({ eligibility_status: "ineligible", status: "rejected" }), {
      primaryAction: "resubmit",
      canResubmit: true,
      isEligible: false,
    })
    expect(screen.getByText("Nộp lại hồ sơ").closest("button")).not.toBeDisabled()
    fireEvent.click(screen.getByText("Nộp lại"))
    expect(spies.onResubmit).toHaveBeenCalled()
  })
})

describe("DecisionActionsPanel — no send-link (D1/D3)", () => {
  it("does not render any 'Gửi link' utility action", () => {
    renderPanel(buildProfile(), { primaryAction: "submit", canSubmit: true, canApprove: true })
    expect(screen.queryByText(/Gửi link/i)).not.toBeInTheDocument()
  })
})
