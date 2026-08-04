/**
 * Nút "Xuất" trên màn Thu học phí (PR-A / H1).
 *
 * Ca then chốt: **tab "Chờ duyệt" phải TẮT nút Xuất.** Tab đó là hàng đợi
 * PHIẾU THU (grain khác) và nó tắt hẳn truy vấn hoá đơn, nên bộ lọc lúc ấy
 * không mô tả tập hoá đơn nào — bấm xuất sẽ ra TOÀN BỘ hoá đơn trong khi người
 * dùng tưởng đang xuất danh sách đang xem. Sai lặng lẽ, không có gì báo.
 */

import type { ReactNode } from "react"
import { describe, expect, it, vi, beforeEach } from "vitest"
import { fireEvent, render, screen } from "@/test/utils/test-utils"

const exportMutate = vi.fn()

// ── Mock hạ tầng của màn hình (chỉ giữ những gì ảnh hưởng nút Xuất) ─────────
vi.mock("@/hooks/finance/useTuitionExport", () => ({
  useTuitionExport: () => ({ mutate: exportMutate, isPending: false }),
}))

const mockExportFilters = {
  status: "issued,partial",
  major_id: 37,
  officer_id: 12,
  academic_year: 2026,
}

const mockFilterState = {
  activeTab: "all",
  page: 1,
  pageSize: 20,
  search: "",
  feeType: "",
  sortBy: "priority",
  sortOrder: "asc",
  feeId: undefined,
  profileId: undefined,
  drawerProfileId: undefined,
  workspaceFilters: {},
}

vi.mock("@/hooks/finance/useInvoicesFilter", () => ({
  useInvoicesFilter: () => ({
    state: mockFilterState,
    handlers: {
      setPage: vi.fn(),
      handleSearchChange: vi.fn(),
      handleFeeTypeChange: vi.fn(),
      handleSortChange: vi.fn(),
      handleTabClick: vi.fn(),
      resetFilters: vi.fn(),
      openDrawer: vi.fn(),
      closeDrawer: vi.fn(),
      setWorkspaceFilter: vi.fn(),
    },
    hasActiveFilters: false,
    apiFilters: {},
    countFilters: {},
    // KHÁC RỖNG: nếu để {} thì assert payload không chứng minh được gì —
    // truyền nhầm bộ lọc rỗng vẫn xanh.
    exportFilters: mockExportFilters,
  }),
}))

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoices: () => ({
    data: { items: [], total: 3, page: 1, page_size: 20 },
    isLoading: false,
    isError: false,
    isFetching: false,
  }),
  useInvoiceStatusCounts: () => ({ data: undefined }),
  invoicesKeys: { all: ["invoices"], lists: () => ["invoices", "list"] },
}))

vi.mock("@/hooks/finance/useFinanceDashboard", () => ({
  useFinanceDashboard: () => ({ data: undefined }),
}))
vi.mock("@/hooks/admissions/useProgramData", () => ({
  useMajorPrograms: () => ({ data: [] }),
}))
vi.mock("@/hooks/useAdminUsers", () => ({
  useAdminUsersList: () => ({ data: undefined }),
}))
vi.mock("@/hooks/useOrganization", () => ({
  useOrganizationUnits: () => ({ data: undefined }),
  flattenOrganizationTree: () => [],
}))
// Không mock hook này thì component gọi thật /api/admission-config/years →
// MSW cảnh báo request ngoài phạm vi + AggregateError bẩn stderr, và test hết
// deterministic (phụ thuộc handler mặc định).
vi.mock("@/hooks/finance/useInvoiceFilterOptions", () => ({
  useInvoiceAcademicYears: () => ({ data: [] }),
  INVOICE_SEMESTER_OPTIONS: [1, 2, 3, 4, 5, 6, 7, 8] as const,
}))

// Tab "Chờ duyệt" render PendingPaymentsTab (dùng useRouter + hàng đợi riêng).
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/finance/invoices",
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  // PHẢI forward onSelect: bỏ nó đi thì không có cách nào bấm được mục trong
  // menu, và test "gửi đúng bộ lọc" trở thành không thể viết.
  DropdownMenuItem: ({
    children,
    onSelect,
  }: {
    children: ReactNode
    onSelect?: () => void
  }) => (
    <button type="button" onClick={() => onSelect?.()}>
      {children}
    </button>
  ),
}))

import { InvoiceListClient } from "./InvoiceListClient"

function exportButton() {
  return screen
    .getAllByRole("button")
    .find((b) => /Xuất|Đang xuất/.test(b.textContent ?? ""))
}

describe("InvoiceListClient — nút Xuất", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFilterState.activeTab = "all"
  })

  it("bật ở tab hoá đơn thường", () => {
    mockFilterState.activeTab = "all"
    render(<InvoiceListClient />)
    const btn = exportButton()
    expect(btn).toBeDefined()
    expect(btn).not.toBeDisabled()
  })

  it("[N] bấm Excel gửi ĐÚNG bộ lọc đang xem", async () => {
    mockFilterState.activeTab = "all"
    render(<InvoiceListClient />)
    const excelItem = screen
      .getAllByRole("button")
      .find((b) => /Excel/.test(b.textContent ?? ""))
    expect(excelItem).toBeDefined()
    fireEvent.click(excelItem!)

    expect(exportMutate).toHaveBeenCalledTimes(1)
    // Đổi InvoiceListClient thành mutate({format, filters: {}}) là ca này đỏ.
    expect(exportMutate).toHaveBeenCalledWith({
      format: "xlsx",
      filters: mockExportFilters,
    })
  })

  it("bấm CSV gửi đúng định dạng csv", () => {
    mockFilterState.activeTab = "all"
    render(<InvoiceListClient />)
    const csvItem = screen
      .getAllByRole("button")
      .find((b) => /CSV/.test(b.textContent ?? ""))
    fireEvent.click(csvItem!)
    expect(exportMutate).toHaveBeenCalledWith({
      format: "csv",
      filters: mockExportFilters,
    })
  })

  it("[N] TẮT ở tab 'Chờ duyệt' (hàng đợi phiếu thu, grain khác)", () => {
    mockFilterState.activeTab = "pending"
    render(<InvoiceListClient />)
    const btn = exportButton()
    expect(btn).toBeDefined()
    // Bỏ điều kiện isPendingTab là ca này đỏ — và bug quay lại im lặng:
    // xuất ra toàn bộ hoá đơn thay vì danh sách đang xem.
    expect(btn).toBeDisabled()
  })
})
