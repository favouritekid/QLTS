/**
 * Vitest tests cho ByMajorView (Phase 2 v8.2 PR-2D.1 v3).
 *
 * Anchor: cell = exact path (NOT aggregate) — read-only with status badge.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ByMajorView } from "./ByMajorView"

// Pass 2 hard-review F-2-1 prerequisite: ByMajorView dùng Next.js navigation
// hooks để sync ``?pathId`` URL param. Test mock cùng pattern với
// ``useAdmissionsFilter.test.ts``.
const replaceMock = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/admin/admission-config",
}))

vi.mock("@/hooks/admissions/useQuotaMatrix", () => ({
  useQuotaMatrix: () => ({
    data: {
      academic_year: 2026,
      total_rows: 1,
      rounds: [{ id: 1, round_code: "DOT_1", round_name: "Đợt 1", is_active: true }],
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
          cells_by_round_id: {},
        },
      ],
    },
  }),
  usePathMatrixByMajor: (academicInfoId: number | undefined) => ({
    data: academicInfoId === 70
      ? {
          academic_info_id: 70,
          academic_year: 2026,
          program_name: "Công nghệ thông tin",
          program_code: "CNTT",
          degree_level: "DH",
          annual_admission_quota: 100,
          sum_admit_allocated: 30,
          sum_remaining: 70,
          rounds: [
            { id: 1, round_code: "DOT_1", round_name: "Đợt 1", is_active: true },
          ],
          methods: [
            {
              admission_method_id: 1,
              method_code: "HB",
              method_name: "Học bạ",
              sum_admit_quota: 30,
              cells_by_round_id: {
                1: {
                  path_id: 106,
                  admission_round_id: 1,
                  admission_method_id: 1,
                  round_quota: 50,
                  admit_quota: 30,
                  submission_count: 5,
                  status: "active",
                  criteria_code: "HB2026_CNTT_DOT_1",
                },
              },
            },
          ],
        }
      : undefined,
    isLoading: false,
  }),
}))

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("ByMajorView", () => {
  beforeEach(() => {
    replaceMock.mockClear()
  })

  it("renders title + auto-select first ngành + load matrix", () => {
    render(wrap(<ByMajorView academicYear={2026} onYearChange={() => {}} />))
    expect(screen.getByText(/Cấu hình theo ngành/)).toBeTruthy()
    expect(screen.getByText("Học bạ")).toBeTruthy()
  })

  it("renders cell with 3-line contract: admit/annual + Submit + status badge", () => {
    render(wrap(<ByMajorView academicYear={2026} onYearChange={() => {}} />))
    expect(screen.getByText(/30 \/ 100/)).toBeTruthy()
    expect(screen.getByText(/Submit 50/)).toBeTruthy()
    expect(screen.getByText(/Đang hoạt động/)).toBeTruthy()
  })

  it("ANCHOR (per-major header): shows cap năm + đã rải + còn lại", () => {
    render(wrap(<ByMajorView academicYear={2026} onYearChange={() => {}} />))
    expect(screen.getByText(/Cap năm:/)).toBeTruthy()
    expect(screen.getByText(/Đã rải:/)).toBeTruthy()
    expect(screen.getByText(/Còn:/)).toBeTruthy()
  })

  it("ANCHOR (read-only): cells rendered as button (no inline input)", () => {
    const { container } = render(
      wrap(<ByMajorView academicYear={2026} onYearChange={() => {}} />),
    )
    expect(container.querySelectorAll("input[type='number']").length).toBe(0)
  })

  // Pass 2 hard-review F-2-2: regression cho ngành dropdown — đảm bảo
  // dropdown trigger render với ngành option khả dụng. Test ngành change
  // → matrix re-fetch không thực hiện được vì hook mock tĩnh, nhưng test
  // dropdown options có ngành đúng tránh regression khi refactor data flow.
  it("ANCHOR (ngành dropdown): trigger render + ngành option có sẵn", () => {
    render(wrap(<ByMajorView academicYear={2026} onYearChange={() => {}} />))
    expect(screen.getByText(/Ngành:/)).toBeTruthy()
    // SelectTrigger hiển thị ngành đã auto-select.
    expect(screen.getAllByText("Công nghệ thông tin").length).toBeGreaterThan(0)
  })

  // Pass 2 hard-review F-2-2: cell click → setOpenPathId qua URL replace.
  // Verify router.replace gọi với ?pathId=N khi user click cell active.
  it("ANCHOR (cell click → URL sync): click cell active emit replace với ?pathId", async () => {
    const user = userEvent.setup()
    render(wrap(<ByMajorView academicYear={2026} onYearChange={() => {}} />))
    // Cell button có aria-label chứa method_name + đợt — pick by partial match.
    const cellButton = screen.getByLabelText(/Mở chi tiết Học bạ/)
    await user.click(cellButton)
    expect(replaceMock).toHaveBeenCalled()
    const callArg = replaceMock.mock.calls[0][0] as string
    expect(callArg).toContain("pathId=106")
  })
})
