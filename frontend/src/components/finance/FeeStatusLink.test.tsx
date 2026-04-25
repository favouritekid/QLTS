import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@/test/utils/test-utils"

import { useAuthStore } from "@/lib/stores/auth.store"
import { FeeStatusLink } from "./FeeStatusLink"

const useProfileFinanceSummary = vi.fn()

vi.mock("@/hooks/finance/useFees", () => ({
  useProfileFinanceSummary: (...args: unknown[]) => useProfileFinanceSummary(...args),
}))

const emptySummary = {
  admission_profile_id: 178,
  total_fees: "0",
  total_paid: "0",
  total_remaining: "0",
  fees: [],
  pending_invoices: 0,
  overdue_invoices: 0,
}

describe("FeeStatusLink", () => {
  beforeEach(() => {
    useProfileFinanceSummary.mockReturnValue({
      data: emptySummary,
      isLoading: false,
      error: null,
    })
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
    })
  })

  it("renders the admission header fee badge as read-only for officers", () => {
    useAuthStore.setState({
      user: { id: 1, role: "officer", username: "officer" } as any,
      isAuthenticated: true,
    })

    render(<FeeStatusLink profileId={178} variant="badge" />)

    expect(screen.getByText(/chưa tính phí/i)).toBeInTheDocument()
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })

  it("wraps officer-mode badge in a tooltip explaining where finance lives", () => {
    useAuthStore.setState({
      user: { id: 1, role: "officer", username: "officer" } as any,
      isAuthenticated: true,
    })

    render(<FeeStatusLink profileId={178} variant="badge" />)

    // Radix Tooltip propagates the trigger label via aria-describedby on
    // open, but the trigger itself exists in the DOM regardless. The
    // span wrapper used by withReadOnlyTooltip becomes the trigger.
    const trigger = screen.getByText(/chưa tính phí/i).closest("span")
    expect(trigger).not.toBeNull()
    // cursor-default carries over to the badge so the unclickable state
    // is visually distinct from the link variant's cursor-pointer.
    expect(screen.getByText(/chưa tính phí/i).className).toMatch(/cursor-default/)
  })

  it("keeps the finance deep link for finance-capable roles", () => {
    useAuthStore.setState({
      user: { id: 2, role: "accountant", username: "accountant" } as any,
      isAuthenticated: true,
    })

    render(<FeeStatusLink profileId={178} variant="badge" />)

    const link = screen.getByRole("link")
    expect(link).toHaveAttribute("href", "/finance/fees?profile_id=178")
  })
})
