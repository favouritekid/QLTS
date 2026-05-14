// src/components/forms/MagicLinkConsumeForm.test.tsx
/**
 * MagicLinkConsumeForm UI Contract Tests (PR-CO-2-FE / PR-3E)
 *
 * Covers:
 *   - per-action title + button label render for all 4 actions
 *   - form validation (empty submit blocked, 4-digit regex enforced)
 *   - happy path → success banner + success toast
 *   - error path (BE 400) → handleApiError called, input reset, form stays mounted
 *   - per-action mutation payload + URL action sent unchanged
 *
 * Non-tautological: API mock fn is asserted with exact (action, token, body)
 * tuple per memory `pattern-change-impact-audit`.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { createTestQueryClient } from "@/test/utils/test-utils"
import type { MagicLinkAction } from "@/lib/zod/magic-link"

// Mock InputOTP with a controlled single input — round-trip value only.
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

// Mock sonner toast.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock the API client function the hook delegates to. Capture
// (action, token, body) for assertion.
const mockConsumeMagicLinkToken = vi.fn()
vi.mock("@/lib/api/magic-link", () => ({
  consumeMagicLinkToken: (...args: unknown[]) =>
    mockConsumeMagicLinkToken(...args),
}))

// Mock handleApiError so we don't render its toasts; just verify the
// onError branch was reached.
const mockHandleApiError = vi.fn()
vi.mock("@/lib/error-handler", () => ({
  handleApiError: (...args: unknown[]) => mockHandleApiError(...args),
}))

// Import AFTER mocks
import { MagicLinkConsumeForm } from "./MagicLinkConsumeForm"
import { toast } from "sonner"

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

function buildSuccessResponse(
  action: MagicLinkAction,
  status: string = "confirmed",
) {
  return {
    message: "Yêu cầu đã được xử lý thành công.",
    profile_id: 42,
    action,
    status,
    consumed_at: "2026-05-14T10:00:00Z",
    next_url: null,
  }
}

// ---------------------------------------------------------------------------
// Per-action render tests
// ---------------------------------------------------------------------------

describe("MagicLinkConsumeForm — per-action render", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it.each([
    ["confirm" as MagicLinkAction, /xác nhận nhập học/i, /xác nhận nhập học/i],
    ["submit" as MagicLinkAction, /gửi hồ sơ tuyển sinh/i, /gửi hồ sơ/i],
    ["resubmit" as MagicLinkAction, /nộp lại hồ sơ/i, /nộp lại/i],
    ["withdraw" as MagicLinkAction, /rút hồ sơ tuyển sinh/i, /xác nhận rút hồ sơ/i],
  ])(
    "action=%s renders correct heading + button label",
    (action, titleRegex, buttonRegex) => {
      withProviders(<MagicLinkConsumeForm action={action} token="t1" />)

      expect(
        screen.getByRole("heading", { name: titleRegex }),
      ).toBeInTheDocument()
      // data-testid is stable across action labels — assert text on it
      const submitBtn = screen.getByTestId("magic-link-submit")
      expect(submitBtn).toBeInTheDocument()
      expect(submitBtn).toHaveTextContent(buttonRegex)
      expect(screen.getByTestId("cccd-input")).toBeInTheDocument()
    },
  )
})

// ---------------------------------------------------------------------------
// Form validation tests
// ---------------------------------------------------------------------------

describe("MagicLinkConsumeForm — validation", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("blocks submit when CCCD is empty (zod regex fails)", async () => {
    withProviders(<MagicLinkConsumeForm action="confirm" token="t1" />)

    fireEvent.click(screen.getByTestId("magic-link-submit"))

    await waitFor(() => {
      expect(mockConsumeMagicLinkToken).not.toHaveBeenCalled()
    })
    expect(screen.getByText(/vui lòng nhập đúng 4 chữ số/i)).toBeInTheDocument()
  })

  it("blocks submit when CCCD contains non-digits", async () => {
    withProviders(<MagicLinkConsumeForm action="confirm" token="t1" />)

    fireEvent.change(screen.getByTestId("cccd-input"), {
      target: { value: "12ab" },
    })
    fireEvent.click(screen.getByTestId("magic-link-submit"))

    await waitFor(() => {
      expect(mockConsumeMagicLinkToken).not.toHaveBeenCalled()
    })
    expect(screen.getByText(/vui lòng nhập đúng 4 chữ số/i)).toBeInTheDocument()
  })

  it("blocks submit when CCCD is < 4 digits", async () => {
    withProviders(<MagicLinkConsumeForm action="confirm" token="t1" />)

    fireEvent.change(screen.getByTestId("cccd-input"), {
      target: { value: "12" },
    })
    fireEvent.click(screen.getByTestId("magic-link-submit"))

    await waitFor(() => {
      expect(mockConsumeMagicLinkToken).not.toHaveBeenCalled()
    })
    // Strengthen non-tautological: assert the user-visible validation
    // message renders, otherwise the test only proves react-hook-form's
    // default-block behaviour rather than this schema's 4-digit rule.
    expect(screen.getByText(/vui lòng nhập đúng 4 chữ số/i)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Happy path test
// ---------------------------------------------------------------------------

describe("MagicLinkConsumeForm — happy path", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("submits (action, token, body) and renders success banner", async () => {
    mockConsumeMagicLinkToken.mockResolvedValueOnce(
      buildSuccessResponse("confirm"),
    )

    withProviders(<MagicLinkConsumeForm action="confirm" token="tok123" />)

    fireEvent.change(screen.getByTestId("cccd-input"), {
      target: { value: "1234" },
    })
    fireEvent.click(screen.getByTestId("magic-link-submit"))

    await waitFor(() => {
      expect(mockConsumeMagicLinkToken).toHaveBeenCalledWith(
        "confirm",
        "tok123",
        { cccd: "1234" },
      )
    })

    // Success banner replaces the form
    expect(
      await screen.findByText(/xác nhận nhập học thành công/i),
    ).toBeInTheDocument()
    expect(toast.success).toHaveBeenCalled()
    // Form input is unmounted in the success state
    expect(screen.queryByTestId("cccd-input")).not.toBeInTheDocument()
  })

  it("threads the URL action through to the API mock unchanged (submit)", async () => {
    mockConsumeMagicLinkToken.mockResolvedValueOnce(
      buildSuccessResponse("submit", "submitted"),
    )

    withProviders(<MagicLinkConsumeForm action="submit" token="tok-sub" />)

    fireEvent.change(screen.getByTestId("cccd-input"), {
      target: { value: "9876" },
    })
    fireEvent.click(screen.getByTestId("magic-link-submit"))

    await waitFor(() => {
      expect(mockConsumeMagicLinkToken).toHaveBeenCalledWith(
        "submit",
        "tok-sub",
        { cccd: "9876" },
      )
    })

    expect(
      await screen.findByText(/đã gửi hồ sơ tuyển sinh/i),
    ).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Error path test
// ---------------------------------------------------------------------------

describe("MagicLinkConsumeForm — error path", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("on BE 400, calls handleApiError + resets input + form stays mounted", async () => {
    mockConsumeMagicLinkToken.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: "CCCD verification failed" },
      },
    })

    withProviders(<MagicLinkConsumeForm action="confirm" token="t1" />)

    const input = screen.getByTestId("cccd-input")
    fireEvent.change(input, { target: { value: "0000" } })
    fireEvent.click(screen.getByTestId("magic-link-submit"))

    await waitFor(() => {
      expect(mockHandleApiError).toHaveBeenCalledTimes(1)
    })

    // Input reset to empty
    await waitFor(() => {
      expect(
        (screen.getByTestId("cccd-input") as HTMLInputElement).value,
      ).toBe("")
    })

    // Form still mounted — user can retry
    expect(screen.getByTestId("magic-link-submit")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: /xác nhận nhập học/i }))
      .toBeInTheDocument()
  })
})
