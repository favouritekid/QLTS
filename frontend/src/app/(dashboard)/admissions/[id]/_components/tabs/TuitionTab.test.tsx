import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@/test/utils/test-utils"

import { useAuthStore } from "@/lib/stores/auth.store"
import { TuitionTab } from "./TuitionTab"

const useProfileFinanceSummary = vi.fn()

vi.mock("@/hooks/finance/useFees", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/finance/useFees")>(
    "@/hooks/finance/useFees"
  )
  return {
    ...actual,
    useProfileFinanceSummary: (...args: unknown[]) => useProfileFinanceSummary(...args),
  }
})

vi.mock("@/hooks/finance/useInstallmentPlans", () => ({
  useInstallmentPlans: () => ({
    data: [{ id: 1, code: "FULL", name: "Thanh toán 1 lần", is_active: true, schedule: [] }],
    isLoading: false,
  }),
}))

const profile = {
  id: 178,
  status: "approved",
  available_actions: ["calculate_fee"],
}

const summary = {
  admission_profile_id: 178,
  total_fees: "10000000",
  total_paid: "0",
  total_remaining: "10000000",
  fees: [
    {
      id: 501,
      fee_type: "tuition",
      academic_year: "2026",
      semester_no: 1,
      final_amount: "10000000",
      paid_amount: "0",
      remaining_amount: "10000000",
      status: "calculated",
    },
  ],
  pending_invoices: 1,
  overdue_invoices: 0,
}

describe("TuitionTab finance module links", () => {
  beforeEach(() => {
    useProfileFinanceSummary.mockReturnValue({
      data: summary,
      isLoading: false,
      error: null,
    })
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
    })
  })

  it("does not render /finance deep links for officers", () => {
    useAuthStore.setState({
      user: { id: 1, role: "officer", username: "officer" } as any,
      isAuthenticated: true,
    })

    render(<TuitionTab profile={profile as any} />)

    expect(screen.getByText("Finance")).toBeInTheDocument()
    expect(document.querySelector('a[href^="/finance"]')).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /tính lại/i })).toBeInTheDocument()
  })

  it("keeps /finance deep links for accountants", () => {
    useAuthStore.setState({
      user: { id: 2, role: "accountant", username: "accountant" } as any,
      isAuthenticated: true,
    })

    render(<TuitionTab profile={profile as any} />)

    expect(screen.getByRole("link", { name: /quản lý trong finance/i })).toHaveAttribute(
      "href",
      "/finance/fees?profile_id=178"
    )
    expect(document.querySelector('a[href="/finance/fees/501"]')).toBeInTheDocument()
  })
})
