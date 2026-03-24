import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { ProgramOfferingPanel } from "./ProgramOfferingPanel";
import * as UseProgramDataHooks from "@/hooks/admissions/useProgramData";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";
import { toast } from "sonner";

// Mock the hooks
vi.mock("@/hooks/admissions/useProgramData", () => ({
  useProgramOfferings: vi.fn(),
  useCreateProgramOffering: vi.fn(),
  useUpdateProgramOffering: vi.fn(),
  useDeleteProgramOffering: vi.fn(),
  useMajorPrograms: vi.fn(),
}));

vi.mock("@/hooks/admissions/useMasterData", () => ({
  useOfferingTypes: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

describe("ProgramOfferingPanel", () => {
  const mockOfferings = [
    {
      id: 1,
      program_id: 1,
      offering_type: "Chính quy",
      duration_semesters: 6,
      total_credits: 120,
      is_active: true,
      program: { name: "Công nghệ Thông tin", code: "648" }
    },
    {
      id: 2,
      program_id: 2,
      offering_type: "Vừa làm vừa học",
      duration_semesters: 8,
      total_credits: 130,
      is_active: true,
      program: { name: "Quản trị Kinh doanh", code: "734" }
    }
  ];

  const mockMajors = [
    { id: 1, name: "Công nghệ Thông tin", code: "648" },
    { id: 2, name: "Quản trị Kinh doanh", code: "734" },
  ];

  const mockOfferingTypes = [
    { id: 10, name: "Chính quy", code: "CQ" },
    { id: 11, name: "Vừa làm vừa học", code: "VLVH" },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    
    (UseProgramDataHooks.useProgramOfferings as any).mockReturnValue({
      data: mockOfferings,
      isLoading: false,
    });
    
    (UseProgramDataHooks.useMajorPrograms as any).mockReturnValue({
      data: mockMajors,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useOfferingTypes as any).mockReturnValue({
      data: mockOfferingTypes,
      isLoading: false,
    });

    (UseProgramDataHooks.useCreateProgramOffering as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseProgramDataHooks.useUpdateProgramOffering as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseProgramDataHooks.useDeleteProgramOffering as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
  });

  it("should render offerings list correctly", () => {
    render(<ProgramOfferingPanel />);

    // Check Major Names (rendered via lookups)
    expect(screen.getByText("Công nghệ Thông tin")).toBeInTheDocument();
    expect(screen.getByText("Quản trị Kinh doanh")).toBeInTheDocument();

    // Check Offering Types
    expect(screen.getByText("Chính quy")).toBeInTheDocument();
    expect(screen.getByText("Vừa làm vừa học")).toBeInTheDocument();
    
    // Check details
    expect(screen.getByText("6")).toBeInTheDocument(); // Duration
    expect(screen.getByText("120")).toBeInTheDocument(); // Credits
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<ProgramOfferingPanel />);

    // Click Thêm mới
    const addButton = screen.getByText("Thêm mới");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Chương trình Tuyển sinh")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Select Major Program
    // Select Major Program & Offering Type
    // Using getAllByRole is safer when text/label selectors are flaky with Radix
    const triggers = await withinDialog.findAllByRole("combobox");
    
    // Assuming order: Program, Type, ...
    const programTrigger = triggers[0]; 
    fireEvent.click(programTrigger);
    const majorOption = await screen.findByText("Công nghệ Thông tin (648)");
    fireEvent.click(majorOption);

    const typeTrigger = triggers[1];
    fireEvent.click(typeTrigger);
    const typeOption = await screen.findByText("Chính quy (CQ)");
    fireEvent.click(typeOption);

    // Input text details
    fireEvent.change(withinDialog.getByLabelText(/Thời gian/i), { target: { value: "7" } });
    fireEvent.change(withinDialog.getByLabelText(/Tổng tín chỉ/i), { target: { value: "140" } });
    
    // Submit
    const submitButton = withinDialog.getByText("Thêm mới");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(expect.objectContaining({
        duration_semesters: 7,
        total_credits: 140,
        program_id: 1, // ID of Công nghệ Thông tin
        offering_type: "Chính quy", // Name of offering type
      }));
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<ProgramOfferingPanel />);

    // Edit Row 1
    const row = screen.getByText("Công nghệ Thông tin").closest("tr");
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const withinDialog = within(dialog);

    // Verify Fields
    await waitFor(() => {
        const durationInput = withinDialog.getByLabelText(/Thời gian/i) as HTMLInputElement;
        expect(durationInput.value).toBe("6");
    });

    const creditInput = withinDialog.getByLabelText(/Tổng tín chỉ/i) as HTMLInputElement;
    expect(creditInput.value).toBe("120");
    
    // Warning: Selects for Program and Offering Type won't strictly "show" text "Công nghệ Thông tin" in input value via simple query
    // But we check that state *would* allow user to see it.
  });

  it("should call delete mutation when delete is confirmed", async () => {
    render(<ProgramOfferingPanel />);

    const row = screen.getByText("Quản trị Kinh doanh").closest("tr");
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
  // BUG-07: offering_type included in create payload
  // ============================================
  it("BUG-07: create payload should include offering_type name string", async () => {
    render(<ProgramOfferingPanel />);

    // Open create dialog
    const addButton = screen.getByText(/thêm mới|add new/i);
    fireEvent.click(addButton);

    const dialog = await screen.findByRole("dialog");
    const withinDialog = within(dialog);

    // Select Major Program & Offering Type via combobox triggers
    const triggers = await withinDialog.findAllByRole("combobox");

    // Select program
    fireEvent.click(triggers[0]);
    const majorOption = await screen.findByText("Công nghệ Thông tin (648)");
    fireEvent.click(majorOption);

    // Select offering type
    fireEvent.click(triggers[1]);
    const typeOption = await screen.findByText("Chính quy (CQ)");
    fireEvent.click(typeOption);

    // Fill required fields
    fireEvent.change(withinDialog.getByLabelText(/duration|thời gian/i), { target: { value: "6" } });
    fireEvent.change(withinDialog.getByLabelText(/total credits|tổng tín chỉ/i), { target: { value: "120" } });

    // Submit
    const submitButton = withinDialog.getByRole("button", { name: /create|thêm mới/i });
    fireEvent.click(submitButton);

    // Verify offering_type is the name string, not the ID
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          offering_type: "Chính quy",
        })
      );
    });

    // Also verify offering_type is a string, not a number
    const callArgs = mockCreateMutate.mock.calls[0][0];
    expect(typeof callArgs.offering_type).toBe("string");
  });

  // ============================================
  // BUG-08: identity fields disabled in edit mode
  // ============================================
  it("BUG-08: program_id and offering_type_id selects should be disabled in edit mode", async () => {
    render(<ProgramOfferingPanel />);

    // Click edit on first row
    const row = screen.getByText("Công nghệ Thông tin").closest("tr");
    const editButton = row?.querySelector("button");
    fireEvent.click(editButton!);

    // Wait for dialog
    const dialog = await screen.findByRole("dialog");
    const withinDialog = within(dialog);

    // The program_id and offering_type_id Select triggers should be disabled
    const programTrigger = withinDialog.getByRole("combobox", { name: /ngành đào tạo|program/i });
    const typeTrigger = withinDialog.getByRole("combobox", { name: /hệ đào tạo|offering type/i });

    expect(programTrigger).toBeDisabled();
    expect(typeTrigger).toBeDisabled();
  });

  // ============================================
  // BUG-27: validation before submit (missing required fields)
  // ============================================
  it("BUG-27: should not call create mutation when program and offering type are not selected", async () => {
    render(<ProgramOfferingPanel />);

    // Open create dialog
    const addButton = screen.getByText(/thêm mới|add new/i);
    fireEvent.click(addButton);

    const dialog = await screen.findByRole("dialog");
    const withinDialog = within(dialog);

    // Fill only non-required fields (duration and credits)
    fireEvent.change(withinDialog.getByLabelText(/duration|thời gian/i), { target: { value: "6" } });
    fireEvent.change(withinDialog.getByLabelText(/total credits|tổng tín chỉ/i), { target: { value: "120" } });

    // Submit without selecting program or offering type
    const submitButton = withinDialog.getByRole("button", { name: /create|thêm mới/i });
    fireEvent.click(submitButton);

    // Wait a tick for async handlers to complete
    await waitFor(() => {
      // The create mutation should NOT have been called due to validation
      expect(mockCreateMutate).not.toHaveBeenCalled();
    });

    // toast.error should have been called with validation message
    expect(toast.error).toHaveBeenCalled();
  });
});
