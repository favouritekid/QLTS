/**
 * DocumentsTab — per-row permission gating + ADM-031 task-orientation.
 *
 * Two concerns are exercised here:
 *
 * 1. Per-row permission flags from PR #5 (`can_upload`, `can_reject`,
 *    `can_reset`, `can_mark_paper_submitted`). Each action button must
 *    only render when the matching backend flag is true.
 *
 * 2. ADM-031 wireframe — missing rows surface a task-oriented hint
 *    ("Cần tải ảnh/scan" vs "Nhận bản giấy tại quầy") and the action
 *    buttons carry explicit labels ("Tải file" / "Đánh dấu đã nhận
 *    giấy") instead of icon-only triggers. Format dialog wording was
 *    rewritten to clarify that the user is declaring the actual paper
 *    type, not uploading additional evidence.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import userEvent from "@testing-library/user-event";

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
  submission_format?: string | null;
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
    expect(screen.getByRole("button", { name: /tải file/i })).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /tải file/i })).not.toBeInTheDocument();
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

  it("shows the paper-receipt button only when can_mark_paper_submitted=true", () => {
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
    expect(
      screen.getByRole("button", { name: /đánh dấu đã nhận giấy/i })
    ).toBeInTheDocument();
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
    expect(
      screen.queryByRole("button", { name: /đánh dấu đã nhận giấy/i })
    ).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /tải file/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /đặt lại/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /đánh dấu đã nhận giấy/i })
    ).not.toBeInTheDocument();
  });
});

describe("DocumentsTab — ADM-031 task-orientation", () => {
  it("missing + requires_upload row shows 'Cần tải ảnh/scan' hint and a Tải file button", () => {
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
    expect(screen.getByText(/cần tải ảnh\/scan/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /tải file/i })).toBeInTheDocument();
    // Paper hint must NOT appear for online docs.
    expect(screen.queryByText(/nhận bản giấy tại quầy/i)).not.toBeInTheDocument();
  });

  it("missing + paper-only row shows 'Nhận bản giấy tại quầy' hint and a Đánh dấu đã nhận giấy button", () => {
    const profile = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.getByText(/nhận bản giấy tại quầy/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /đánh dấu đã nhận giấy/i })
    ).toBeInTheDocument();
    // Online hint must NOT appear for paper-only docs.
    expect(screen.queryByText(/cần tải ảnh\/scan/i)).not.toBeInTheDocument();
  });

  it("non-missing rows do not surface either task hint", () => {
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        code: "HD_NH",
        label: "Hợp đồng",
        status: "paper_submitted",
        is_mandatory: false,
        requires_upload: false,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.queryByText(/cần tải ảnh\/scan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/nhận bản giấy tại quầy/i)).not.toBeInTheDocument();
  });
});

describe("DocumentsTab — ADM-031 progress and status labels", () => {
  it("splits header into ghi nhận / chờ kiểm tra / hoàn tất yêu cầu", () => {
    const profile = buildProfile([
      {
        // Online row: officer has not verified yet → counts as recorded
        // and pending, but NOT as satisfying the requirement.
        code: "A",
        label: "A",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        // Online row already verified → recorded + satisfied.
        code: "B",
        label: "B",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        // Paper-only row marked received → recorded + satisfied
        // (backend `paper_submitted` already completes the requirement).
        code: "P",
        label: "P",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
      },
      {
        code: "C",
        label: "C",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    // Recorded = uploaded + verified + paper_submitted = 3 of 4
    expect(screen.getByText(/đã ghi nhận 3\/4/i)).toBeInTheDocument();
    // Pending verification = uploaded only = 1
    expect(screen.getByText(/chờ kiểm tra 1/i)).toBeInTheDocument();
    // Satisfied = verified + paper_submitted = 2 of 4 (backend gate)
    expect(screen.getByText(/hoàn tất yêu cầu 2\/4/i)).toBeInTheDocument();
    // Progress reflects backend mandatory-completion semantics. 2 of 4
    // mandatory rows satisfy the requirement → 50%.
    const progressBar = screen.getByRole("progressbar", {
      name: /tiến độ hoàn tất tài liệu/i,
    });
    expect(progressBar).toHaveAttribute("aria-valuenow", "50");
  });

  it("uploaded status renders as 'Đã ghi nhận', verified as 'Đã kiểm tra'", () => {
    const profile = buildProfile([
      {
        code: "U",
        label: "Uploaded row",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        code: "V",
        label: "Verified row",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        code: "P",
        label: "Paper row",
        status: "paper_submitted",
        is_mandatory: false,
        requires_upload: false,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    // Header summary already mentions both phrases, so a row badge would
    // collide with the summary node. Match all and assert presence of at
    // least one badge per status — header renders these phrases too.
    expect(screen.getAllByText(/đã ghi nhận \(online\)/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/đã kiểm tra/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/đã nhận bản giấy/i).length).toBeGreaterThan(0);
  });
});

describe("DocumentsTab — ADM-031 format dialog", () => {
  it("opens with task-oriented title, required-format note, and centralized labels", async () => {
    const user = userEvent.setup();
    const profile = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: true,
        submission_format: "certified_copy",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);

    await user.click(
      screen.getByRole("button", { name: /đánh dấu đã nhận giấy/i })
    );

    const dialog = await screen.findByRole("dialog");
    // Task-oriented title — declaring the actual format, not uploading
    // additional evidence.
    expect(
      screen.getByRole("heading", { name: /loại bản thực tế trong file\/giấy này/i })
    ).toBeInTheDocument();
    // Required-format requirement is surfaced verbatim.
    expect(dialog).toHaveTextContent(/yêu cầu hồ sơ:/i);
    expect(dialog).toHaveTextContent(/bản sao chứng thực/i);
    // Centralized labels (admission-helpers) — old strings ("Bản chính",
    // "Bản photocopy", "Bản sao có chứng thực") must not appear.
    expect(dialog).toHaveTextContent(/bản gốc/i);
    expect(dialog).toHaveTextContent(/bản chụp\/scan không chứng thực/i);
    expect(dialog).not.toHaveTextContent(/bản chính/i);
    expect(dialog).not.toHaveTextContent(/^bản photocopy$/im);
  });

  it("shows a soft warning when the chosen actual format differs from the required format", async () => {
    const user = userEvent.setup();
    const profile = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: true,
        submission_format: "certified_copy",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);

    await user.click(
      screen.getByRole("button", { name: /đánh dấu đã nhận giấy/i })
    );

    // Default selectedFormat is the required format → warning hidden.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // Switch to a different actual format → warning surfaces.
    await user.click(screen.getByRole("radio", { name: /bản gốc/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/khác với yêu cầu hồ sơ/i);
  });
});
