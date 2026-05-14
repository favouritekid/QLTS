/**
 * Vitest tests for RoundsManagementTab year-level (Phase 2 v8.2 PR-2A v2).
 *
 * Top-level standalone tab (NOT drawer) — Q1 v8.2 workflow inversion.
 * Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
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
              // Phase 3 close-out 2026-05-14 — Q-P3-02 / Q-P3-06 fields
              // surfaced via this PR. DOT_1 in this fixture is the
              // "multi-NV enabled" round; DOT_2 below stays at server
              // default (false / 168h) so the form can assert both paths.
              allow_multi_nv: true,
              confirm_expiry_hours: 72,
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
              allow_multi_nv: false,
              confirm_expiry_hours: 168,
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
  // Hotfix: restore round hook đã thêm trong CHECKPOINT 2 nhưng test mock
  // chưa cover → component crash khi import useRestoreRound.
  useRestoreRound: () => ({ mutateAsync: vi.fn() }),
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
    // CHECKPOINT 2 (2026-05-10): restore round feature thay Lưu trữ button
    // bằng Khôi phục cho rows đã archive. Test-debt fix 2026-05-11:
    // archive button count đổi 2 → 1 (chỉ row active còn Lưu trữ); thêm
    // restoreButtons assertion cho row archived.
    const editButtons = screen.getAllByRole("button", { name: /Sửa đợt/i })
    const extendButtons = screen.getAllByRole("button", { name: /Gia hạn đợt/i })
    const archiveButtons = screen.getAllByRole("button", { name: /Lưu trữ đợt/i })
    const restoreButtons = screen.getAllByRole("button", { name: /Khôi phục đợt/i })

    // 2 rows total. Active row (DOT_1): Sửa + Gia hạn + Lưu trữ.
    // Archived row (DOT_2): Sửa (disabled) + Gia hạn (disabled) + Khôi phục.
    expect(editButtons.length).toBe(2)
    expect(extendButtons.length).toBe(2)
    expect(archiveButtons.length).toBe(1)  // chỉ trên DOT_1 active
    expect(restoreButtons.length).toBe(1)  // chỉ trên DOT_2 archived

    // Last row (DOT_2 archived) Sửa + Gia hạn buttons disabled
    expect(editButtons[1]).toBeDisabled()
    expect(extendButtons[1]).toBeDisabled()
    // Restore button trên archived row KHÔNG bị disabled (admin có thể
    // restore đợt đã archive bất kỳ lúc nào).
    expect(restoreButtons[0]).not.toBeDisabled()
  })

  it("ANCHOR (Phase 3 close-out 2026-05-14): edit dialog seeds 2 Phase 3 fields from row", () => {
    // Regression guard: if roundToFormState() ever drops the new Phase 3
    // fields, the edit dialog will open with defaults (false / 168) for
    // DOT_1 even though the row has (true / 72). The form would then
    // silently overwrite the persisted multi-NV flag on next save —
    // exactly the failure mode this anchor catches.
    render(wrap(<RoundsManagementTab />))

    // Open DOT_1 edit dialog. The fixture says DOT_1 has
    // allow_multi_nv=true + confirm_expiry_hours=72.
    const editButtons = screen.getAllByRole("button", { name: /Sửa đợt/i })
    fireEvent.click(editButtons[0])

    // Checkbox state mirrors the seeded value: TRUE for DOT_1.
    const allowMultiNvCheckbox = screen.getByLabelText(
      /Cho phép nhiều nguyện vọng/i
    ) as HTMLInputElement
    // Radix Checkbox reflects state via data-state="checked"; standard
    // checked attribute also flips for accessibility.
    expect(allowMultiNvCheckbox.getAttribute("data-state")).toBe("checked")

    // NumberInput seeded with row.confirm_expiry_hours.
    const expiryInput = screen.getByLabelText(
      /Thời hạn xác nhận nhập học/i
    ) as HTMLInputElement
    expect(expiryInput.value).toBe("72")
  })
})
