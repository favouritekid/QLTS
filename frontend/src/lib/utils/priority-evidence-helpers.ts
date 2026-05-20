/**
 * Q9 #07 Phase E.4 — Priority evidence display helpers (pure functions).
 *
 * Thin Client Philosophy: NO business logic. Pure presentation/formatting
 * helpers + read-through fallback for transient display projection.
 */

import type {
  AdmissionProfileResponse,
  PriorityEvidenceDocumentItem,
  PriorityObjectEvidenceDisplayEntry,
  PriorityObjectEvidenceEntry,
} from "@/lib/zod/admissions"

// ==============================================================================
// EVIDENCE DISPLAY FALLBACK
// ==============================================================================

/**
 * Read evidence với display projection fallback.
 *
 * BE Phase E.4 ships `priority_object_evidence_display` (TRANSIENT) enriched
 * với verified_by_name + document_file_path. FE prefer này over raw column
 * cho UI rendering. Fallback to raw nếu BE chưa populate (vd legacy data,
 * BE error path skips _populate_response_fields).
 *
 * Returns Record<sub_code, entry> — entries may be display schema (enriched)
 * hoặc write schema (raw). FE renders defensively cho cả 2 shapes.
 */
export function getEvidence(
  profile: Pick<
    AdmissionProfileResponse,
    "priority_object_evidence" | "priority_object_evidence_display"
  >,
): Record<string, PriorityObjectEvidenceEntry | PriorityObjectEvidenceDisplayEntry> {
  return profile.priority_object_evidence_display ?? profile.priority_object_evidence
}

// ==============================================================================
// FILE PATH → DISPLAY FILENAME
// ==============================================================================

/**
 * Extract basename từ S3 file_path cho FE display.
 *
 * BE ProfileDocument.file_path là full S3 path (vd
 * "uploads/admissions/42/priority_04_abc123.pdf"). FE display basename
 * (`priority_04_abc123.pdf`) để compact UI. Per spec Section VI — không
 * có dedicated `original_filename` column (defer Phase E.5+).
 *
 * Returns empty string cho null/undefined/empty input để JSX an toàn.
 */
export function getDisplayFilename(filePath: string | null | undefined): string {
  if (!filePath) return ""
  const segments = filePath.split("/")
  return segments[segments.length - 1] || filePath
}

// ==============================================================================
// MISSING EVIDENCE INLINE WARNING (Decision #2)
// ==============================================================================

/**
 * Check if UT sub_code missing minh chứng file (Decision #2 inline warning).
 *
 * BE compute `missing_priority_evidence_codes` trong _populate_priority_
 * evidence_projections helper. FE render warning ⚠ Chưa scan minh chứng
 * cho codes trong list. KHÔNG block submit — warning purely UX (per
 * Decision #2 "inline warning, KHÔNG eligibility gate").
 */
export function isMissingEvidenceFile(
  profile: Pick<AdmissionProfileResponse, "missing_priority_evidence_codes">,
  subCode: string,
): boolean {
  return (profile.missing_priority_evidence_codes ?? []).includes(subCode)
}

// ==============================================================================
// EVIDENCE STATUS LABEL MAPPING
// ==============================================================================

export const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  pending: "Chờ duyệt",
  verified: "Đã duyệt",
  rejected: "Đã từ chối",
}

export const EVIDENCE_STATUS_BADGES: Record<string, { label: string; tone: "neutral" | "success" | "warning" | "danger" }> = {
  pending: { label: "⏳ Chờ duyệt", tone: "warning" },
  verified: { label: "✅ Đã duyệt", tone: "success" },
  rejected: { label: "✗ Từ chối", tone: "danger" },
}

/**
 * Resolve verify document_id từ priority_evidence_documents.
 *
 * Per PR-2 P1 contract (adjustment #4): FE verify mutation MUST pass
 * server-side document_id nếu đã upload, KHÔNG hardcode null. Null chỉ
 * cho paper-only verify (no file scanned yet).
 *
 * Returns:
 * - document_id (number) nếu evidence document exists (status uploaded/
 *   verified/rejected)
 * - null nếu missing (paper-only verify path)
 */
export function resolveVerifyDocumentId(
  profile: Pick<AdmissionProfileResponse, "priority_evidence_documents">,
  subCode: string,
): number | null {
  const doc = (profile.priority_evidence_documents ?? []).find(
    (item: PriorityEvidenceDocumentItem) => item.sub_code === subCode,
  )
  return doc?.document_id ?? null
}

/**
 * Find priority evidence document item by sub_code.
 *
 * Convenience accessor cho UI components — UtEvidenceCards reads từ G0a
 * pre-projection thay vì zip với evidence dict + catalog.
 */
export function findEvidenceDocument(
  profile: Pick<AdmissionProfileResponse, "priority_evidence_documents">,
  subCode: string,
): PriorityEvidenceDocumentItem | undefined {
  return (profile.priority_evidence_documents ?? []).find(
    (item: PriorityEvidenceDocumentItem) => item.sub_code === subCode,
  )
}

// ==============================================================================
// EVIDENCE TYPE GUARDS
// ==============================================================================

/**
 * Type-narrowing helper — check if entry is enriched display schema
 * (has verified_by_name OR document_file_path).
 */
export function isDisplayEntry(
  entry: PriorityObjectEvidenceEntry | PriorityObjectEvidenceDisplayEntry,
): entry is PriorityObjectEvidenceDisplayEntry {
  return (
    "verified_by_name" in entry || "document_file_path" in entry
  )
}
