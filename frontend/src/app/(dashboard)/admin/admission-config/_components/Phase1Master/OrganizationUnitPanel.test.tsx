import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@/test/utils/test-utils";
import { OrganizationUnitPanel } from "./OrganizationUnitPanel";
import * as UseMasterDataHooks from "@/hooks/admissions/useMasterData";

// Mock the hooks
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useOrganizationUnits: vi.fn(),
  useCreateOrganizationUnit: vi.fn(),
  useUpdateOrganizationUnit: vi.fn(),
  useDeleteOrganizationUnit: vi.fn(),
}));

// Mock the SmartUnitSelector's internal hook (imports from a different path)
// SmartUnitSelector uses useOrganizationUnits from @/hooks/useOrganization
vi.mock("@/hooks/useOrganization", () => ({
  useOrganizationUnits: vi.fn(() => ({
    data: [
      {
        id: 1,
        name: "Faculty of IT",
        type: "Khoa",
        parent_id: null,
        is_active: true,
        children: [
          { id: 2, name: "Software Engineering", type: "Bộ môn", parent_id: 1, is_active: true, children: [] },
          { id: 3, name: "Computer Science", type: "Bộ môn", parent_id: 1, is_active: true, children: [] },
        ],
      },
      { id: 4, name: "Faculty of Medical", type: "Khoa", parent_id: null, is_active: true, children: [] },
    ],
    isLoading: false,
  })),
  flattenOrganizationTree: vi.fn((units: any[]) => {
    const result: any[] = [];
    const traverse = (items: any[], level: number) => {
      for (const item of items) {
        result.push({ unit: item, level, hasChildren: !!(item.children?.length) });
        if (item.children) traverse(item.children, level + 1);
      }
    };
    traverse(units, 0);
    return result;
  }),
  getAllDescendantIds: vi.fn(() => new Set<number>()),
}));

describe("OrganizationUnitPanel", () => {
  const mockData = [
    {
      id: 1,
      name: "Faculty of IT",
      type: "Khoa",
      parent_id: null,
      is_active: true,
      children: [
        {
          id: 2,
          name: "Software Engineering",
          type: "Bộ môn",
          parent_id: 1,
          is_active: true,
          children: [],
        },
        {
          id: 3,
          name: "Computer Science",
          type: "Bộ môn",
          parent_id: 1,
          is_active: true,
          children: [],
        },
      ],
    },
    {
      id: 4,
      name: "Faculty of Medical",
      type: "Khoa",
      parent_id: null,
      is_active: true,
      children: [],
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    // Default mock implementation
    (UseMasterDataHooks.useOrganizationUnits as any).mockReturnValue({
      data: mockData,
      isLoading: false,
    });
    (UseMasterDataHooks.useCreateOrganizationUnit as any).mockReturnValue({
      mutateAsync: vi.fn(),
    });
    (UseMasterDataHooks.useUpdateOrganizationUnit as any).mockReturnValue({
      mutateAsync: vi.fn(),
    });
    (UseMasterDataHooks.useDeleteOrganizationUnit as any).mockReturnValue({
      mutateAsync: vi.fn(),
    });
  });

  it("should render flattened list with correct hierarchy", () => {
    render(<OrganizationUnitPanel />);

    // 1. Verify all items are rendered (flattened)
    const facultyItems = screen.getAllByText("Faculty of IT");
    expect(facultyItems.length).toBeGreaterThan(0);
    expect(screen.getByText("Software Engineering")).toBeInTheDocument();
    expect(screen.getByText("Computer Science")).toBeInTheDocument();
    expect(screen.getByText("Faculty of Medical")).toBeInTheDocument();

    // 2. Verify Hierarchy Visualization (Indentation)
    // Find the row containing "Software Engineering"
    const nameSpan = screen.getByText("Software Engineering");
    const containerDiv = nameSpan.parentElement; // The div with flex and padding
    
    // Check padding logic (Level 1 should have 24px padding)
    expect(containerDiv).toHaveStyle({ paddingLeft: '24px' });

    // Check for the presence of the indentation marker.
    const arrowSpan = containerDiv?.querySelector(".text-muted-foreground");
    expect(arrowSpan).toBeInTheDocument();
    expect(arrowSpan).toHaveTextContent("└─"); 
  });

  it("should sort items by name within the hierarchy", () => {
    render(<OrganizationUnitPanel />);
    
    const cells = screen.getAllByText(/Faculty|Computer|Software/);
    const cellTexts = cells.map(cell => cell.textContent);

    const itIndex = cellTexts.findIndex(t => t?.includes("Faculty of IT"));
    const csIndex = cellTexts.findIndex(t => t?.includes("Computer Science"));
    const seIndex = cellTexts.findIndex(t => t?.includes("Software Engineering"));

    expect(itIndex).toBeLessThan(csIndex);
    expect(csIndex).toBeLessThan(seIndex);
  });

  it("should populate form data correctly when editing a child item", async () => {
    render(<OrganizationUnitPanel />);
    
    const seRow = screen.getByText("Software Engineering").closest("tr");
    const buttons = seRow?.querySelectorAll("button");
    const editButton = buttons?.[0];
    fireEvent.click(editButton!);

    // Verify Dialog Open
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // Scope queries to the dialog
    const withinDialog = within(dialog);

    // 1. Name
    const nameInput = withinDialog.getByLabelText(/Tên đơn vị/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Software Engineering");

    // 2. Type
    expect(withinDialog.getByText("Bộ môn")).toBeInTheDocument();

    // 3. Parent 
    expect(withinDialog.getByText(/Faculty of IT/)).toBeInTheDocument();
  });
});
