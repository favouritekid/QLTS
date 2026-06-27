import { describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"
import { fireEvent, render, screen } from "@/test/utils/test-utils"

import { InvoiceFilterBar } from "./InvoiceFilterBar"
import type { InvoiceWorkspaceFilters } from "@/types/finance.types"

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  DropdownMenuItem: ({
    children,
    onClick,
  }: {
    children: ReactNode
    onClick?: () => void
  }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
}))

function renderFilterBar(workspaceFilters: InvoiceWorkspaceFilters = {}) {
  const setWorkspaceFilter = vi.fn()

  render(
    <InvoiceFilterBar
      search=""
      onSearchChange={vi.fn()}
      feeType=""
      onFeeTypeChange={vi.fn()}
      sortBy="priority"
      sortOrder="asc"
      onSortChange={vi.fn()}
      hasActiveFilters={Object.keys(workspaceFilters).length > 0}
      onReset={vi.fn()}
      workspaceFilters={workspaceFilters}
      setWorkspaceFilter={setWorkspaceFilter}
      majorOptions={[{ id: 11, name: "Công nghệ thông tin", degree_level: "Cao đẳng" }]}
      academicYearOptions={[2026, 2025]}
      semesterOptions={[1, 2, 3]}
      officerOptions={[{ id: 21, name: "Nguyễn Tư Vấn" }]}
      unitOptions={[{ id: 31, name: "Cơ sở 1", level: 0 }]}
    />,
  )

  return setWorkspaceFilter
}

describe("InvoiceFilterBar", () => {
  it("sets academic year, semester, officer, and unit workspace filters", () => {
    const setWorkspaceFilter = renderFilterBar()

    fireEvent.click(screen.getByText("2026"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("academic_year", 2026)

    fireEvent.click(screen.getByText("HK2"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("semester_no", 2)

    fireEvent.click(screen.getByText("Nguyễn Tư Vấn"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("officer_id", 21)

    fireEvent.click(screen.getByText("Cơ sở 1"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("unit_id", 31)
  })

  it("renders chips that clear the new workspace filters", () => {
    const setWorkspaceFilter = renderFilterBar({
      academic_year: 2026,
      semester_no: 2,
      officer_id: 21,
      unit_id: 31,
    })

    fireEvent.click(screen.getByLabelText("Bỏ lọc Năm: 2026"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("academic_year", undefined)

    fireEvent.click(screen.getByLabelText("Bỏ lọc HK: 2"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("semester_no", undefined)

    fireEvent.click(screen.getByLabelText("Bỏ lọc TVV: Nguyễn Tư Vấn"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("officer_id", undefined)

    fireEvent.click(screen.getByLabelText("Bỏ lọc Đơn vị: Cơ sở 1"))
    expect(setWorkspaceFilter).toHaveBeenCalledWith("unit_id", undefined)
  })
})
