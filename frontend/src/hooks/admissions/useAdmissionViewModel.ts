/**
 * Admission ViewModel Hook
 * 
 * ARCHITECTURE STANDARD: Frontend Domain Service Layer (Section 2.6)
 * 
 * This hook provides a View Model that:
 * 1. Wraps useGetAdmission query
 * 2. Transforms backend data for UI consumption
 * 3. Provides UX-only derivations (labels, colors, flags)
 * 4. Does NOT perform business logic calculations
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 2.6.6
 * @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #10
 */

import { useMemo } from "react"
import { useGetAdmission } from "./useAdmissions"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { StepStatus, EligibilityStatus } from "./types"

// ============================================================================
// STATUS LABELS & COLORS (UX derivation - allowed per 2.6.4)
// ============================================================================

const STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  submitted: "Chờ duyệt",
  resubmitted: "Nộp lại",
  approved: "Đã duyệt",
  rejected: "Từ chối",
  confirmed: "Đã xác nhận",
  enrolled: "Đã nhập học",
  overridden: "Đã override",
  revision_requested: "Yêu cầu bổ sung",
  withdrawn: "Đã rút hồ sơ",
}

const STATUS_COLORS: Record<string, string> = {
  draft: "gray",
  submitted: "yellow",
  resubmitted: "amber",
  approved: "green",
  rejected: "red",
  confirmed: "emerald",
  enrolled: "blue",
  overridden: "purple",
  revision_requested: "orange",
  withdrawn: "gray",
}

// ============================================================================
// VIEW MODEL INTERFACE
// ============================================================================

export interface AdmissionViewModel {
  // -------------------------------------------------------------------------
  // Pass-through fields (directly from backend)
  // -------------------------------------------------------------------------
  id: number
  lead_id: number
  status: string
  version?: number // Optional - may not be present in all responses
  academic_year?: number
  created_at: string
  updated_at: string
  
  // Personal Info (pass-through)
  full_name?: string | null
  phone?: string | null
  email?: string | null
  dob?: string | null
  gender?: string | null
  citizen_id?: string | null
  
  // Nested relationships
  lead?: AdmissionProfileResponse["lead"]
  student?: AdmissionProfileResponse["student"]
  
  // Applied rules (pass-through)
  applied_rules: AdmissionProfileResponse["applied_rules"]
  
  // Form data (pass-through for form population)
  family_info: AdmissionProfileResponse["family_info"]
  academic_history: AdmissionProfileResponse["academic_history"]
  admission_scores: AdmissionProfileResponse["admission_scores"]
  documents_checklist: AdmissionProfileResponse["documents_checklist"]
  
  // Backend-computed scores
  total_score?: number | null
  average_score?: number | null
  
  // Audit trail
  approved_at?: string | null
  approved_by_id?: number | null
  rejected_at?: string | null
  rejected_by_id?: number | null

  // Claim/assignment fields
  assigned_reviewer_id?: number | null
  assigned_reviewer_name?: string | null
  assigned_at?: string | null
  assigned_officer_name?: string | null

  // -------------------------------------------------------------------------
  // UX Derivations (computed from backend data - allowed per 2.6.4)
  // -------------------------------------------------------------------------
  
  /** Vietnamese label for current status */
  statusLabel: string
  
  /** Color name for status badge */
  statusColor: string
  
  // -------------------------------------------------------------------------
  // Permission Flags (from backend available_actions)
  // -------------------------------------------------------------------------
  
  canEdit: boolean
  canSave: boolean
  canSubmit: boolean
  canApprove: boolean
  canReject: boolean
  canEnroll: boolean
  canDelete: boolean
  canClaim: boolean
  canUnclaim: boolean

  // -------------------------------------------------------------------------
  // Backend-Computed State (pass-through, NOT calculated)
  // -------------------------------------------------------------------------
  
  /** Eligibility status from backend */
  eligibilityStatus: EligibilityStatus
  
  /** Boolean convenience for "is eligible" */
  isEligible: boolean
  
  /** Is profile qualified for admission */
  isQualified: boolean | null
  
  /** Validation errors from backend */
  validationErrors: string[]

  /** Validation summary (grouped errors) */
  validationSummary: AdmissionProfileResponse["validation_summary"]

  /** Grouped validation errors (categorized display) */
  groupedValidationErrors: AdmissionProfileResponse["grouped_validation_errors"]

  /** Step status for sidebar navigation */
  stepsStatus: Record<number, StepStatus>
  
  /** Completion percentage (0-100) */
  completionPercent: number
  
  /** Available workflow actions */
  availableActions: string[]
  
  /** Permission flags object */
  permissions: Record<string, boolean>

  // -------------------------------------------------------------------------
  // Legacy Snake_case Fields (for component compatibility)
  // -------------------------------------------------------------------------
  completion_percent: number
  eligibility_status: string
  step_status?: Record<string, string> | null
  validation_errors: string[]
  validation_summary?: AdmissionProfileResponse["validation_summary"]
  grouped_validation_errors?: AdmissionProfileResponse["grouped_validation_errors"]
  available_actions: string[]
}

// ============================================================================
// HOOK IMPLEMENTATION
// ============================================================================

/**
 * Hook that provides a View Model for admission profile.
 * 
 * @example
 * ```tsx
 * function AdmissionPage({ id }) {
 *   const { data: vm, isLoading, error } = useAdmissionViewModel(id)
 *   
 *   if (!vm) return <Loading />
 *   
 *   return (
 *     <>
 *       <StatusBadge status={vm.status} label={vm.statusLabel} color={vm.statusColor} />
 *       {vm.canSubmit && <SubmitButton />}
 *       {vm.isEligible ? <EligibleIcon /> : <IneligibleIcon />}
 *     </>
 *   )
 * }
 * ```
 */
export function useAdmissionViewModel(
  id: number,
  options?: {
    enabled?: boolean
    initialData?: AdmissionProfileResponse
    staleTime?: number
  }
) {
  const query = useGetAdmission(id, options)

  const viewModel = useMemo((): AdmissionViewModel | null => {
    const data = query.data
    if (!data) return null

    // Destructure for clarity
    const {
      status,
      available_actions = [],
      step_status,
      eligibility_status = "pending",
      validation_errors = [],
      validation_summary,
      grouped_validation_errors,
      completion_percent = 0,
      permissions = {},
      ...rest
    } = data

    // Convert step_status string keys to number keys
    const stepsStatus: Record<number, StepStatus> = {}
    if (step_status) {
      Object.entries(step_status).forEach(([key, value]) => {
        stepsStatus[parseInt(key, 10)] = value
      })
    }

    return {
      // Pass-through fields
      ...rest,
      status,
      
      // Re-export snake_case fields for component compatibility (Zod Schema)
      // Fixes 0% completion and missing status badges in ExecutiveSummary
      completion_percent: completion_percent,
      eligibility_status: eligibility_status,
      step_status: step_status,
      validation_errors: validation_errors,
      validation_summary: validation_summary,
      grouped_validation_errors: grouped_validation_errors,
      permissions: permissions,
      available_actions: available_actions,

      // UX Derivations (labels/colors)
      statusLabel: STATUS_LABELS[status] ?? status,
      statusColor: STATUS_COLORS[status] ?? "gray",
      
      // Permission flags from available_actions
      canEdit: available_actions.includes("edit"),
      canSave: available_actions.includes("save"),
      canSubmit: available_actions.includes("submit"),
      canApprove: available_actions.includes("approve"),
      canReject: available_actions.includes("reject"),
      canEnroll: available_actions.includes("enroll"),
      canDelete: available_actions.includes("delete"),
      canClaim: available_actions.includes("claim"),
      canUnclaim: available_actions.includes("unclaim"),

      // Claim/assignment display fields
      assigned_reviewer_id: data.assigned_reviewer_id,
      assigned_reviewer_name: data.assigned_reviewer_name,
      assigned_at: data.assigned_at,
      assigned_officer_name: data.assigned_officer_name,

      // Backend-computed state (pass-through)
      eligibilityStatus: eligibility_status as EligibilityStatus,
      isEligible: eligibility_status === "eligible",
      isQualified: data.is_qualified ?? null,
      validationErrors: validation_errors,
      validationSummary: validation_summary,
      groupedValidationErrors: grouped_validation_errors,
      stepsStatus,
      completionPercent: completion_percent,
      availableActions: available_actions,
      // permissions already in snake_case above
    }
  }, [query.data])

  return {
    ...query,
    data: viewModel,
  }
}

// Re-export types for convenience
export type { StepStatus, EligibilityStatus }
