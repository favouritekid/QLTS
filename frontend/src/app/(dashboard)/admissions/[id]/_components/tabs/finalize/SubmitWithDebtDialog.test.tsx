/**
 * SubmitWithDebtDialog — fast-track "Nộp kèm nợ giấy tờ" tests
 * (TUITION_PREPAY_FASTTRACK_PLAN.md §4 / C4).
 *
 * Pins:
 *   - Trigger "Nộp kèm nợ giấy tờ" renders.
 *   - Owed docs come from `missing_doc_codes`, humanised via documents_checklist.
 *   - Reason is MANDATORY: confirm disabled while empty, enabled once filled.
 *   - Confirm fires `{ acknowledge_missing_docs: true, document_debt_reason }`
 *     with the trimmed reason.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Pass-through Dialog mock (no Radix portal / open-state) so the dialog body is
// always in the tree — we assert on its content + confirm directly.
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DialogTrigger: ({ children }: { children: React.ReactNode; asChild?: boolean }) => <>{children}</>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div data-testid="dialog-content">{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import { SubmitWithDebtDialog } from "./SubmitWithDebtDialog"

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: "draft",
    version: 1,
    academic_year: 2026,
    permissions: {},
    eligibility_status: "ineligible",
    validation_errors: [],
    available_actions: [],
    completion_percent: 90,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [
      { code: "hoc_ba_thpt", label: "Học bạ THPT", status: "missing" },
      { code: "cccd", label: "CCCD bản sao", status: "missing" },
    ],
    missing_priority_evidence_codes: [],
    missing_doc_codes: ["hoc_ba_thpt", "cccd"],
    outstanding_debt_codes: [],
    can_submit_with_document_debt: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

describe("SubmitWithDebtDialog", () => {
  beforeEach(() => vi.clearAllMocks())

  it("renders the 'Nộp kèm nợ giấy tờ' trigger", () => {
    render(
      <SubmitWithDebtDialog profile={buildProfile()} onConfirm={vi.fn()} isSubmitting={false} />,
    )
    expect(screen.getByText("Nộp kèm nợ giấy tờ")).toBeInTheDocument()
  })

  it("lists owed docs from missing_doc_codes, humanised via documents_checklist", () => {
    render(
      <SubmitWithDebtDialog profile={buildProfile()} onConfirm={vi.fn()} isSubmitting={false} />,
    )
    expect(screen.getByText("Học bạ THPT")).toBeInTheDocument()
    expect(screen.getByText("CCCD bản sao")).toBeInTheDocument()
    // Count heading reflects the number of owed codes.
    expect(screen.getByText("Giấy tờ còn nợ (2)")).toBeInTheDocument()
  })

  it("falls back to the raw code when no checklist label matches", () => {
    render(
      <SubmitWithDebtDialog
        profile={buildProfile({ documents_checklist: [], missing_doc_codes: ["weird_code"] })}
        onConfirm={vi.fn()}
        isSubmitting={false}
      />,
    )
    expect(screen.getByText("weird_code")).toBeInTheDocument()
  })

  it("disables confirm while the reason is empty, enables once filled", () => {
    render(
      <SubmitWithDebtDialog profile={buildProfile()} onConfirm={vi.fn()} isSubmitting={false} />,
    )
    const confirm = screen.getByRole("button", { name: "Xác nhận nộp" })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Lý do cho nợ/), {
      target: { value: "HS xin cấp lại học bạ, hẹn 30/06" },
    })
    expect(confirm).not.toBeDisabled()
  })

  it("keeps confirm disabled for whitespace-only reason", () => {
    render(
      <SubmitWithDebtDialog profile={buildProfile()} onConfirm={vi.fn()} isSubmitting={false} />,
    )
    fireEvent.change(screen.getByLabelText(/Lý do cho nợ/), { target: { value: "   " } })
    expect(screen.getByRole("button", { name: "Xác nhận nộp" })).toBeDisabled()
  })

  it("fires onConfirm with acknowledge_missing_docs + trimmed reason", () => {
    const onConfirm = vi.fn()
    render(
      <SubmitWithDebtDialog profile={buildProfile()} onConfirm={onConfirm} isSubmitting={false} />,
    )
    fireEvent.change(screen.getByLabelText(/Lý do cho nợ/), {
      target: { value: "  cấp lại học bạ  " },
    })
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận nộp" }))
    expect(onConfirm).toHaveBeenCalledWith({
      acknowledge_missing_docs: true,
      document_debt_reason: "cấp lại học bạ",
    })
  })

  it("shows a spinner label + disables confirm while submitting", () => {
    render(
      <SubmitWithDebtDialog profile={buildProfile()} onConfirm={vi.fn()} isSubmitting={true} />,
    )
    // Even with a reason present, the submitting state blocks re-confirm.
    fireEvent.change(screen.getByLabelText(/Lý do cho nợ/), { target: { value: "abc" } })
    const confirm = screen.getByRole("button", { name: /Đang xử lý/ })
    expect(confirm).toBeDisabled()
  })
})
