// src/app/(dashboard)/admissions/[id]/_components/SendConfirmationButton.test.tsx
/**
 * SendConfirmationButton UI tests (PR-B).
 *
 * Contract:
 *   - Click button → POST /send-confirmation → dialog opens with confirm_url
 *   - Email-queued path: success alert with the email
 *   - No-email path: destructive alert prompting manual share
 *   - Copy button writes to navigator.clipboard and toasts
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createTestQueryClient } from "@/test/utils/test-utils"

// Hoisted mocks — vi.mock() factories can't close over outer `const` refs
// because they run at module-transform time, before the module body.
const hoisted = vi.hoisted(() => ({
  mockSendConfirmation: vi.fn(),
  mockToastSuccess: vi.fn(),
  mockToastError: vi.fn(),
  mockHandleApiError: vi.fn(),
}))

vi.mock("@/lib/api/client", () => ({
  api: { post: (...args: unknown[]) => hoisted.mockSendConfirmation(...args) },
}))

vi.mock("sonner", () => ({
  toast: {
    success: hoisted.mockToastSuccess,
    error: hoisted.mockToastError,
  },
}))

vi.mock("@/lib/error-handler", () => ({
  handleApiError: (...args: unknown[]) => hoisted.mockHandleApiError(...args),
}))

const {
  mockSendConfirmation,
  mockToastSuccess,
  mockHandleApiError,
} = hoisted

import { SendConfirmationButton } from "./SendConfirmationButton"

function withProviders(ui: React.ReactElement, client?: QueryClient) {
  const queryClient = client ?? createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  )
}

function mockResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    data: {
      message: "ok",
      token_expires_at: "2026-04-26T10:00:00Z",
      sent_to_email: "applicant@example.com",
      phone: "0901234567",
      sent_to_phone: "0901234567",
      token_value: "abc123",
      confirm_url: "https://qlts.tnpc.edu.vn/confirm/abc123",
      ...overrides,
    },
  }
}

describe("SendConfirmationButton", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Always provide a clipboard mock — jsdom doesn't ship navigator.clipboard
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
  })

  it("renders the trigger button", () => {
    withProviders(<SendConfirmationButton profileId={1} />)
    expect(
      screen.getByRole("button", { name: /gửi liên kết xác nhận/i }),
    ).toBeInTheDocument()
  })

  it("opens dialog with confirm_url after successful send (email queued)", async () => {
    mockSendConfirmation.mockResolvedValueOnce(mockResponse())

    withProviders(<SendConfirmationButton profileId={1} />)
    fireEvent.click(
      screen.getByRole("button", { name: /gửi liên kết xác nhận/i }),
    )

    await waitFor(() => expect(mockSendConfirmation).toHaveBeenCalledTimes(1))

    // Dialog content — DialogTitle ID h2
    const title = await screen.findByText(
      "Liên kết xác nhận nhập học",
      { selector: "h2" },
    )
    expect(title).toBeInTheDocument()
    // Success alert with email (title + description both match — assert 1+)
    expect(screen.getAllByText(/đã gửi email/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/applicant@example\.com/)).toBeInTheDocument()
    // URL shown in input (exact label — not regex — to avoid clashing
    // with the DialogTitle "Liên kết xác nhận nhập học" which Radix
    // associates via aria-labelledby).
    expect(screen.getByLabelText("Liên kết xác nhận")).toHaveValue(
      "https://qlts.tnpc.edu.vn/confirm/abc123",
    )
  })

  it("shows destructive alert when lead has no email", async () => {
    mockSendConfirmation.mockResolvedValueOnce(
      mockResponse({ sent_to_email: null }),
    )

    withProviders(<SendConfirmationButton profileId={1} />)
    fireEvent.click(
      screen.getByRole("button", { name: /gửi liên kết xác nhận/i }),
    )

    expect(
      await screen.findByText(/thí sinh chưa có email/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/0901234567/)).toBeInTheDocument()
  })

  it("copies confirm_url to clipboard when Copy button clicked", async () => {
    mockSendConfirmation.mockResolvedValueOnce(mockResponse())

    withProviders(<SendConfirmationButton profileId={1} />)
    fireEvent.click(
      screen.getByRole("button", { name: /gửi liên kết xác nhận/i }),
    )

    await screen.findByText(/liên kết xác nhận nhập học/i)

    const copyButton = screen.getByRole("button", { name: /sao chép liên kết/i })
    fireEvent.click(copyButton)

    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "https://qlts.tnpc.edu.vn/confirm/abc123",
      ),
    )
    expect(mockToastSuccess).toHaveBeenCalledWith("Đã sao chép liên kết")
  })

  it("calls handleApiError on failure", async () => {
    const err = Object.assign(new Error("boom"), {
      isAxiosError: true,
      response: { status: 500, data: { code: "SERVER_ERROR" } },
    })
    mockSendConfirmation.mockRejectedValueOnce(err)

    withProviders(<SendConfirmationButton profileId={1} />)
    fireEvent.click(
      screen.getByRole("button", { name: /gửi liên kết xác nhận/i }),
    )

    await waitFor(() => expect(mockHandleApiError).toHaveBeenCalledTimes(1))
    // Dialog NOT opened on error
    expect(
      screen.queryByText(/liên kết xác nhận nhập học/i),
    ).not.toBeInTheDocument()
  })
})
