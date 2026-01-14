import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@/test/utils/test-utils";
import { DocumentTypePanel } from "./DocumentTypePanel";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

// Mock the hooks
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useDocumentTypes: vi.fn(),
  useCreateDocumentType: vi.fn(),
  useUpdateDocumentType: vi.fn(),
  useDeleteDocumentType: vi.fn(),
}));

describe("DocumentTypePanel", () => {
  const mockData = [
    {
      id: 1,
      code: "hoc_ba",
      name: "Học bạ THPT",
      description: "High school transcript",
      display_order: 1,
      is_active: true,
    },
    {
      id: 2,
      code: "cccd",
      name: "CCCD/CMND",
      description: "Identity card",
      display_order: 2,
      is_active: true,
    },
  ];

  const mockCreateMutate = vi.fn();
  const mockUpdateMutate = vi.fn();
  const mockDeleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    
    (UseMasterDataHooks.useDocumentTypes as any).mockReturnValue({
      data: mockData,
      isLoading: false,
    });
    
    (UseMasterDataHooks.useCreateDocumentType as any).mockReturnValue({
      mutateAsync: mockCreateMutate,
    });
    
    (UseMasterDataHooks.useUpdateDocumentType as any).mockReturnValue({
      mutateAsync: mockUpdateMutate,
    });
    
    (UseMasterDataHooks.useDeleteDocumentType as any).mockReturnValue({
      mutateAsync: mockDeleteMutate,
    });
  });

  it("should render document types list correctly", () => {
    render(<DocumentTypePanel />);

    expect(screen.getByText("Học bạ THPT")).toBeInTheDocument();
    expect(screen.getByText("High school transcript")).toBeInTheDocument();
    expect(screen.getByText("CCCD/CMND")).toBeInTheDocument();
    expect(screen.getByText("Identity card")).toBeInTheDocument();
  });

  it("should open create dialog and submit form correctly", async () => {
    render(<DocumentTypePanel />);

    // Click Add New
    const addButton = screen.getByText("Add New");
    fireEvent.click(addButton);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Create Document Type")).toBeInTheDocument();

    const withinDialog = within(dialog);

    // Fill Form
    fireEvent.change(withinDialog.getByLabelText(/Code/i), { target: { value: "bang_tn" } });
    fireEvent.change(withinDialog.getByLabelText(/Name/i), { target: { value: "Bằng tốt nghiệp" } });
    fireEvent.change(withinDialog.getByLabelText(/Description/i), { target: { value: "Graduation certificate" } });
    
    // Submit
    const submitButton = withinDialog.getByText("Create");
    fireEvent.click(submitButton);

    // Check Mutation
    await waitFor(() => {
      expect(mockCreateMutate).toHaveBeenCalledWith(expect.objectContaining({
        code: "bang_tn",
        name: "Bằng tốt nghiệp",
        description: "Graduation certificate",
        display_order: 3, // length + 1
      }));
    });
  });

  it("should open edit dialog and populate data correctly", async () => {
    render(<DocumentTypePanel />);

    // Edit "Học bạ THPT" (Row 1)
    const row = screen.getByText("Học bạ THPT").closest("tr");
    const editButton = row?.querySelector("button"); 
    fireEvent.click(editButton!);

    // Verify Dialog
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const withinDialog = within(dialog);

    // Verify Fields
    const codeInput = withinDialog.getByLabelText(/Code/i) as HTMLInputElement;
    expect(codeInput.value).toBe("hoc_ba");
    expect(codeInput.disabled).toBe(true);

    const nameInput = withinDialog.getByLabelText(/Name/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Học bạ THPT");

    const descInput = withinDialog.getByLabelText(/Description/i) as HTMLTextAreaElement;
    expect(descInput.value).toBe("High school transcript");
  });

  it("should call delete mutation when delete is confirmed", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => true);

    render(<DocumentTypePanel />);

    // Delete "CCCD/CMND" (Row 2)
    const row = screen.getByText("CCCD/CMND").closest("tr");
    const buttons = row?.querySelectorAll("button");
    const deleteButton = buttons?.[1]; 
    
    fireEvent.click(deleteButton!);

    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteMutate).toHaveBeenCalledWith(2);
  });
});
