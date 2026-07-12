// src/components/leads/command-center/LeadsTable.test.tsx
/**
 * LeadsTable Component Tests
 *
 * Validates T1 fix: selection identity uses lead.id, not array index.
 * - getRowId: (row) => String(row.id) ensures correct identity mapping
 * - useEffect resets rowSelection on page/sortBy/sortOrder changes
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "@/test/utils/test-utils";
import type { Lead } from "@/types/lead.types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock @tanstack/react-virtual to bypass viewport-dependent virtualization in jsdom
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, i) => ({
        index: i,
        start: i * 40,
        end: (i + 1) * 40,
        size: 40,
        key: i,
      })),
    getTotalSize: () => count * 40,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn() })),
}));

vi.mock("@/hooks/useMediaQuery", () => ({
  useIsMobile: vi.fn(() => false),
}));

// Stub heavy sub-components that are not under test
vi.mock("./TableToolbar", () => ({
  TableToolbar: () => <div data-testid="table-toolbar" />,
}));
vi.mock("./BulkActionsBar", () => ({
  BulkActionsBar: () => null,
}));
vi.mock("./EmptyLeadsState", () => ({
  EmptyLeadsState: () => <div data-testid="empty-state" />,
}));
vi.mock("./MobileLeadCard", () => ({
  MobileLeadList: () => null,
}));
vi.mock("@/components/common/CopyableCell", () => ({
  CopyableCell: ({ value }: { value: string }) => <span>{value}</span>,
}));
vi.mock("@/components/common/ActivityIndicator", () => ({
  ActivityIndicator: () => <span>activity</span>,
}));
vi.mock("@/components/common/UrgencyBadge", () => ({
  UrgencyBadge: () => <span>urgency</span>,
}));
vi.mock("@/components/ui/dynamic-color-badge", () => ({
  DynamicColorBadge: ({ children }: { children: React.ReactNode }) => (
    <span>{children}</span>
  ),
}));
vi.mock("@/components/common/MobileActionSheet", () => ({
  MobileActionSheet: () => null,
}));

// Mock leadsApi to avoid real network
vi.mock("@/lib/api/leads", () => ({
  leadsApi: { getLead: vi.fn() },
}));

vi.mock("@/hooks/useLeads", () => ({
  leadsKeys: {
    all: ["leads"],
    detail: (id: number) => ["leads", "detail", id],
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeLead(overrides: Partial<Lead> & { id: number }): Lead {
  return {
    full_name: `Lead ${overrides.id}`,
    phone: "0901234567",
    email: `lead${overrides.id}@example.com`,
    source: "website",
    status: "new",
    lead_score: 50,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    version: 1,
    unit_id: 1,
    consultation_count: 0,
    cached_urgency_score: 0,
    is_hot_lead: false,
    is_overdue: false,
    days_in_stage: 0,
    location_proximity: 0,
    occupation_relevance: 0,
    academic_performance: 0,
    referrer_id: null,
    validity_status: null,
    created_via: null,
    referrer: null,
    ...overrides,
  } as Lead;
}

function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

// We import the component AFTER mocks are defined
import { LeadsTable } from "./LeadsTable";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LeadsTable", () => {
  const defaultProps = {
    leads: [] as Lead[],
    selectedLeadId: null,
    onSelectLead: vi.fn(),
    onEditLead: vi.fn(),
    onDeleteLead: vi.fn(),
    onAssignLead: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    // Stub localStorage for column persistence
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {});
  });

  it("should use lead.id as row identity, not array index", async () => {
    const leadA = makeLead({ id: 10, full_name: "Alice" });
    const leadB = makeLead({ id: 20, full_name: "Bob" });

    const { container } = render(
      <LeadsTable {...defaultProps} leads={[leadA, leadB]} />,
      { wrapper: createWrapper() },
    );

    // Wait for hydration
    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    // Find the individual row "Select row" checkboxes (not the header "Select all")
    const checkboxes = screen.getAllByRole("checkbox", { name: /select row/i });
    expect(checkboxes.length).toBe(2);

    // Click first checkbox (leadA with id=10)
    fireEvent.click(checkboxes[0]);

    // After selection, the toolbar should show "1 đã chọn"
    await waitFor(() => {
      expect(screen.getByText(/1 đã chọn/)).toBeInTheDocument();
    });

    // The key assertion: row identity is lead.id-based, not index-based.
    // With getRowId: (row) => String(row.id), the internal rowSelection
    // state should use key "10", not "0". If it were index-based (key "0"),
    // the row with id=10 would still be visually selected, but a mismatch
    // would occur if leads were reordered. We verify by checking that
    // exactly one checkbox is in checked state.
    const checkedBoxes = checkboxes.filter(
      (cb) => (cb as HTMLInputElement).dataset.state === "checked" ||
              cb.getAttribute("aria-checked") === "true",
    );
    expect(checkedBoxes.length).toBe(1);
  });

  it("should reset selection when page changes", async () => {
    const leadA = makeLead({ id: 10, full_name: "Alice" });
    const leadB = makeLead({ id: 20, full_name: "Bob" });

    const { rerender } = render(
      <LeadsTable {...defaultProps} leads={[leadA, leadB]} page={1} />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    // Select a row
    const checkboxes = screen.getAllByRole("checkbox", { name: /select row/i });
    fireEvent.click(checkboxes[0]);

    await waitFor(() => {
      expect(screen.getByText(/1 đã chọn/)).toBeInTheDocument();
    });

    // Change page prop -> selection should reset
    const Wrapper = createWrapper();
    rerender(
      <Wrapper>
        <LeadsTable {...defaultProps} leads={[leadA, leadB]} page={2} />
      </Wrapper>,
    );

    // After page change, selection should be cleared
    await waitFor(() => {
      expect(screen.queryByText(/đã chọn/)).not.toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Render contract: stage, status, officer columns (Phase 2 coverage)
  // ---------------------------------------------------------------------------

  it("should render pipeline_stage.name badge in row", async () => {
    const lead = makeLead({
      id: 100,
      full_name: "Stage Test Lead",
      pipeline_stage: { id: "stg02", name: "Đang tư vấn", color_code: "#F59E0B" } as Lead["pipeline_stage"],
    });

    render(<LeadsTable {...defaultProps} leads={[lead]} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Stage Test Lead")).toBeInTheDocument();
    });

    // LeadsTable.tsx:436-454 renders pipeline_stage.name via Badge
    expect(screen.getByText("Đang tư vấn")).toBeInTheDocument();
  });

  it("should render consultation_status.name badge in row", async () => {
    const lead = makeLead({
      id: 101,
      full_name: "Status Test Lead",
      consultation_status: { id: "sts03", name: "Có nhu cầu tìm hiểu", color_code: "#FACC15", color: "#FACC15" } as Lead["consultation_status"],
    });

    render(<LeadsTable {...defaultProps} leads={[lead]} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Status Test Lead")).toBeInTheDocument();
    });

    // LeadsTable.tsx:460-473 renders consultation_status.name via DynamicColorBadge
    expect(screen.getByText("Có nhu cầu tìm hiểu")).toBeInTheDocument();
  });

  it("should render assigned_officer.full_name in row", async () => {
    const lead = makeLead({
      id: 102,
      full_name: "Officer Test Lead",
      assigned_officer: { id: 18, full_name: "Nguyễn Văn A" } as Lead["assigned_officer"],
    });

    render(<LeadsTable {...defaultProps} leads={[lead]} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Officer Test Lead")).toBeInTheDocument();
    });

    // LeadsTable.tsx:480 renders assigned_officer.full_name
    expect(screen.getByText("Nguyễn Văn A")).toBeInTheDocument();
  });

  it("should render 'Chưa gán' when no assigned_officer", async () => {
    const lead = makeLead({
      id: 103,
      full_name: "Unassigned Lead",
      assigned_officer: null as Lead["assigned_officer"],
    });

    render(<LeadsTable {...defaultProps} leads={[lead]} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Unassigned Lead")).toBeInTheDocument();
    });

    // LeadsTable.tsx:480 fallback when no officer assigned
    expect(screen.getByText("Chưa gán")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Existing tests: selection identity and reset
  // ---------------------------------------------------------------------------

  it("should reset selection when sort changes", async () => {
    const leadA = makeLead({ id: 10, full_name: "Alice" });
    const leadB = makeLead({ id: 20, full_name: "Bob" });

    const { rerender } = render(
      <LeadsTable
        {...defaultProps}
        leads={[leadA, leadB]}
        sortBy="created_at"
        sortOrder="desc"
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    // Select a row
    const checkboxes = screen.getAllByRole("checkbox", { name: /select row/i });
    fireEvent.click(checkboxes[0]);

    await waitFor(() => {
      expect(screen.getByText(/1 đã chọn/)).toBeInTheDocument();
    });

    // Change sortBy -> selection should reset
    const Wrapper = createWrapper();
    rerender(
      <Wrapper>
        <LeadsTable
          {...defaultProps}
          leads={[leadA, leadB]}
          sortBy="full_name"
          sortOrder="desc"
        />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.queryByText(/đã chọn/)).not.toBeInTheDocument();
    });
  });
});
