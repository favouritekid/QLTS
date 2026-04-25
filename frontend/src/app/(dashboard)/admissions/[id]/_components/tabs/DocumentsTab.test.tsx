/**
 * DocumentsTab per-row permission gating (PR #5).
 *
 * The tab now renders each action button based on the explicit backend
 * flag (`doc.can_upload`, `doc.can_reject`, `doc.can_reset`,
 * `doc.can_mark_paper_submitted`) instead of the coarse
 * `can('edit')` role check. These tests exercise combinations directly
 * against the rendered DOM so any regression that falls back to a role
 * check or inverts a flag gets caught.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";

import { DocumentsTab } from "./DocumentsTab";

// Mutation hooks issue network calls — stub them so the tab renders in
// isolation without MSW handlers.
vi.mock("@/hooks/admissions/useAdmissions", () => ({
  useUploadAdmissionDocument: () => ({ mutate: vi.fn(), isPending: false }),
  useMarkPaperSubmitted: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useRejectDocument: () => ({ mutate: vi.fn(), isPending: false }),
  useResetDocument: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}));

type DocRow = {
  code: string;
  label: string;
  status: string;
  is_mandatory: boolean;
  requires_upload: boolean;
  can_upload?: boolean;
  can_reject?: boolean;
  can_reset?: boolean;
  can_mark_paper_submitted?: boolean;
  file_path?: string | null;
  uploaded_at?: string | null;
};

function buildProfile(docs: DocRow[]) {
  // Minimal profile shape — only the fields DocumentsTab reads. Cast to
  // AdmissionProfileResponse at the call site to keep the helper tight.
  return {
    id: 1,
    status: "draft",
    documents_checklist: docs,
    // DocumentsTab reads applied_rules.upload_config up front for file-size /
    // allowed-type hints; stub an empty rule set so render doesn't crash.
    applied_rules: {
      upload_config: {
        allowed_types: ["application/pdf", "image/jpeg", "image/png"],
        max_file_size: 10 * 1024 * 1024,
      },
    },
  };
}

describe("DocumentsTab — per-row permission flags", () => {
  it("renders Upload only when can_upload=true", () => {
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước công dân",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        can_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.getByRole("button", { name: /tải lên/i })).toBeInTheDocument();
  });

  it("hides Upload when can_upload=false even if status=missing", () => {
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước công dân",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        can_upload: false,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.queryByRole("button", { name: /tải lên/i })).not.toBeInTheDocument();
  });

  it("shows Reject only when can_reject=true", () => {
    const uploadedWithReject = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_reject: true,
      },
    ]);
    const { unmount } = render(<DocumentsTab profile={uploadedWithReject as never} isEditable />);
    expect(screen.getByRole("button", { name: /từ chối/i })).toBeInTheDocument();
    unmount();

    const uploadedNoReject = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_reject: false,
      },
    ]);
    render(<DocumentsTab profile={uploadedNoReject as never} isEditable />);
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
  });

  it("shows Reset only when can_reset=true regardless of status", () => {
    const profile = buildProfile([
      {
        code: "BANG_TN",
        label: "Bằng tốt nghiệp",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        can_reset: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.getByRole("button", { name: /đặt lại/i })).toBeInTheDocument();
  });

  it("shows paper-submit checkbox only when can_mark_paper_submitted=true", () => {
    const paperAllowed = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: true,
      },
    ]);
    const { unmount } = render(<DocumentsTab profile={paperAllowed as never} isEditable />);
    expect(screen.getByLabelText(/đã nộp/i)).toBeInTheDocument();
    unmount();

    const paperBlocked = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: false,
      },
    ]);
    render(<DocumentsTab profile={paperBlocked as never} isEditable />);
    expect(screen.queryByLabelText(/đã nộp/i)).not.toBeInTheDocument();
  });

  it("renders all buttons hidden when every flag is omitted (legacy row default)", () => {
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        // no can_* flags → optional() defaults surface as undefined → all hidden
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.queryByRole("button", { name: /tải lên/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /đặt lại/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/đã nộp/i)).not.toBeInTheDocument();
  });
});
