import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { SubjectGroupPanel } from "./SubjectGroupPanel";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

// Mock the hooks
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useSubjects: vi.fn(),
  useCreateSubject: vi.fn(),
  useUpdateSubject: vi.fn(),
  useDeleteSubject: vi.fn(),
  useSubjectGroups: vi.fn(),
}));

describe("SubjectTable (via SubjectGroupPanel)", () => {
  const mockData = [
    {
      id: 1,
      code: "TOAN",
      name_vi: "Toán",
      name_en: "Mathematics",
      display_order: 1,
      is_active: true,
    },
    {
      id: 2,
      code: "VAT_LY",
      name_vi: "Vật lý",
      name_en: "Physics",
      display_order: 2,
      is_active: true,
    },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    
    (UseMasterDataHooks.useSubjects as any).mockReturnValue({
      data: mockData,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useCreateSubject as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseMasterDataHooks.useUpdateSubject as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseMasterDataHooks.useDeleteSubject as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
    
    (UseMasterDataHooks.useSubjectGroups as any).mockReturnValue({
      data: [],
      isLoading: false,
    });
  });

  it("should render subjects list correctly", () => {
    render(<SubjectGroupPanel />);
    // "Subjects" is the default tab, so we don't need to switch

    expect(screen.getByText("TOAN")).toBeInTheDocument();
    expect(screen.getByText("Toán")).toBeInTheDocument();
    expect(screen.getByText("VAT_LY")).toBeInTheDocument();
    expect(screen.getByText("Vật lý")).toBeInTheDocument();
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<SubjectGroupPanel />);

    // Click Thêm mới
    const addButton = screen.getByText("Thêm mới");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Môn học")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Fill Form
    fireEvent.change(withinDialog.getByLabelText(/Mã môn/i), { target: { value: "HOA_HOC" } });
    fireEvent.change(withinDialog.getByLabelText(/Tên môn \(Tiếng Việt\)/i), { target: { value: "Hóa học" } });

    // Submit
    const submitButton = withinDialog.getByText("Thêm mới");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(expect.objectContaining({
        code: "HOA_HOC",
        name_vi: "Hóa học",
        display_order: 3, // length + 1
      }));
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<SubjectGroupPanel />);

    // Edit "TOAN" (Row 1)
    const row = screen.getByText("TOAN").closest("tr");
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const withinDialog = within(dialog);

    // Verify Fields
    await waitFor(() => {
      const codeInput = withinDialog.getByLabelText(/Mã môn/i) as HTMLInputElement;
      expect(codeInput.value).toBe("TOAN");
    });
    const codeInput = withinDialog.getByLabelText(/Mã môn/i) as HTMLInputElement;
    expect(codeInput.disabled).toBe(true);

    const nameInput = withinDialog.getByLabelText(/Tên môn \(Tiếng Việt\)/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Toán");
  });

  it("should call delete mutation when delete is confirmed", async () => {
    render(<SubjectGroupPanel />);

    // Delete "VAT_LY" (Row 2)
    const row = screen.getByText("VAT_LY").closest("tr");
    const buttons = row?.querySelectorAll("button");
    const deleteButton = buttons?.[1];

    fireEvent.click(deleteButton!);

    // Wait for AlertDialog to appear and confirm deletion
    const alertDialog = await screen.findByRole("alertdialog");
    const confirmBtn = within(alertDialog).getByRole("button", { name: /xóa/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockDeleteMutate).toHaveBeenCalledWith(2);
    });
  });
});
