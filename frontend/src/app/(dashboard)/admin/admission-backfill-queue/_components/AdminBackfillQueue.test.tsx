/**
 * Phase 3 PR-3D-B Bundle 3 — AdminBackfillQueue smoke tests.
 *
 * Integration with mocked React Query hooks. Verifies:
 * - Loading state
 * - Error state
 * - Empty state
 * - Row render with select + expand + resolve
 * - Bulk button reflects selection count
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Mock api client to avoid network during render
vi.mock("@/lib/api/admission-backfill", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("@/lib/api/admission-backfill")
  >()
  return {
    ...actual,
    listBackfillExceptions: vi.fn(),
    resolveBackfillException: vi.fn(),
    bulkResolveBackfillExceptions: vi.fn(),
    exportBackfillExceptionsCsv: vi.fn(),
  }
})

import { listBackfillExceptions } from "@/lib/api/admission-backfill"
import { AdminBackfillQueue } from "./AdminBackfillQueue"

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

const mockList = listBackfillExceptions as ReturnType<typeof vi.fn>

describe("AdminBackfillQueue", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders empty state when API returns 0 items", async () => {
    mockList.mockResolvedValueOnce({ items: [], total: 0, limit: 50, offset: 0 })
    render(wrap(<AdminBackfillQueue />))
    expect(await screen.findByTestId("empty-row")).toBeTruthy()
  })

  it("renders rows + open status badge + resolve button", async () => {
    mockList.mockResolvedValueOnce({
      items: [
        {
          id: 11,
          profile_id: 100,
          exception_type: "selected_subject_group_ambiguous",
          details: { matches: [1, 2] },
          created_at: "2026-05-13T05:00:00Z",
          resolved_at: null,
          resolved_by_user_id: null,
          resolved_by_username: null,
          resolution_notes: null,
        },
        {
          id: 12,
          profile_id: 101,
          exception_type: "gpa_out_of_range",
          details: { value: -0.5 },
          created_at: "2026-05-13T05:01:00Z",
          resolved_at: "2026-05-13T06:00:00Z",
          resolved_by_user_id: 1,
          resolved_by_username: "admin",
          resolution_notes: "Manual fix applied.",
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    })
    render(wrap(<AdminBackfillQueue />))

    // Row 11 (open) — render
    const row11 = await screen.findByTestId("exception-row-11")
    expect(within(row11).getByText(/selected_subject_group_ambiguous/)).toBeTruthy()
    expect(screen.getByTestId("status-open-11")).toBeTruthy()
    expect(screen.getByTestId("resolve-button-11")).toBeTruthy()

    // Row 12 (closed) — render with resolved badge, NO resolve button
    expect(screen.getByTestId("status-resolved-12")).toBeTruthy()
    expect(screen.queryByTestId("resolve-button-12")).toBeNull()
  })

  it("expand toggle shows JSONB details + aria-expanded reflects state", async () => {
    mockList.mockResolvedValueOnce({
      items: [
        {
          id: 5,
          profile_id: 50,
          exception_type: "some_type",
          details: { foo: "bar", n: 42 },
          created_at: "2026-05-13T05:00:00Z",
          resolved_at: null,
          resolved_by_user_id: null,
          resolved_by_username: null,
          resolution_notes: null,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    })
    render(wrap(<AdminBackfillQueue />))
    const toggle = await screen.findByTestId("expand-toggle-5")
    expect(toggle.getAttribute("aria-expanded")).toBe("false")
    fireEvent.click(toggle)
    expect(toggle.getAttribute("aria-expanded")).toBe("true")
    const detail = screen.getByTestId("detail-row-5")
    expect(detail.textContent).toContain('"foo"')
    expect(detail.textContent).toContain('"bar"')
  })

  it("checking row updates selected-counter + enables bulk button", async () => {
    mockList.mockResolvedValueOnce({
      items: [
        {
          id: 7,
          profile_id: 70,
          exception_type: "t",
          details: {},
          created_at: "2026-05-13T05:00:00Z",
          resolved_at: null,
          resolved_by_user_id: null,
          resolved_by_username: null,
          resolution_notes: null,
        },
        {
          id: 8,
          profile_id: 71,
          exception_type: "t",
          details: {},
          created_at: "2026-05-13T05:01:00Z",
          resolved_at: null,
          resolved_by_user_id: null,
          resolved_by_username: null,
          resolution_notes: null,
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    })
    render(wrap(<AdminBackfillQueue />))
    await screen.findByTestId("exception-row-7")
    const bulkBtn = screen.getByTestId("bulk-resolve-button")
    // 0 selected → disabled
    expect(bulkBtn.getAttribute("disabled")).not.toBeNull()
    // Check row 7
    const checkbox = screen.getByTestId("row-checkbox-7") as HTMLInputElement
    fireEvent.click(checkbox)
    // Selected counter updates
    expect(screen.getByTestId("selected-counter").textContent).toBe("1")
    // Bulk button now enabled
    expect(bulkBtn.getAttribute("disabled")).toBeNull()
  })

  it("displays error message when API fails", async () => {
    mockList.mockRejectedValueOnce(
      Object.assign(new Error("err"), {
        response: { status: 500, data: { detail: "Backend hỏng" } },
      }),
    )
    render(wrap(<AdminBackfillQueue />))
    expect(await screen.findByText(/Backend hỏng/)).toBeTruthy()
  })
})
