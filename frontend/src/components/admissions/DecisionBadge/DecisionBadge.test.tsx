/**
 * Phase 3 PR-3D-A Sub-4 — DecisionBadge component tests.
 *
 * Non-tautological per memory `pattern-change-impact-audit`:
 * - Each variant asserts SPECIFIC label text + role + ARIA
 * - Display order suffix appears for `admitted` + `waitlisted` variants
 * - Default variant (pending/skip) renders different copy
 *
 * 4 supported decisions × 1 base + display_order optional = 8+ scenarios.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { DecisionBadge, ResultPublishedBadge } from "./DecisionBadge"

describe("DecisionBadge", () => {
  describe("admitted variant", () => {
    it("renders 'Đậu' label without displayOrder", () => {
      render(<DecisionBadge decision="admitted" />)
      const badge = screen.getByRole("status")
      expect(badge.textContent).toBe("Đậu")
      expect(badge).toHaveAttribute("aria-label", "Đậu")
    })

    it("renders 'Đậu NV{n}' with displayOrder", () => {
      render(<DecisionBadge decision="admitted" displayOrder={1} />)
      expect(screen.getByRole("status").textContent).toBe("Đậu NV1")
    })

    it("applies green styling for admitted", () => {
      const { container } = render(<DecisionBadge decision="admitted" />)
      const badge = container.querySelector("[role='status']")
      expect(badge?.className).toContain("bg-green-50")
      expect(badge?.className).toContain("text-green-700")
    })
  })

  describe("waitlisted variant", () => {
    it("renders 'Chờ ghế NV{n}' with displayOrder", () => {
      render(<DecisionBadge decision="waitlisted" displayOrder={2} />)
      expect(screen.getByRole("status").textContent).toBe("Chờ ghế NV2")
    })

    it("applies amber styling for waitlisted", () => {
      const { container } = render(<DecisionBadge decision="waitlisted" />)
      const badge = container.querySelector("[role='status']")
      expect(badge?.className).toContain("bg-amber-50")
    })
  })

  describe("rejected variant", () => {
    it("renders 'Trượt' label (no displayOrder suffix)", () => {
      // Rejected doesn't suffix order — semantic: no successful NV
      render(<DecisionBadge decision="rejected" displayOrder={1} />)
      expect(screen.getByRole("status").textContent).toBe("Trượt")
    })

    it("applies red styling for rejected", () => {
      const { container } = render(<DecisionBadge decision="rejected" />)
      const badge = container.querySelector("[role='status']")
      expect(badge?.className).toContain("bg-red-50")
    })
  })

  describe("skip + pending variants (cascade-stop outcomes)", () => {
    it("skip renders 'Bỏ xét' label (cascade-stop after first admit)", () => {
      render(<DecisionBadge decision="skip" />)
      expect(screen.getByRole("status").textContent).toBe("Bỏ xét")
    })

    it("pending renders 'Chờ xét' fallback", () => {
      render(<DecisionBadge decision="pending" />)
      expect(screen.getByRole("status").textContent).toBe("Chờ xét")
    })
  })

  describe("size variants", () => {
    it("sm size applies smaller padding", () => {
      const { container } = render(<DecisionBadge decision="admitted" size="sm" />)
      expect(container.querySelector("[role='status']")?.className).toContain("text-xs")
    })

    it("lg size applies font-semibold + larger padding", () => {
      const { container } = render(<DecisionBadge decision="admitted" size="lg" />)
      const cls = container.querySelector("[role='status']")?.className
      expect(cls).toContain("text-base")
      expect(cls).toContain("font-semibold")
    })
  })

  describe("custom className merge", () => {
    it("merges custom className without breaking variant class", () => {
      const { container } = render(
        <DecisionBadge decision="admitted" className="custom-test-class" />,
      )
      const cls = container.querySelector("[role='status']")?.className
      expect(cls).toContain("custom-test-class")
      expect(cls).toContain("bg-green-50")
    })
  })
})

describe("ResultPublishedBadge (profile-level T6 announcement)", () => {
  it("renders 'Đã công bố KQ' with sky styling", () => {
    render(<ResultPublishedBadge />)
    const badge = screen.getByRole("status")
    expect(badge.textContent).toBe("Đã công bố KQ")
    expect(badge.className).toContain("bg-sky-50")
    expect(badge).toHaveAttribute("aria-label", "Đã công bố kết quả")
  })

  it("supports size lg", () => {
    const { container } = render(<ResultPublishedBadge size="lg" />)
    expect(container.querySelector("[role='status']")?.className).toContain(
      "text-base",
    )
  })
})
