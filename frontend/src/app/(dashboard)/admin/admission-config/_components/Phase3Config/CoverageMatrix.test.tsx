/**
 * Vitest tests cho CoverageMatrix (PR matrix-funnel — readiness nhóm-theo-đợt).
 *
 * Anchor: rows nhóm theo admission_round_id, sort theo round_code, mỗi nhóm
 * 1 section header (round_name + code + badge mở/đóng); rows con render dưới.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { CoverageMatrix } from "./CoverageMatrix"

const searchParamsMock = vi.fn(() => new URLSearchParams("academicInfo=70"))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => searchParamsMock(),
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
}))

// Rows cố tình xếp DOT_2 trước DOT_1 để chứng minh sort theo round_code.
vi.mock("@/hooks/admissions/useAdmissionPaths", () => ({
  useCoverageMatrix: () => ({
    data: {
      academic_info_id: 70,
      total_paths: 3,
      paths_ready: 2,
      all_ready: false,
      rows: [
        {
          path_id: 2,
          method_name: "THPT QG",
          method_code: "thpt_qg",
          status: "draft",
          admission_round_id: 5,
          round_code: "DOT_2",
          round_name: "Đợt 2 - 2026",
          round_is_active: false,
          has_criteria: true,
          has_documents: true,
          has_quota: true,
          can_activate: true,
          validation_errors: [],
        },
        {
          path_id: 1,
          method_name: "Học bạ",
          method_code: "hoc_ba",
          status: "active",
          admission_round_id: 1,
          round_code: "DOT_1",
          round_name: "Đợt 1 - 2026",
          round_is_active: true,
          has_criteria: true,
          has_documents: false,
          has_quota: true,
          can_activate: false,
          validation_errors: ["Chưa cấu hình hồ sơ (Documents)"],
        },
        {
          path_id: 3,
          method_name: "Xét tuyển thẳng",
          method_code: "xet_tuyen_thang",
          status: "active",
          admission_round_id: 1,
          round_code: "DOT_1",
          round_name: "Đợt 1 - 2026",
          round_is_active: true,
          has_criteria: true,
          has_documents: true,
          has_quota: true,
          can_activate: true,
          validation_errors: [],
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

describe("CoverageMatrix — nhóm theo đợt", () => {
  it("renders 1 section header mỗi đợt (round_name + code)", () => {
    render(wrap(<CoverageMatrix academicYear={2026} onYearChange={() => {}} />))
    // 2 đợt → 2 section header (1 lần mỗi tên đợt, dù DOT_1 có 2 path).
    expect(screen.getAllByText("Đợt 1 - 2026")).toHaveLength(1)
    expect(screen.getAllByText("Đợt 2 - 2026")).toHaveLength(1)
    expect(screen.getByText("(DOT_1)")).toBeTruthy()
    expect(screen.getByText("(DOT_2)")).toBeTruthy()
  })

  it("sort section theo round_code: DOT_1 trước DOT_2", () => {
    render(wrap(<CoverageMatrix academicYear={2026} onYearChange={() => {}} />))
    const headers = screen.getAllByText(/Đợt \d - 2026/)
    expect(headers[0].textContent).toContain("Đợt 1")
    expect(headers[1].textContent).toContain("Đợt 2")
  })

  it("badge trạng thái đợt: round_is_active=true → Đang mở, false → Đã đóng", () => {
    render(wrap(<CoverageMatrix academicYear={2026} onYearChange={() => {}} />))
    expect(screen.getByText("Đang mở")).toBeTruthy()
    expect(screen.getByText("Đã đóng")).toBeTruthy()
  })

  it("rows con render dưới header (3 phương thức)", () => {
    render(wrap(<CoverageMatrix academicYear={2026} onYearChange={() => {}} />))
    expect(screen.getByText("Học bạ")).toBeTruthy()
    expect(screen.getByText("THPT QG")).toBeTruthy()
    expect(screen.getByText("Xét tuyển thẳng")).toBeTruthy()
  })
})
