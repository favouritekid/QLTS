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
  useVerifyDocument: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
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
    // File chờ duyệt = 1 (uploaded only) — round 9 rename.
    expect(within(kpi).getByText(/^file chờ duyệt$/i)).toBeInTheDocument();
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
  it("renders a semantic table with the round-7 6-column header (Cách ghi nhận merged into Yêu cầu)", () => {
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
      "Tên giấy tờ",
      "Yêu cầu",
      "Đã ghi nhận",
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
    // Title cell is now index 0 (the "#" column was removed in round 7).
    const labels = rows.map((r) => within(r).getAllByRole("cell")[0]?.textContent);
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
    // Round 7 dropped the "#" column → cells are
    // Tên | Yêu cầu | Đã ghi nhận | Trạng thái | Thao tác (index 2 = reception).
    const table = screen.getByRole("table");
    const cells = within(table).getAllByRole("cell");
    const receptionCell = cells[2];
    expect(receptionCell?.textContent).toMatch(/Chưa/);
  });

  it("requires_upload=false row shows 'Nhận giấy' how-to + icon button with 'Đánh dấu đã nhận giấy' aria-label", () => {
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
    // Short verb in the table cell — the long "Nhận giấy tại quầy" was
    // dropped in round 6 to match the screenshot. Tooltip still keeps
    // the long copy.
    expect(within(table).getByText(/^Nhận giấy$/)).toBeInTheDocument();
    expect(
      within(table).queryByText(/Nhận giấy tại quầy/i),
    ).not.toBeInTheDocument();
    // Round 8: action buttons are icon-only with Radix Tooltip — aria-label
    // is the accessible name, no visible label text.
    const paperButton = within(table).getByRole("button", {
      name: /đánh dấu đã nhận giấy/i,
    });
    expect(paperButton).toHaveAccessibleName(/đánh dấu đã nhận giấy/i);
  });
});

// =============================================================================
// ADM-031 ROUND 7 — "YÊU CẦU" CELL ABSORBS "CÁCH GHI NHẬN"
// =============================================================================

describe("DocumentsTab — ADM-031 round 8 cells layout", () => {
  it("Tên cell shows 'Bắt buộc' on line 2 (mandatory marker moved out of name and Yêu cầu cell)", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "certified_copy",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    // Cells: Tên | Yêu cầu | Đã ghi nhận | Trạng thái | Thao tác
    const cells = within(table).getAllByRole("cell");
    const tenCell = cells[0];
    const yeuCauCell = cells[1];
    expect(tenCell.textContent).toMatch(/Học bạ/);
    expect(tenCell.textContent).toMatch(/Bắt buộc/);
    // "Mã: ..." no longer visible in Tên cell (moved to title attribute).
    expect(tenCell.textContent).not.toMatch(/Mã:/);
    // Yêu cầu cell only carries format + how-to (Bắt buộc/Tùy chọn moved
    // to Tên cell in round 8).
    expect(yeuCauCell.textContent).not.toMatch(/Bắt buộc/);
    expect(yeuCauCell.textContent).toMatch(/Chứng thực/);
    expect(yeuCauCell.textContent).toMatch(/Tải file/);
  });

  it("requires_upload=false row puts 'Gốc' + 'Nhận giấy' in Yêu cầu cell", () => {
    const profile = buildProfile([
      {
        code: "PHIEU",
        label: "Phiếu cam kết",
        status: "missing",
        is_mandatory: true,
        requires_upload: false,
        submission_format: "original",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const cells = within(table).getAllByRole("cell");
    const yeuCauCell = cells[1];
    expect(yeuCauCell.textContent).toMatch(/Gốc/);
    expect(yeuCauCell.textContent).toMatch(/Nhận giấy/);
  });
});

// =============================================================================
// ADM-031 ROUND 7 — VERIFY BUTTON
// =============================================================================

describe("DocumentsTab — ADM-031 round 7 verify button", () => {
  it("renders 'Duyệt' button when can_verify=true", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        actual_submission_format: "certified_copy",
        can_verify: true,
      } as never,
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(
      within(table).getByRole("button", { name: /duyệt tài liệu/i }),
    ).toBeInTheDocument();
  });

  it("hides 'Duyệt' when can_verify=false", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_verify: false,
      } as never,
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(
      screen.queryByRole("button", { name: /duyệt tài liệu/i }),
    ).not.toBeInTheDocument();
  });
});

// =============================================================================
// ADM-031 ROUND 7 — paper_submitted_at DATE IN RECEPTION CELL
// =============================================================================

describe("DocumentsTab — ADM-031 round 7 paper_submitted_at", () => {
  it("paper_submitted row renders the paper_submitted_at date in the reception cell", () => {
    const profile = buildProfile([
      {
        code: "PHIEU",
        label: "Phiếu cam kết",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
        actual_submission_format: "original",
        paper_submitted_at: "2026-04-28T10:30:00+00:00",
      } as never,
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const cells = within(table).getAllByRole("cell");
    // Reception cell at index 2 — contains: actual format short ("Gốc")
    // + date + reception bucket ("Bản giấy").
    const receptionCell = cells[2];
    expect(receptionCell.textContent).toMatch(/Bản giấy/);
    expect(receptionCell.textContent).toMatch(/28\/04\/2026/);
  });

  it("uploaded row renders the uploaded_at date in the reception cell, not paper_submitted_at", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        actual_submission_format: "certified_copy",
        uploaded_at: "2026-03-15T08:00:00+00:00",
      } as never,
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const cells = within(table).getAllByRole("cell");
    const receptionCell = cells[2];
    expect(receptionCell.textContent).toMatch(/File scan/);
    expect(receptionCell.textContent).toMatch(/15\/03\/2026/);
  });
});

// =============================================================================
// ADM-031 ROUND 6 — STATUS WORKFLOW LABELS
// =============================================================================

describe("DocumentsTab — ADM-031 round 6 status workflow labels", () => {
  it("missing row shows 'Cần làm' status + 'Chưa' reception", () => {
    const profile = buildProfile([
      {
        code: "C",
        label: "Bằng",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(within(table).getByText(/^Cần làm$/)).toBeInTheDocument();
    expect(within(table).getByText(/^Chưa$/)).toBeInTheDocument();
    // Old workflow copy must not leak.
    expect(within(table).queryByText(/^Chưa nộp$/)).not.toBeInTheDocument();
  });

  it("uploaded row shows 'Chờ duyệt' status + 'File scan' reception", () => {
    const profile = buildProfile([
      {
        code: "U",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(within(table).getByText(/^Chờ duyệt$/)).toBeInTheDocument();
    expect(within(table).getByText(/^File scan$/)).toBeInTheDocument();
    expect(within(table).queryByText(/Đã ghi nhận file/)).not.toBeInTheDocument();
  });

  it("paper_submitted row shows 'Đã nhận giấy' status (round 9 — backend counts as satisfied) + 'Bản giấy' reception", () => {
    const profile = buildProfile([
      {
        code: "P",
        label: "Phiếu",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    // Round 9: paper_submitted is "Đã nhận giấy" (success-tinted) so the
    // row matches the KPI semantics — backend already treats it as
    // satisfying the mandatory-doc gate, so it is NOT "Chờ duyệt".
    expect(within(table).getByText(/^Đã nhận giấy$/)).toBeInTheDocument();
    expect(within(table).getByText(/^Bản giấy$/)).toBeInTheDocument();
    // Long-form legacy copy must not leak.
    expect(within(table).queryByText(/Đã nhận bản giấy/)).not.toBeInTheDocument();
  });

  it("verified row shows 'Đã duyệt' status + 'File scan' reception", () => {
    const profile = buildProfile([
      {
        code: "V",
        label: "Học bạ",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(within(table).getByText(/^Đã duyệt$/)).toBeInTheDocument();
    expect(within(table).getByText(/^File scan$/)).toBeInTheDocument();
    expect(within(table).queryByText(/^Đã kiểm tra$/)).not.toBeInTheDocument();
  });

  it("rejected row shows 'Từ chối' status + 'Chưa' reception", () => {
    const profile = buildProfile([
      {
        code: "R",
        label: "Bằng",
        status: "rejected",
        is_mandatory: true,
        requires_upload: true,
        rejection_reason: "Mờ",
      } as never,
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(within(table).getByText(/^Từ chối$/)).toBeInTheDocument();
    expect(within(table).getByText(/^Chưa$/)).toBeInTheDocument();
    expect(within(table).queryByText(/^Không hợp lệ$/)).not.toBeInTheDocument();
  });
});

// =============================================================================
// ADM-031 ROUND 6 — SHORT FORMAT LABELS IN TABLE
// =============================================================================

describe("DocumentsTab — ADM-031 round 6 short format labels", () => {
  it("table renders short format labels (Gốc / Chứng thực / Chụp/scan)", () => {
    const profile = buildProfile([
      {
        code: "A",
        label: "Bằng",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "original",
      },
      {
        code: "B",
        label: "Học bạ",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "certified_copy",
      },
      {
        code: "C",
        label: "Ảnh",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "photo",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    expect(within(table).getByText(/^Gốc$/)).toBeInTheDocument();
    expect(within(table).getByText(/^Chứng thực$/)).toBeInTheDocument();
    expect(within(table).getByText(/^Chụp\/scan$/)).toBeInTheDocument();
  });

  it("full format label still appears in tooltip / aria-label", () => {
    const profile = buildProfile([
      {
        code: "C",
        label: "Ảnh",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "photo",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    // The cell wrapping the short label carries the full string in
    // aria-label / title so screen readers still get the long form.
    const fullLabel = within(table).getByLabelText(
      /Bản chụp\/scan không chứng thực/i,
    );
    expect(fullLabel).toBeInTheDocument();
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
    // Forbidden by user spec for round 8.
    expect(container.textContent).not.toMatch(/chứng cứ|evidence/i);
    // Required new copy — short labels in body, full label in title attr.
    expect(container.textContent).toMatch(/Tải file/);
    // Full label still reachable via title attribute on the format span.
    const fullLabelEls = container.querySelectorAll(
      '[title*="Bản chụp/scan không chứng thực"]',
    );
    expect(fullLabelEls.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// ADM-031 ROUND 5 — RECORDED FORMAT (round 4 carryover)
// =============================================================================

describe("DocumentsTab — ADM-031 recorded format display", () => {
  it("shows actual_submission_format on uploaded rows (short label visible, full label in title)", () => {
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
    // Both required ("Chứng thực") and recorded ("Chụp/scan") short
    // labels are visible.
    expect(container.textContent).toMatch(/Chứng thực/);
    expect(container.textContent).toMatch(/Chụp\/scan/);
    // Full label reachable via title attr (e.g., aria-label on format span).
    expect(
      container.querySelector('[aria-label="Bản sao chứng thực"]'),
    ).toBeInTheDocument();
  });

  it("shows verified_format on verified rows (reception bucket = 'File scan')", () => {
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
    // Reception bucket reads "File scan" + the format short label.
    expect(container.textContent).toMatch(/File scan/);
    expect(container.textContent).toMatch(/Chứng thực/);
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
