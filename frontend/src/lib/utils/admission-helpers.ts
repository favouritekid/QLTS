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
 * Get Vietnamese label for document submission format.
 * @param format Format code (original | certified_copy | photo)
 * @returns Vietnamese format name
 */
export function getFormatLabel(format: string): string {
  const labels: Record<string, string> = {
    original: "Bản chính",
    certified_copy: "Bản sao có chứng thực",
    photo: "Bản photocopy",
  }

  return labels[format] ?? format
}

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
      variant: "secondary",
      label: "Đã tải lên",
      iconName: "Upload",
    },
    verified: {
      variant: "default",
      label: "Đã xác nhận",
      iconName: "CheckCircle2",
    },
    rejected: {
      variant: "destructive",
      label: "Từ chối",
      iconName: "XCircle",
    },
    paper_submitted: {
      variant: "secondary",
      label: "Nộp giấy",
      iconName: "FileText",
    },
  }

  return config[status] ?? config.missing
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
// SCORE VALIDATION
// ==============================================================================

/**
 * Check if a subject score passes the minimum threshold.
 * @param score Subject score (0-10)
 * @param minSubjectScore Minimum allowed score from applied_rules
 * @returns True if score passes threshold
 */
export function isSubjectPassing(
  score: number | null | undefined,
  minSubjectScore: number | null | undefined
): boolean {
  if (score === null || score === undefined) return false
  const threshold = minSubjectScore ?? 0
  return score >= threshold
}

/**
 * Check if total score passes the minimum threshold.
 * @param totalScore Total admission score
 * @param minScore Minimum required score from applied_rules
 * @returns True if total score passes threshold
 */
export function isTotalScorePassing(
  totalScore: number | null | undefined,
  minScore: number | null | undefined
): boolean {
  if (totalScore === null || totalScore === undefined) return false
  const threshold = minScore ?? 0
  return totalScore >= threshold
}
