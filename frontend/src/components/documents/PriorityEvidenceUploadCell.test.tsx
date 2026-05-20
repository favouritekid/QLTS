/**
 * Q9 #07 Phase E.4 — PriorityEvidenceUploadCell view/replace mode tests.
 *
 * Pins P1 fix contract (PR-3 Step C audit cycle): 2-mode render flow.
 *   - View mode: server has file → summary + [Xem PDF] + [Tải lại]
 *   - Replace mode: no file OR [Tải lại] clicked → FileUpload dropzone visible
 *   - Cancel button (replace mode while server has file) returns to view mode
 */
import { describe, it, expect } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, fireEvent } from "@/test/utils/test-utils"

import { PriorityEvidenceUploadCell } from "./PriorityEvidenceUploadCell"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

function makeProfile(
  overrides: Partial<AdmissionProfileResponse> = {},
): AdmissionProfileResponse {
  return {
    id: 42,
    version: 5,
    status: "submitted",
    academic_year: 2026,
    priority_object_codes: [],
    priority_object_evidence: {},
    priority_object_evidence_display: null,
    missing_priority_evidence_codes: [],
    priority_evidence_documents: [],
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("PriorityEvidenceUploadCell — view mode (server has file)", () => {
  it("renders summary + [Xem PDF] + [Tải lại] when file exists", () => {
    const profile = makeProfile({
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04_abc.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(wrap(<PriorityEvidenceUploadCell profile={profile} subCode="04" />))

    expect(screen.getByTestId("priority-evidence-view-04")).toBeInTheDocument()
    expect(screen.getByTestId("priority-evidence-replace-04")).toBeInTheDocument()
    expect(screen.getByText("priority_04_abc.pdf")).toBeInTheDocument()
  })

  it("toggles to replace mode when [Tải lại] clicked", () => {
    const profile = makeProfile({
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04_abc.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(wrap(<PriorityEvidenceUploadCell profile={profile} subCode="04" />))

    // Initially view mode
    expect(screen.getByTestId("priority-evidence-replace-04")).toBeInTheDocument()
    expect(
      screen.queryByTestId("priority-evidence-cancel-replace-04"),
    ).not.toBeInTheDocument()

    // Click [Tải lại] → replace mode
    fireEvent.click(screen.getByTestId("priority-evidence-replace-04"))

    // Cancel button appears (replace mode + file exists)
    expect(
      screen.getByTestId("priority-evidence-cancel-replace-04"),
    ).toBeInTheDocument()
  })

  it("cancel button returns to view mode", () => {
    const profile = makeProfile({
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04_abc.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(wrap(<PriorityEvidenceUploadCell profile={profile} subCode="04" />))

    fireEvent.click(screen.getByTestId("priority-evidence-replace-04"))
    expect(
      screen.getByTestId("priority-evidence-cancel-replace-04"),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("priority-evidence-cancel-replace-04"))
    expect(screen.getByTestId("priority-evidence-replace-04")).toBeInTheDocument()
    expect(
      screen.queryByTestId("priority-evidence-cancel-replace-04"),
    ).not.toBeInTheDocument()
  })
})

describe("PriorityEvidenceUploadCell — replace mode (no server file)", () => {
  it("renders FileUpload dropzone directly when no file exists", () => {
    const profile = makeProfile({
      priority_evidence_documents: [
        {
          sub_code: "07",
          bonus_points: 0.5,
          label: "Hộ nghèo",
          document_id: null,
          document_file_path: null,
          status: "missing",
          verification_status: "pending",
        },
      ],
    })
    render(wrap(<PriorityEvidenceUploadCell profile={profile} subCode="07" />))

    // No [Tải lại] button (no file to replace)
    expect(
      screen.queryByTestId("priority-evidence-replace-07"),
    ).not.toBeInTheDocument()
    // No cancel button (no existing file for "huỷ thay file" semantics)
    expect(
      screen.queryByTestId("priority-evidence-cancel-replace-07"),
    ).not.toBeInTheDocument()
    // Description shows UT label
    expect(screen.getByText(/Hộ nghèo/)).toBeInTheDocument()
  })
})
