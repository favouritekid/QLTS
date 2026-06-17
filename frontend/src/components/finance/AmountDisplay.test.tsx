import { describe, it, expect } from "vitest"
import { render } from "@/test/utils/test-utils"

import { AmountDisplay, PaidAmount, RemainingAmount } from "./AmountDisplay"

// textContent (not getByText) so assertions don't depend on the exact
// whitespace Intl.NumberFormat inserts before ₫ (a non-breaking space).
describe("AmountDisplay", () => {
  it("formats a raw API decimal string", () => {
    const { container } = render(<AmountDisplay amount="3000000.00" />)
    expect(container.textContent).toContain("3.000.000")
  })

  it("formats a raw number", () => {
    const { container } = render(<AmountDisplay amount={3000000} />)
    expect(container.textContent).toContain("3.000.000")
  })

  it("is idempotent on an already-formatted string (no double-format)", () => {
    // Regression guard: passing a *_formatted view-model field
    // ("3.000.000 ₫") back into AmountDisplay used to re-parse "3.000.000"
    // as the decimal 3 (JS reads '.' as a decimal point) and render "3 ₫".
    const { container } = render(<AmountDisplay amount="3.000.000 ₫" />)
    expect(container.textContent).toContain("3.000.000")
  })

  it("strips the currency suffix when showCurrency is false", () => {
    const { container } = render(
      <AmountDisplay amount="3.000.000 ₫" showCurrency={false} />,
    )
    expect(container.textContent).toContain("3.000.000")
    expect(container.textContent).not.toContain("₫")
  })

  it("does not truncate large amounts (regression for the 70.000 case)", () => {
    const { container } = render(<AmountDisplay amount="70000" />)
    expect(container.textContent).toContain("70.000")
  })
})

// RemainingAmount / PaidAmount were also migrated to parseAmountInput; their
// callers pass *_formatted strings ("6.200.000 ₫"), so cover both the rendered
// text and the numericAmount-driven styling/comparison paths.
describe("RemainingAmount", () => {
  it("renders the full formatted text for a preformatted input", () => {
    const { container } = render(<RemainingAmount amount="6.200.000 ₫" />)
    expect(container.textContent).toContain("6.200.000")
  })

  it("applies warning styling when remaining > 0", () => {
    const { container } = render(<RemainingAmount amount="6.200.000 ₫" />)
    expect(container.querySelector(".text-warning-600")).not.toBeNull()
  })

  it("applies success styling when remaining is zero", () => {
    const { container } = render(<RemainingAmount amount="0 ₫" />)
    expect(container.querySelector(".text-success-600")).not.toBeNull()
  })
})

describe("PaidAmount", () => {
  it("marks fully-paid (success styling) when paid >= total for formatted inputs", () => {
    const { container } = render(
      <PaidAmount amount="9.200.000 ₫" totalAmount="9.200.000 ₫" />,
    )
    expect(container.querySelector(".text-success-600")).not.toBeNull()
  })

  it("does not mark fully-paid when paid < total", () => {
    const { container } = render(
      <PaidAmount amount="3.000.000 ₫" totalAmount="9.200.000 ₫" />,
    )
    expect(container.querySelector(".text-success-600")).toBeNull()
  })
})
