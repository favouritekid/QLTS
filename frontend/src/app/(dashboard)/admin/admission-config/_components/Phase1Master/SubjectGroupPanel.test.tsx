import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { SubjectGroupTable } from "./SubjectGroupTable";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

// Mock the hooks
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useSubjectGroups: vi.fn(),
  useCreateSubjectGroup: vi.fn(),
  useUpdateSubjectGroup: vi.fn(),
  useDeleteSubjectGroup: vi.fn(),
  useSubjects: vi.fn(),
}));

describe("SubjectGroupPanel", () => {
  const mockData = [
    {
      id: 1,
      code: "A00",
      name: "Toán-Lý-Hóa",
      description: "Math, Physics, Chemistry",
      display_order: 1,
      is_active: true,
      subjects: [
        { code: "MATH", name_vi: "Toán", position: 1 },
        { code: "PHYS", name_vi: "Lý", position: 2 },
        { code: "CHEM", name_vi: "Hóa", position: 3 },
      ]
    },
    {
      id: 2,
      code: "D01",
      name: "Toán-Văn-Anh",
      description: "Math, Literature, English",
      display_order: 2,
      is_active: true,
      subjects: [] // Empty subjects case
    },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    
    (UseMasterDataHooks.useSubjectGroups as any).mockReturnValue({
      data: mockData,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useCreateSubjectGroup as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseMasterDataHooks.useUpdateSubjectGroup as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseMasterDataHooks.useDeleteSubjectGroup as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
    
    // Mock useSubjects for the panel which might call it
    (UseMasterDataHooks.useSubjects as any).mockReturnValue({
      data: [],
      isLoading: false,
    });
  });

  it("should render subject groups list correctly", async () => {
    render(<SubjectGroupTable />);

    expect(screen.getByText("A00")).toBeInTheDocument();
    expect(screen.getByText("Toán-Lý-Hóa")).toBeInTheDocument();
    
    // Check Subject Badges
    expect(screen.getByText("MATH")).toBeInTheDocument();
    expect(screen.getByText("PHYS")).toBeInTheDocument();
    expect(screen.getByText("CHEM")).toBeInTheDocument();

    expect(screen.getByText("D01")).toBeInTheDocument();
    expect(screen.getByText("Toán-Văn-Anh")).toBeInTheDocument();
    // Check Empty State
    expect(screen.getByText("No subjects assigned")).toBeInTheDocument();
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<SubjectGroupTable />);

    // Click Add New
    const addButton = screen.getByText("Add New");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Subject Group")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Fill Form
    fireEvent.change(withinDialog.getByLabelText(/Group Code/i), { target: { value: "A01" } });
    fireEvent.change(withinDialog.getByLabelText(/Group Name/i), { target: { value: "Toán-Lý-Anh" } });
    
    // Submit
    const submitButton = withinDialog.getByText("Create");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(expect.objectContaining({
        code: "A01",
        name: "Toán-Lý-Anh",
        display_order: 3, // length + 1
      }));
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<SubjectGroupTable />);

    // Edit "A00" (Row 1)
    const row = screen.getByText("A00").closest("tr");
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const withinDialog = within(dialog);

    // Verify Fields
    await waitFor(() => {
      const codeInput = withinDialog.getByLabelText(/Group Code/i) as HTMLInputElement;
      expect(codeInput.value).toBe("A00");
    });
    
    // Check if disabled
    const codeInput = withinDialog.getByLabelText(/Group Code/i) as HTMLInputElement;
    expect(codeInput.disabled).toBe(true);

    const nameInput = withinDialog.getByLabelText(/Group Name/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Toán-Lý-Hóa");

    // Verify Current Subjects Info Display
    expect(withinDialog.getByText(/Current Subjects:/i)).toBeInTheDocument();
    expect(withinDialog.getByText("1. Toán")).toBeInTheDocument();
    expect(withinDialog.getByText("2. Lý")).toBeInTheDocument();
    expect(withinDialog.getByText("3. Hóa")).toBeInTheDocument();
  });

  it("should call delete mutation when delete is confirmed", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => true);

    render(<SubjectGroupTable />);

    // Delete "D01" (Row 2)
    const row = screen.getByText("D01").closest("tr");
    const buttons = row?.querySelectorAll("button");
    const deleteButton = buttons?.[1]; 
    
    fireEvent.click(deleteButton!);

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(mockDeleteMutate).toHaveBeenCalledWith(2);
    });
  });
});
