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
