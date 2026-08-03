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
import { render, screen } from "@/test/utils/test-utils"

const exportMutate = vi.fn()

// ── Mock hạ tầng của màn hình (chỉ giữ những gì ảnh hưởng nút Xuất) ─────────
vi.mock("@/hooks/finance/useTuitionExport", () => ({
  useTuitionExport: () => ({ mutate: exportMutate, isPending: false }),
}))

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
    exportFilters: {},
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
  DropdownMenuItem: ({ children }: { children: ReactNode }) => (
    <button type="button">{children}</button>
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
