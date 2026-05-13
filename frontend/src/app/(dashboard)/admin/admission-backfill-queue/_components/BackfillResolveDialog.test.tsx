/**
 * Phase 3 PR-3D-B Bundle 3 — BackfillResolveDialog tests.
 */
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { BackfillResolveDialog } from "./BackfillResolveDialog"
import type { AdmissionBackfillException } from "@/lib/zod/admission-backfill"

function makeTarget(
  overrides: Partial<AdmissionBackfillException> = {},
): AdmissionBackfillException {
  return {
    id: 42,
    profile_id: 100,
    exception_type: "selected_subject_group_ambiguous",
    details: { matches: [1, 2] },
    created_at: "2026-05-13T05:00:00Z",
    resolved_at: null,
    resolved_by_user_id: null,
    resolved_by_username: null,
    resolution_notes: null,
    ...overrides,
  }
}

describe("BackfillResolveDialog", () => {
  it("single-mode title shows exception id + type + profile id in description", () => {
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        target={makeTarget()}
        onSubmit={() => {}}
        isSubmitting={false}
      />,
    )
    expect(screen.getByText("Đóng ngoại lệ #42")).toBeTruthy()
    expect(
      screen.getByText(/selected_subject_group_ambiguous.*#100/),
    ).toBeTruthy()
  })

  it("bulk-mode title shows count + bulk warning", () => {
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        bulkCount={12}
        onSubmit={() => {}}
        isSubmitting={false}
      />,
    )
    expect(screen.getByText("Đóng 12 ngoại lệ")).toBeTruthy()
    expect(screen.getByText(/đóng đồng loạt 12 dòng/)).toBeTruthy()
  })

  it("confirm disabled when reason below min 5 chars", () => {
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        target={makeTarget()}
        onSubmit={() => {}}
        isSubmitting={false}
      />,
    )
    const confirmBtn = screen.getByTestId("backfill-resolve-confirm")
    expect(confirmBtn.getAttribute("disabled")).not.toBeNull()
    const textarea = screen.getByTestId(
      "backfill-resolve-textarea",
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "abc" } })
    expect(confirmBtn.getAttribute("disabled")).not.toBeNull()
    expect(screen.getByTestId("backfill-resolve-error").textContent).toContain(
      "tối thiểu 5",
    )
    fireEvent.change(textarea, { target: { value: "abcdef" } })
    expect(confirmBtn.getAttribute("disabled")).toBeNull()
  })

  it("onSubmit fires with trimmed reason", () => {
    const onSubmit = vi.fn()
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        target={makeTarget()}
        onSubmit={onSubmit}
        isSubmitting={false}
      />,
    )
    const textarea = screen.getByTestId(
      "backfill-resolve-textarea",
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "  Manual review approved  " } })
    fireEvent.click(screen.getByTestId("backfill-resolve-confirm"))
    expect(onSubmit).toHaveBeenCalledWith("Manual review approved")
  })

  it("server error message displays via role=alert", () => {
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        target={makeTarget()}
        onSubmit={() => {}}
        isSubmitting={false}
        errorMessage="Backfill exception 42 not found"
      />,
    )
    expect(
      screen.getByTestId("backfill-resolve-server-error").textContent,
    ).toContain("not found")
  })

  it("bulk result summary renders counters when bulkResult provided", () => {
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        bulkCount={10}
        onSubmit={() => {}}
        isSubmitting={false}
        bulkResult={{
          requested: 10,
          resolved: 8,
          skipped_already_resolved: 1,
          missing: 1,
          missing_ids: [99],
        }}
      />,
    )
    const summary = screen.getByTestId("bulk-result-summary")
    expect(summary.textContent).toContain("Yêu cầu:")
    expect(summary.textContent).toContain("Đã đóng:")
    // Counters present
    expect(summary.textContent).toMatch(/10/)
    expect(summary.textContent).toMatch(/8/)
  })

  it("isSubmitting disables textarea + buttons + swaps label", () => {
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={() => {}}
        target={makeTarget()}
        onSubmit={() => {}}
        isSubmitting={true}
      />,
    )
    const confirm = screen.getByTestId("backfill-resolve-confirm")
    expect(confirm.textContent).toContain("Đang xử lý")
    expect(confirm.getAttribute("disabled")).not.toBeNull()
    const textarea = screen.getByTestId(
      "backfill-resolve-textarea",
    ) as HTMLTextAreaElement
    expect(textarea.disabled).toBe(true)
  })

  it("cancel button calls onOpenChange(false)", () => {
    const onOpenChange = vi.fn()
    render(
      <BackfillResolveDialog
        open={true}
        onOpenChange={onOpenChange}
        target={makeTarget()}
        onSubmit={() => {}}
        isSubmitting={false}
      />,
    )
    fireEvent.click(screen.getByText("Huỷ"))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
