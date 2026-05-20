/**
 * Q9 #07 Phase E.4 — Pure helper unit tests.
 *
 * Vitest pure-function tests cho display projection fallback, filename
 * extraction, missing-file detection, document_id resolution. KHÔNG mount
 * components — chỉ logic level.
 */

import { describe, expect, it } from "vitest"

import {
  findEvidenceDocument,
  getDisplayFilename,
  getEvidence,
  isDisplayEntry,
  isMissingEvidenceFile,
  resolveVerifyDocumentId,
} from "./priority-evidence-helpers"

describe("getEvidence — display projection fallback", () => {
  it("prefers priority_object_evidence_display when present", () => {
    const profile = {
      priority_object_evidence: {
        "04": { status: "verified" as const, verified_by: 7 },
      },
      priority_object_evidence_display: {
        "04": {
          status: "verified" as const,
          verified_by: 7,
          verified_by_name: "Trịnh Tố Uyên",
          document_file_path: "uploads/admissions/42/x.pdf",
        },
      },
    }
    const evidence = getEvidence(profile)
    expect(evidence["04"]).toHaveProperty("verified_by_name", "Trịnh Tố Uyên")
  })

  it("falls back to raw priority_object_evidence when display is null", () => {
    const profile = {
      priority_object_evidence: {
        "04": { status: "verified" as const, verified_by: 7 },
      },
      priority_object_evidence_display: null,
    }
    const evidence = getEvidence(profile)
    expect(evidence["04"].status).toBe("verified")
    expect(evidence["04"]).not.toHaveProperty("verified_by_name")
  })

  it("returns empty object when both undefined-like", () => {
    const profile = {
      priority_object_evidence: {},
      priority_object_evidence_display: null,
    }
    expect(getEvidence(profile)).toEqual({})
  })
})

describe("getDisplayFilename — basename extract", () => {
  it("extracts basename from S3 path", () => {
    expect(getDisplayFilename("uploads/admissions/42/priority_04_abc.pdf"))
      .toBe("priority_04_abc.pdf")
  })

  it("returns empty string for null/undefined/empty", () => {
    expect(getDisplayFilename(null)).toBe("")
    expect(getDisplayFilename(undefined)).toBe("")
    expect(getDisplayFilename("")).toBe("")
  })

  it("returns input as-is when no slash separator", () => {
    expect(getDisplayFilename("filename.pdf")).toBe("filename.pdf")
  })

  it("handles Windows-style backslash defensively (treats as no-separator)", () => {
    // Spec uses S3 forward-slash paths. Backslash returns as-is (no split).
    expect(getDisplayFilename("uploads\\admissions\\42\\x.pdf"))
      .toBe("uploads\\admissions\\42\\x.pdf")
  })

  it("strips trailing-slash edge case", () => {
    expect(getDisplayFilename("uploads/admissions/42/")).toBe("uploads/admissions/42/")
  })
})

describe("isMissingEvidenceFile — Decision #2 inline warning", () => {
  it("returns true when sub_code in missing_priority_evidence_codes", () => {
    const profile = { missing_priority_evidence_codes: ["07", "08"] }
    expect(isMissingEvidenceFile(profile, "07")).toBe(true)
    expect(isMissingEvidenceFile(profile, "08")).toBe(true)
  })

  it("returns false when sub_code NOT in missing list", () => {
    const profile = { missing_priority_evidence_codes: ["07"] }
    expect(isMissingEvidenceFile(profile, "04")).toBe(false)
  })

  it("returns false when missing_priority_evidence_codes is empty array", () => {
    const profile = { missing_priority_evidence_codes: [] }
    expect(isMissingEvidenceFile(profile, "04")).toBe(false)
  })

  it("returns false defensively when field undefined-like", () => {
    const profile = { missing_priority_evidence_codes: undefined as unknown as string[] }
    expect(isMissingEvidenceFile(profile, "04")).toBe(false)
  })
})

describe("resolveVerifyDocumentId — PR-2 P1 adjustment #4", () => {
  it("returns document_id from priority_evidence_documents when present", () => {
    const profile = {
      priority_evidence_documents: [
        {
          sub_code: "04",
          bonus_points: 1.0,
          label: "Giấy chứng nhận con thương binh",
          document_id: 99,
          document_file_path: "uploads/admissions/42/priority_04.pdf",
          status: "uploaded" as const,
          verification_status: "pending" as const,
        },
      ],
    }
    expect(resolveVerifyDocumentId(profile, "04")).toBe(99)
  })

  it("returns null when document_id missing on item (status='missing')", () => {
    const profile = {
      priority_evidence_documents: [
        {
          sub_code: "07",
          bonus_points: 0.5,
          label: "Hộ nghèo",
          document_id: null,
          document_file_path: null,
          status: "missing" as const,
          verification_status: null,
        },
      ],
    }
    expect(resolveVerifyDocumentId(profile, "07")).toBeNull()
  })

  it("returns null when sub_code not in priority_evidence_documents", () => {
    const profile = { priority_evidence_documents: [] }
    expect(resolveVerifyDocumentId(profile, "04")).toBeNull()
  })
})

describe("findEvidenceDocument", () => {
  const profile = {
    priority_evidence_documents: [
      {
        sub_code: "04",
        bonus_points: 1.0,
        label: "Con thương binh",
        document_id: 99,
        document_file_path: "uploads/.../x.pdf",
        status: "uploaded" as const,
        verification_status: "verified" as const,
      },
      {
        sub_code: "07",
        bonus_points: 0.5,
        label: "Hộ nghèo",
        document_id: null,
        document_file_path: null,
        status: "missing" as const,
        verification_status: null,
      },
    ],
  }

  it("finds matching sub_code item", () => {
    const item = findEvidenceDocument(profile, "04")
    expect(item?.label).toBe("Con thương binh")
    expect(item?.bonus_points).toBe(1.0)
  })

  it("returns undefined for non-existent sub_code", () => {
    expect(findEvidenceDocument(profile, "99")).toBeUndefined()
  })

  it("handles empty list", () => {
    expect(findEvidenceDocument({ priority_evidence_documents: [] }, "04"))
      .toBeUndefined()
  })
})

describe("isDisplayEntry — type narrowing", () => {
  it("returns true for entry with verified_by_name", () => {
    const entry = { status: "verified" as const, verified_by_name: "Test" }
    expect(isDisplayEntry(entry)).toBe(true)
  })

  it("returns true for entry with document_file_path", () => {
    const entry = { status: "verified" as const, document_file_path: "x.pdf" }
    expect(isDisplayEntry(entry)).toBe(true)
  })

  it("returns false for raw entry without display fields", () => {
    const entry = { status: "verified" as const, verified_by: 7 }
    expect(isDisplayEntry(entry)).toBe(false)
  })
})
