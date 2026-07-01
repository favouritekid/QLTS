// src/app/(dashboard)/admissions/_components/roster-parts.test.tsx
import { describe, it, expect } from "vitest"
import { render } from "@/test/utils/test-utils"
import { TuitionHk1 } from "./roster-parts"

describe("TuitionHk1", () => {
  it('renders "—" when status is "none"', () => {
    const { container } = render(<TuitionHk1 paid={0} remaining={0} status="none" />)
    expect(container.textContent).toContain("—")
    expect(container.textContent).not.toContain("Đã đóng")
  })

  it('renders "—" when status is null (no HK1 fee)', () => {
    const { container } = render(<TuitionHk1 paid={null} remaining={null} status={null} />)
    expect(container.textContent).toContain("—")
  })

  it("shows Đã đóng / Còn lại with formatted VND", () => {
    const { container } = render(
      <TuitionHk1 paid={3000000} remaining={6200000} status="partial" />,
    )
    expect(container.textContent).toContain("Đã đóng")
    expect(container.textContent).toContain("Còn lại")
    expect(container.textContent).toContain("3.000.000")
    expect(container.textContent).toContain("6.200.000")
  })

  it("maps status → dot color (BE emits status, FE only colors)", () => {
    expect(
      render(<TuitionHk1 paid={9200000} remaining={0} status="paid" />)
        .container.querySelector(".bg-success-500"),
    ).not.toBeNull()
    expect(
      render(<TuitionHk1 paid={3000000} remaining={6200000} status="partial" />)
        .container.querySelector(".bg-amber-500"),
    ).not.toBeNull()
    expect(
      render(<TuitionHk1 paid={0} remaining={9200000} status="unpaid" />)
        .container.querySelector(".bg-gray-400"),
    ).not.toBeNull()
    expect(
      render(<TuitionHk1 paid={0} remaining={1000000} status="overdue" />)
        .container.querySelector(".bg-error-500"),
    ).not.toBeNull()
  })
})
