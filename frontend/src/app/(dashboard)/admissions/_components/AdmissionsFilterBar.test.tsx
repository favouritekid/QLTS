import { describe, it, expect, vi, beforeEach } from "vitest"
import type { ReactNode } from "react"
import { render, screen } from "@/test/utils/test-utils"
import { fireEvent, within } from "@testing-library/react"
import { AdmissionsFilterBar, type AdmissionsFilterBarProps } from "./AdmissionsFilterBar"
import { CURRENT_ADMISSIONS_YEAR } from "@/hooks/admissions/filterDefaults"

// Role drives the assignment-group gating (UX-only; backend enforces real scope).
const mockAuthState = vi.hoisted(() => ({ role: "admin" as string }))
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: 1, username: "u", role: mockAuthState.role } }),
}))
// Role-aware so officer vs reviewer sections render DISTINCT users (else the same
// aria-label appears twice → getByLabelText is ambiguous).
vi.mock("@/hooks/useAdminUsers", () => ({
  useAdminUsersList: (params: { role?: string }) => ({
    data:
      params?.role === "officer"
        ? { users: [{ id: 10, full_name: "Nguyễn Văn A" }], total_count: 1 }
        : { users: [{ id: 20, full_name: "Trần Thị B" }], total_count: 1 },
  }),
}))
vi.mock("@/hooks/useOrganization", () => ({
  useOrganizationUnits: () => ({
    data: [{ id: 5, name: "Phòng Tuyển Sinh", children: [] }],
  }),
}))

// Render Popover / DropdownMenu content always-open in tests (repo pattern, see
// ProfileActionMenu.test) so assertions don't depend on Radix pointer-event open.
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}))

beforeEach(() => {
  mockAuthState.role = "admin"
})

function setup(overrides: Partial<AdmissionsFilterBarProps> = {}) {
  const props: AdmissionsFilterBarProps = {
    search: "",
    onSearchChange: vi.fn(),
    academicYear: CURRENT_ADMISSIONS_YEAR,
    yearOptions: [CURRENT_ADMISSIONS_YEAR, CURRENT_ADMISSIONS_YEAR - 1],
    onYearChange: vi.fn(),
    statusFilters: [],
    onStatusChange: vi.fn(),
    majorFilter: "",
    majorPrograms: [{ id: 1, name: "CNTT" }],
    onMajorChange: vi.fn(),
    degreeLevelFilter: "",
    degreeLevels: [{ code: "cd", name: "Cao đẳng" }],
    onDegreeLevelChange: vi.fn(),
    paymentStatusFilter: "",
    onPaymentStatusChange: vi.fn(),
    dateFrom: "",
    dateTo: "",
    onDateFromChange: vi.fn(),
    onDateToChange: vi.fn(),
    sortBy: "created_at",
    sortOrder: "desc",
    onSortChange: vi.fn(),
    officerFilters: [],
    onOfficerChange: vi.fn(),
    unitId: "",
    onUnitIdChange: vi.fn(),
    reviewerFilters: [],
    onReviewerChange: vi.fn(),
    unassigned: false,
    onUnassignedChange: vi.fn(),
    onReset: vi.fn(),
    ...overrides,
  }
  render(<AdmissionsFilterBar {...props} />)
  return props
}

function openFilters() {
  fireEvent.click(screen.getByRole("button", { name: /bộ lọc nâng cao/i }))
}

describe("AdmissionsFilterBar", () => {
  it("forwards the search input value", () => {
    const props = setup()
    fireEvent.change(screen.getByLabelText(/tìm kiếm hồ sơ/i), { target: { value: "an" } })
    expect(props.onSearchChange).toHaveBeenCalledWith("an")
  })

  it("renders a chip per active status filter; removing it calls onStatusChange", () => {
    const props = setup({ statusFilters: ["submitted"] })
    // "Chờ duyệt" appears as both a chip AND a status checkbox (popover content is
    // always-rendered under the mock) → assert ≥1 + target the chip's remove button.
    expect(screen.getAllByText("Chờ duyệt").length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole("button", { name: /bỏ lọc chờ duyệt/i }))
    expect(props.onStatusChange).toHaveBeenCalledWith([])
  })

  it("counts active filter GROUPS on the Bộ lọc badge (status = 1 group)", () => {
    // status group (1) + payment group (1) = 2
    setup({ statusFilters: ["submitted", "approved"], paymentStatusFilter: "paid" })
    // Scope to the Bộ lọc trigger so the badge "2" isn't confused with other "2"s
    // now that the popover content renders under the mock.
    const filterButton = screen.getByRole("button", { name: /bộ lọc nâng cao/i })
    expect(within(filterButton).getByText("2")).toBeInTheDocument()
  })

  it("shows a Năm chip for a non-default year; removing it resets to current year", () => {
    const props = setup({ academicYear: CURRENT_ADMISSIONS_YEAR - 1 })
    const removeBtn = screen.getByRole("button", {
      name: new RegExp(`bỏ lọc năm ${CURRENT_ADMISSIONS_YEAR - 1}`, "i"),
    })
    fireEvent.click(removeBtn)
    expect(props.onYearChange).toHaveBeenCalledWith(CURRENT_ADMISSIONS_YEAR)
  })

  it("Xóa tất cả calls onReset", () => {
    const props = setup({ statusFilters: ["submitted"] })
    fireEvent.click(screen.getByRole("button", { name: /xóa tất cả/i }))
    expect(props.onReset).toHaveBeenCalled()
  })

  describe("Phân công group — role gating", () => {
    it("admin sees Cán bộ + Người duyệt + Đơn vị", () => {
      mockAuthState.role = "admin"
      setup()
      openFilters()
      expect(screen.getByText("Cán bộ phụ trách")).toBeInTheDocument()
      expect(screen.getByText("Người duyệt")).toBeInTheDocument()
      expect(screen.getByText("Đơn vị")).toBeInTheDocument()
    })

    it("manager sees Cán bộ but NOT Đơn vị", () => {
      mockAuthState.role = "manager"
      setup()
      openFilters()
      expect(screen.getByText("Cán bộ phụ trách")).toBeInTheDocument()
      expect(screen.queryByText("Đơn vị")).not.toBeInTheDocument()
    })

    it("officer does NOT see the Phân công group at all", () => {
      mockAuthState.role = "officer"
      setup()
      openFilters()
      expect(screen.queryByText("Phân công")).not.toBeInTheDocument()
      expect(screen.queryByText("Cán bộ phụ trách")).not.toBeInTheDocument()
    })

    it("toggling an officer checkbox calls onOfficerChange with the id", () => {
      mockAuthState.role = "admin"
      const props = setup()
      openFilters()
      fireEvent.click(screen.getByLabelText("Nguyễn Văn A"))
      expect(props.onOfficerChange).toHaveBeenCalledWith(["10"])
    })

    it('renders an officer chip and a "Chưa giao" chip', () => {
      const props = setup({ officerFilters: ["10"], unassigned: true })
      // officer chip resolves the name from the fetched list
      expect(screen.getByText(/Cán bộ: Nguyễn Văn A/)).toBeInTheDocument()
      const chuaGiao = screen.getByText("Chưa giao")
      expect(chuaGiao).toBeInTheDocument()
      fireEvent.click(screen.getByRole("button", { name: /bỏ lọc chưa giao/i }))
      expect(props.onUnassignedChange).toHaveBeenCalledWith(false)
    })
  })

  describe("payment + sort options", () => {
    it('offers a "Quá hạn" payment option', () => {
      setup()
      openFilters()
      expect(screen.getByText("Quá hạn")).toBeInTheDocument()
    })

    it('offers "Còn lại nhiều nhất" sort option', () => {
      setup()
      fireEvent.click(screen.getByRole("button", { name: /sắp xếp/i }))
      expect(screen.getByText("Còn lại nhiều nhất")).toBeInTheDocument()
    })
  })
})
