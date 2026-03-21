import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const mockUseCollaborators = vi.fn();
const mockUseCreateCollaborator = vi.fn();

vi.mock("@/hooks/useCollaborators", () => ({
  useCollaborators: (...args: unknown[]) => mockUseCollaborators(...args),
  useCreateCollaborator: () => mockUseCreateCollaborator(),
  useUpdateCollaborator: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useAdminUsers", () => ({
  useAdminUsersList: () => ({ data: null, isLoading: false }),
}));

vi.mock("@/components/common/selectors", () => ({
  SmartUnitSelector: () => <div data-testid="unit-selector" />,
}));

vi.mock("@/components/common/EmptyState", () => ({
  TableEmptyState: ({ title }: { title: string }) => <div>{title}</div>,
}));

import { OfficerCollaboratorsClient } from "./OfficerCollaboratorsClient";
import type { CollaboratorsPage } from "@/types/collaborator.types";

const mockCollaborators: CollaboratorsPage = {
  total_count: 2,
  collaborators: [
    {
      id: 1,
      code: "CTV-001",
      full_name: "Nguyen Van A",
      phone: "0912345678",
      email: null,
      status: "active" as const,
      unit_id: 1,
      user_id: null,
      managed_by_officer_id: 10,
      id_card_number: null,
      bank_account: null,
      bank_name: null,
      address: null,
      notes: null,
      created_at: "2026-03-20T10:00:00Z",
      updated_at: "2026-03-20T10:00:00Z",
      approved_at: null,
      unit: null,
      managed_by_officer: null,
    },
    {
      id: 2,
      code: "CTV-002",
      full_name: "Tran Thi B",
      phone: "0987654321",
      email: null,
      status: "pending" as const,
      unit_id: 1,
      user_id: null,
      managed_by_officer_id: 10,
      id_card_number: null,
      bank_account: null,
      bank_name: null,
      address: null,
      notes: null,
      created_at: "2026-03-21T10:00:00Z",
      updated_at: "2026-03-21T10:00:00Z",
      approved_at: null,
      unit: null,
      managed_by_officer: null,
    },
  ],
};

describe("OfficerCollaboratorsClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseCollaborators.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    });
    mockUseCreateCollaborator.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  it("renders the officer collaborators list with 5 columns", () => {
    render(<OfficerCollaboratorsClient initialData={mockCollaborators} />);

    // Header
    expect(screen.getByText("CTV của tôi")).toBeDefined();

    // Table data renders (desktop + mobile may duplicate, use getAllByText)
    expect(screen.getAllByText("Nguyen Van A").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("CTV-001").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("0912345678").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Hoạt động").length).toBeGreaterThanOrEqual(1);

    // Column headers (desktop only)
    expect(screen.getByRole("button", { name: /Mã CTV/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /Họ tên/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /SĐT/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /Trạng thái/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /Ngày tạo/i })).toBeDefined();
  });

  it("renders create button and opens dialog on click", () => {
    render(<OfficerCollaboratorsClient initialData={mockCollaborators} />);

    const createButton = screen.getByRole("button", {
      name: /Đề xuất CTV mới|Đề xuất/i,
    });
    expect(createButton).toBeDefined();

    fireEvent.click(createButton);

    // Dialog should open with officer-specific title
    expect(screen.getAllByText("Đề xuất CTV mới").length).toBeGreaterThanOrEqual(1);
  });

  it("does not render claims tab", () => {
    render(<OfficerCollaboratorsClient initialData={mockCollaborators} />);

    expect(screen.queryByText("Yêu cầu claim")).toBeNull();
  });

  it("does not render approve/suspend/edit actions", () => {
    render(<OfficerCollaboratorsClient initialData={mockCollaborators} />);

    expect(screen.queryByText("Duyệt CTV")).toBeNull();
    expect(screen.queryByText("Đình chỉ")).toBeNull();
    expect(screen.queryByText("Sửa thông tin")).toBeNull();
    expect(screen.queryByText("Mở menu thao tác")).toBeNull();
  });

  it("officer dialog does not render unit selector or officer combobox", () => {
    render(<OfficerCollaboratorsClient initialData={mockCollaborators} />);

    // Open dialog
    const createButton = screen.getByRole("button", {
      name: /Đề xuất CTV mới|Đề xuất/i,
    });
    fireEvent.click(createButton);

    // Unit selector and officer combobox should NOT be rendered
    expect(screen.queryByTestId("unit-selector")).toBeNull();
    expect(screen.queryByText("Nhân viên quản lý")).toBeNull();
  });

  it("status filter has only 3 options plus all", () => {
    render(<OfficerCollaboratorsClient initialData={mockCollaborators} />);

    // The status filter should not have "inactive" option
    expect(screen.queryByText("Ngưng HĐ")).toBeNull();
  });
});
