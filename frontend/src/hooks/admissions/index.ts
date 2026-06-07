/**
 * Admission Hooks - Re-exports
 *
 * Centralized exports for all admission-related hooks.
 * Import from this file for cleaner imports in components.
 *
 * @example
 * ```tsx
 * import {
 *   useGetAdmission,
 *   useUpdateAdmission,
 *   useAdmissionViewModel,
 * } from "@/hooks/admissions"
 * ```
 */

// ============================================================================
// QUERY HOOKS (useAdmissions.ts)
// ============================================================================
export {
  // Query Keys
  admissionsKeys,
  // Queries
  useListAdmissions,
  useGetAdmission,
  useAcademicYears,
  useDegreeLevelsPublic,
  useAdmissionPrograms,
  useAdmissionStatusCounts,
  useAdmissionStats,
  // Mutations
  useCreateAdmission,
  useUpdateAdmission,
  useRecordApplicationFeePayment,
  useSubmitAdmission,
  useResubmitAdmission,
  useApproveAdmission,
  useRejectAdmission,
  // E2E #10 fix 2026-05-15 — manager request_revision flow
  useRequestRevisionAdmission,
  // Phase 3 multi-NV: 1-click publish (bỏ start-review YAGNI)
  usePublishAdmissionResult,
  useEnrollStudent,
  useDeleteAdmission,
  useUploadAdmissionDocument,
  useMarkPaperSubmitted,
  useVerifyDocument,
  useRejectDocument,
  useResetDocument,
  // Bulk Actions
  useBulkApproveAdmissions,
  useBulkRejectAdmissions,
  useBulkAssignAdmissions,
  useClaimAdmission,
  useUnclaimAdmission,
  useExportAdmissions,
} from "./useAdmissions"

// ============================================================================
// FILTER HOOK (URL sync + localStorage + tab management)
// ============================================================================
export { useAdmissionsFilter } from "./useAdmissionsFilter"
export type {
  AdmissionsFilterState,
  AdmissionsFilterHandlers,
  UseAdmissionsFilterReturn,
} from "./useAdmissionsFilter"

// ============================================================================
// VIEW MODEL HOOKS (Phase 3 - Architecture Compliance)
// ============================================================================
export { useAdmissionViewModel } from "./useAdmissionViewModel"

// ============================================================================
// TYPES
// ============================================================================
export type {
  StepStatus,
  EligibilityStatus,
  AdmissionStatus,
  AdmissionViewStatus,
  AdmissionAction,
  DocumentStatus,
  SubmissionFormat,
  SubjectScore,
  ScoringConfig,
} from "./types"

