/**
 * DocumentsTab — KPI strip + responsive table layout (ADM-031 round 5).
 *
 * Three concerns are exercised here:
 *
 * 1. Per-row permission flags from PR #5 (`can_upload`, `can_reject`,
 *    `can_reset`, `can_mark_paper_submitted`). Each action button must
 *    only render when the matching backend flag is true.
 *
 * 2. ADM-031 task-orientation. Missing rows surface a task-oriented
 *    hint and the action buttons carry explicit Vietnamese labels
 *    ("Tải file" / "Đánh dấu đã nhận giấy") instead of icon-only
 *    triggers. Format dialog wording was rewritten to clarify that
 *    the user is declaring the actual paper type, not uploading
 *    additional evidence.
 *
 * 3. ADM-031 round 5 layout. The card body now renders a KPI strip
 *    on top and a semantic table on the desktop (md+) breakpoint, so
 *    officers read the cohort state at a glance and the row actions
 *    have a stable column. Mobile <md still gets a stacked card.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DocumentsTab } from "./DocumentsTab";

vi.mock("@/hooks/admissions/useAdmissions", () => ({
  useUploadAdmissionDocument: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
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
  actual_submission_format?: string | null;
  verified_format?: string | null;
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

// =============================================================================
// PER-ROW PERMISSION FLAGS (PR #5)
// =============================================================================

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
    // Both desktop table + mobile card render in jsdom (no media-query
    // resolution); scope to the table so the duplicate doesn't clash.
    const table = screen.getByRole("table");
    expect(within(table).getByRole("button", { name: /tải file/i })).toBeInTheDocument();
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
    const allowed = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_reject: true,
      },
    ]);
    const { unmount } = render(<DocumentsTab profile={allowed as never} isEditable />);
    const allowedTable = screen.getByRole("table");
    expect(
      within(allowedTable).getByRole("button", { name: /từ chối/i }),
    ).toBeInTheDocument();
    unmount();

    const blocked = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_reject: false,
      },
    ]);
    render(<DocumentsTab profile={blocked as never} isEditable />);
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
  });

  it("shows Reset only when can_reset=true regardless of status", () => {
    const profile = buildProfile([
      {
        code: "BANG_TN",
        label: "Bằng tốt nghiệp",
        status: "rejected",
        is_mandatory: true,
        requires_upload: true,
        can_reset: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    // Reset button is icon-only; assert via aria-label inside the table
    // (mobile card duplicate would also match).
    const table = screen.getByRole("table");
    expect(
      within(table).getByRole("button", { name: /đặt lại tài liệu về chưa nộp/i }),
    ).toBeInTheDocument();
  });

  it("shows the paper-receipt button only when can_mark_paper_submitted=true", () => {
    const allowed = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: true,
      },
    ]);
    // Both desktop table and mobile <ul> render in jsdom; tailwind md: media
    // queries don't drop one layout, so the same button shows up twice.
    // Scope to the table so the assertion is unambiguous.
    const { unmount } = render(<DocumentsTab profile={allowed as never} isEditable />);
    const table = screen.getByRole("table");
    expect(
      within(table).getByRole("button", { name: /đánh dấu đã nhận giấy/i }),
    ).toBeInTheDocument();
    unmount();

    const blocked = buildProfile([
      {
        code: "HD_NH",
        label: "Hợp đồng ngân hàng",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: false,
      },
    ]);
    render(<DocumentsTab profile={blocked as never} isEditable />);
    expect(
      screen.queryByRole("button", { name: /đánh dấu đã nhận giấy/i }),
    ).not.toBeInTheDocument();
  });
});

// =============================================================================
// ADM-031 ROUND 5 — KPI STRIP
// =============================================================================

describe("DocumentsTab — ADM-031 round 5 KPI strip", () => {
  it("renders 4 KPI tiles with the expected counts", () => {
    const profile = buildProfile([
      // Online row already verified → recorded + satisfied.
      {
        code: "B",
        label: "Học bạ",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
      },
      // Online row officer has not verified yet → recorded + pending.
      {
        code: "A",
        label: "Ảnh 3x4",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
      // Paper-only row marked received → recorded + satisfied.
      {
        code: "P",
        label: "Phiếu cam kết",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
      },
      // Mandatory missing → action queue.
      {
        code: "C",
        label: "Bằng tốt nghiệp",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const kpi = screen.getByRole("group", { name: /tổng quan tài liệu/i });
    // Tổng tài liệu = 4
    expect(within(kpi).getByText(/^tổng tài liệu$/i)).toBeInTheDocument();
    expect(within(kpi).getByText("4")).toBeInTheDocument();
    // Đã ghi nhận = 3/4 (uploaded + verified + paper_submitted)
    expect(within(kpi).getByText(/^đã ghi nhận$/i)).toBeInTheDocument();
    expect(within(kpi).getByText("3/4")).toBeInTheDocument();
    // Chờ kiểm tra = 1 (uploaded only)
    expect(within(kpi).getByText(/^chờ kiểm tra$/i)).toBeInTheDocument();
    expect(within(kpi).getByText("1")).toBeInTheDocument();
    // Hoàn tất yêu cầu = 2/4 (verified + paper_submitted)
    expect(within(kpi).getByText(/^hoàn tất yêu cầu$/i)).toBeInTheDocument();
    expect(within(kpi).getByText("2/4")).toBeInTheDocument();
  });
});

// =============================================================================
// ADM-031 ROUND 5 — TABLE LAYOUT
// =============================================================================

describe("DocumentsTab — ADM-031 round 5 desktop table", () => {
  it("renders a semantic table with the 7-column header", () => {
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const headers = within(table).getAllByRole("columnheader");
    const headerLabels = headers.map((h) => h.textContent?.trim());
    expect(headerLabels).toEqual([
      "#",
      "Tên giấy tờ",
      "Yêu cầu",
      "Đã ghi nhận",
      "Cách ghi nhận",
      "Trạng thái",
      "Thao tác",
    ]);
  });

  it("sorts rows by work-queue priority: missing/rejected → uploaded/paper_submitted → verified", () => {
    const profile = buildProfile([
      // Intentionally out of order to verify sort.
      {
        code: "A",
        label: "Verified mandatory",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        code: "B",
        label: "Uploaded mandatory",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        code: "C",
        label: "Missing optional",
        status: "missing",
        is_mandatory: false,
        requires_upload: true,
      },
      {
        code: "D",
        label: "Missing mandatory",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1); // skip header
    const labels = rows.map((r) => within(r).getAllByRole("cell")[1]?.textContent);
    // Priority: missing(mandatory) → missing(optional) → uploaded → verified
    expect(labels[0]).toContain("Missing mandatory");
    expect(labels[1]).toContain("Missing optional");
    expect(labels[2]).toContain("Uploaded mandatory");
    expect(labels[3]).toContain("Verified mandatory");
  });
});

// =============================================================================
// ADM-031 ROUND 5 — RECEPTION + HOW-TO COLUMNS
// =============================================================================

describe("DocumentsTab — ADM-031 round 5 reception & how-to columns", () => {
  it("requires_upload=true row shows 'Tải file' how-to and 'File'/'Chưa' reception bucket", () => {
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
    const { container } = render(<DocumentsTab profile={profile as never} isEditable />);
    expect(container.textContent).toMatch(/Tải file/);
    // The row exposes the "Chưa" reception bucket for missing.
    const table = screen.getByRole("table");
    const cells = within(table).getAllByRole("cell");
    const receptionCell = cells[3]; // # | Tên | Yêu cầu | Đã ghi nhận | ...
    expect(receptionCell?.textContent).toMatch(/^Chưa/);
  });

  it("requires_upload=false row shows 'Nhận giấy tại quầy' how-to + 'Đánh dấu đã nhận giấy' button", () => {
    const profile = buildProfile([
      {
        code: "PHIEU",
        label: "Phiếu cam kết",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        can_mark_paper_submitted: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(within(table).getByText(/Nhận giấy tại quầy/)).toBeInTheDocument();
    expect(
      within(table).getByRole("button", { name: /đánh dấu đã nhận giấy/i }),
    ).toBeInTheDocument();
    // No upload-flow copy on a paper-only row.
    expect(within(table).queryByText(/^Tải file$/)).not.toBeInTheDocument();
  });
});

// =============================================================================
// ADM-031 ROUND 5 — NO LEGACY "ONLINE" COPY ANYWHERE
// =============================================================================

describe("DocumentsTab — ADM-031 round 5 deprecated copy guard", () => {
  it("does not render any 'online' copy for any document state", () => {
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "photo",
        actual_submission_format: "photo",
      },
      {
        code: "HD",
        label: "Hợp đồng",
        status: "paper_submitted",
        is_mandatory: false,
        requires_upload: false,
        submission_format: "certified_copy",
        actual_submission_format: "certified_copy",
      },
      {
        code: "BANG_TN",
        label: "Bằng tốt nghiệp",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "certified_copy",
        verified_format: "certified_copy",
        actual_submission_format: "certified_copy",
      },
    ]);
    const { container } = render(<DocumentsTab profile={profile as never} isEditable />);
    // Forbidden legacy copy.
    expect(container.textContent).not.toMatch(/\bonline\b/i);
    expect(container.textContent).not.toMatch(/\bnộp giấy\b/i);
    expect(container.textContent).not.toMatch(/\(online\)/i);
    expect(container.textContent).not.toMatch(/Bản photocopy/);
    expect(container.textContent).not.toMatch(/Bản photo\/scan/);
    expect(container.textContent).not.toMatch(/Ảnh chụp hoặc scan/);
    // Required new copy.
    expect(container.textContent).toMatch(/Tải file/);
    expect(container.textContent).toMatch(/Bản chụp\/scan không chứng thực/);
  });
});

// =============================================================================
// ADM-031 ROUND 5 — RECORDED FORMAT (round 4 carryover)
// =============================================================================

describe("DocumentsTab — ADM-031 recorded format display", () => {
  it("shows actual_submission_format on uploaded rows", () => {
    const profile = buildProfile([
      {
        code: "anh_3x4",
        label: "Ảnh 3x4",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "certified_copy",
        actual_submission_format: "photo",
      },
    ]);
    const { container } = render(<DocumentsTab profile={profile as never} isEditable />);
    // Required + recorded both visible.
    expect(container.textContent).toMatch(/Bản sao chứng thực/);
    expect(container.textContent).toMatch(/Bản chụp\/scan không chứng thực/);
  });

  it("shows verified_format on verified rows", () => {
    const profile = buildProfile([
      {
        code: "hoc_ba_thpt",
        label: "Học bạ THPT",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "certified_copy",
        actual_submission_format: "certified_copy",
        verified_format: "certified_copy",
      },
    ]);
    const { container } = render(<DocumentsTab profile={profile as never} isEditable />);
    // Reception bucket reads "File" + the format detail.
    expect(container.textContent).toMatch(/File/);
    expect(container.textContent).toMatch(/Bản sao chứng thực/);
  });
});

// =============================================================================
// ADM-031 ROUND 2 — PAPER DIALOG
// =============================================================================

describe("DocumentsTab — ADM-031 paper-receipt dialog", () => {
  it("opens with paper-specific title, prompt, primary button, and centralized labels", async () => {
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

    const table = screen.getByRole("table");
    await user.click(
      within(table).getByRole("button", { name: /đánh dấu đã nhận giấy/i }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(
      screen.getByRole("heading", { name: /xác nhận bản giấy vừa nhận/i }),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/bản giấy vừa nhận là bản gì\?/i);
    expect(dialog).toHaveTextContent(/yêu cầu hồ sơ:/i);
    expect(dialog).toHaveTextContent(/bản sao chứng thực/i);
    expect(dialog).toHaveTextContent(/bản gốc/i);
    expect(dialog).toHaveTextContent(/bản chụp\/scan không chứng thực/i);
    expect(dialog).not.toHaveTextContent(/bản chính/i);
    expect(screen.getByRole("button", { name: /^ghi nhận giấy$/i })).toBeInTheDocument();
  });

  it("shows paper-specific soft warning when actual ≠ required", async () => {
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
    const table = screen.getByRole("table");
    await user.click(
      within(table).getByRole("button", { name: /đánh dấu đã nhận giấy/i }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /bản gốc/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/bản giấy thực tế khác yêu cầu hồ sơ/i);
    expect(alert).toHaveTextContent(/trước khi ghi nhận/i);
  });
});

// =============================================================================
// ADM-031 ROUND 2 — UPLOAD DIALOG
// =============================================================================

describe("DocumentsTab — ADM-031 upload dialog", () => {
  it("opens with upload-specific title after a file is selected", async () => {
    const user = userEvent.setup();
    const profile = buildProfile([
      {
        code: "CCCD",
        label: "Căn cước công dân",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        can_upload: true,
        submission_format: "photo",
      },
    ]);
    const { container } = render(<DocumentsTab profile={profile as never} isEditable />);

    // Click the row's "Tải file" button to arm the hidden file input,
    // then fire the change with a fake file. Scope to the table so the
    // duplicate mobile-card button doesn't clash.
    const table = screen.getByRole("table");
    await user.click(within(table).getByRole("button", { name: /^tải file$/i }));
    const fileInput = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    const file = new File(["dummy"], "ccd.pdf", { type: "application/pdf" });
    await user.upload(fileInput, file);

    const dialog = await screen.findByRole("dialog");
    expect(
      screen.getByRole("heading", { name: /^tải file tài liệu$/i }),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/file này là bản gì\?/i);
    expect(within(dialog).getByRole("button", { name: /^tải file$/i })).toBeInTheDocument();
  });
});
