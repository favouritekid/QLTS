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
import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import { within, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";

import { DocumentsTab } from "./DocumentsTab";

// Mock MỘT PHẦN: giữ `admissionsKeys` thật (hook GĐ1b làm mới cache theo khoá ấy); chỉ thay ba hook nhận giấy.
// Duyệt / Từ chối / Đặt lại / Lịch sử GĐ1b đi qua axios THẬT + MSW (`@/test/mocks/server`).
vi.mock("@/hooks/admissions/useAdmissions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/admissions/useAdmissions")>()),
  useUploadAdmissionDocument: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useMarkPaperSubmitted: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useUpdateGraduationProof: () => ({ mutate: vi.fn(), isPending: false }),
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
  // GĐ1b (hợp đồng bản 5 B1) — buildProfile điền mặc định; ca kiểm đè khi cần
  can_verify?: boolean;
  can_view_history?: boolean;
  document_row_id?: number | null;
  row_version?: number | null;
  verify_block_reason?: string | null;
  requires_ack?: boolean;
  reset_requires_reason?: boolean;
  reset_keeps_evidence?: boolean;
  is_extra?: boolean;
  submission_format?: string | null;
  actual_submission_format?: string | null;
  verified_format?: string | null;
  document_id?: number | null;
  file_path?: string | null;
  uploaded_at?: string | null;
  paper_submitted_at?: string | null;
  verified_at?: string | null;
  verified_by?: number | null;
  verified_by_name?: string | null;
};

function buildProfile(docs: DocRow[]) {
  // Minimal profile shape — only the fields DocumentsTab reads. Cast to
  // AdmissionProfileResponse at the call site to keep the helper tight.
  return {
    id: 1,
    status: "draft",
    // GĐ1b bản 5 B1: khoá định danh + cờ LUÔN có trong phản hồi hồ sơ ⇒ mặc định "có dòng, mọi cờ tắt".
    documents_checklist: docs.map((d, i) => ({
      document_row_id: i + 1,
      row_version: 1,
      can_verify: false,
      can_reject: false,
      can_reset: false,
      can_view_history: false,
      verify_block_reason: null,
      requires_ack: false,
      reset_requires_reason: false,
      reset_keeps_evidence: false,
      ...d,
    })),
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
      within(table).getByRole("button", { name: /^đặt lại giấy bằng tốt nghiệp$/i }),
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
// PR2 — AUTHED DOCUMENT DOWNLOAD (View button)
// =============================================================================

describe("DocumentsTab — PR2 authed document download", () => {
  it("View button opens the authed download endpoint when document_id present", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        document_id: 99,
        file_path: "uploads/profile_1/hocba.pdf",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    fireEvent.click(
      within(table).getByRole("button", { name: /xem tài liệu/i }),
    );
    expect(openSpy).toHaveBeenCalledTimes(1);
    const url = String(openSpy.mock.calls[0][0]);
    // profile.id = 1 (buildProfile), document_id = 99.
    expect(url).toContain("/api/admissions/1/documents/99/download");
    expect(url).not.toContain("/uploads");
    openSpy.mockRestore();
  });

  it("hides the View button when document_id is null even if file_path present (stale/rollback)", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        document_id: null,
        file_path: "uploads/profile_1/hocba.pdf",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(
      screen.queryByRole("button", { name: /xem tài liệu/i }),
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

  it("sorts rows by work-queue priority: missing/rejected → uploaded → verified", () => {
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

  it("paper_submitted sorts with verified (round 10 D1: both are 'satisfied')", () => {
    // Round 9 made paper_submitted satisfy the mandatory gate; round 10
    // sorts it into bucket 3 alongside verified so the work queue isn't
    // interrupted by a "done" row labelled "Đã nhận giấy".
    const profile = buildProfile([
      {
        code: "P",
        label: "Paper submitted",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
      },
      {
        code: "U",
        label: "Uploaded online",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
      },
      {
        code: "M",
        label: "Missing mandatory",
        status: "missing",
        is_mandatory: true,
        requires_upload: true,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    const labels = rows.map((r) => within(r).getAllByRole("cell")[0]?.textContent);
    expect(labels[0]).toContain("Missing mandatory"); // priority 1
    expect(labels[1]).toContain("Uploaded online");   // priority 2
    expect(labels[2]).toContain("Paper submitted");   // priority 3 (with verified)
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
      within(table).getByRole("button", { name: /^duyệt giấy học bạ$/i }),
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
      screen.queryByRole("button", { name: /duyệt giấy/i }),
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

  it("paper-only verified row preserves paper_submitted_at as the recorded date (round 10 E1)", () => {
    // Paper docs (requires_upload=false) have no uploaded_at; once the
    // manager flips them to verified, the FE must keep showing the
    // paper-receipt date instead of falling back to a null uploaded_at.
    const profile = buildProfile([
      {
        code: "GIAY",
        label: "Bản giấy đã duyệt",
        status: "verified",
        is_mandatory: true,
        requires_upload: false,
        actual_submission_format: "original",
        verified_format: "original",
        paper_submitted_at: "2026-04-22T09:15:00+00:00",
        // uploaded_at intentionally absent to mirror real paper docs.
        verified_at: "2026-04-25T11:00:00+00:00",
        verified_by: 7,
        verified_by_name: "Nguyễn Văn A",
      } as never,
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    const cells = within(table).getAllByRole("cell");
    const receptionCell = cells[2];
    // Paper-receipt date (22/04) must still render even though status is now verified.
    expect(receptionCell.textContent).toMatch(/22\/04\/2026/);
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

// =============================================================================
// ADM-031 ROUND 10 — VERIFIER IDENTITY (who verified + when)
// =============================================================================

describe("DocumentsTab — ADM-031 round 10 verifier identity", () => {
  it("renders verifier name + short date below the 'Đã duyệt' badge", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        submission_format: "certified_copy",
        verified_format: "certified_copy",
        verified_at: "2026-04-29T08:30:00+00:00",
        verified_by: 7,
        verified_by_name: "Nguyễn Văn A",
      },
    ]);
    const { container } = render(
      <DocumentsTab profile={profile as never} isEditable />,
    );
    // Name appears at least once (desktop + mobile) alongside the dd/mm/yyyy date.
    expect(container.textContent).toMatch(/Nguyễn Văn A/);
    expect(container.textContent).toMatch(/29\/04\/2026/);
  });

  it("falls back to 'User #<id>' when verified_by_name is null but id is present", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        verified_at: "2026-04-29T08:30:00+00:00",
        verified_by: 42,
        verified_by_name: null,
      },
    ]);
    const { container } = render(
      <DocumentsTab profile={profile as never} isEditable />,
    );
    expect(container.textContent).toMatch(/User #42/);
  });

  it("shows only the date when neither verified_by_name nor verified_by is set", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "verified",
        is_mandatory: true,
        requires_upload: true,
        verified_at: "2026-04-29T08:30:00+00:00",
        verified_by: null,
        verified_by_name: null,
      },
    ]);
    const { container } = render(
      <DocumentsTab profile={profile as never} isEditable />,
    );
    expect(container.textContent).toMatch(/29\/04\/2026/);
    expect(container.textContent).not.toMatch(/User #/);
  });

  it("does NOT render a verifier line for non-verified statuses (e.g. uploaded)", () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ THPT",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        // Stale verifier columns from a prior cycle should be ignored as
        // long as status !== verified — only the latest workflow state
        // drives the secondary line.
        verified_at: "2026-04-20T08:30:00+00:00",
        verified_by: 7,
        verified_by_name: "Nguyễn Văn A",
      },
    ]);
    const { container } = render(
      <DocumentsTab profile={profile as never} isEditable />,
    );
    // The "Đã ghi nhận" cell renders the date next to format with a leading
    // bullet ("Chứng thực · 20/04/2026") — but that's not the verifier line
    // and the name should NOT appear anywhere when status is not verified.
    expect(container.textContent).not.toMatch(/Nguyễn Văn A/);
  });
});

// =============================================================================
// Q9 #07 PHASE E.4 PR-3 — ELIGIBILITY SUMMARY FOOTER (spec V3 §III)
// =============================================================================

function buildProfileWithPriority(
  docs: DocRow[],
  priorityDocs: Array<{
    sub_code: string;
    label: string;
    bonus_points: number;
    document_id: number | null;
    document_file_path: string | null;
    status: "missing" | "uploaded" | "verified" | "rejected";
    verification_status: "pending" | "verified" | "rejected" | null;
  }>,
) {
  const base = buildProfile(docs) as Record<string, unknown>;
  base.priority_evidence_documents = priorityDocs;
  return base;
}

describe("DocumentsTab — Phase E.4 eligibility summary footer", () => {
  it("hides footer entirely when no mandatory docs and no priority docs", () => {
    const profile = buildProfileWithPriority(
      [
        {
          code: "OPT_ONE",
          label: "Tài liệu tuỳ chọn",
          status: "missing",
          is_mandatory: false,
          requires_upload: true,
        },
      ],
      [],
    );
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(
      screen.queryByTestId("documents-tab-eligibility-summary"),
    ).not.toBeInTheDocument();
  });

  it("shows Bắt buộc line with 'cần X nữa' remainder when some mandatory docs unverified", () => {
    const profile = buildProfileWithPriority(
      [
        {
          code: "HOC_BA",
          label: "Học bạ THPT",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "CCCD",
          label: "CCCD",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "BANG_TN",
          label: "Bằng tốt nghiệp",
          status: "uploaded",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "ANH_3X4",
          label: "Ảnh 3x4",
          status: "missing",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "KHAM_SK",
          label: "Khám sức khoẻ",
          status: "missing",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      [],
    );
    render(<DocumentsTab profile={profile as never} isEditable />);
    const summary = screen.getByTestId("eligibility-summary-mandatory");
    expect(summary).toHaveTextContent(/Bắt buộc:\s*2\/5 đã duyệt/);
    expect(summary).toHaveTextContent(/cần 3 nữa/);
  });

  it("Bắt buộc line drops 'cần X nữa' when all mandatory docs verified", () => {
    const profile = buildProfileWithPriority(
      [
        {
          code: "HOC_BA",
          label: "Học bạ THPT",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "CCCD",
          label: "CCCD",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      [],
    );
    render(<DocumentsTab profile={profile as never} isEditable />);
    const summary = screen.getByTestId("eligibility-summary-mandatory");
    expect(summary).toHaveTextContent(/Bắt buộc:\s*2\/2 đã duyệt/);
    expect(summary.textContent).not.toMatch(/cần/);
  });

  it("paper_submitted does NOT count toward verified (strict semantic per spec)", () => {
    const profile = buildProfileWithPriority(
      [
        {
          code: "BANG_TN",
          label: "Bằng tốt nghiệp",
          status: "paper_submitted",
          is_mandatory: true,
          requires_upload: false,
        },
        {
          code: "HOC_BA",
          label: "Học bạ",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      [],
    );
    render(<DocumentsTab profile={profile as never} isEditable />);
    const summary = screen.getByTestId("eligibility-summary-mandatory");
    // paper_submitted is "satisfied" but NOT "verified" — spec text is strict.
    expect(summary).toHaveTextContent(/1\/2 đã duyệt/);
    expect(summary).toHaveTextContent(/cần 1 nữa/);
  });

  it("Ưu tiên line shows missing UT codes for priority docs without file", () => {
    const profile = buildProfileWithPriority([], [
      {
        sub_code: "04",
        label: "Giấy chứng nhận con thương binh",
        bonus_points: 1.0,
        document_id: 99,
        document_file_path: "uploads/profile_1/ut04.pdf",
        status: "verified",
        verification_status: "verified",
      },
      {
        sub_code: "07",
        label: "Giấy chứng nhận hộ nghèo",
        bonus_points: 0.5,
        document_id: null,
        document_file_path: null,
        status: "missing",
        verification_status: null,
      },
      {
        sub_code: "08",
        label: "Giấy xác nhận chất độc",
        bonus_points: 0.5,
        document_id: null,
        document_file_path: null,
        status: "missing",
        verification_status: null,
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const summary = screen.getByTestId("eligibility-summary-priority");
    expect(summary).toHaveTextContent(/Ưu tiên:\s*1\/3 đã tải lên/);
    expect(summary).toHaveTextContent(/UT07, UT08 thiếu minh chứng/);
  });

  it("Ưu tiên line drops missing-codes suffix when all priority docs uploaded", () => {
    const profile = buildProfileWithPriority([], [
      {
        sub_code: "04",
        label: "Giấy chứng nhận con thương binh",
        bonus_points: 1.0,
        document_id: 99,
        document_file_path: "uploads/profile_1/ut04.pdf",
        status: "verified",
        verification_status: "verified",
      },
      {
        sub_code: "07",
        label: "Giấy chứng nhận hộ nghèo",
        bonus_points: 0.5,
        document_id: 100,
        document_file_path: "uploads/profile_1/ut07.pdf",
        status: "uploaded",
        verification_status: "pending",
      },
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const summary = screen.getByTestId("eligibility-summary-priority");
    expect(summary).toHaveTextContent(/Ưu tiên:\s*2\/2 đã tải lên/);
    expect(summary.textContent).not.toMatch(/thiếu minh chứng/);
  });

  it("renders both lines together when profile has both mandatory + priority docs", () => {
    const profile = buildProfileWithPriority(
      [
        {
          code: "HOC_BA",
          label: "Học bạ",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "CCCD",
          label: "CCCD",
          status: "uploaded",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      [
        {
          sub_code: "08",
          label: "Giấy xác nhận chất độc",
          bonus_points: 0.5,
          document_id: null,
          document_file_path: null,
          status: "missing",
          verification_status: null,
        },
      ],
    );
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(
      screen.getByTestId("eligibility-summary-mandatory"),
    ).toHaveTextContent(/1\/2 đã duyệt.*cần 1 nữa/);
    expect(
      screen.getByTestId("eligibility-summary-priority"),
    ).toHaveTextContent(/0\/1 đã tải lên.*UT08 thiếu/);
  });
});

// =============================================================================
// FAST-TRACK NỢ GIẤY TỜ — "Nợ giấy tờ" BANNER (TUITION_PREPAY_FASTTRACK_PLAN.md §4b ③)
// =============================================================================

/** buildProfile + the fast-track debt fields the banner reads. */
function buildProfileWithDebt(opts: {
  docs: DocRow[];
  outstanding_debt_codes?: string[];
  missing_doc_codes?: string[];
  document_debt?: {
    codes: string[];
    reason: string;
    by_user_id: number;
    at: string;
  } | null;
}) {
  const base = buildProfile(opts.docs) as Record<string, unknown>;
  base.outstanding_debt_codes = opts.outstanding_debt_codes ?? [];
  base.missing_doc_codes = opts.missing_doc_codes ?? [];
  base.document_debt = opts.document_debt ?? null;
  return base;
}

describe("DocumentsTab — fast-track nợ giấy tờ banner", () => {
  it("hides the banner when outstanding_debt_codes is empty", () => {
    const profile = buildProfileWithDebt({
      docs: [
        {
          code: "hoc_ba_thpt",
          label: "Học bạ THPT",
          status: "verified",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      outstanding_debt_codes: [],
      document_debt: {
        codes: ["hoc_ba_thpt"],
        reason: "đã bổ sung",
        by_user_id: 7,
        at: "2026-06-16T03:00:00+00:00",
      },
    });
    render(<DocumentsTab profile={profile as never} isEditable />);
    expect(screen.queryByText(/Nợ giấy tờ/)).not.toBeInTheDocument();
  });

  it("renders the banner with count + owed-doc labels + reason/when when outstanding", () => {
    const profile = buildProfileWithDebt({
      docs: [
        {
          code: "hoc_ba_thpt",
          label: "Học bạ THPT",
          status: "missing",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "cccd",
          label: "CCCD bản sao",
          status: "uploaded",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      outstanding_debt_codes: ["hoc_ba_thpt", "cccd"],
      missing_doc_codes: ["hoc_ba_thpt"],
      document_debt: {
        codes: ["hoc_ba_thpt", "cccd"],
        reason: "HS xin cấp lại học bạ, hẹn 30/06",
        by_user_id: 7,
        at: "2026-06-16T03:00:00+00:00",
      },
    });
    render(<DocumentsTab profile={profile as never} isEditable />);
    const banner = screen.getByRole("status");
    expect(within(banner).getByText("Nợ giấy tờ (2)")).toBeInTheDocument();
    expect(within(banner).getByText("Học bạ THPT")).toBeInTheDocument();
    expect(within(banner).getByText("CCCD bản sao")).toBeInTheDocument();
    expect(within(banner).getByText(/HS xin cấp lại học bạ/)).toBeInTheDocument();
  });

  it("L5: labels a still-missing code 'Chưa nộp' and an uploaded-pending code 'Chờ xác minh'", () => {
    const profile = buildProfileWithDebt({
      docs: [
        {
          code: "hoc_ba_thpt",
          label: "Học bạ THPT",
          status: "missing",
          is_mandatory: true,
          requires_upload: true,
        },
        {
          code: "cccd",
          label: "CCCD bản sao",
          status: "uploaded",
          is_mandatory: true,
          requires_upload: true,
        },
      ],
      // Both still owed (verified-based); only hoc_ba is still fully missing.
      outstanding_debt_codes: ["hoc_ba_thpt", "cccd"],
      missing_doc_codes: ["hoc_ba_thpt"],
      document_debt: {
        codes: ["hoc_ba_thpt", "cccd"],
        reason: "cho nợ",
        by_user_id: 7,
        at: "2026-06-16T03:00:00+00:00",
      },
    });
    render(<DocumentsTab profile={profile as never} isEditable />);
    const banner = screen.getByRole("status");
    // hoc_ba_thpt ∈ missing_doc_codes → "Chưa nộp".
    expect(within(banner).getByText("Chưa nộp")).toBeInTheDocument();
    // cccd ∈ outstanding but NOT missing (uploaded, awaiting verify) → "Chờ xác minh".
    expect(within(banner).getByText("Chờ xác minh")).toBeInTheDocument();
  });

  it("falls back to the raw code when documents_checklist has no matching label", () => {
    const profile = buildProfileWithDebt({
      docs: [],
      outstanding_debt_codes: ["mystery_doc"],
      missing_doc_codes: ["mystery_doc"],
      document_debt: {
        codes: ["mystery_doc"],
        reason: "cho nợ",
        by_user_id: 7,
        at: "2026-06-16T03:00:00+00:00",
      },
    });
    render(<DocumentsTab profile={profile as never} isEditable />);
    const banner = screen.getByRole("status");
    expect(within(banner).getByText("mystery_doc")).toBeInTheDocument();
  });
});

// =============================================================================
// GĐ1b — nối nút lẻ (hợp đồng bản 4 §2.4 + bản 5; biên bản V4 §3)
// =============================================================================

describe("DocumentsTab — GĐ1b nút lẻ theo cờ máy chủ", () => {
  const API = "http://localhost:8000";
  afterEach(() => server.resetHandlers());

  function giayDuyet(over: Partial<DocRow> = {}): DocRow {
    return {
      code: "HOC_BA",
      label: "Học bạ",
      status: "paper_submitted",
      is_mandatory: true,
      requires_upload: false,
      actual_submission_format: "certified_copy",
      document_row_id: 31,
      row_version: 7,
      ...over,
    };
  }

  it("aria-label các nút GĐ1b mang TÊN giấy (hai giấy ⇒ phân biệt được)", () => {
    const profile = buildProfile([
      giayDuyet({ can_verify: true, can_reject: true, can_reset: true, can_view_history: true }),
      giayDuyet({
        code: "CCCD",
        label: "Căn cước",
        document_row_id: 32,
        can_verify: true,
        can_reject: true,
        can_reset: true,
        can_view_history: true,
      }),
    ]);
    render(<DocumentsTab profile={profile as never} isEditable />);
    const table = screen.getByRole("table");
    for (const ten of ["Học bạ", "Căn cước"]) {
      for (const nut of ["Duyệt giấy", "Từ chối giấy", "Đặt lại giấy", "Lịch sử giấy"]) {
        expect(within(table).getByRole("button", { name: `${nut} ${ten}` })).toBeInTheDocument();
      }
    }
  });

  it("mọi cờ GĐ1b tắt ⇒ không nút Duyệt / Từ chối / Đặt lại / Lịch sử", () => {
    render(<DocumentsTab profile={buildProfile([giayDuyet()]) as never} isEditable />);
    const table = screen.getByRole("table");
    expect(
      within(table).queryByRole("button", { name: /duyệt giấy|từ chối giấy|đặt lại giấy|lịch sử giấy/i }),
    ).toBeNull();
  });

  it("Duyệt mở hộp chọn hình thức (mặc định = hình thức lúc nhận) và gửi expected_row_version = row_version", async () => {
    const than: unknown[] = [];
    server.use(
      http.patch(`${API}/api/admissions/1/documents/HOC_BA/verify-format`, async ({ request }) => {
        than.push(await request.json());
        return HttpResponse.json({ id: 1 });
      }),
    );
    const user = userEvent.setup();
    render(<DocumentsTab profile={buildProfile([giayDuyet({ can_verify: true, can_change_format: true })]) as never} isEditable />);
    await user.click(within(screen.getByRole("table")).getByRole("button", { name: "Duyệt giấy Học bạ" }));
    const hop = await screen.findByRole("dialog");
    expect(within(hop).getByLabelText("Bản sao chứng thực")).toBeChecked();
    await user.click(within(hop).getByRole("button", { name: "Duyệt" }));
    await waitFor(() => expect(than).toHaveLength(1));
    expect(than[0]).toEqual({ format: "certified_copy", expected_row_version: 7, unknown_submitter_ack: false });
  });

  it("Duyệt giấy thiếu hình thức lúc nhận ⇒ KHÔNG dự phòng photo: nút Duyệt khoá tới khi chọn", async () => {
    const user = userEvent.setup();
    render(
      <DocumentsTab
        profile={buildProfile([giayDuyet({ can_verify: true, can_change_format: true, actual_submission_format: null })]) as never}
        isEditable
      />,
    );
    await user.click(within(screen.getByRole("table")).getByRole("button", { name: "Duyệt giấy Học bạ" }));
    const hop = await screen.findByRole("dialog");
    expect(within(hop).getByRole("button", { name: "Duyệt" })).toBeDisabled();
  });

  it("Đặt lại: hộp bắt buộc lý do; giấy đã duyệt giữ tệp ⇒ câu giữ tệp scan, không câu xoá tệp; thân {reason, expected_row_version}", async () => {
    const than: unknown[] = [];
    server.use(
      http.post(`${API}/api/admissions/1/documents/HOC_BA/reset`, async ({ request }) => {
        than.push(await request.json());
        return HttpResponse.json({ id: 1 });
      }),
    );
    const user = userEvent.setup();
    render(
      <DocumentsTab
        profile={
          buildProfile([
            giayDuyet({
              status: "verified",
              requires_upload: true,
              document_id: 31,
              verified_format: "certified_copy",
              can_reset: true,
              reset_requires_reason: true,
              reset_keeps_evidence: true,
            }),
          ]) as never
        }
        isEditable
      />,
    );
    await user.click(within(screen.getByRole("table")).getByRole("button", { name: "Đặt lại giấy Học bạ" }));
    const hop = await screen.findByRole("dialog");
    expect(hop).toHaveTextContent("Tệp scan được giữ lại");
    expect(hop.textContent ?? "").not.toMatch(/sẽ bị x[oó]a/i);
    const nut = within(hop).getByRole("button", { name: "Đặt lại" });
    expect(nut).toBeDisabled();
    await user.type(within(hop).getByLabelText(/Lý do đặt lại/), "nhầm hồ sơ");
    await user.click(nut);
    await waitFor(() => expect(than).toHaveLength(1));
    expect(than[0]).toEqual({ reason: "nhầm hồ sơ", expected_row_version: 7, unknown_submitter_ack: false });
  });

  it("requires_ack ⇒ hộp Từ chối có cam kết không rõ người nhận; thân mang unknown_submitter_ack = true", async () => {
    const than: unknown[] = [];
    server.use(
      http.post(`${API}/api/admissions/1/documents/HOC_BA/reject`, async ({ request }) => {
        than.push(await request.json());
        return HttpResponse.json({
          code: "HOC_BA",
          status: "rejected",
          rejection_reason: "mờ",
          rejected_at: null,
          rejected_by_id: 2,
          document_row_id: 31,
          row_version: 8,
        });
      }),
    );
    const user = userEvent.setup();
    render(
      <DocumentsTab profile={buildProfile([giayDuyet({ can_reject: true, requires_ack: true })]) as never} isEditable />,
    );
    await user.click(within(screen.getByRole("table")).getByRole("button", { name: "Từ chối giấy Học bạ" }));
    const hop = await screen.findByRole("dialog");
    expect(within(hop).getByTestId("hop-cam-ket-khong-ro-nguoi-nhan")).toBeInTheDocument();
    await user.type(within(hop).getByLabelText(/Lý do từ chối/), "mờ");
    const nut = within(hop).getByRole("button", { name: "Từ chối" });
    expect(nut).toBeDisabled();
    await user.click(within(hop).getByRole("checkbox"));
    await user.click(nut);
    await waitFor(() => expect(than).toHaveLength(1));
    expect(than[0]).toEqual({ reason: "mờ", expected_row_version: 7, unknown_submitter_ack: true });
  });

  it("can_view_history ⇒ nút Lịch sử mở hộp lịch sử theo document_row_id", async () => {
    const goi: string[] = [];
    server.use(
      http.get(`${API}/api/admissions/1/documents/31/history`, ({ request }) => {
        goi.push(request.url);
        return HttpResponse.json({
          document_row_id: 31,
          document_type_code: "HOC_BA",
          status: "paper_submitted",
          row_version: 7,
          entries: [],
          evidence_files: [],
        });
      }),
    );
    const user = userEvent.setup();
    render(<DocumentsTab profile={buildProfile([giayDuyet({ can_view_history: true })]) as never} isEditable />);
    await user.click(within(screen.getByRole("table")).getByRole("button", { name: "Lịch sử giấy Học bạ" }));
    expect(await screen.findByText("Chưa có thao tác nào được ghi.")).toBeInTheDocument();
    expect(goi).toHaveLength(1);
  });

  it("verify_block_reason own_submission ⇒ hiện lý do khoá Duyệt, không nút Duyệt", () => {
    render(
      <DocumentsTab
        profile={buildProfile([giayDuyet({ can_reject: true, verify_block_reason: "own_submission" })]) as never}
        isEditable
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByTestId("ly-do-khoa-duyet")).toHaveTextContent("không tự duyệt");
    expect(within(table).queryByRole("button", { name: /duyệt giấy/i })).toBeNull();
  });

  it("lệch hợp đồng: cờ bật mà định danh null ⇒ KHÔNG nút GĐ1b + báo thiếu định danh", () => {
    render(
      <DocumentsTab
        profile={buildProfile([giayDuyet({ document_row_id: null, row_version: null, can_reset: true })]) as never}
        isEditable
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).queryByRole("button", { name: /đặt lại giấy/i })).toBeNull();
    expect(within(table).getByTestId("giay-thieu-dinh-danh")).toBeInTheDocument();
  });

  it("X1: giấy ngoài cấu hình can_reset ⇒ nút Đặt lại mang tên giấy và bỏ câu không thể chỉnh trực tiếp", () => {
    render(
      <DocumentsTab
        profile={
          buildProfile([
            giayDuyet({ code: "GIAY_CU", label: "Giấy cũ", is_extra: true, is_mandatory: false, can_reset: true }),
          ]) as never
        }
        isEditable
      />,
    );
    expect(screen.getByRole("button", { name: "Đặt lại giấy Giấy cũ" })).toBeInTheDocument();
    expect(screen.queryByText(/không thể chỉnh trực tiếp ở đây/)).toBeNull();
  });

  it("X1: giấy ngoài cấu hình mọi cờ tắt ⇒ không nút, giữ câu không thể chỉnh trực tiếp", () => {
    render(
      <DocumentsTab
        profile={
          buildProfile([giayDuyet({ code: "GIAY_CU", label: "Giấy cũ", is_extra: true, is_mandatory: false })]) as never
        }
        isEditable
      />,
    );
    expect(screen.queryByRole("button", { name: /đặt lại giấy/i })).toBeNull();
    expect(screen.getByText(/không thể chỉnh trực tiếp ở đây/)).toBeInTheDocument();
  });
});
