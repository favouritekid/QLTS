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
  // Mutations
  useCreateAdmission,
  useUpdateAdmission,
  useSubmitAdmission,
  useEnrollStudent,
  useDeleteAdmission,
  useUploadAdmissionDocument,
  useMarkPaperSubmitted,
  useRejectDocument,
} from "./useAdmissions"

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

