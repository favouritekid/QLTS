/**
 * Vitest tests cho GlobalMatrixView (Phase 2 v8.2 PR-2D.1 v3).
 *
 * Anchor tests per memory pattern-change-impact-audit.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { GlobalMatrixView } from "./GlobalMatrixView"


vi.mock("@/hooks/admissions/useQuotaMatrix", () => ({
  useQuotaMatrix: () => ({
    data: {
      academic_year: 2026,
      total_rows: 1,
      rounds: [
        { id: 1, round_code: "DOT_1", round_name: "Đợt 1", is_active: true },
      ],
      rows: [
        {
          academic_info_id: 70,
          academic_year: 2026,
          program_name: "Công nghệ thông tin",
          program_code: "CNTT",
          degree_level: "DH",
          annual_admission_quota: 100,
          sum_admit_allocated: 30,
          sum_remaining: 70,
          cells_by_round_id: {
            1: {
              admission_round_id: 1,
              round_code: "DOT_1",
              total_admit_quota: 30,
              total_round_quota: 50,
              total_submission_count: 5,
              path_count: 2,
            },
          },
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  // Pass 2 hard-review F-2-2: AggregateDrawer (nested) dùng cùng module —
  // mock minimal shape để drawer render khi user click cell mở tổng hợp.
  usePathMatrixByMajor: () => ({
    data: undefined,
    isLoading: true,
  }),
}))

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("GlobalMatrixView", () => {
  it("renders matrix title + year + total badge", () => {
    render(
      wrap(<GlobalMatrixView academicYear={2026} onYearChange={() => {}} />),
    )
    expect(screen.getByText(/Ma trận toàn cảnh năm 2026/)).toBeTruthy()
    expect(screen.getByText(/1 ngành × 1 đợt/)).toBeTruthy()
  })

  it("renders aggregate cell theo contract 3-line: Admit/Annual + Submit + path_count", () => {
    render(
      wrap(<GlobalMatrixView academicYear={2026} onYearChange={() => {}} />),
    )
    // Cell aggregate dòng 1: total_admit_quota / annual_admission_quota
    expect(screen.getByText(/30 \/ 100/)).toBeTruthy()
    // Cell aggregate dòng 2: Submit cap
    expect(screen.getByText(/Submit 50/)).toBeTruthy()
    // Cell aggregate dòng 3: path_count
    expect(screen.getByText(/2 phương thức/)).toBeTruthy()
  })

  it("ANCHOR: shows ngành column với program_code", () => {
    render(
      wrap(<GlobalMatrixView academicYear={2026} onYearChange={() => {}} />),
    )
    expect(screen.getByText("Công nghệ thông tin")).toBeTruthy()
    expect(screen.getByText("CNTT")).toBeTruthy()
  })

  it("ANCHOR (cell read-only): cell rendered as button (not input/select)", () => {
    const { container } = render(
      wrap(<GlobalMatrixView academicYear={2026} onYearChange={() => {}} />),
    )
    // Cell phải render như button drill-down — không có input cho inline edit
    const cellButtons = container.querySelectorAll("button")
    const hasCellButton = Array.from(cellButtons).some((b) =>
      b.textContent?.includes("Submit"),
    )
    expect(hasCellButton).toBe(true)
    expect(container.querySelectorAll("input[type='number']").length).toBe(0)
  })

  // Pass 2 hard-review F-2-2: cell click → AggregateDrawer mở với context
  // đúng (academicInfoId + roundId + programName + roundCode). Tránh
  // regression khi refactor cell-to-drawer dispatch.
  it("ANCHOR (cell click → AggregateDrawer): mở drawer với context ngành+đợt", async () => {
    const user = userEvent.setup()
    render(
      wrap(<GlobalMatrixView academicYear={2026} onYearChange={() => {}} />),
    )
    // Click aggregate cell — aria-label chứa "Mở tổng hợp" + program_name + đợt.
    const cellButton = screen.getByLabelText(/Mở tổng hợp Công nghệ thông tin đợt DOT_1/)
    await user.click(cellButton)
    // AggregateDrawer hiển thị header với program_name + roundCode.
    await waitFor(() => {
      // Drawer header chứa "Đợt" + program_name + DOT_1.
      expect(screen.getAllByText(/DOT_1/).length).toBeGreaterThan(0)
    })
  })
})
