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
    onCheckCondition: vi.fn(),
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

  // ===== STEP NAVIGATION (steps 1-7) — Q9 #07 Phase D.2: Priority tab added at step 4 =====

  describe("Step navigation (steps 1-7)", () => {
    it("shows Save + Next when step < 8 and save=true", () => {
      const profile = buildProfile({ status: "draft", permissions: { save: true } });
      renderActions(profile, 3);

      expect(screen.getByText("Lưu thay đổi")).toBeInTheDocument();
      expect(screen.getByText("Tiếp tục")).toBeInTheDocument();
      expect(screen.getByText(getStatusConfig("draft").label)).toBeInTheDocument();
    });

    it("shows Back for steps 2-7 even without save permission", () => {
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

  // ===== STEP 8: NAVIGATION-ONLY (decision actions moved to FinalizeTab) =====

  describe("Step 8: Sticky bar (navigation + Kiểm tra toàn bộ only)", () => {
    it("shows Kiểm tra toàn bộ at step 8 (any role)", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { submit: true },
      });
      renderActions(profile, 8);

      expect(screen.getByText("Kiểm tra toàn bộ")).toBeInTheDocument();
    });

    it("Commit 2: KHÔNG render Submit/Approve/Reject/Resubmit ở sticky bar (moved to FinalizeTab)", () => {
      const profile = buildProfile({
        status: "draft",
        permissions: { submit: true, approve: true, reject: true, resubmit: true },
        eligibility_status: "eligible",
      });
      renderActions(profile, 8);

      expect(screen.queryByText("Nộp hồ sơ")).not.toBeInTheDocument();
      expect(screen.queryByText("Phê duyệt")).not.toBeInTheDocument();
      expect(screen.queryByText("Nộp lại hồ sơ")).not.toBeInTheDocument();
      // "Từ chối" có thể appear ở các nơi khác (badge, etc.); chỉ assert
      // không có Reject button bằng cách query button có aria-label/role
      expect(screen.queryByRole("button", { name: "Từ chối" })).not.toBeInTheDocument();
    });

    it("hides Tiếp tục + Lưu nhưng GIỮ Quay lại ở step 8 (officer/manager có thể sửa lại)", () => {
      const profile = buildProfile({ status: "draft", permissions: { submit: true } });
      renderActions(profile, 8);

      expect(screen.queryByText("Tiếp tục")).not.toBeInTheDocument();
      expect(screen.queryByText("Lưu thay đổi")).not.toBeInTheDocument();
      // Commit 1: Quay lại visible ở step 8 để officer/manager review xong có thể sửa hồ sơ.
      expect(screen.getByText("Quay lại")).toBeInTheDocument();
    });
  });

  // Commit 7: Claim/Unclaim/Delete moved to ProfileActionMenu (header dropdown).
  // Enroll/PublishResult/RequestRevision moved to FinalizeTab decision panel.
  // Tests for those actions live in ProfileActionMenu.test.tsx + FinalizeTab.test.tsx.

  // ===== SEND CONFIRMATION (approved) =====

  describe("Send confirmation", () => {
    it("approved + send_confirmation=true: shows send button", () => {
      const profile = buildProfile({
        status: "approved",
        permissions: { send_confirmation: true },
      });
      renderActions(profile, 8);

      // Mocked child renders a stub button — see vi.mock at top of file.
      expect(screen.getByTestId("send-confirmation-button")).toBeInTheDocument();
    });

    it("approved + send_confirmation=false: hides send button", () => {
      // E.g. officer role that does not have the backend permission.
      const profile = buildProfile({
        status: "approved",
        permissions: { send_confirmation: false },
      });
      renderActions(profile, 8);

      expect(screen.queryByTestId("send-confirmation-button")).not.toBeInTheDocument();
    });

    it("confirmed does NOT show send button (applicant already confirmed)", () => {
      const profile = buildProfile({
        status: "confirmed",
        permissions: { send_confirmation: false, enroll: true },
      });
      renderActions(profile, 8);

      expect(screen.queryByTestId("send-confirmation-button")).not.toBeInTheDocument();
      // Commit 7: Ghi danh moved to FinalizeTab decision panel; sticky bar
      // không render. AdmissionActions chỉ giữ navigation + send buttons.
      expect(screen.queryByText("Ghi danh")).not.toBeInTheDocument();
    });

    it("submitted does NOT show send button (not approved yet)", () => {
      const profile = buildProfile({
        status: "submitted",
        permissions: { send_confirmation: false, approve: true },
      });
      renderActions(profile, 8);

      expect(screen.queryByTestId("send-confirmation-button")).not.toBeInTheDocument();
    });
  });

  // ===== ENROLLED (terminal) =====

  describe("Enrolled (terminal)", () => {
    it("enrolled + no workflow permissions: only badge visible", () => {
      const profile = buildProfile({
        status: "enrolled",
        permissions: {},
      });
      renderActions(profile, 8);

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
