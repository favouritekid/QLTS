/**
 * Q9 #07 Phase E.4 — UtEvidenceCards smoke render tests.
 *
 * Pins § 3 UT evidence cards key contracts (render-level, mutation behavior
 * defer integration tests):
 *   - Empty state when priority_object_codes []
 *   - Renders per-code card với label/bonus
 *   - Missing-file inline warning (Decision #2)
 *   - Paper-only badge cho verified entries paper_only_verification=true
 *   - "Mở tab Giấy tờ" button calls onNavigateToDocuments (adjustment #3)
 */
import { describe, it, expect, vi } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, fireEvent } from "@/test/utils/test-utils"

import { UtEvidenceCards } from "./UtEvidenceCards"
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
    priority_resolution_snapshot: null,
    priority_audit_log: null,
    permissions: { verify_priority_object: true } as never,
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("UtEvidenceCards — empty state", () => {
  it("renders empty state when no codes", () => {
    const profile = makeProfile()
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(screen.getByTestId("ut-evidence-empty")).toBeInTheDocument()
    expect(screen.queryByTestId("ut-evidence-card-04")).not.toBeInTheDocument()
  })
})

describe("UtEvidenceCards — per-code render", () => {
  it("renders card for each priority_object_code", () => {
    const profile = makeProfile({
      priority_object_codes: ["04", "07"],
      priority_object_evidence: {
        "04": { status: "verified", verified_by: 7 },
        "07": { status: "pending" },
      },
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04.pdf",
          status: "uploaded",
          verification_status: "verified",
        },
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
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(screen.getByTestId("ut-evidence-card-04")).toBeInTheDocument()
    expect(screen.getByTestId("ut-evidence-card-07")).toBeInTheDocument()
    expect(screen.getByText("Con thương binh")).toBeInTheDocument()
    expect(screen.getByText("Hộ nghèo")).toBeInTheDocument()
  })

  it("shows verified status badge for verified entry", () => {
    const profile = makeProfile({
      priority_object_codes: ["04"],
      priority_object_evidence: {
        "04": { status: "verified", verified_by: 7 },
      },
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(screen.getByTestId("ut-status-badge-verified")).toBeInTheDocument()
  })
})

describe("UtEvidenceCards — PR2 authed download link", () => {
  it("[Xem PDF] points at the authed download endpoint, not /uploads", () => {
    const profile = makeProfile({
      priority_object_codes: ["04"],
      priority_object_evidence: { "04": { status: "verified", verified_by: 7 } },
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    const viewLink = screen.getByTestId("ut-evidence-view-04")
    expect(viewLink.getAttribute("href")).toContain(
      "/api/admissions/42/documents/99/download",
    )
    expect(viewLink.getAttribute("href")).not.toContain("/uploads")
  })

  it("hides [Xem PDF] when document_id is null (stale/rollback), keeps filename text", () => {
    const profile = makeProfile({
      priority_object_codes: ["04"],
      priority_object_evidence: { "04": { status: "verified", verified_by: 7 } },
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: null,
          document_file_path: "uploads/admissions/42/priority_04.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(screen.queryByTestId("ut-evidence-view-04")).not.toBeInTheDocument()
    // Filename info still rendered (block gated on document_file_path).
    expect(screen.getByText(/Minh chứng:/)).toBeInTheDocument()
  })
})

describe("UtEvidenceCards — Decision #2 inline warning", () => {
  it("renders missing-file warning when sub_code in missing_priority_evidence_codes", () => {
    const profile = makeProfile({
      priority_object_codes: ["08"],
      priority_object_evidence: {
        "08": { status: "pending" },
      },
      missing_priority_evidence_codes: ["08"],
      priority_evidence_documents: [
        {
          sub_code: "08",
          bonus_points: 0.5,
          label: "Chất độc hóa học",
          document_id: null,
          document_file_path: null,
          status: "missing",
          verification_status: "pending",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(
      screen.getByTestId("ut-evidence-missing-warning-08"),
    ).toBeInTheDocument()
    expect(screen.getByText(/Chưa có minh chứng/)).toBeInTheDocument()
  })

  it("does NOT show warning when sub_code not in missing list", () => {
    const profile = makeProfile({
      priority_object_codes: ["04"],
      priority_object_evidence: {
        "04": { status: "verified", verified_by: 7 },
      },
      missing_priority_evidence_codes: [],
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04.pdf",
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(
      screen.queryByTestId("ut-evidence-missing-warning-04"),
    ).not.toBeInTheDocument()
  })
})

describe("UtEvidenceCards — onNavigateToDocuments (adjustment #3)", () => {
  it("invokes callback when 'Mở tab Giấy tờ' button clicked", () => {
    const onNav = vi.fn()
    const profile = makeProfile({
      priority_object_codes: ["08"],
      priority_object_evidence: { "08": { status: "pending" } },
      missing_priority_evidence_codes: ["08"],
      priority_evidence_documents: [
        {
          sub_code: "08",
          bonus_points: 0.5,
          label: "Chất độc hóa học",
          document_id: null,
          document_file_path: null,
          status: "missing",
          verification_status: "pending",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={onNav}
        />,
      ),
    )
    fireEvent.click(screen.getByTestId("ut-evidence-navigate-documents-08"))
    expect(onNav).toHaveBeenCalledTimes(1)
  })
})

describe("UtEvidenceCards — paper-only badge (Decision #3)", () => {
  it("renders 'Hồ sơ giấy' badge when paper_only_verification=true on display entry", () => {
    const profile = makeProfile({
      priority_object_codes: ["04"],
      priority_object_evidence: {
        "04": {
          status: "verified",
          verified_by: 7,
          paper_only_verification: true,
        },
      },
      priority_object_evidence_display: {
        "04": {
          status: "verified",
          verified_by: 7,
          verified_by_name: "Trịnh Tố Uyên",
          verified_at: "2026-05-20T08:00:00+00:00",
          paper_only_verification: true,
        },
      },
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Con thương binh",
          document_id: null,
          document_file_path: null,
          status: "verified",
          verification_status: "verified",
        },
      ],
    })
    render(
      wrap(
        <UtEvidenceCards
          profile={profile}
          canVerify
          isEditable
          onNavigateToDocuments={() => {}}
        />,
      ),
    )
    expect(screen.getByText("Hồ sơ giấy")).toBeInTheDocument()
  })
})
