/**
 * IssueLocator — reviewer "Cần yêu cầu sửa" strip tests.
 *
 * Pins: per-step chips with count + severity word (error steps first), max 3 + "+N",
 * CTA is "Xem Step X" (navigate, NOT "Sửa"), warning-without-step fallback line,
 * and renders nothing when there is no work.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { IssueLocator } from "./IssueLocator"
import type { ReadinessActionItem } from "./useSubmissionReadiness"

function item(overrides: Partial<ReadinessActionItem> & { step: number }): ReadinessActionItem {
  return {
    id: overrides.id ?? `step-${overrides.step}`,
    step: overrides.step,
    severity: overrides.severity ?? "warning",
    message: overrides.message ?? "issue",
    source: overrides.source ?? "message",
    count: overrides.count,
  }
}

describe("IssueLocator", () => {
  it("renders a chip per step with count + severity word; error steps first", () => {
    render(
      <IssueLocator
        items={[
          item({ step: 6, severity: "warning", count: 1 }),
          item({ step: 5, severity: "error", count: 2 }),
        ]}
        hasOutstandingWarnings
        onNavigateToStep={() => {}}
      />,
    )
    expect(screen.getByText(/Bước 5 · 2 vấn đề/)).toBeInTheDocument()
    expect(screen.getByText(/Bước 6 · 1 vấn đề/)).toBeInTheDocument()
    // error step (5) chip comes before warning step (6)
    const buttons = screen.getAllByRole("button")
    expect(buttons[0].getAttribute("aria-label")).toContain("Xem Bước 5")
  })

  it("CTA navigates via onNavigateToStep and uses 'Xem' (never 'Sửa') for reviewers", () => {
    const onNavigateToStep = vi.fn()
    render(
      <IssueLocator
        items={[item({ step: 4, severity: "error", count: 2 })]}
        hasOutstandingWarnings={false}
        onNavigateToStep={onNavigateToStep}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: /Xem Bước 4/ }))
    expect(onNavigateToStep).toHaveBeenCalledWith(4)
    expect(screen.queryByText(/Sửa/)).not.toBeInTheDocument()
  })

  it("shows at most 3 chips + a '+N bước khác' overflow", () => {
    render(
      <IssueLocator
        items={[1, 2, 3, 4, 5].map((step) => item({ step, severity: "warning", count: 1 }))}
        hasOutstandingWarnings
        onNavigateToStep={() => {}}
      />,
    )
    expect(screen.getAllByRole("button")).toHaveLength(3)
    expect(screen.getByText(/\+2 bước khác/)).toBeInTheDocument()
  })

  it("no routable items but warnings → fallback line pointing to detail (NO '0' metric)", () => {
    render(<IssueLocator items={[]} hasOutstandingWarnings onNavigateToStep={() => {}} />)
    expect(screen.getByTestId("issue-locator-warning")).toBeInTheDocument()
    expect(screen.getByText(/Có cảnh báo cần rà soát/)).toBeInTheDocument()
    expect(screen.queryByText(/Mục cần xử lý/)).not.toBeInTheDocument()
  })

  it("no items + no warnings → renders nothing", () => {
    const { container } = render(
      <IssueLocator items={[]} hasOutstandingWarnings={false} onNavigateToStep={() => {}} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
