/**
 * useAdmissionViewStatus
 * 
 * REPLACEMENT for useAdmissionValidation.ts (DELETED)
 * 
 * This hook ONLY READS backend-computed state.
 * NO business logic calculation in frontend.
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 0.5.1 (State Ownership)
 * @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #1
 */

import { useMemo } from "react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export type StepStatus = "success" | "warning" | "error" | "locked"
export type EligibilityStatus = "eligible" | "ineligible" | "pending"

export interface AdmissionViewStatus {
  /**
   * Backend-computed eligibility status
   * Read from profile.eligibility_status
   */
  isEligible: boolean
  eligibilityStatus: EligibilityStatus
  
  /**
   * Backend-computed step status for sidebar
   * Read from profile.step_status
   */
  stepsStatus: Record<number, StepStatus>
  
  /**
   * Backend-computed validation errors
   * Read from profile.validation_errors
   */
  validationErrors: string[]
  
  /**
   * Backend-computed validation summary (grouped errors)
   * Read from profile.validation_summary
   */
  validationSummary: AdmissionProfileResponse["validation_summary"]
  
  /**
   * Profile completion percentage (0-100)
   * Read from profile.completion_percent
   */
  completionPercent: number
}

/**
 * Hook to read admission validation status from BACKEND.
 * 
 * ❌ OLD (DELETED): useAdmissionValidation - calculated FE business logic
 * ✅ NEW (THIS): useAdmissionViewStatus - only reads backend state
 * 
 * @example
 * const { isEligible, stepsStatus, validationErrors } = useAdmissionViewStatus(profile)
 * 
 * // Render based on backend state
 * {isEligible ? <SubmitButton /> : <ValidationMessage errors={validationErrors} />}
 */
export function useAdmissionViewStatus(
  profile: AdmissionProfileResponse | null | undefined
): AdmissionViewStatus {
  return useMemo(() => {
    // Default values when profile is not available
    if (!profile) {
      return {
        isEligible: false,
        eligibilityStatus: "pending" as EligibilityStatus,
        stepsStatus: {},
        validationErrors: [],
        validationSummary: null,
        completionPercent: 0,
      }
    }

    // Convert step_status keys from string to number (JSON serializes int keys as strings)
    const stepsStatus: Record<number, StepStatus> = {}
    if (profile.step_status) {
      Object.entries(profile.step_status).forEach(([key, value]) => {
        stepsStatus[parseInt(key, 10)] = value
      })
    }

    return {
      // Backend-computed eligibility
      isEligible: profile.eligibility_status === "eligible",
      eligibilityStatus: profile.eligibility_status ?? "pending",
      
      // Backend-computed step status (converted to number keys)
      stepsStatus,
      
      // Backend-computed validation errors
      validationErrors: profile.validation_errors ?? [],
      
      // Backend-computed validation summary
      validationSummary: profile.validation_summary,
      
      // Backend-computed completion percentage
      completionPercent: profile.completion_percent ?? 0,
    }
  }, [profile])
}
