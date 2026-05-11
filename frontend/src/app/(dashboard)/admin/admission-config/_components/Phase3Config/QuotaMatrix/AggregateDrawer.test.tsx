/**
 * Vitest tests cho AggregateDrawer (Phase 2 v8.2 PR-2D.1 v3).
 *
 * Anchor: drawer chỉ filter cells thuộc round được click (NOT all rounds).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { AggregateDrawer } from "./AggregateDrawer"

// Pass 2 hard-review F-2-2: PathDetailDrawer (nested) dùng useAdmissionPath
// + useUpdatePathQuota; mock cả 2 module để drill-down render an toàn.
vi.mock("@/hooks/admissions/useAdmissionPaths", () => ({
  useAdmissionPath: () => ({ data: undefined, isLoading: true }),
  useUpdateAdmissionPath: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useActivateAdmissionPath: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeactivateAdmissionPath: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock("@/hooks/admissions/useQuotaMatrix", () => ({
  usePathMatrixByMajor: () => ({
    data: {
      academic_info_id: 70,
      academic_year: 2026,
      program_name: "Công nghệ thông tin",
      program_code: "CNTT",
      degree_level: "DH",
      annual_admission_quota: 100,
      sum_admit_allocated: 80,
      sum_remaining: 20,
      rounds: [
        { id: 1, round_code: "DOT_1", round_name: "Đợt 1", is_active: true },
        { id: 2, round_code: "DOT_2", round_name: "Đợt 2", is_active: true },
      ],
      methods: [
        {
          admission_method_id: 1,
          method_code: "HB",
          method_name: "Học bạ",
          sum_admit_quota: 50,
          cells_by_round_id: {
            1: {
              path_id: 106,
              admission_round_id: 1,
              admission_method_id: 1,
              round_quota: 50,
              admit_quota: 30,
              submission_count: 5,
              status: "active",
              criteria_code: "HB_DOT_1",
            },
            2: {
              path_id: 107,
              admission_round_id: 2,
              admission_method_id: 1,
              round_quota: 40,
              admit_quota: 20,
              submission_count: 0,
              status: "draft",
              criteria_code: "HB_DOT_2",
            },
          },
        },
        {
          admission_method_id: 3,
          method_code: "THPT",
          method_name: "THPT",
          sum_admit_quota: 30,
          cells_by_round_id: {
            1: {
              path_id: 108,
              admission_round_id: 1,
              admission_method_id: 3,
              round_quota: 60,
              admit_quota: 30,
              submission_count: 2,
              status: "active",
              criteria_code: "THPT_DOT_1",
            },
            2: null,
          },
        },
      ],
    },
    isLoading: false,
  }),
}))

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("AggregateDrawer", () => {
  it("renders header với program_name + đợt selected", () => {
    render(
      wrap(
        <AggregateDrawer
          academicInfoId={70}
          roundId={1}
          programName="Công nghệ thông tin"
          roundCode="DOT_1"
          onClose={() => {}}
        />,
      ),
    )
    expect(screen.getByText("Công nghệ thông tin")).toBeTruthy()
    expect(screen.getByText(/Đợt/)).toBeTruthy()
    expect(screen.getByText("DOT_1")).toBeTruthy()
  })

  it("ANCHOR (round filter): DOT_1 lists 2 methods (HB + THPT)", () => {
    render(
      wrap(
        <AggregateDrawer
          academicInfoId={70}
          roundId={1}
          programName="CNTT"
          roundCode="DOT_1"
          onClose={() => {}}
        />,
      ),
    )
    expect(screen.getByText("Học bạ")).toBeTruthy()
    // method_name + method_code đều là "THPT" → 2 occurrences
    expect(screen.getAllByText("THPT").length).toBeGreaterThan(0)
    expect(screen.getByText(/2 phương thức/)).toBeTruthy()
  })

  it("ANCHOR (filter DOT_2): method có cell null ở DOT_2 KHÔNG xuất hiện", () => {
    render(
      wrap(
        <AggregateDrawer
          academicInfoId={70}
          roundId={2}
          programName="CNTT"
          roundCode="DOT_2"
          onClose={() => {}}
        />,
      ),
    )
    // DOT_2: HB có cell nhưng THPT cell=null → THPT method row không render
    expect(screen.getByText("Học bạ")).toBeTruthy()
    expect(screen.queryByText("THPT")).toBeNull()
    // 1 method only
    expect(screen.getByText(/1 phương thức/)).toBeTruthy()
  })

  it("renders summary box với cap năm + sum_admit_allocated + còn lại", () => {
    render(
      wrap(
        <AggregateDrawer
          academicInfoId={70}
          roundId={1}
          programName="CNTT"
          roundCode="DOT_1"
          onClose={() => {}}
        />,
      ),
    )
    expect(screen.getByText(/Cap năm:/)).toBeTruthy()
    expect(screen.getByText(/Đã rải toàn ngành:/)).toBeTruthy()
    expect(screen.getByText("100")).toBeTruthy()
    expect(screen.getByText("80")).toBeTruthy()
  })

  // Pass 2 hard-review F-2-2: ChevronRight click → PathDetailDrawer nested
  // mở với pathId đúng. Verify drill-down flow + tránh regression khi
  // refactor button-to-drawer dispatch trong AggregateDrawer.
  it("ANCHOR (drill-down): ChevronRight click → PathDetailDrawer nested", async () => {
    const user = userEvent.setup()
    render(
      wrap(
        <AggregateDrawer
          academicInfoId={70}
          roundId={1}
          programName="CNTT"
          roundCode="DOT_1"
          onClose={() => {}}
        />,
      ),
    )
    // ChevronRight button có aria-label "Mở chi tiết đường <method_name>".
    const drillBtn = screen.getByLabelText(/Mở chi tiết đường Học bạ/)
    await user.click(drillBtn)
    // PathDetailDrawer hiển thị fallback title "Đường tuyển sinh #<pathId>"
    // khi data chưa load (mocked isLoading=true) — pathId=106 cho HB DOT_1.
    await waitFor(() => {
      expect(screen.getByText(/Đường tuyển sinh #106/)).toBeTruthy()
    })
  })
})
