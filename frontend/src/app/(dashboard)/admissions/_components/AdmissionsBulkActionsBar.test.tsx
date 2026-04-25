import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import { AdmissionsBulkActionsBar } from "./AdmissionsBulkActionsBar";

/**
 * Bulk bar is a thin view over the per-row `available_actions` intersection
 * computed in AdmissionsClient. These tests lock the current contract:
 * a button renders iff its matching `can*` prop is true. Defaulting any
 * can* to `true` (the previous behaviour) is what leaked officer-visible
 * approve/reject actions for which the API would 404.
 */
describe("AdmissionsBulkActionsBar", () => {
  const baseProps = {
    selectedCount: 2,
    onClearSelection: vi.fn(),
    onBulkApprove: vi.fn(),
    onBulkReject: vi.fn(),
    onBulkAssign: vi.fn(),
    onExport: vi.fn(),
    isLoading: false,
  };

  it("renders nothing when no rows are selected", () => {
    const { container } = render(
      <AdmissionsBulkActionsBar
        {...baseProps}
        selectedCount={0}
        canApprove={true}
        canReject={true}
        canAssign={true}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("hides Approve/Reject/Assign when every can* flag is false (officer view)", () => {
    render(
      <AdmissionsBulkActionsBar
        {...baseProps}
        canApprove={false}
        canReject={false}
        canAssign={false}
      />
    );
    expect(screen.queryByRole("button", { name: /duyệt/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /gán officer/i })).not.toBeInTheDocument();
    // Export is always available regardless of permission flags.
    expect(screen.getByRole("button", { name: /xuất/i })).toBeInTheDocument();
  });

  it("shows only Approve when the intersection grants approve only", () => {
    render(
      <AdmissionsBulkActionsBar
        {...baseProps}
        canApprove={true}
        canReject={false}
        canAssign={false}
      />
    );
    expect(screen.getByRole("button", { name: /duyệt/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /gán officer/i })).not.toBeInTheDocument();
  });

  it("shows Assign officer only when canAssign is true (manager same-unit view)", () => {
    render(
      <AdmissionsBulkActionsBar
        {...baseProps}
        canApprove={false}
        canReject={false}
        canAssign={true}
      />
    );
    expect(screen.getByRole("button", { name: /gán officer/i })).toBeInTheDocument();
  });

  it("shows all three action buttons for admin (every flag true)", () => {
    render(
      <AdmissionsBulkActionsBar
        {...baseProps}
        canApprove={true}
        canReject={true}
        canAssign={true}
      />
    );
    expect(screen.getByRole("button", { name: /duyệt/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /từ chối/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /gán officer/i })).toBeInTheDocument();
  });
});
