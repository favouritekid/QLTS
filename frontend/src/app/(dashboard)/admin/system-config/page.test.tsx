/**
 * Vitest anchor tests for the system-config admin page (Phase 3
 * close-out 2026-05-14). Verifies the table renders existing rows + the
 * edit dialog round-trips a value mutation through the mocked hook.
 *
 * Non-tautological per memory ``pattern-change-impact-audit``: the
 * mutation assertion checks the EXACT payload shape (``value`` parsed
 * back from the JSON-aware textarea), not just "mutate was called".
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import SystemConfigPage from "./page"

const mockMutateAsync = vi.fn()

vi.mock("@/hooks/admin/useSystemConfig", () => ({
  useSystemConfigList: () => ({
    data: {
      total: 2,
      items: [
        {
          key: "max_choices_per_profile",
          value: 5,
          description: "Số nguyện vọng tối đa mỗi hồ sơ (Phase 3 Q-P3-01)",
          updated_at: "2026-05-12T00:00:00Z",
          updated_by_user_id: 1,
        },
        {
          key: "current_intake_year",
          value: 2026,
          description: "Năm tuyển sinh hiện hành (storefront default)",
          updated_at: "2026-05-09T00:00:00Z",
          updated_by_user_id: 1,
        },
      ],
    },
    isLoading: false,
  }),
  useUpdateSystemConfig: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
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

describe("/admin/system-config page", () => {
  it("renders heading + the table of config rows", () => {
    render(wrap(<SystemConfigPage />))
    expect(screen.getByText("Cấu hình hệ thống")).toBeTruthy()
    expect(screen.getByText("max_choices_per_profile")).toBeTruthy()
    expect(screen.getByText("current_intake_year")).toBeTruthy()
  })

  it("ANCHOR (Phase 3 close-out): edit dialog seeds value + sends parsed JSON on save", async () => {
    mockMutateAsync.mockReset()
    render(wrap(<SystemConfigPage />))

    // Open edit dialog for max_choices_per_profile.
    const editBtn = screen.getByTestId("system-config-edit-max_choices_per_profile")
    fireEvent.click(editBtn)

    // Value textarea is seeded with the current value rendered as JSON
    // (number ``5`` → ``"5"`` so JSON.parse will round-trip back to int).
    const valueInput = screen.getByTestId(
      "system-config-value-input"
    ) as HTMLTextAreaElement
    expect(valueInput.value).toBe("5")

    // Admin edits to ``10``.
    fireEvent.change(valueInput, { target: { value: "10" } })

    // Submit and verify the mutation receives the parsed-int payload —
    // NOT the literal string "10". This is the contract that keeps the
    // BE engine reading an int via SystemConfigService.get_int.
    fireEvent.click(screen.getByTestId("system-config-submit"))

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledTimes(1)
    })
    expect(mockMutateAsync).toHaveBeenCalledWith({
      key: "max_choices_per_profile",
      data: {
        value: 10,
        description: "Số nguyện vọng tối đa mỗi hồ sơ (Phase 3 Q-P3-01)",
      },
    })
  })
})
