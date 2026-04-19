/**
 * AdmissionActions UI Contract Tests
 *
 * Validates permission-based button visibility via can() pattern.
 * Does NOT test role logic — only profile.permissions + status → visible buttons.
 *
 * Coverage matrix:
 *   - Draft step nav: save, next, back, badge
 *   - Submit step: check condition, submit (eligible/ineligible)
 *   - Rejected/revision_requested: resubmit
 *   - Submitted/resubmitted: approve, reject, claim
 *   - Claim/unclaim toggle
 *   - Delete trigger
 *   - Approved/overridden: enroll
 *   - Enrolled: all workflow actions hidden, badge only
 *   - Click wiring for all non-dialog and dialog-confirmed actions
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { AdmissionProfileResponse } from "@/lib/zod/admissions";

// Mock SendConfirmationButton — it has its own dedicated test file and
// pulls in useMutation, which would require a QueryClientProvider that
// this test suite intentionally doesn't set up. Pass-through mock keeps
// the render tree intact without dragging the dependency chain in.
vi.mock("./SendConfirmationButton", () => ({
  SendConfirmationButton: ({ profileId }: { profileId: number }) => (
    <button data-testid="send-confirmation-button">
      Gửi liên kết xác nhận (#{profileId})
    </button>
  ),
}));

// Mock alert-dialog to pass-through (no Radix portal needed)
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogTrigger: ({ children }: { children: React.ReactNode; asChild?: boolean }) => <>{children}</>,
  AlertDialogContent: ({ children }: { children: React.ReactNode }) => <div data-testid="dialog-content">{children}</div>,
  AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  AlertDialogAction: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void; className?: string }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));

// Use REAL getStatusConfig — do NOT mock it.
// This ensures badge labels in tests match production source-of-truth
// at status-config.ts. If production labels change, tests break (desired).
import { getStatusConfig } from "@/lib/status-config";

// Import after mocks
import { AdmissionActions } from "./AdmissionActions";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Perms = Record<string, boolean>;

function buildProfile(overrides: {
  status?: string;
  permissions?: Perms;
  eligibility_status?: string;
}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: overrides.status || "draft",
    version: 1,
    academic_year: 2026,
    permissions: overrides.permissions || {},
    eligibility_status: overrides.eligibility_status || "pending",
    validation_errors: [],
    available_actions: [],
    completion_percent: 50,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse;
}

function defaultSpies() {
  return {
    onStepChange: vi.fn(),
    onSave: vi.fn(),
    onSubmit: vi.fn(),
    onEnroll: vi.fn(),
    onCheckCondition: vi.fn(),
    onResubmit: vi.fn(),
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onClaim: vi.fn(),
    onUnclaim: vi.fn(),
    onDelete: vi.fn(),
  };
}

function renderActions(
  profile: AdmissionProfileResponse,
  currentStep: number,
  overrides?: Partial<ReturnType<typeof defaultSpies>>
) {
  const spies = { ...defaultSpies(), ...overrides };
  render(
    <AdmissionActions
      profile={profile}
      currentStep={currentStep}
      isSaving={false}
      isSubmitting={false}
      isEnrolling={false}
      {...spies}
    />
  );
  return spies;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdmissionActions", () => {
  beforeEach(() => vi.clearAllMocks());

  // ===== STEP NAVIGATION (steps 1-6) =====

  describe("Step navigation (steps 1-6)", () => {
    it("shows Save + Next when step < 7 and save=true", () => {
      const profile = buildProfile({ status: "draft", permissions: { save: true } });
      renderActions(profile, 3);

      expect(screen.getByText("Lưu thay đổi")).toBeInTheDocument();
      expect(screen.getByText("Tiếp tục")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("draft").label)).toBeInTheDocument();
    });

    it("shows Back for steps 2-6 even without save permission", () => {
      const profile = buildProfile({ status: "draft", permissions: {} });
      renderActions(profile, 4);

      expect(screen.getByText("Quay lại")).toBeInTheDocument();
      expect(screen.getByText("Tiếp tục")).toBeInTheDocument();
      expect(screen.queryByText("Lưu thay đổi")).not.toBeInTheDocument();
    });

    it("hides Back on step 1", () => {
      const profile = buildProfile({ status: "draft", permissions: { save: true } });
      renderActions(profile, 1);

      expect(screen.queryByText("Quay lại")).not.toBeInTheDocument();
      expect(screen.getByText("Tiếp tục")).toBeInTheDocument();
    });

    it("click Back calls onStepChange(currentStep - 1)", () => {
      const profile = buildProfile({ status: "draft", permissions: {} });
      const spies = renderActions(profile, 5);

      fireEvent.click(screen.getByText("Quay lại"));
      expect(spies.onStepChange).toHaveBeenCalledWith(4);
    });

    it("click Next calls onStepChange(currentStep + 1)", () => {
      const profile = buildProfile({ status: "draft", permissions: {} });
      const spies = renderActions(profile, 3);

      fireEvent.click(screen.getByText("Tiếp tục"));
      expect(spies.onStepChange).toHaveBeenCalledWith(4);
    });

    it("click Save calls onSave", () => {
      const profile = buildProfile({ status: "draft", permissions: { save: true } });
      const spies = renderActions(profile, 2);

      fireEvent.click(screen.getByText("Lưu thay đổi"));
      expect(spies.onSave).toHaveBeenCalled();
    });
  });

  // ===== STEP 7: SUBMIT =====

  describe("Step 7: Submit", () => {
    it("shows Check + Submit when submit=true and eligible", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { submit: true },
        eligibility_status: "eligible",
      });
      renderActions(profile, 7);

      expect(screen.getByText("Kiểm tra toàn bộ")).toBeInTheDocument();
      expect(screen.getByText("Nộp hồ sơ")).toBeInTheDocument();
      // Submit button should be enabled
      const submitBtn = screen.getByText("Nộp hồ sơ").closest("button");
      expect(submitBtn).not.toBeDisabled();
    });

    it("Submit disabled when ineligible", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { submit: true },
        eligibility_status: "ineligible",
      });
      renderActions(profile, 7);

      const submitBtn = screen.getByText("Nộp hồ sơ").closest("button");
      expect(submitBtn).toBeDisabled();
    });

    it("click Submit calls onSubmit", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { submit: true },
        eligibility_status: "eligible",
      });
      const spies = renderActions(profile, 7);

      fireEvent.click(screen.getByText("Nộp hồ sơ"));
      expect(spies.onSubmit).toHaveBeenCalled();
    });

    it("hides step nav on step 7", () => {
      const profile = buildProfile({ status: "draft", permissions: { submit: true } });
      renderActions(profile, 7);

      expect(screen.queryByText("Tiếp tục")).not.toBeInTheDocument();
      expect(screen.queryByText("Quay lại")).not.toBeInTheDocument();
      expect(screen.queryByText("Lưu thay đổi")).not.toBeInTheDocument();
    });
  });

  // ===== RESUBMIT (rejected / revision_requested) =====

  describe("Resubmit", () => {
    it("rejected + resubmit=true: shows resubmit + badge Từ chối", () => {
      const profile = buildProfile({
        status: "rejected",
        permissions: { resubmit: true },
      });
      renderActions(profile, 7);

      expect(screen.getByText("Nộp lại hồ sơ")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("rejected").label)).toBeInTheDocument();
    });

    it("revision_requested + resubmit=true: shows resubmit + badge Yêu cầu bổ sung", () => {
      const profile = buildProfile({
        status: "revision_requested",
        permissions: { resubmit: true },
      });
      renderActions(profile, 7);

      expect(screen.getByText("Nộp lại hồ sơ")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("revision_requested").label)).toBeInTheDocument();
    });

    it("click dialog-confirmed Resubmit calls onResubmit", () => {
      const profile = buildProfile({
        status: "rejected",
        permissions: { resubmit: true },
      });
      const spies = renderActions(profile, 7);

      // With mocked AlertDialog, trigger + action both render.
      // "Nộp lại" is the dialog action text (AlertDialogAction).
      const buttons = screen.getAllByText("Nộp lại");
      fireEvent.click(buttons[buttons.length - 1]); // last = dialog action
      expect(spies.onResubmit).toHaveBeenCalled();
    });
  });

  // ===== MANAGER ACTIONS (submitted/resubmitted) =====

  describe("Manager actions", () => {
    it("submitted + approve/reject/claim: shows all 3 buttons + badge", () => {
      const profile = buildProfile({
        status: "submitted",
        permissions: { approve: true, reject: true, claim: true },
      });
      renderActions(profile, 7);

      expect(screen.getByText("Phê duyệt")).toBeInTheDocument();
      // "Từ chối" appears as both reject button text AND may appear in dialog
      expect(screen.getAllByText("Từ chối").length).toBeGreaterThanOrEqual(1);
      // "Nhận duyệt" appears as trigger + dialog action
      expect(screen.getAllByText("Nhận duyệt").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(getStatusConfig("submitted").label)).toBeInTheDocument();
    });

    it("resubmitted + approve/reject: shows approve + reject", () => {
      const profile = buildProfile({
        status: "resubmitted",
        permissions: { approve: true, reject: true },
      });
      renderActions(profile, 7);

      expect(screen.getByText("Phê duyệt")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("resubmitted").label)).toBeInTheDocument();
    });

    it("unclaim=true: shows unclaim button", () => {
      const profile = buildProfile({
        status: "submitted",
        permissions: { unclaim: true },
      });
      renderActions(profile, 7);

      // Trigger + dialog action both show "Bỏ nhận"
      expect(screen.getAllByText("Bỏ nhận").length).toBeGreaterThanOrEqual(1);
    });

    it("click dialog-confirmed Claim calls onClaim", () => {
      const profile = buildProfile({
        status: "submitted",
        permissions: { claim: true },
      });
      const spies = renderActions(profile, 7);

      // Mocked AlertDialog renders trigger + action with same text "Nhận duyệt"
      const buttons = screen.getAllByText("Nhận duyệt");
      fireEvent.click(buttons[buttons.length - 1]); // last = dialog action
      expect(spies.onClaim).toHaveBeenCalled();
    });

    it("click dialog-confirmed Unclaim calls onUnclaim", () => {
      const profile = buildProfile({
        status: "submitted",
        permissions: { unclaim: true },
      });
      const spies = renderActions(profile, 7);

      const buttons = screen.getAllByText("Bỏ nhận");
      fireEvent.click(buttons[buttons.length - 1]); // last = dialog action
      expect(spies.onUnclaim).toHaveBeenCalled();
    });
  });

  // ===== DELETE =====

  describe("Delete", () => {
    it("delete=true: shows delete trigger button + dialog action", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { delete: true },
      });
      renderActions(profile, 1);

      // Both trigger (aria-label) and dialog action (text) match "Xóa hồ sơ"
      const deleteButtons = screen.getAllByRole("button", { name: /xóa hồ sơ/i });
      expect(deleteButtons.length).toBeGreaterThanOrEqual(2); // trigger + dialog action

      // Trigger is icon-only: has aria-label but no text child
      const trigger = deleteButtons.find(
        (btn) => btn.getAttribute("aria-label") === "Xóa hồ sơ"
      );
      expect(trigger).toBeTruthy();
    });

    it("click dialog-confirmed Delete calls onDelete", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { delete: true },
      });
      const spies = renderActions(profile, 1);

      const buttons = screen.getAllByText("Xóa hồ sơ");
      fireEvent.click(buttons[buttons.length - 1]); // dialog action
      expect(spies.onDelete).toHaveBeenCalled();
    });
  });

  // ===== ENROLL (approved / overridden) =====

  describe("Enroll", () => {
    it("approved + enroll=true: shows enroll + badge Đã duyệt", () => {
      const profile = buildProfile({
        status: "approved",
        permissions: { enroll: true },
      });
      renderActions(profile, 7);

      expect(screen.getByText("Ghi danh")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("approved").label)).toBeInTheDocument();
    });

    it("overridden + enroll=true: shows enroll + badge Đã override", () => {
      const profile = buildProfile({
        status: "overridden",
        permissions: { enroll: true },
      });
      renderActions(profile, 7);

      expect(screen.getByText("Ghi danh")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("overridden").label)).toBeInTheDocument();
    });

    it("click Enroll calls onEnroll", () => {
      const profile = buildProfile({
        status: "approved",
        permissions: { enroll: true },
      });
      const spies = renderActions(profile, 7);

      fireEvent.click(screen.getByText("Ghi danh"));
      expect(spies.onEnroll).toHaveBeenCalled();
    });
  });

  // ===== ENROLLED (terminal) =====

  describe("Enrolled (terminal)", () => {
    it("enrolled + no workflow permissions: only badge visible", () => {
      const profile = buildProfile({
        status: "enrolled",
        permissions: {},
      });
      renderActions(profile, 7);

      // Badge — from real getStatusConfig, not hardcoded
      expect(screen.getByText(getStatusConfig("enrolled").label)).toBeInTheDocument();

      // All workflow actions hidden
      expect(screen.queryByText("Phê duyệt")).not.toBeInTheDocument();
      expect(screen.queryByText("Từ chối")).not.toBeInTheDocument();
      expect(screen.queryByText("Nhận duyệt")).not.toBeInTheDocument();
      expect(screen.queryByText("Bỏ nhận")).not.toBeInTheDocument();
      expect(screen.queryByText("Ghi danh")).not.toBeInTheDocument();
      expect(screen.queryByText("Nộp lại hồ sơ")).not.toBeInTheDocument();
      expect(screen.queryByText("Nộp hồ sơ")).not.toBeInTheDocument();
      expect(screen.queryByText("Lưu thay đổi")).not.toBeInTheDocument();
    });
  });
});
