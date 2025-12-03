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
 *   useSubmitAdmission
 * } from "@/hooks/admissions"
 * ```
 */

export {
  // Query Keys
  admissionsKeys,
  // Queries
  useGetAdmission,
  useAdmissionProfile,
  // Mutations
  useCreateAdmission,
  useUpdateAdmission,
  useSubmitAdmission,
  useEnrollStudent,
  // Utilities
  useIsProfileEditable,
  useCanSubmitProfile,
  useCanEnrollStudent,
} from "./useAdmissions"
