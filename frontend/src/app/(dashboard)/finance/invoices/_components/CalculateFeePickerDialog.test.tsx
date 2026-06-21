/**
 * Regression: the "Tính phí" picker must query the FINANCE-scoped lookup
 * (GET /api/fees/calculable-profiles) — not /api/admissions, which accountant
 * is denied by design — so the main finance role can pick a profile (PR2 P1).
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@/test/utils/test-utils"

import { CalculateFeePickerDialog } from "./CalculateFeePickerDialog"

const listCalculableProfiles = vi.fn()

vi.mock("@/lib/api/fees", () => ({
  feesApi: {
    listCalculableProfiles: (search: string) => listCalculableProfiles(search),
  },
}))

describe("CalculateFeePickerDialog", () => {
  beforeEach(() => {
    listCalculableProfiles.mockReset()
    listCalculableProfiles.mockResolvedValue({
      profiles: [
        { id: 25, full_name: "Nguyễn Thế Đạt", phone: "0900000001" },
        { id: 100, full_name: "Nguyễn Phi Hùng", phone: "0900000002" },
      ],
    })
  })

  it("queries the finance picker endpoint and renders the results", async () => {
    render(
      <CalculateFeePickerDialog open onOpenChange={vi.fn()} onPick={vi.fn()} />,
    )
    fireEvent.change(screen.getByLabelText(/tìm học sinh/i), {
      target: { value: "Nguyễn" },
    })

    await waitFor(() =>
      expect(listCalculableProfiles).toHaveBeenCalledWith("Nguyễn"),
    )
    expect(await screen.findByText("Nguyễn Thế Đạt")).toBeInTheDocument()
    // Profile code derived client-side, mirrors the backend (HS-000025).
    expect(screen.getByText(/HS-000025/)).toBeInTheDocument()
  })

  it("calls onPick with the chosen profile id", async () => {
    const onPick = vi.fn()
    render(
      <CalculateFeePickerDialog open onOpenChange={vi.fn()} onPick={onPick} />,
    )
    fireEvent.change(screen.getByLabelText(/tìm học sinh/i), {
      target: { value: "Nguyễn" },
    })

    fireEvent.click(await screen.findByText("Nguyễn Thế Đạt"))
    expect(onPick).toHaveBeenCalledWith(25)
  })

  it("does not query for fewer than 2 characters", async () => {
    render(
      <CalculateFeePickerDialog open onOpenChange={vi.fn()} onPick={vi.fn()} />,
    )
    fireEvent.change(screen.getByLabelText(/tìm học sinh/i), {
      target: { value: "N" },
    })
    // Wait past the 300ms debounce — still must not fire.
    await new Promise((r) => setTimeout(r, 400))
    expect(listCalculableProfiles).not.toHaveBeenCalled()
  })
})
