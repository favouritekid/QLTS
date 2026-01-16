/**
 * Admission Domain Types
 * 
 * Shared types for the admission module.
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 2.6.6
 */

// ============================================================================
// STATUS TYPES
// ============================================================================

/**
 * Step status for sidebar navigation.
 * 
 * - success: Step is complete and valid
 * - warning: Step has optional missing items
 * - error: Step has required missing items
 * - locked: Step is not yet accessible
 */
export type StepStatus = "success" | "warning" | "error" | "locked"

/**
 * Eligibility status computed by backend.
 * 
 * - eligible: Profile meets all admission criteria
 * - ineligible: Profile does not meet criteria
 * - pending: Still being evaluated (incomplete data)
 */
export type EligibilityStatus = "eligible" | "ineligible" | "pending"

/**
 * Admission profile status (workflow state).
 */
export type AdmissionStatus = 
  | "draft"
  | "submitted"
  | "resubmitted"
  | "approved"
  | "rejected"
  | "confirmed"
  | "enrolled"
  | "overridden"

// ============================================================================
// VIEW MODEL TYPES
// ============================================================================

/**
 * Minimal view status returned by useAdmissionViewStatus hook.
 */
export interface AdmissionViewStatus {
  isEligible: boolean
  eligibilityStatus: EligibilityStatus
  stepsStatus: Record<number, StepStatus>
  validationErrors: string[]
  validationSummary: {
    gpa?: { has_error: boolean; label: string; count: number }
    documents?: { has_error: boolean; label: string; count: number }
    personal?: { has_error: boolean; label: string; count: number }
  } | null | undefined
  completionPercent: number
}

// ============================================================================
// ACTION TYPES
// ============================================================================

/**
 * Available actions that can be performed on an admission profile.
 * These are returned by the backend in available_actions array.
 */
export type AdmissionAction = 
  | "edit"
  | "save"
  | "submit"
  | "approve"
  | "reject"
  | "resubmit"
  | "confirm"
  | "enroll"
  | "delete"
  | "override"

// ============================================================================
// DOCUMENT TYPES
// ============================================================================

/**
 * Document upload status.
 */
export type DocumentStatus = "missing" | "uploaded" | "verified" | "rejected"

/**
 * Document submission format.
 */
export type SubmissionFormat = "photo" | "certified_copy" | "original"

// ============================================================================
// SCORE TYPES
// ============================================================================

/**
 * Subject score entry.
 */
export interface SubjectScore {
  subject_code: string
  score: number | null
}

/**
 * Admission scoring configuration.
 */
export interface ScoringConfig {
  method_type: "gpa_only" | "subject_based" | "combined"
  min_gpa?: number
  min_score?: number
  subject_groups?: string[]
}
