/**
 * Vitest tests for RoundsManagementTab year-level (Phase 2 v8.2 PR-2A v2).
 *
 * Top-level standalone tab (NOT drawer) — Q1 v8.2 workflow inversion.
 * Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { RoundsManagementTab } from "./RoundsManagementTab"

vi.mock("@/hooks/admissions/useAdmissionRounds", () => ({
  useAdmissionRounds: (year: number | null) => ({
    data: year === 2026
      ? {
          total: 2,
          items: [
            {
              id: 1,
              academic_year: 2026,
              round_code: "DOT_1",
              round_name: "Đợt 1 - 2026",
              start_date: "2026-03-01",
              end_date: "2026-06-30",
              is_active: true,
              archived_at: null,
              extended_at: null,
              extended_by_user_id: null,
              extension_reason: null,
              created_at: "2026-05-09T00:00:00Z",
              updated_at: "2026-05-09T00:00:00Z",
            },
            {
              id: 2,
              academic_year: 2026,
              round_code: "DOT_2",
              round_name: "Đợt 2 - 2026",
              start_date: null,
              end_date: null,
              is_active: false,
              archived_at: "2026-05-09T01:00:00Z",
              extended_at: null,
              extended_by_user_id: null,
              extension_reason: null,
              created_at: "2026-05-09T00:00:00Z",
              updated_at: "2026-05-09T01:00:00Z",
            },
          ],
        }
      : undefined,
    isLoading: false,
  }),
  useCreateRound: () => ({ mutateAsync: vi.fn() }),
  useBulkCreateRounds: () => ({ mutateAsync: vi.fn() }),
  useUpdateRound: () => ({ mutateAsync: vi.fn() }),
  useSoftArchiveRound: () => ({ mutateAsync: vi.fn() }),
  useExtendRound: () => ({ mutateAsync: vi.fn() }),
}))

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("RoundsManagementTab year-level", () => {
  it("renders top-level tab với year selector + action buttons", () => {
    render(wrap(<RoundsManagementTab />))
    // Top-level heading
    expect(screen.getByText("Đợt tuyển sinh")).toBeTruthy()
    // Year selector label
    expect(screen.getByText(/Năm học:/i)).toBeTruthy()
    // Action buttons
    expect(screen.getByRole("button", { name: /Tạo nhanh 4 đợt/i })).toBeTruthy()
    expect(screen.getByRole("button", { name: /Thêm đợt/i })).toBeTruthy()
  })

  it("renders rounds list when data loaded", () => {
    // Mock returns 2 rounds when year === 2026 (default current year).
    // Empty-state path requires year selector interaction (Vitest JSDOM
    // limitation với Radix Select portal — defer to Playwright e2e).
    render(wrap(<RoundsManagementTab />))
    // Both round codes visible
    expect(screen.getByText("DOT_1")).toBeTruthy()
    expect(screen.getByText("DOT_2")).toBeTruthy()
  })

  it("ANCHOR (P3-2 v8.2): renders Vietnamese status labels", () => {
    render(wrap(<RoundsManagementTab />))
    // DOT_1 active → "Đang hoạt động"
    expect(screen.getByText("Đang hoạt động")).toBeTruthy()
    // DOT_2 archived → "Đã lưu trữ"
    expect(screen.getByText("Đã lưu trữ")).toBeTruthy()
  })

  it("disables action buttons on archived rounds", () => {
    render(wrap(<RoundsManagementTab />))
    // 3 action button types: Sửa đợt, Gia hạn đợt, Lưu trữ đợt per row
    // DOT_2 archived → buttons disabled
    const editButtons = screen.getAllByRole("button", { name: /Sửa đợt/i })
    const extendButtons = screen.getAllByRole("button", { name: /Gia hạn đợt/i })
    const archiveButtons = screen.getAllByRole("button", { name: /Lưu trữ đợt/i })

    // 2 rows × 3 button types = 6 buttons, 3 disabled (archived row)
    expect(editButtons.length).toBe(2)
    expect(extendButtons.length).toBe(2)
    expect(archiveButtons.length).toBe(2)

    // Last row (DOT_2 archived) buttons should be disabled (P2-2 v8.2 —
    // idiomatic jest-dom matcher).
    expect(editButtons[1]).toBeDisabled()
    expect(extendButtons[1]).toBeDisabled()
    expect(archiveButtons[1]).toBeDisabled()
  })
})
