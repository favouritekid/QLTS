// src/components/forms/ConfirmAdmissionForm.test.tsx
/**
 * ConfirmAdmissionForm UI Contract Tests (PR-4)
 *
 * Covers the state machine the page renders based on `useConfirmTokenInfo`:
 *   - loading spinner
 *   - happy path form render + submit → success banner
 *   - already_used / locked / expired / !valid banners
 *   - wrong CCCD (400) → form stays mounted, token info query invalidated
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createTestQueryClient } from "@/test/utils/test-utils"

// Mock InputOTP (context-heavy) with a controlled single input — we
// only care about the value round-trip, not the OTP UI slot rendering.
vi.mock("@/components/ui/input-otp", () => ({
  InputOTP: ({
    value,
    onChange,
    disabled,
  }: {
    value: string
    onChange: (v: string) => void
    disabled?: boolean
  }) => (
    <input
      data-testid="cccd-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    />
  ),
  InputOTPGroup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  InputOTPSlot: () => null,
}))

// Mock sonner toasts so we can assert without touching a real toaster.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock the API layer the hook delegates to.
const mockGetConfirmTokenInfo = vi.fn()
const mockConfirmAdmissionByToken = vi.fn()
vi.mock("@/lib/api/admissions", () => ({
  getConfirmTokenInfo: (...args: unknown[]) => mockGetConfirmTokenInfo(...args),
  confirmAdmissionByToken: (...args: unknown[]) => mockConfirmAdmissionByToken(...args),
}))

// Mock handleApiError so we don't exercise its full behaviour — only care
// that the mutation onError path was reached.
const mockHandleApiError = vi.fn()
vi.mock("@/lib/error-handler", () => ({
  handleApiError: (...args: unknown[]) => mockHandleApiError(...args),
}))

// Import AFTER mocks
import { ConfirmAdmissionForm } from "./ConfirmAdmissionForm"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function withProviders(ui: React.ReactElement, client?: QueryClient) {
  const queryClient = client ?? createTestQueryClient()
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
  }
}

function buildInfo(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    valid: true,
    expired: false,
    locked: false,
    already_used: false,
    attempts_remaining: 5,
    profile_name: "Nguyễn Văn A",
    expires_at: "2026-04-25T10:00:00Z",
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ConfirmAdmissionForm", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders form with CCCD input when token info is valid", async () => {
    mockGetConfirmTokenInfo.mockResolvedValueOnce(buildInfo())

    withProviders(<ConfirmAdmissionForm token="t1" />)

    expect(
      await screen.findByRole("heading", { name: /xác nhận nhập học/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Nguyễn Văn A/)).toBeInTheDocument()
    expect(screen.getByTestId("cccd-input")).toBeInTheDocument()
  })

  it("renders attempts-remaining hint when attempts_remaining < 5", async () => {
    mockGetConfirmTokenInfo.mockResolvedValueOnce(
      buildInfo({ attempts_remaining: 3 }),
    )

    withProviders(<ConfirmAdmissionForm token="t1" />)

    await screen.findByRole("heading", { name: /xác nhận nhập học/i })
    expect(screen.getByText(/còn/i)).toBeInTheDocument()
    expect(screen.getByText(/3/)).toBeInTheDocument()
  })

  it("renders 'đã xác nhận trước đó' banner when already_used", async () => {
    mockGetConfirmTokenInfo.mockResolvedValueOnce(
      buildInfo({ already_used: true }),
    )

    withProviders(<ConfirmAdmissionForm token="t1" />)

    expect(
      await screen.findByText(/đã xác nhận trước đó/i),
    ).toBeInTheDocument()
    expect(screen.queryByTestId("cccd-input")).not.toBeInTheDocument()
  })

  it("renders 'bị khoá' banner when locked", async () => {
    mockGetConfirmTokenInfo.mockResolvedValueOnce(
      buildInfo({ locked: true, valid: false }),
    )

    withProviders(<ConfirmAdmissionForm token="t1" />)

    expect(await screen.findByText(/bị khoá/i)).toBeInTheDocument()
    expect(screen.queryByTestId("cccd-input")).not.toBeInTheDocument()
  })

  it("renders 'hết hạn' banner when expired", async () => {
    mockGetConfirmTokenInfo.mockResolvedValueOnce(
      buildInfo({ expired: true, valid: false }),
    )

    withProviders(<ConfirmAdmissionForm token="t1" />)

    // Title of the banner — specific match to avoid ambiguity with description text
    expect(
      await screen.findByText(/^Liên kết đã hết hạn$/),
    ).toBeInTheDocument()
    expect(screen.queryByTestId("cccd-input")).not.toBeInTheDocument()
  })

  it("renders 'không tìm thấy liên kết' banner when query errors", async () => {
    mockGetConfirmTokenInfo.mockRejectedValueOnce(new Error("network"))

    withProviders(<ConfirmAdmissionForm token="t1" />)

    expect(
      await screen.findByText(/không tìm thấy liên kết/i),
    ).toBeInTheDocument()
  })

  it("shows success banner after successful confirm", async () => {
    mockGetConfirmTokenInfo.mockResolvedValueOnce(buildInfo())
    mockConfirmAdmissionByToken.mockResolvedValueOnce({
      message: "ok",
      profile_id: 1,
      status: "confirmed",
      confirmed_at: "2026-04-20T10:00:00Z",
    })

    withProviders(<ConfirmAdmissionForm token="t1" />)

    // Wait for loaded form
    const input = await screen.findByTestId("cccd-input")
    fireEvent.change(input, { target: { value: "1234" } })

    const submit = screen.getByRole("button", { name: /xác nhận nhập học/i })
    fireEvent.click(submit)

    await waitFor(() => {
      expect(mockConfirmAdmissionByToken).toHaveBeenCalledWith("t1", {
        last_digits_citizen_id: "1234",
      })
    })

    // Success banner renders
    expect(
      await screen.findByText(/xác nhận nhập học thành công/i),
    ).toBeInTheDocument()
  })

  it("invalidates token info query on error (wrong CCCD → stateful refetch)", async () => {
    // First call: form-valid info; Second call (after invalidation): show locked
    mockGetConfirmTokenInfo
      .mockResolvedValueOnce(buildInfo({ attempts_remaining: 1 }))
      .mockResolvedValueOnce(buildInfo({ locked: true, valid: false }))

    mockConfirmAdmissionByToken.mockRejectedValueOnce(
      Object.assign(new Error("Bad CCCD"), {
        isAxiosError: true,
        response: { status: 400, data: { code: "VALIDATION_FAILED" } },
      }),
    )

    withProviders(<ConfirmAdmissionForm token="t1" />)

    const input = await screen.findByTestId("cccd-input")
    fireEvent.change(input, { target: { value: "9999" } })

    fireEvent.click(screen.getByRole("button", { name: /xác nhận nhập học/i }))

    // handleApiError called with our error
    await waitFor(() => expect(mockHandleApiError).toHaveBeenCalledTimes(1))

    // Refetch triggered → second getConfirmTokenInfo call with locked=true
    await waitFor(() => expect(mockGetConfirmTokenInfo).toHaveBeenCalledTimes(2))

    // After the refetch, the locked banner should eventually render
    expect(await screen.findByText(/bị khoá/i)).toBeInTheDocument()
  })
})
