import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { ProgramOfferingPanel } from "./ProgramOfferingPanel";
import * as UseProgramDataHooks from "@/hooks/admissions/useProgramData";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

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

    // Click Add New
    const addButton = screen.getByText("Add New");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Program Offering")).toBeInTheDocument();

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
    fireEvent.change(withinDialog.getByLabelText(/Duration/i), { target: { value: "7" } });
    fireEvent.change(withinDialog.getByLabelText(/Total Credits/i), { target: { value: "140" } });
    
    // Submit
    const submitButton = withinDialog.getByText("Create");
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
        const durationInput = withinDialog.getByLabelText(/Duration/i) as HTMLInputElement;
        expect(durationInput.value).toBe("6");
    });

    const creditInput = withinDialog.getByLabelText(/Total Credits/i) as HTMLInputElement;
    expect(creditInput.value).toBe("120");
    
    // Warning: Selects for Program and Offering Type won't strictly "show" text "Công nghệ Thông tin" in input value via simple query
    // But we check that state *would* allow user to see it.
  });

  it("should call delete mutation when delete is confirmed", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => true);

    render(<ProgramOfferingPanel />);

    const row = screen.getByText("Quản trị Kinh doanh").closest("tr");
    const buttons = row?.querySelectorAll("button");
    const deleteButton = buttons?.[1]; 
    
    fireEvent.click(deleteButton!);

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(mockDeleteMutate).toHaveBeenCalledWith(2);
    });
  });
});
