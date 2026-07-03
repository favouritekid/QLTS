import { describe, it, expect, vi, beforeEach } from "vitest"
import { fireEvent, render, screen, waitFor } from "@/test/utils/test-utils"

import { useAuthStore } from "@/lib/stores/auth.store"
import { TuitionTab } from "./TuitionTab"

const useProfileFinanceSummary = vi.fn()
const { recordFeeMutateAsync } = vi.hoisted(() => ({
  recordFeeMutateAsync: vi.fn(),
}))

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

vi.mock("@/hooks/admissions", () => ({
  useRecordApplicationFeePayment: () => ({
    mutateAsync: recordFeeMutateAsync,
    isPending: false,
  }),
}))

const profile = {
  id: 178,
  status: "approved",
  permissions: { calculate_fee: true },
  available_actions: ["calculate_fee"],
  applied_rules: {
    application_fee: 0,
    requires_application_fee: false,
    fee_status: "exempt",
  },
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
      has_payable_invoice: false,
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
    recordFeeMutateAsync.mockReset()
    recordFeeMutateAsync.mockResolvedValue({ id: 178 })
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

  it("shows the QR button when the fee has a payable invoice (BE flag)", () => {
    useAuthStore.setState({
      user: { id: 1, role: "officer", username: "officer" } as any,
      isAuthenticated: true,
    })
    useProfileFinanceSummary.mockReturnValue({
      data: {
        ...summary,
        fees: [{ ...summary.fees[0], status: "partial", has_payable_invoice: true }],
      },
      isLoading: false,
      error: null,
    })

    render(<TuitionTab profile={profile as any} />)

    expect(
      screen.getByRole("button", { name: /mã qr chuyển khoản/i })
    ).toBeInTheDocument()
  })

  it("hides the QR button when has_payable_invoice is false, even if status looks payable", () => {
    // status 'partial' would have shown the button under the old status-derive
    // logic; the BE flag is now the single source (penalty-only / draft-next cases).
    useAuthStore.setState({
      user: { id: 1, role: "officer", username: "officer" } as any,
      isAuthenticated: true,
    })
    useProfileFinanceSummary.mockReturnValue({
      data: {
        ...summary,
        fees: [{ ...summary.fees[0], status: "partial", has_payable_invoice: false }],
      },
      isLoading: false,
      error: null,
    })

    render(<TuitionTab profile={profile as any} />)

    expect(
      screen.queryByRole("button", { name: /mã qr chuyển khoản/i })
    ).not.toBeInTheDocument()
  })
})

describe("TuitionTab application fee collection", () => {
  beforeEach(() => {
    useProfileFinanceSummary.mockReturnValue({
      data: summary,
      isLoading: false,
      error: null,
    })
    useAuthStore.setState({
      user: { id: 1, role: "officer", username: "officer" } as any,
      isAuthenticated: true,
    })
    recordFeeMutateAsync.mockReset()
    recordFeeMutateAsync.mockResolvedValue({ id: 178 })
  })

  it("shows the collection button only when backend grants the action", () => {
    render(<TuitionTab profile={makeApplicationFeeProfile()} />)

    expect(
      screen.getByRole("button", { name: /thu l/i })
    ).toBeInTheDocument()
  })

  it("hides the collection button when the backend flag is absent", () => {
    render(
      <TuitionTab
        profile={makeApplicationFeeProfile({
          permissions: { record_fee_payment: false },
          available_actions: [],
        })}
      />
    )

    expect(screen.queryByRole("button", { name: /thu l/i })).not.toBeInTheDocument()
  })

  it("does not collect when permissions deny even if available_actions drift", () => {
    render(
      <TuitionTab
        profile={makeApplicationFeeProfile({
          permissions: { record_fee_payment: false },
          available_actions: ["record_fee_payment"],
        })}
      />
    )

    expect(screen.queryByRole("button", { name: /thu l/i })).not.toBeInTheDocument()
  })

  it("renders receipt data for a paid application fee without a collect button", () => {
    render(
      <TuitionTab
        profile={makeApplicationFeeProfile({
          permissions: { record_fee_payment: false },
          available_actions: [],
          applied_rules: {
            application_fee: 100000,
            requires_application_fee: true,
            fee_status: "paid",
            fee_paid_at: "2026-06-07T08:30:00Z",
            fee_payment_data: {
              transaction_id: "PAID-001",
              amount: "100000",
              payment_method_code: "cash",
              paid_at: "2026-06-07T08:30:00Z",
              recorded_by: 7,
            },
          },
        })}
      />
    )

    expect(screen.getByText("PAID-001")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /thu l/i })).not.toBeInTheDocument()
  })

  it("submits the receipt and backend amount through the mutation", async () => {
    render(<TuitionTab profile={makeApplicationFeeProfile()} />)

    fireEvent.click(screen.getByRole("button", { name: /thu l/i }))
    fireEvent.change(screen.getByLabelText(/bi/i), {
      target: { value: "RCPT-001" },
    })
    fireEvent.click(screen.getByRole("button", { name: /x/i }))

    await waitFor(() => {
      expect(recordFeeMutateAsync).toHaveBeenCalledWith({
        transaction_id: "RCPT-001",
        amount: 100000,
        payment_method_code: "cash",
      })
    })
  })

  it("keeps the dialog open and shows backend errors", async () => {
    recordFeeMutateAsync.mockRejectedValueOnce({
      response: { data: { detail: "Receipt already used" } },
    })

    render(<TuitionTab profile={makeApplicationFeeProfile()} />)

    fireEvent.click(screen.getByRole("button", { name: /thu l/i }))
    fireEvent.change(screen.getByLabelText(/bi/i), {
      target: { value: "RCPT-ERR" },
    })
    fireEvent.click(screen.getByRole("button", { name: /x/i }))

    expect(await screen.findByText("Receipt already used")).toBeInTheDocument()
    expect(screen.getByLabelText(/bi/i)).toBeInTheDocument()
  })
})

function makeApplicationFeeProfile(overrides: Record<string, unknown> = {}) {
  return {
    ...profile,
    status: "submitted",
    permissions: { record_fee_payment: true },
    available_actions: ["record_fee_payment"],
    applied_rules: {
      application_fee: 100000,
      requires_application_fee: true,
      fee_status: "pending",
    },
    ...overrides,
  } as any
}
