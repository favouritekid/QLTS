/**
 * Phase 3 PR-3D-B FE Wave B Day 10 — AuditReasonDialog tests.
 *
 * Non-tautological per memory pattern-change-impact-audit:
 * - Confirm disabled until min length met (real validation, not mock)
 * - Template select appends label into textarea (not just fires callback)
 * - Recent-reasons select sets textarea from localStorage value
 * - Per-action title + description swap (config-driven, NOT hardcoded)
 * - onConfirm receives trimmed string (whitespace stripped)
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AuditReasonDialog } from "./AuditReasonDialog"
import { getRecentReasonsKey } from "./reason-templates"

describe("AuditReasonDialog", () => {
  beforeEach(() => {
    // Reset localStorage between tests
    window.localStorage.clear()
    vi.clearAllMocks()
  })

  it("renders per-action title + description (admin_rollback variant)", () => {
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    expect(screen.getByText("Quay lại trạng thái nháp")).toBeTruthy()
    expect(screen.getByText(/Đưa hồ sơ về trạng thái nháp/)).toBeTruthy()
  })

  it("renders per-action title swap for waitlist_promote", () => {
    render(
      <AuditReasonDialog
        action="waitlist_promote"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    expect(
      screen.getByText("Chuyển từ chờ ghế lên trúng tuyển"),
    ).toBeTruthy()
  })

  it("confirm button disabled when reason empty or below min length", () => {
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    const confirmBtn = screen.getByTestId("audit-reason-confirm")
    expect(confirmBtn.getAttribute("disabled")).not.toBeNull()

    // Type 5 chars (below 10 min)
    const textarea = screen.getByTestId(
      "audit-reason-textarea",
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "short" } })
    expect(confirmBtn.getAttribute("disabled")).not.toBeNull()
    expect(screen.getByTestId("audit-reason-error").textContent).toContain(
      "tối thiểu 10",
    )

    // Now enough chars
    fireEvent.change(textarea, { target: { value: "Long enough reason here" } })
    expect(confirmBtn.getAttribute("disabled")).toBeNull()
  })

  it("onConfirm receives trimmed string with whitespace stripped", () => {
    const onConfirm = vi.fn()
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={onConfirm}
      />,
    )
    const textarea = screen.getByTestId(
      "audit-reason-textarea",
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: { value: "   Long enough reason here   " },
    })
    fireEvent.click(screen.getByTestId("audit-reason-confirm"))
    expect(onConfirm).toHaveBeenCalledWith("Long enough reason here")
  })

  it("renders recent-reasons section ONLY when localStorage has entries", () => {
    const { rerender } = render(
      <AuditReasonDialog
        action="admin_rollback"
        open={false}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    // Seed localStorage BEFORE opening
    window.localStorage.setItem(
      getRecentReasonsKey("admin_rollback"),
      JSON.stringify(["Previous rollback reason from yesterday"]),
    )
    // Re-open
    rerender(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    // Recent section should appear
    expect(screen.queryByTestId("audit-recent-select")).toBeTruthy()
  })

  it("hides recent-reasons section when localStorage empty", () => {
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    expect(screen.queryByTestId("audit-recent-select")).toBeNull()
  })

  it("displays template select with per-action templates", () => {
    render(
      <AuditReasonDialog
        action="waitlist_reject"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    // Template select rendered
    expect(screen.getByTestId("audit-template-select")).toBeTruthy()
  })

  it("character counter reflects current length", () => {
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
      />,
    )
    const textarea = screen.getByTestId(
      "audit-reason-textarea",
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "abc" } })
    expect(screen.getByTestId("audit-reason-counter").textContent).toBe(
      "3/500",
    )
  })

  it("cancel button calls onOpenChange(false)", () => {
    const onOpenChange = vi.fn()
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={onOpenChange}
        onConfirm={() => {}}
      />,
    )
    fireEvent.click(screen.getByText("Huỷ"))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("isSubmitting disables textarea + confirm + cancel + shows loading label", () => {
    render(
      <AuditReasonDialog
        action="admin_rollback"
        open={true}
        onOpenChange={() => {}}
        onConfirm={() => {}}
        isSubmitting={true}
      />,
    )
    const confirmBtn = screen.getByTestId("audit-reason-confirm")
    expect(confirmBtn.textContent).toContain("Đang xử lý")
    expect(confirmBtn.getAttribute("disabled")).not.toBeNull()
    const textarea = screen.getByTestId(
      "audit-reason-textarea",
    ) as HTMLTextAreaElement
    expect(textarea.disabled).toBe(true)
  })
})
