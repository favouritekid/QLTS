import { useMemo } from "react"
import { UseFormReturn, useWatch, FieldValues } from "react-hook-form"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"

export type StepStatus = "success" | "warning" | "error" | "locked"

interface FamilyMember {
  is_primary_guardian: boolean;
}

interface DocumentItem {
  status: string;
  file_path?: string;
  code: string;
}

interface ValidationResult {
  stepsStatus: Record<number, StepStatus>
  isEligible: boolean
  missingItems: {
    code: string
    label: string
    status: "error" | "warning"
  }[]
  metrics: {
      uploadedDocsCount: number
      totalMandatoryDocs: number
      gpa: number
      minGpa: number
  }
}

export function useAdmissionValidation(
  form: UseFormReturn<FieldValues>,
  profile: AdmissionProfileResponse | null | undefined
): ValidationResult {
  // Watch all values to trigger re-validation
  const values = useWatch({ control: form.control })

  return useMemo(() => {
    const status: Record<number, StepStatus> = {}
    const missing: ValidationResult["missingItems"] = []

    // --- RULES ---
    const appliedRules = profile?.applied_rules || {}
    const minGpa = appliedRules.min_gpa ?? 5.0
    const mandatoryDocs: string[] = appliedRules.mandatory_docs || []

    // 1. Personal Info
    // Required: full_name, dob, gender, citizen_id
    const hasBasicInfo = !!(values.full_name && values.dob && values.gender)
    const hasCitizenId = !!values.citizen_id
    
    if (!hasCitizenId) {
        status[1] = "error"
        missing.push({ code: "CCCD", label: "CCCD", status: "error" })
    } else if (!hasBasicInfo) {
        status[1] = "warning"
    } else {
        status[1] = "success"
    }

    // 2. Family
    // Required: At least one primary guardian
    const hasPrimaryGuardian = values.family_info?.some((f: FamilyMember) => f.is_primary_guardian)
    if (!hasPrimaryGuardian) {
        status[2] = "error"
        missing.push({ code: "GUARDIAN", label: "Phụ huynh", status: "error" })
    } else {
        status[2] = "success"
    }

    // 3. Academic
    // Required: At least one record
    const hasAcademic = (values.academic_history?.length || 0) > 0
    status[3] = hasAcademic ? "success" : "warning"

    // 4. Scores
    // Required: GPA >= minGpa and gpa is not null
    const gpa = values.admission_scores?.gpa ?? 0
    // Check if score object exists and gpa is provided (not 0 default if actually 0, but here 0 means likely empty or fail)
    // Actually we need to check if it's strictly defined. 
    // In our logic: null/undefined -> 0.
    
    // Check strict input presence:
    const hasGpaInput = values.admission_scores?.gpa !== undefined && values.admission_scores?.gpa !== null
    
    if (!hasGpaInput) {
        status[4] = "error"
        missing.push({ code: "GPA_MISSING", label: "Nhập điểm", status: "error" })
    } else if (gpa < minGpa) {
        status[4] = "error"
        missing.push({ code: "GPA_LOW", label: "GPA thấp", status: "error" })
    } else {
        status[4] = "success"
    }

    // 5. Documents
    const uploadedDocs = (values.documents_checklist || [])
        .filter((d: DocumentItem) => d.status === "uploaded" && d.file_path)
    const uploadedDocCodes = uploadedDocs.map((d: DocumentItem) => d.code)
    
    const missingDocs = mandatoryDocs.filter((code: string) => !uploadedDocCodes.includes(code))
    
    if (missingDocs.length > 0) {
        status[5] = "error"
        missing.push({ 
            code: "DOCS", 
            label: `Tài liệu ${uploadedDocs.length}/${mandatoryDocs.length}`, 
            status: "error" 
        })
    } else {
        status[5] = "success"
    }

    // 6. Tuition (Future) - Dependent on Eligibility
    // 7. Finalize
    const isEligible = status[1] !== "error" && status[2] !== "error" && status[4] !== "error" && status[5] !== "error"
    
    status[6] = isEligible ? "warning" : "locked" // Placeholder for tuition
    status[7] = isEligible ? "warning" : "locked"

    return {
      stepsStatus: status,
      isEligible,
      missingItems: missing,
      metrics: {
          uploadedDocsCount: uploadedDocs.length,
          totalMandatoryDocs: mandatoryDocs.length,
          gpa,
          minGpa
      }
    }
  }, [values, profile]) // Re-run when form values or profile changes
}
