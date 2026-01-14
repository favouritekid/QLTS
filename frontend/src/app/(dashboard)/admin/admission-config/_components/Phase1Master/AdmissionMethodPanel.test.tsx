import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { AdmissionMethodPanel } from "./AdmissionMethodPanel";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

// Mock the hooks
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useAdmissionMethods: vi.fn(),
  useCreateAdmissionMethod: vi.fn(),
  useUpdateAdmissionMethod: vi.fn(),
  useDeleteAdmissionMethod: vi.fn(),
}));

describe("AdmissionMethodPanel", () => {
  const mockData = [
    {
      id: 1,
      code: "hoc_ba",
      name: "Xét học bạ THPT",
      description: "Based on high school results",
      requires_gpa: true,
      requires_subject_scores: true,
      display_order: 1,
      is_active: true,
    },
    {
      id: 2,
      code: "thpt_qg",
      name: "Xét điểm thi THPT QG",
      description: "Based on national exam",
      requires_gpa: false,
      requires_subject_scores: true,
      display_order: 2,
      is_active: true,
    },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    
    (UseMasterDataHooks.useAdmissionMethods as any).mockReturnValue({
      data: mockData,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useCreateAdmissionMethod as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseMasterDataHooks.useUpdateAdmissionMethod as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseMasterDataHooks.useDeleteAdmissionMethod as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
  });

  it("should render admission methods list correctly with custom columns", () => {
    render(<AdmissionMethodPanel />);

    // Check Names
    expect(screen.getByText("Xét học bạ THPT")).toBeInTheDocument();
    expect(screen.getByText("Xét điểm thi THPT QG")).toBeInTheDocument();

    // Check Custom Columns (Yes/No)
    // "requires_gpa" is true for first item -> "✓ Yes"
    // We expect at least one "✓ Yes"
    const yesText = screen.getAllByText("✓ Yes");
    expect(yesText.length).toBeGreaterThan(0);
    
    // "requires_gpa" is false for second item -> "✗ No"
    const noText = screen.getAllByText("✗ No");
    expect(noText.length).toBeGreaterThan(0);
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<AdmissionMethodPanel />);

    // Click Add New
    const addButton = screen.getByText("Add New");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Admission Method")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Fill Form
    // Text Inputs
    fireEvent.change(withinDialog.getByLabelText(/Code/i), { target: { value: "dgnl" } });
    fireEvent.change(withinDialog.getByLabelText(/Name/i), { target: { value: "Đánh giá năng lực" } });
    
    // Checkboxes (using getByLabelText on the label text next to checkbox)
    // Radix/Shadcn Checkbox is button role usually, relying on label click is safest integration test
    const gpaLabel = withinDialog.getByText("Requires GPA (Grade Point Average)");
    fireEvent.click(gpaLabel); // Toggle to checked (default false)

    // Submit
    const submitButton = withinDialog.getByText("Create");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(expect.objectContaining({
        code: "dgnl",
        name: "Đánh giá năng lực",
        requires_gpa: true,
        requires_subject_scores: false, // Default
        display_order: 3, // length + 1
      }));
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<AdmissionMethodPanel />);

    // Edit "Xét học bạ THPT" (Row 1)
    const row = screen.getByText("Xét học bạ THPT").closest("tr");
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    const withinDialog = within(dialog);

    // Verify Fields
    const codeInput = withinDialog.getByLabelText(/Code/i) as HTMLInputElement;
    expect(codeInput.value).toBe("hoc_ba");
    expect(codeInput.disabled).toBe(true);

    const nameInput = withinDialog.getByLabelText(/Name/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Xét học bạ THPT");

    // Verify Checkbox state
    // For Radix Checkbox, the button element has data-state="checked"
    // We find the checkbox by the label it is associated with or by role checkbox
    // Finding by label text and getting previous sibling or associated control is tricky in JSDOM
    // Best way: find by role checkbox. Since there are two, we need to be specific or get all.
    const checkboxes = withinDialog.getAllByRole("checkbox");
    
    // First checkbox is GPA (based on form order)
    expect(checkboxes[0]).toHaveAttribute("data-state", "checked"); // requires_gpa: true
    expect(checkboxes[1]).toHaveAttribute("data-state", "checked"); // requires_subject_scores: true
  });

  it("should call delete mutation when delete is confirmed", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => true);

    render(<AdmissionMethodPanel />);

    // Delete "Xét điểm thi THPT QG" (Row 2)
    const row = screen.getByText("Xét điểm thi THPT QG").closest("tr");
    const buttons = row?.querySelectorAll("button");
    const deleteButton = buttons?.[1]; 
    
    fireEvent.click(deleteButton!);

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(mockDeleteMutate).toHaveBeenCalledWith(2);
    });
  });
});
