import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@/test/utils/test-utils"
import { fireEvent } from "@testing-library/react"
import { AdmissionsFilterBar, type AdmissionsFilterBarProps } from "./AdmissionsFilterBar"
import { CURRENT_ADMISSIONS_YEAR } from "@/hooks/admissions/filterDefaults"

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
    onReset: vi.fn(),
    ...overrides,
  }
  render(<AdmissionsFilterBar {...props} />)
  return props
}

describe("AdmissionsFilterBar", () => {
  it("forwards the search input value", () => {
    const props = setup()
    fireEvent.change(screen.getByLabelText(/tìm kiếm hồ sơ/i), { target: { value: "an" } })
    expect(props.onSearchChange).toHaveBeenCalledWith("an")
  })

  it("renders a chip per active status filter; removing it calls onStatusChange", () => {
    const props = setup({ statusFilters: ["submitted"] })
    expect(screen.getByText("Chờ duyệt")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /bỏ lọc chờ duyệt/i }))
    expect(props.onStatusChange).toHaveBeenCalledWith([])
  })

  it("counts active filter GROUPS on the Bộ lọc badge (status = 1 group)", () => {
    // status group (1) + payment group (1) = 2
    setup({ statusFilters: ["submitted", "approved"], paymentStatusFilter: "paid" })
    expect(screen.getByText("2")).toBeInTheDocument()
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
})
