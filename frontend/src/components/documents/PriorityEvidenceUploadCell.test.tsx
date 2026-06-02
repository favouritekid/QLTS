/**
 * Q9 #07 Phase E.4 — PriorityEvidenceUploadCell view/replace mode tests.
 *
 * Pins P1 fix contract (PR-3 Step C audit cycle): 2-mode render flow.
 *   - View mode: server has file → summary + [Xem PDF] + [Tải lại]
 *   - Replace mode: no file OR [Tải lại] clicked → FileUpload dropzone visible
 *   - Cancel button (replace mode while server has file) returns to view mode
 *
 * Plus PR-3 audit P2 (2026-05-20): pin RESPONSE CONTRACT — `onUpload` MUST
 * await mutation, locate matching sub_code in updated.priority_evidence_documents,
 * and return `document_file_path`. Without contract pin, BE rename of the
 * field (or missing population) silently breaks the FileUpload success
 * state with no test caught the drift (vitest mock tautological without it).
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, fireEvent, waitFor } from "@/test/utils/test-utils"

import { PriorityEvidenceUploadCell } from "./PriorityEvidenceUploadCell"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// ---------------------------------------------------------------------------
// Mock FileUpload — capture the onUpload callback so contract tests can
// invoke it directly with a controlled File and assert the returned Promise
// shape. Real FileUpload requires DnD events; we don't need to retest its
// internals here, only the wrapper's contract WITH it.
// ---------------------------------------------------------------------------
const fileUploadOnUploadSpy = vi.fn()

vi.mock("@/components/common/upload/FileUpload", () => ({
  FileUpload: ({
    onUpload,
    description,
  }: {
    onUpload: (file: File) => Promise<string>
    description?: string
  }) => {
    fileUploadOnUploadSpy.mockImplementation(onUpload)
    return (
      <div data-testid="probe-file-upload">
        {/* Render description so existing tests asserting on UT label
            (vd "Hộ nghèo") still pass — the real FileUpload renders it. */}
        {description && <span>{description}</span>}
      </div>
    )
  },
}))

// useUploadPriorityEvidence — control the mutation return so contract tests
// can pin what `onUpload` reads from the response.
const mutateAsyncSpy = vi.fn()
vi.mock("@/lib/hooks/use-priority-evidence", () => ({
  useUploadPriorityEvidence: () => ({
    mutateAsync: mutateAsyncSpy,
    isPending: false,
  }),
}))

beforeEach(() => {
  mutateAsyncSpy.mockReset()
  fileUploadOnUploadSpy.mockReset()
})

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

    const viewLink = screen.getByTestId("priority-evidence-view-04")
    expect(viewLink).toBeInTheDocument()
    // PR2: [Xem PDF] points at the authed download endpoint (profile 42,
    // document 99), NOT the raw /uploads path (now 404).
    expect(viewLink.getAttribute("href")).toContain(
      "/api/admissions/42/documents/99/download",
    )
    expect(viewLink.getAttribute("href")).not.toContain("/uploads")
    expect(screen.getByTestId("priority-evidence-replace-04")).toBeInTheDocument()
    expect(screen.getByText("priority_04_abc.pdf")).toBeInTheDocument()
  })

  it("hides [Xem PDF] but keeps [Tải lại] when document_id is null (stale/rollback)", () => {
    // PR2: a file present in a cached/rolled-back response without a
    // document_id has no authed download URL → hide the link (NO fallback to
    // the raw path), but the [Tải lại] re-upload affordance must remain.
    const profile = makeProfile({
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: null,
          document_file_path: "uploads/admissions/42/priority_04_abc.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(wrap(<PriorityEvidenceUploadCell profile={profile} subCode="04" />))

    expect(
      screen.queryByTestId("priority-evidence-view-04"),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId("priority-evidence-replace-04")).toBeInTheDocument()
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

// =============================================================================
// PR-3 audit P2 — response contract pinning (handleUpload onUpload)
// =============================================================================

function buildEmptyProfile(subCode: string): AdmissionProfileResponse {
  return makeProfile({
    priority_evidence_documents: [
      {
        sub_code: subCode,
        bonus_points: 0.5,
        label: "Hộ nghèo",
        document_id: null,
        document_file_path: null,
        status: "missing",
        verification_status: "pending",
      },
    ],
  })
}

describe("PriorityEvidenceUploadCell — onUpload response contract", () => {
  it("returns document_file_path from updated.priority_evidence_documents matching sub_code", async () => {
    mutateAsyncSpy.mockResolvedValue(
      makeProfile({
        priority_evidence_documents: [
          {
            sub_code: "07",
            bonus_points: 0.5,
            label: "Hộ nghèo",
            document_id: 200,
            document_file_path: "uploads/admissions/42/priority_07_xyz.pdf",
            status: "uploaded",
            verification_status: "pending",
          },
        ],
      }),
    )
    render(
      wrap(
        <PriorityEvidenceUploadCell
          profile={buildEmptyProfile("07")}
          subCode="07"
        />,
      ),
    )

    // Invoke captured handler directly — bypassing FileUpload internals.
    // Pins what onUpload (wrapper's handleUpload) actually returns when
    // BE response carries document_file_path for matching sub_code.
    const onUpload = fileUploadOnUploadSpy.getMockImplementation()!
    const result = await onUpload(
      new File(["x"], "probe.pdf", { type: "application/pdf" }),
    )
    expect(result).toBe("uploads/admissions/42/priority_07_xyz.pdf")
    expect(mutateAsyncSpy).toHaveBeenCalledWith(
      expect.objectContaining({ file: expect.any(File) }),
    )
  })

  it("throws explicit error when response missing document_file_path for the sub_code", async () => {
    // Defensive — BE response shape regression should fail loud, not
    // silently leave the FileUpload item in pending state forever.
    mutateAsyncSpy.mockResolvedValue(
      makeProfile({
        priority_evidence_documents: [
          {
            sub_code: "07",
            bonus_points: 0.5,
            label: "Hộ nghèo",
            document_id: 200,
            // BE drift simulation: file_path was renamed / not populated.
            document_file_path: null,
            status: "uploaded",
            verification_status: "pending",
          },
        ],
      }),
    )
    render(
      wrap(
        <PriorityEvidenceUploadCell
          profile={buildEmptyProfile("07")}
          subCode="07"
        />,
      ),
    )

    const onUpload = fileUploadOnUploadSpy.getMockImplementation()!
    await expect(
      onUpload(new File(["x"], "probe.pdf", { type: "application/pdf" })),
    ).rejects.toThrow(/UT07/)
  })

  it("throws when response contains no entry for the sub_code at all (drift)", async () => {
    mutateAsyncSpy.mockResolvedValue(
      makeProfile({
        priority_evidence_documents: [
          // Server response somehow lost the sub_code row entirely.
          {
            sub_code: "99",
            bonus_points: 0.5,
            label: "Other",
            document_id: 201,
            document_file_path: "uploads/admissions/42/other.pdf",
            status: "uploaded",
            verification_status: "pending",
          },
        ],
      }),
    )
    render(
      wrap(
        <PriorityEvidenceUploadCell
          profile={buildEmptyProfile("07")}
          subCode="07"
        />,
      ),
    )

    const onUpload = fileUploadOnUploadSpy.getMockImplementation()!
    await expect(
      onUpload(new File(["x"], "probe.pdf", { type: "application/pdf" })),
    ).rejects.toThrow(/UT07/)
  })

  it("invokes mutateAsync with the File argument (request shape contract)", async () => {
    mutateAsyncSpy.mockResolvedValue(
      makeProfile({
        priority_evidence_documents: [
          {
            sub_code: "07",
            bonus_points: 0.5,
            label: "Hộ nghèo",
            document_id: 200,
            document_file_path: "uploads/admissions/42/priority_07.pdf",
            status: "uploaded",
            verification_status: "pending",
          },
        ],
      }),
    )
    render(
      wrap(
        <PriorityEvidenceUploadCell
          profile={buildEmptyProfile("07")}
          subCode="07"
        />,
      ),
    )

    const myFile = new File(["x"], "evidence.pdf", { type: "application/pdf" })
    const onUpload = fileUploadOnUploadSpy.getMockImplementation()!
    await onUpload(myFile)

    expect(mutateAsyncSpy).toHaveBeenCalledTimes(1)
    expect(mutateAsyncSpy).toHaveBeenCalledWith({ file: myFile })
  })
})
