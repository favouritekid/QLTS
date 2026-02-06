import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { AcademicInfoPanel } from "./AcademicInfoPanel";
import * as UseProgramDataHooks from "@/hooks/admissions/useProgramData";

// Mock the hooks
vi.mock("@/hooks/admissions/useProgramData", () => ({
  useOfferingAcademicInfos: vi.fn(),
  useProgramOfferings: vi.fn(),
  useCreateOfferingAcademicInfo: vi.fn(),
  useUpdateOfferingAcademicInfo: vi.fn(),
  useDeleteOfferingAcademicInfo: vi.fn(),
}));

describe("AcademicInfoPanel", () => {
  const mockAcademicInfos = [
    {
      id: 1,
      offering_id: 1,
      academic_year: 2024,
      tuition_fee_per_year: 25000000,
      annual_admission_quota: 100,
      is_published: true,
    },
    {
      id: 2,
      offering_id: 2,
      academic_year: 2024,
      tuition_fee_per_year: 30000000,
      annual_admission_quota: 50,
      is_published: false,
    }
  ];

  const mockOfferings = [
    { 
      id: 1, 
      name: "CNTT - Chính quy", 
      code: "IT-CQ",
      offering_type: "Chính quy",
      program: { name: "CNTT", code: "IT", degree_level: "Đại học" }
    },
    { 
      id: 2, 
      name: "QTVHKD - VLVH", 
      code: "BA-VLVH",
      offering_type: "Vừa làm vừa học",
      program: { name: "QTVHKD", code: "BA", degree_level: "Đại học" }
    },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    
    (UseProgramDataHooks.useOfferingAcademicInfos as any).mockReturnValue({
      data: mockAcademicInfos,
      isLoading: false,
    });
    
    (UseProgramDataHooks.useProgramOfferings as any).mockReturnValue({
      data: mockOfferings,
      isLoading: false,
    });
    
    (UseProgramDataHooks.useCreateOfferingAcademicInfo as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
      isPending: false,
    });
    
    (UseProgramDataHooks.useUpdateOfferingAcademicInfo as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
      isPending: false,
    });
    
    (UseProgramDataHooks.useDeleteOfferingAcademicInfo as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
      isPending: false,
    });
  });

  it("should render academic info list correctly", () => {
    render(<AcademicInfoPanel />);

    // Check Offering Names
    expect(screen.getByText("CNTT - Chính quy")).toBeInTheDocument();
    
    // Check Years
    expect(screen.getAllByText("2024").length).toBeGreaterThan(0);
    
    // Check formatted currency
    // 25000000 => 25.000.000 ₫ or similar depending on locale. 
    // We look for parts of it or use a flexible matcher.
    expect(screen.getByText(/25\.000\.000/)).toBeInTheDocument();
    
    // Check Quota
    expect(screen.getByText("100")).toBeInTheDocument();

    // Check Status
    expect(screen.getByText("Published")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<AcademicInfoPanel />);

    // Click Add New
    const addButton = screen.getByText("Add New");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Academic Info")).toBeInTheDocument();

    const withinDialog = within(dialog);

    const triggers = await withinDialog.findAllByRole("combobox");
    const selectTrigger = triggers[0];
    fireEvent.click(selectTrigger);
    const offeringOption = await screen.findByText("CNTT - Chính quy (IT-CQ)");
    fireEvent.click(offeringOption);

    // Input details
    fireEvent.change(withinDialog.getByLabelText(/Academic Year/i), { target: { value: "2025" } });
    fireEvent.change(withinDialog.getByLabelText(/Tuition Fee per Year/i), { target: { value: "26000000" } });
    fireEvent.change(withinDialog.getByLabelText(/Annual Admission Quota/i), { target: { value: "120" } });
    
    // Check Publish
    const publishCheckbox = withinDialog.getByLabelText(/Publish this academic info/i);
    fireEvent.click(publishCheckbox);

    // Submit
    const submitButton = withinDialog.getByText("Create");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(expect.objectContaining({
        offering_id: 1,
        academic_year: 2025,
        tuition_fee_per_year: 26000000,
        annual_admission_quota: 120,
        is_published: true,
      }));
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<AcademicInfoPanel />);

    // Edit Row 1
    const row = screen.getByText("CNTT - Chính quy").closest("tr"); // Depends on name or computed?
    // Computed name is "CNTT - Chính quy" because program name="CNTT", type="Chính quy"
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const withinDialog = within(dialog);

    // Verify Fields
    await waitFor(() => {
       const yearInput = withinDialog.getByLabelText(/Academic Year/i) as HTMLInputElement;
       expect(yearInput.value).toBe("2024");
    });

    const feeInput = withinDialog.getByLabelText(/Tuition Fee per Year/i) as HTMLInputElement;
    expect(feeInput.value).toBe("25000000");
    
    const quotaInput = withinDialog.getByLabelText(/Annual Admission Quota/i) as HTMLInputElement;
    expect(quotaInput.value).toBe("100");
  });

  it("should call delete mutation when delete is confirmed", async () => {
    render(<AcademicInfoPanel />);

    // With new mock data/logic: "QTVHKD - Vừa làm vừa học"
    const row = screen.getByText("QTVHKD - Vừa làm vừa học").closest("tr");
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
