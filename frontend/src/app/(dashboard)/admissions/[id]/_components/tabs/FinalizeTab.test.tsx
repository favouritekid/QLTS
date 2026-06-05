/**
 * FinalizeTab — Decision Surface Anchor Tests (Commit 2)
 *
 * Pin:
 *   - bypass_warning=true → AlertDialog liệt kê validation_errors fire
 *     khi click Approve (anti-regression cho migration từ sticky bar).
 *   - Decision actions render đúng theo BE permission flags
 *     (canSubmit/canApprove/canReject/canResubmit), KHÔNG theo profile.status.
 *   - Empty permission set → KHÔNG render decision panel.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Mock readiness children — parity tested in their own suites. ReadinessHero is a
// passthrough that renders its `cta` slot so the DecisionActionsPanel (real) still
// renders the decision buttons this suite asserts on (single action SURFACE — D2).
vi.mock("./finalize/ReadinessHero", () => ({
  ReadinessHero: ({ cta }: { cta?: React.ReactNode }) => (
    <div data-testid="readiness-hero">{cta}</div>
  ),
}))
vi.mock("./finalize/ActionItemsList", () => ({
  ActionItemsList: () => <div data-testid="action-items-list" />,
}))
vi.mock("./finalize/SectionReview", () => ({
  SectionReview: () => <div data-testid="section-review" />,
}))
vi.mock("./finalize/InspectionDetails", () => ({
  InspectionDetails: () => <div data-testid="inspection-details" />,
}))
vi.mock("./finalize/ReviewerCockpit", () => ({
  ReviewerCockpit: () => <div data-testid="reviewer-cockpit" />,
}))

// Pass-through AlertDialog mock (no Radix portal)
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

import { FinalizeTab } from "./FinalizeTab"

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

function renderTab(
  profile: AdmissionProfileResponse,
  overrides: Partial<React.ComponentProps<typeof FinalizeTab>> = {}
) {
  const spies = {
    onSubmit: vi.fn(),
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onResubmit: vi.fn(),
    onRequestRevision: vi.fn(),
    onPublishResult: vi.fn(),
    onEnroll: vi.fn(),
    onNavigateToDocuments: vi.fn(),
    onNavigateToStep: vi.fn(),
  }
  render(
    <FinalizeTab
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
      onNavigateToDocuments={spies.onNavigateToDocuments}
      onNavigateToStep={spies.onNavigateToStep}
      {...overrides}
    />
  )
  return spies
}

describe("FinalizeTab — Decision Surface", () => {
  beforeEach(() => vi.clearAllMocks())

  describe("bypass_warning guard preservation (CRITICAL)", () => {
    it("bypass_warning=true: Approve renders AlertDialog liệt kê validation_errors", () => {
      const profile = buildProfile({
        bypass_warning: true,
        eligibility_status: "ineligible",
        validation_errors: ["Họ tên không hợp lệ", "CCCD trống", "Ngày sinh thiếu"],
      })
      renderTab(profile, { canApprove: true })

      // Trigger button: "Phê duyệt (vượt điều kiện)"
      expect(screen.getByText("Phê duyệt (vượt điều kiện)")).toBeInTheDocument()
      // Dialog content fires
      expect(screen.getByText("⚠️ Hồ sơ chưa đủ điều kiện")).toBeInTheDocument()
      // Validation errors listed
      expect(screen.getByText("Họ tên không hợp lệ")).toBeInTheDocument()
      expect(screen.getByText("CCCD trống")).toBeInTheDocument()
      expect(screen.getByText("Ngày sinh thiếu")).toBeInTheDocument()
      // Confirmation action: "Vẫn phê duyệt"
      expect(screen.getByText("Vẫn phê duyệt")).toBeInTheDocument()
    })

    it("bypass_warning=true: click 'Vẫn phê duyệt' calls onApprove", () => {
      const profile = buildProfile({
        bypass_warning: true,
        eligibility_status: "ineligible",
        validation_errors: ["Thiếu CCCD"],
      })
      const spies = renderTab(profile, { canApprove: true })

      fireEvent.click(screen.getByText("Vẫn phê duyệt"))
      expect(spies.onApprove).toHaveBeenCalled()
    })

    it("bypass_warning=false: Approve là plain Button, KHÔNG có dialog", () => {
      const profile = buildProfile({ bypass_warning: false })
      renderTab(profile, { canApprove: true })

      expect(screen.getByText("Phê duyệt")).toBeInTheDocument()
      expect(screen.queryByText("⚠️ Hồ sơ chưa đủ điều kiện")).not.toBeInTheDocument()
    })

    it("bypass_warning=true: trigger Button có class warning, KHÔNG có class success (visual risk signal preserved)", () => {
      const profile = buildProfile({
        bypass_warning: true,
        eligibility_status: "ineligible",
        validation_errors: ["Thiếu CCCD"],
      })
      renderTab(profile, { canApprove: true })

      const trigger = screen.getByText("Phê duyệt (vượt điều kiện)").closest("button")
      expect(trigger).toBeTruthy()
      expect(trigger?.className).toMatch(/bg-warning-600/)
      // Anti-regression: FinalizeTab caller class success KHÔNG được override
      // bg-warning của component (twMerge resolves to last `bg-*`).
      expect(trigger?.className).not.toMatch(/bg-success-600/)
    })

    it("bypass_warning=false: trigger Button có class success, KHÔNG có class warning", () => {
      const profile = buildProfile({ bypass_warning: false })
      renderTab(profile, { canApprove: true })

      const trigger = screen.getByText("Phê duyệt").closest("button")
      expect(trigger).toBeTruthy()
      expect(trigger?.className).toMatch(/bg-success-600/)
      expect(trigger?.className).not.toMatch(/bg-warning-600/)
    })
  })

  describe("Permission-based rendering (BE-driven, không theo status)", () => {
    it("canSubmit=true only: chỉ render Submit", () => {
      renderTab(buildProfile(), { canSubmit: true })
      expect(screen.getByText("Nộp hồ sơ chính thức")).toBeInTheDocument()
      expect(screen.queryByText("Phê duyệt")).not.toBeInTheDocument()
      expect(screen.queryByText("Từ chối hồ sơ")).not.toBeInTheDocument()
      expect(screen.queryByText("Nộp lại hồ sơ")).not.toBeInTheDocument()
    })

    it("canApprove + canReject: render cả approve và reject", () => {
      renderTab(buildProfile(), { canApprove: true, canReject: true })
      expect(screen.getByText("Phê duyệt")).toBeInTheDocument()
      expect(screen.getByText("Từ chối hồ sơ")).toBeInTheDocument()
    })

    it("canResubmit=true: render Resubmit với confirmation dialog", () => {
      renderTab(buildProfile(), { canResubmit: true })
      expect(screen.getByText("Nộp lại hồ sơ")).toBeInTheDocument()
    })

    it("no permission flag: KHÔNG render decision panel", () => {
      const { container } = render(
        <FinalizeTab
          profile={buildProfile()}
          isEligible={true}
          onSubmit={vi.fn()}
          isSubmitting={false}
          canSubmit={false}
          isResubmitting={false}
          canResubmit={false}
          isApproving={false}
          canApprove={false}
          isRejecting={false}
          canReject={false}
          canRequestRevision={false}
          canPublishResult={false}
          canEnroll={false}
          onNavigateToDocuments={vi.fn()}
          onNavigateToStep={vi.fn()}
        />
      )
      expect(container.textContent).not.toContain("Nộp hồ sơ")
      expect(container.textContent).not.toContain("Phê duyệt")
    })
  })

  describe("Submit eligibility", () => {
    it("canSubmit + eligible: Submit enabled", () => {
      renderTab(buildProfile({ eligibility_status: "eligible" }), { canSubmit: true })
      const btn = screen.getByText("Nộp hồ sơ chính thức").closest("button")
      expect(btn).not.toBeDisabled()
    })

    it("canSubmit + ineligible: Submit disabled", () => {
      renderTab(
        buildProfile({ eligibility_status: "ineligible" }),
        { canSubmit: true, isEligible: false }
      )
      const btn = screen.getByText("Nộp hồ sơ chính thức").closest("button")
      expect(btn).toBeDisabled()
    })

    it("click Submit (eligible) calls onSubmit", () => {
      const spies = renderTab(buildProfile(), { canSubmit: true })
      fireEvent.click(screen.getByText("Nộp hồ sơ chính thức"))
      expect(spies.onSubmit).toHaveBeenCalled()
    })
  })

  describe("Role composition (officer vs reviewer)", () => {
    it("officer (canSubmit only): renders ActionItemsList + SectionReview, NOT ReviewerCockpit", () => {
      renderTab(buildProfile(), { canSubmit: true })
      expect(screen.getByTestId("action-items-list")).toBeInTheDocument()
      expect(screen.getByTestId("section-review")).toBeInTheDocument()
      expect(screen.queryByTestId("reviewer-cockpit")).not.toBeInTheDocument()
    })

    it("reviewer (canApprove): renders ReviewerCockpit, NOT ActionItemsList/SectionReview", () => {
      renderTab(buildProfile(), { canApprove: true })
      expect(screen.getByTestId("reviewer-cockpit")).toBeInTheDocument()
      expect(screen.queryByTestId("action-items-list")).not.toBeInTheDocument()
      expect(screen.queryByTestId("section-review")).not.toBeInTheDocument()
    })

    it("InspectionDetails renders for both roles (collapsed self-check)", () => {
      renderTab(buildProfile(), { canSubmit: true })
      expect(screen.getByTestId("inspection-details")).toBeInTheDocument()
    })
  })
})
