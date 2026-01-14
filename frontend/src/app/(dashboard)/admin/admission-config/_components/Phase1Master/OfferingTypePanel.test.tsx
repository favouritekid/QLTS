import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { OfferingTypePanel } from "./OfferingTypePanel";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

// Mock the hooks
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useOfferingTypes: vi.fn(),
  useCreateOfferingType: vi.fn(),
  useUpdateOfferingType: vi.fn(),
  useDeleteOfferingType: vi.fn(),
}));

describe("OfferingTypePanel", () => {
  const mockData = [
    {
      id: 1,
      code: "regular",
      name: "Regular",
      display_order: 1,
      is_active: true,
    },
    {
      id: 2,
      code: "part_time",
      name: "Part-time",
      display_order: 2,
      is_active: true,
    },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    
    (UseMasterDataHooks.useOfferingTypes as any).mockReturnValue({
      data: mockData,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useCreateOfferingType as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseMasterDataHooks.useUpdateOfferingType as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseMasterDataHooks.useDeleteOfferingType as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
  });

  it("should render offering types list correctly", () => {
    render(<OfferingTypePanel />);

    expect(screen.getByText("Regular")).toBeInTheDocument();
    expect(screen.getByText("Part-time")).toBeInTheDocument();
    expect(screen.getByText("regular")).toBeInTheDocument(); // Code
    expect(screen.getByText("part_time")).toBeInTheDocument(); // Code
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<OfferingTypePanel />);

    // Click Add New
    const addButton = screen.getByText("Add New");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Offering Type")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Fill Form
    const codeInput = withinDialog.getByLabelText(/Code/i);
    const nameInput = withinDialog.getByLabelText(/Name/i);
    
    fireEvent.change(codeInput, { target: { value: "distance" } });
    fireEvent.change(nameInput, { target: { value: "Distance Learning" } });

    // Submit
    const submitButton = withinDialog.getByText("Create");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith({
        code: "distance",
        name: "Distance Learning",
        display_order: 3, // Default is length + 1 (2 + 1 = 3)
        is_active: true,
      });
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<OfferingTypePanel />);

    // Find Edit button for "Regular"
    // Regular is row 1
    const row = screen.getByText("Regular").closest("tr");
    const editButton = row?.querySelector("button"); // First button is Edit
    expect(editButton).toBeInTheDocument();

    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Edit Offering Type")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Verify Fields
    const codeInput = withinDialog.getByLabelText(/Code/i) as HTMLInputElement;
    const nameInput = withinDialog.getByLabelText(/Name/i) as HTMLInputElement;

    expect(codeInput.value).toBe("regular");
    expect(codeInput.disabled).toBe(true); // Code is disabled in edit
    expect(nameInput.value).toBe("Regular");
  });

  it("should call delete mutation when delete is confirmed", async () => {
    // Mock window.confirm
    vi.spyOn(window, "confirm").mockImplementation(() => true);

    render(<OfferingTypePanel />);

    // Find Delete button for "Part-time"
    const row = screen.getByText("Part-time").closest("tr");
    const buttons = row?.querySelectorAll("button");
    const deleteButton = buttons?.[1]; // Second button is Delete
    expect(deleteButton).toBeInTheDocument();

    fireEvent.click(deleteButton!);

    // Check Mutation
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(mockDeleteMutate).toHaveBeenCalledWith(2); // Part-time ID is 2
    });
  });
});
