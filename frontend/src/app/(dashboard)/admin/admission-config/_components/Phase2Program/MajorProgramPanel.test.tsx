import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { MajorProgramPanel } from "./MajorProgramPanel";
import * as UseProgramDataHooks from "@/hooks/admissions/useProgramData";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";
import { toast } from "sonner";

// Mock the hooks
vi.mock("@/hooks/admissions/useProgramData", () => ({
  useMajorPrograms: vi.fn(),
  useCreateMajorProgram: vi.fn(),
  useUpdateMajorProgram: vi.fn(),
  useDeleteMajorProgram: vi.fn(),
}));

vi.mock("@/hooks/admissions/useMasterData", () => ({
  useOrganizationUnits: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

describe("MajorProgramPanel", () => {
  const mockPrograms = [
    {
      id: 1,
      code: "6480201",
      name: "Công nghệ Thông tin",
      degree_level: "Cao đẳng",
      unit_id: 1,
      is_heavy: false,
      is_active: true,
      offerings: [], // simplified
    },
    {
      id: 2,
      code: "7340101",
      name: "Quản trị Kinh doanh",
      degree_level: "Đại học",
      unit_id: 2,
      is_heavy: false,
      is_active: true,
      offerings: [],
    }
  ];

  const mockUnits = [
    { id: 1, name: "Khoa CNTT", type: "Khoa" },
    { id: 2, name: "Khoa Kinh tế", type: "Khoa" },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    
    (UseProgramDataHooks.useMajorPrograms as any).mockReturnValue({
      data: mockPrograms,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useOrganizationUnits as any).mockReturnValue({
      data: mockUnits,
      isLoading: false,
    });
    
    (UseProgramDataHooks.useCreateMajorProgram as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseProgramDataHooks.useUpdateMajorProgram as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseProgramDataHooks.useDeleteMajorProgram as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
  });

  it("should render list grouped by degree level", () => {
    render(<MajorProgramPanel />);

    // Verify Group Headers and Data presence (might appear multiple times)
    expect(screen.getAllByText("Cao đẳng").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Đại học").length).toBeGreaterThan(0);

    // Verify Programs
    expect(screen.getByText("Công nghệ Thông tin")).toBeInTheDocument();
    expect(screen.getByText("6480201")).toBeInTheDocument();
    expect(screen.getByText("Quản trị Kinh doanh")).toBeInTheDocument();
    expect(screen.getByText("7340101")).toBeInTheDocument();
    
    // Verify Unit Name Resolution
    expect(screen.getByText("Khoa CNTT")).toBeInTheDocument();
    expect(screen.getByText("Khoa Kinh tế")).toBeInTheDocument();
  });

  it("should open create dialog and verify form structure", async () => {
    render(<MajorProgramPanel />);

    // Click Thêm mới
    const addButton = screen.getByText("Thêm mới");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Ngành đào tạo")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Verify form fields are present and interactive
    const codeInput = withinDialog.getByLabelText(/Mã ngành/i);
    expect(codeInput).toBeInTheDocument();
    fireEvent.change(codeInput, { target: { value: "NEW_CODE" } });
    expect((codeInput as HTMLInputElement).value).toBe("NEW_CODE");

    const nameInput = withinDialog.getByLabelText(/Tên chương trình/i);
    expect(nameInput).toBeInTheDocument();
    fireEvent.change(nameInput, { target: { value: "New Program" } });
    expect((nameInput as HTMLInputElement).value).toBe("New Program");

    // Verify submit button is present
    const submitButton = withinDialog.getByText("Thêm mới");
    expect(submitButton).toBeInTheDocument();

    // Note: SmartUnitSelector (combobox variant) and Radix Select for degree_level
    // don't render options reliably in JSDOM. The submit would be blocked by
    // unit_id validation (toast.error). We verify form structure instead.
    fireEvent.click(submitButton);

    // Since unit_id is not selected, validation blocks the mutation
    await waitFor(() => {
      expect(mockCreateMutate).not.toHaveBeenCalled();
    });
    expect(toast.error).toHaveBeenCalledWith("Vui lòng chọn đơn vị quản lý");
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<MajorProgramPanel />);

    // Edit "Công nghệ Thông tin"
    const row = screen.getByText("6480201").closest("tr");
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const withinDialog = within(dialog);

    // Verify Fields
    await waitFor(() => {
        const codeInput = withinDialog.getByLabelText(/Mã ngành/i) as HTMLInputElement;
        expect(codeInput.value).toBe("6480201");
    });

    const codeInput = withinDialog.getByLabelText(/Mã ngành/i) as HTMLInputElement;
    expect(codeInput.disabled).toBe(true);

    const nameInput = withinDialog.getByLabelText(/Tên chương trình/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Công nghệ Thông tin");
    
    // Verify mapped Unit ID is present in the select (element existence check mainly as value is hidden)
    // We can assume the correct value is passed to the component state
  });

  it("should call delete mutation when delete is confirmed", async () => {
    render(<MajorProgramPanel />);

    // Delete "Quản trị Kinh doanh"
    const row = screen.getByText("7340101").closest("tr");
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

  // ============================================
  // BUG-26: unit_id validation on create
  // ============================================
  it("BUG-26: should not call create mutation when unit_id is not selected", async () => {
    render(<MajorProgramPanel />);

    // Open create dialog
    const addButton = screen.getByText(/thêm mới|add new/i);
    fireEvent.click(addButton);

    const dialog = await screen.findByRole("dialog");
    const withinDialog = within(dialog);

    // Fill code and name but NOT unit_id
    fireEvent.change(withinDialog.getByLabelText(/Mã ngành/i), { target: { value: "9990001" } });
    fireEvent.change(withinDialog.getByLabelText(/Tên chương trình/i), { target: { value: "Test Program" } });

    // Do NOT select a unit (unit_id remains null from initialFormData)

    // Submit
    const submitButton = withinDialog.getByRole("button", { name: /create|thêm mới/i });
    fireEvent.click(submitButton);

    // Wait for async validation to complete
    await waitFor(() => {
      // The create mutation should NOT have been called due to missing unit_id
      expect(mockCreateMutate).not.toHaveBeenCalled();
    });

    // toast.error should have been called with the unit validation message
    expect(toast.error).toHaveBeenCalledWith("Vui lòng chọn đơn vị quản lý");
  });
});
