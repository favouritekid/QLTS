/**
 * Admission Helper Utilities
 *
 * Utility functions for Executive Summary display.
 * Follows Thin Client Philosophy: NO business logic, only presentation formatting.
 */

import type { AppliedRules, DocumentItem } from "@/lib/zod/admissions"

// ==============================================================================
// ADMISSION METHOD LABELS
// ==============================================================================

/**
 * Get human-readable label for admission method code.
 * @param appliedRules Applied rules snapshot from backend
 * @returns Formatted admission method label
 */
export function getAdmissionMethodLabel(appliedRules: AppliedRules): string {
  const methodLabels: Record<string, string> = {
    HOC_BA: "Xét học bạ THPT",
    THI_THPT: "Xét điểm thi THPT Quốc gia",
    DGNL: "Xét điểm đánh giá năng lực",
    IELTS: "Xét chứng chỉ IELTS",
    SAT: "Xét điểm SAT",
    TUYEN_THANG: "Tuyển thẳng",
    UU_TIEN: "Xét ưu tiên",
  }

  const method = appliedRules.admission_method
  if (!method) return "Chưa xác định"

  return methodLabels[method] ?? method
}

// ==============================================================================
// SUBJECT LABELS
// ==============================================================================

/**
 * Get Vietnamese label for subject code.
 * @param code Subject code (e.g., "math", "physics")
 * @returns Vietnamese subject name
 */
export function getSubjectLabel(code: string): string {
  const labels: Record<string, string> = {
    math: "Toán",
    physics: "Vật lý",
    chemistry: "Hóa học",
    biology: "Sinh học",
    literature: "Ngữ văn",
    english: "Tiếng Anh",
    history: "Lịch sử",
    geography: "Địa lý",
    civic_education: "GDCD",
    foreign_language: "Ngoại ngữ",
  }

  return labels[code] ?? code
}

// ==============================================================================
// DOCUMENT FORMAT LABELS
// ==============================================================================

/**
 * Document submission format codes accepted by backend doc_configs and
 * verify-format endpoints. Centralised so UI labels stay consistent across
 * DocumentsTab, DocumentChecklist, and any future format picker.
 */
export type DocumentFormatCode = "original" | "certified_copy" | "photo"

const FORMAT_LABELS: Record<DocumentFormatCode, string> = {
  original: "Bản gốc",
  certified_copy: "Bản sao chứng thực",
  photo: "Bản chụp/scan không chứng thực",
}

const FORMAT_DESCRIPTIONS: Record<DocumentFormatCode, string> = {
  original: "Giấy tờ gốc do cơ quan có thẩm quyền cấp",
  certified_copy: "Bản photocopy đã được công chứng/chứng thực",
  photo: "Bản chụp ảnh hoặc scan, không có công chứng",
}

/**
 * Get Vietnamese label for document submission format.
 * Single source of truth — do not duplicate this map in components.
 * @param format Format code (original | certified_copy | photo) or unknown
 * @returns Vietnamese format name (falls back to raw code if unknown)
 */
export function getFormatLabel(format: string | null | undefined): string {
  if (!format) return "-"
  return FORMAT_LABELS[format as DocumentFormatCode] ?? format
}

/**
 * Get short description for a document submission format.
 * Used in pickers to clarify what each option physically represents.
 */
export function getFormatDescription(format: string | null | undefined): string {
  if (!format) return ""
  return FORMAT_DESCRIPTIONS[format as DocumentFormatCode] ?? ""
}

/**
 * Ordered list of document format options for radio/select pickers.
 */
export const DOCUMENT_FORMAT_OPTIONS: ReadonlyArray<{
  value: DocumentFormatCode
  label: string
  description: string
}> = [
  { value: "original", label: FORMAT_LABELS.original, description: FORMAT_DESCRIPTIONS.original },
  { value: "certified_copy", label: FORMAT_LABELS.certified_copy, description: FORMAT_DESCRIPTIONS.certified_copy },
  { value: "photo", label: FORMAT_LABELS.photo, description: FORMAT_DESCRIPTIONS.photo },
]

// ==============================================================================
// DOCUMENT STATUS CONFIG
// ==============================================================================

export interface DocumentStatusConfig {
  variant: "default" | "secondary" | "destructive" | "outline"
  label: string
  iconName: "XCircle" | "Upload" | "CheckCircle2" | "FileText"
}

/**
 * Get status configuration for document status.
 * Note: This returns config object, not JSX. Components should use this to create Badge.
 * @param status Document status from backend
 * @returns Status configuration (variant, label, iconName)
 */
export function getDocumentStatusConfig(status: string): DocumentStatusConfig {
  const config: Record<string, DocumentStatusConfig> = {
    missing: {
      variant: "destructive",
      label: "Chưa nộp",
      iconName: "XCircle",
    },
    uploaded: {
      // "Ghi nhận" (received) is intentionally distinct from "Kiểm tra"
      // (verified). Officer still has to verify the upload before this row
      // counts as fully complete.
      variant: "secondary",
      label: "Đã ghi nhận file",
      iconName: "Upload",
    },
    verified: {
      variant: "default",
      label: "Đã kiểm tra",
      iconName: "CheckCircle2",
    },
    rejected: {
      variant: "destructive",
      label: "Từ chối",
      iconName: "XCircle",
    },
    paper_submitted: {
      variant: "secondary",
      label: "Đã nhận bản giấy",
      iconName: "FileText",
    },
  }

  return config[status] ?? config.missing
}

/**
 * True when the row has been fully checked by an officer. Use ONLY when
 * you specifically need the "officer-verified" subset — for the
 * mandatory-completion gauge, prefer ``isDocumentRequirementSatisfied``
 * so that paper_submitted (which the backend already accepts as
 * satisfying the requirement) is not surfaced as incomplete.
 */
export function isDocumentVerified(status: string): boolean {
  return status === "verified"
}

/**
 * True when the row has been received in some form — either uploaded
 * online or accepted as paper at the counter. Verified rows are also
 * recorded.
 */
export function isDocumentRecorded(status: string): boolean {
  return status === "uploaded" || status === "paper_submitted" || status === "verified"
}

/**
 * ADM-031.6 follow-up: True when the row satisfies the backend's
 * mandatory-document gate. Mirrors the strict-mode check at
 * ``Backend_FastAPI/app/services/admission_service.py:566`` which
 * accepts BOTH ``verified`` and ``paper_submitted`` as completing the
 * requirement. ``uploaded`` (file received but officer hasn't verified
 * yet) is intentionally excluded — that row is still pending check.
 *
 * Use this for the "Hoàn tất yêu cầu" / mandatory-progress metric so
 * paper-only rows don't masquerade as incomplete just because they were
 * never digitised.
 */
export function isDocumentRequirementSatisfied(status: string): boolean {
  return status === "verified" || status === "paper_submitted"
}

/**
 * ADM-031.6 follow-up: True when the row was uploaded online but still
 * waits for officer verification. This is the "Chờ kiểm tra" bucket;
 * surfacing it lets officers see the verification queue separately from
 * fully completed rows.
 */
export function isDocumentPendingVerification(status: string): boolean {
  return status === "uploaded"
}

// ==============================================================================
// DATE FORMATTING
// ==============================================================================

/**
 * Format ISO date string to Vietnamese date format.
 * @param isoString ISO 8601 date string from backend
 * @returns Formatted date string (dd/mm/yyyy)
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "-"

  try {
    const date = new Date(isoString)
    return date.toLocaleDateString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    })
  } catch {
    return isoString
  }
}

/**
 * Format ISO datetime string to Vietnamese datetime format.
 * @param isoString ISO 8601 datetime string from backend
 * @returns Formatted datetime string (dd/mm/yyyy HH:mm)
 */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "-"

  try {
    const date = new Date(isoString)
    return date.toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return isoString
  }
}

// ==============================================================================
// DOCUMENT COUNTING
// ==============================================================================

/**
 * Count documents by status (for summary display).
 * @param documents Documents checklist from backend
 * @param status Status to count
 * @param mandatoryOnly Count only mandatory documents
 * @returns Count of documents matching criteria
 */
export function countDocumentsByStatus(
  documents: DocumentItem[],
  status: string,
  mandatoryOnly: boolean = true
): number {
  return documents.filter(
    (doc) =>
      doc.status === status &&
      (!mandatoryOnly || doc.is_mandatory)
  ).length
}

/**
 * Get total count of mandatory documents.
 * @param documents Documents checklist from backend
 * @returns Total mandatory documents
 */
export function getMandatoryDocsCount(documents: DocumentItem[]): number {
  return documents.filter((doc) => doc.is_mandatory).length
}

/**
 * Get count of verified mandatory documents.
 * @param documents Documents checklist from backend
 * @returns Count of verified mandatory documents
 */
export function getVerifiedDocsCount(documents: DocumentItem[]): number {
  return countDocumentsByStatus(documents, "verified", true)
}

/**
 * Get count of missing mandatory documents.
 * @param documents Documents checklist from backend
 * @returns Count of missing mandatory documents
 */
export function getMissingDocsCount(documents: DocumentItem[]): number {
  return countDocumentsByStatus(documents, "missing", true)
}

// ==============================================================================
// SCORE VALIDATION - REMOVED (Thin Client Compliance)
// ==============================================================================
//
// The following functions have been REMOVED as they violate Thin Client philosophy:
// - isSubjectPassing() - Use profile.score_snapshot_status.subject_statuses instead
// - isTotalScorePassing() - Use profile.score_snapshot_status.total_status instead
//
// Backend now computes pass/fail status and returns it in the API response.
// See: ScoreSnapshot.tsx for correct usage pattern.
// ==============================================================================
