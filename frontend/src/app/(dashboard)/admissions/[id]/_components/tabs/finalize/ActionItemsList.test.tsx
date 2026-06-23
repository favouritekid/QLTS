/**
 * ActionItemsList — anchor tests.
 *
 * Pins: empty → renders nothing; rows are real <button>s that deep-link via
 * onNavigateToStep; "Sửa Step X" CTA carries the correct step.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { ActionItemsList } from "./ActionItemsList"
import type { ReadinessActionItem } from "./useSubmissionReadiness"

const items: ReadinessActionItem[] = [
  { id: "step-5", step: 5, severity: "error", message: "Điểm chưa đạt", source: "message" },
  { id: "step-6", step: 6, severity: "error", message: "Thiếu giấy khai sinh", source: "message", canDeferAsDocumentDebt: true },
  { id: "step-3", step: 3, severity: "warning", message: "Học tập cần bổ sung", source: "section" },
]

describe("ActionItemsList", () => {
  it("renders nothing when there are no items", () => {
    const { container } = render(<ActionItemsList items={[]} onNavigateToStep={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders one button row per item with 'Sửa Bước X'", () => {
    render(<ActionItemsList items={items} onNavigateToStep={vi.fn()} />)
    expect(screen.getByText("Việc cần xử lý (3)")).toBeInTheDocument()
    expect(screen.getByText("Điểm chưa đạt")).toBeInTheDocument()
    expect(screen.getByText("Sửa Bước 5")).toBeInTheDocument()
    expect(screen.getByText("Có thể nộp kèm nợ giấy tờ")).toBeInTheDocument()
    expect(screen.getByText("Phải sửa trước khi nộp")).toBeInTheDocument()
    expect(screen.getByText("Cần rà soát")).toBeInTheDocument()
    expect(screen.getByText("Sửa Bước 3")).toBeInTheDocument()
    // rows are real buttons (keyboard-activatable)
    expect(screen.getByText("Điểm chưa đạt").closest("button")).toBeTruthy()
  })

  it("clicking a row calls onNavigateToStep with the item's step", () => {
    const onNavigateToStep = vi.fn()
    render(<ActionItemsList items={items} onNavigateToStep={onNavigateToStep} />)
    fireEvent.click(screen.getByText("Điểm chưa đạt").closest("button")!)
    expect(onNavigateToStep).toHaveBeenCalledWith(5)
  })
})
