"use client"

import { useState, useEffect, useMemo } from "react"
import { useForm, FormProvider } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

// Phase 7: Reusable status banners
import { StatusBanner, ValidationErrorsBanner, AdmissionPendingBanner } from "@/components/ui/StatusBanner"

import {
  useGetAdmission,
  useUpdateAdmission,
  useSubmitAdmission,
  useEnrollStudent,
} from "@/hooks/admissions"
import {
  admissionProfileUpdateSchema,
  type AdmissionProfileResponse,
  type AdmissionProfileUpdate,
} from "@/lib/zod/admissions"

// Architecture Standards (Phase 7)
import { usePermissions } from "@/hooks/usePermissions"
import { getStatusConfig } from "@/lib/status-config"

// Layout & Components
import { AdmissionLayout } from "./layout/AdmissionLayout"
import { AdmissionActions } from "./AdmissionActions"

// Tabs
import { PersonalInfoTab } from "./tabs/PersonalInfoTab"
import { FamilyTab } from "./tabs/FamilyTab"
import { AcademicHistoryTab } from "./tabs/AcademicHistoryTab"
import { ScoresTab } from "./tabs/ScoresTab"
import { DocumentsTab } from "./tabs/DocumentsTab"
import { TuitionTab } from "./tabs/TuitionTab"
import { FinalizeTab } from "./tabs/FinalizeTab"

interface AdmissionDetailClientProps {
  profileId: number
  initialData: AdmissionProfileResponse
}

export function AdmissionDetailClient({
  profileId,
  initialData,
}: AdmissionDetailClientProps) {
  // =========================================================================
  // 1. Data Fetching
  // =========================================================================
  const { data: profile } = useGetAdmission(profileId, {
    initialData,
    staleTime: 15000, // 15 seconds - auto-refresh when stale
  })

  const updateMutation = useUpdateAdmission(profileId)
  const submitMutation = useSubmitAdmission(profileId)
  const enrollMutation = useEnrollStudent(profileId)

  // =========================================================================
  // 2. Phase 7: Permission-Based Rendering (ADR-FE-002)
  // =========================================================================
  const { can } = usePermissions(profile)
  
  // =========================================================================
  // 3. Phase 7: Status-Driven UI (ADR-FE-003)
  // =========================================================================
  const statusConfig = useMemo(
    () => getStatusConfig(profile?.status ?? 'draft'),
    [profile?.status]
  )
  
  // =========================================================================
  // 4. Phase 7: Backend-Computed Fields (ADR-FE-001)
  // Read eligibility from backend instead of local calculation
  // =========================================================================
  const isEligible = profile?.eligibility_status === 'eligible'
  const validationErrors = profile?.validation_errors ?? []
  const completionPercent = profile?.completion_percent ?? 0
  
  // Convert validation errors to missingItems format for AdmissionLayout
  // Note: missingItems is kept for backward compatibility but Header now uses validation_summary
  const missingItems = useMemo(() => 
    validationErrors.map(err => ({
      code: err,
      label: err,
      status: "error" as const
    }))
  , [validationErrors])

  // =========================================================================
  // Phase 0.9: Read step_status from Backend (Architecture Compliant)
  // Backend computes, Frontend renders - NO local calculation
  // =========================================================================
  const stepsStatus = useMemo(() => {
    // Read directly from backend step_status
    const backendStatus = profile?.step_status
    if (backendStatus) {
      // Convert string keys from JSON to number keys for component compatibility
      const converted: Record<number, "success" | "warning" | "error" | "locked"> = {}
      for (const [key, value] of Object.entries(backendStatus)) {
        converted[parseInt(key, 10)] = value as "success" | "warning" | "error" | "locked"
      }
      return converted
    }
    // Fallback for backward compatibility (if backend doesn't return step_status yet)
    return {
      1: "success", 2: "success", 3: "success", 
      4: "success", 5: "success", 6: "success", 7: "locked"
    } as Record<number, "success" | "warning" | "error" | "locked">
  }, [profile?.step_status])

  // =========================================================================
  // 5. Navigation State
  // =========================================================================
  const [currentStep, setCurrentStep] = useState(1)

  // =========================================================================
  // 6. Form Setup
  // =========================================================================
  const form = useForm<AdmissionProfileUpdate>({
    resolver: zodResolver(admissionProfileUpdateSchema),
    mode: "onBlur", // ADR-FE-001: Validate on blur, not on every change
    defaultValues: {
      citizen_id: profile?.citizen_id || "",
      full_name: profile?.full_name || "",
      phone: profile?.phone || "",
      email: profile?.email || "",
      dob: profile?.dob || undefined,
      gender: profile?.gender || "",
      social_insurance_number: profile?.social_insurance_number || "",
      nationality: profile?.nationality || "",
      ethnicity: profile?.ethnicity || "",
      religion: profile?.religion || "",
      disability_type: profile?.disability_type || "",
      permanent_province: profile?.permanent_province || "",
      permanent_district: profile?.permanent_district || "",
      permanent_ward: profile?.permanent_ward || "",
      place_of_birth: profile?.place_of_birth || "",
      native_place: profile?.native_place || "",
      union_entry_date: profile?.union_entry_date || undefined,
      party_entry_date: profile?.party_entry_date || undefined,
      party_official_entry_date: profile?.party_official_entry_date || undefined,
      family_info: profile?.family_info || [],
      academic_history: profile?.academic_history || [],
      admission_scores: profile?.admission_scores || {},
      documents_checklist: profile?.documents_checklist || [],
      version: profile?.version ?? 1,
    },
  })

  // Form Reset on Data Update
  useEffect(() => {
    if (profile) {
      form.reset({
        citizen_id: profile.citizen_id || "",
        full_name: profile.full_name || "",
        phone: profile.phone || "",
        email: profile.email || "",
        dob: profile.dob || undefined,
        gender: profile.gender || "",
        social_insurance_number: profile.social_insurance_number || "",
        nationality: profile.nationality || "",
        ethnicity: profile.ethnicity || "",
        religion: profile.religion || "",
        disability_type: profile.disability_type || "",
        permanent_province: profile.permanent_province || "",
        permanent_district: profile.permanent_district || "",
        permanent_ward: profile.permanent_ward || "",
        place_of_birth: profile.place_of_birth || "",
        native_place: profile.native_place || "",
        union_entry_date: profile.union_entry_date || undefined,
        party_entry_date: profile.party_entry_date || undefined,
        party_official_entry_date: profile.party_official_entry_date || undefined,
        family_info: profile.family_info || [],
        academic_history: profile.academic_history || [],
        admission_scores: profile.admission_scores || {},
        documents_checklist: profile.documents_checklist || [],
        version: profile.version ?? 1,
      })
    }
  }, [profile, form])

  // =========================================================================
  // 7. Handlers
  // =========================================================================
  const handleSave = () => {
    const data = form.getValues()
    const payload = {
      ...data,
      citizen_id: data.citizen_id === "" ? null : data.citizen_id,
      admission_scores: !data.admission_scores?.gpa ? null : data.admission_scores
    }
    updateMutation.mutate(payload)
  }

  const handleSubmit = async () => {
    await submitMutation.mutateAsync()
  }

  const handleEnroll = () => {
    enrollMutation.mutate()
  }

  const handleCheckCondition = () => {
    // Navigate to first error step
    if (stepsStatus[1] === "error") setCurrentStep(1)
    else if (stepsStatus[4] === "error") setCurrentStep(4)
    else if (stepsStatus[5] === "error") setCurrentStep(5)
  }

  if (!profile) return null

  // =========================================================================
  // 8. Render
  // =========================================================================
  return (
    <FormProvider {...form}>
      <AdmissionLayout 
        profile={profile}
        currentStep={currentStep}
        onStepChange={setCurrentStep}
        stepsStatus={stepsStatus}
        validation={{ isEligible, missingItems }}
      >
        {/* Phase 7: Status-Driven Banners */}
        <StatusBanner status={profile.status} />
        <AdmissionPendingBanner status={profile.status} />
        {/* Phase 0.9: ValidationErrorsBanner removed - validation shown in Header + Sidebar */}

        {/* TAB CONTENT */}
        <div className="bg-white rounded-lg shadow-sm min-h-[500px] p-1">
          {currentStep === 1 && <PersonalInfoTab profile={profile} form={form as any} isEditable={can('edit')} />}
          {currentStep === 2 && <FamilyTab form={form as any} isEditable={can('edit')} />}
          {currentStep === 3 && <AcademicHistoryTab form={form as any} isEditable={can('edit')} />}
          {currentStep === 4 && <ScoresTab form={form as any} isEditable={can('edit')} minGpa={profile.applied_rules?.min_gpa ?? 0} appliedRules={profile.applied_rules} profile={profile} />}
          {currentStep === 5 && <DocumentsTab profile={profile} isEditable={can('edit')} />}
          {currentStep === 6 && <TuitionTab profile={profile} />}
          {currentStep === 7 && <FinalizeTab isEligible={isEligible} onSubmit={handleSubmit} isSubmitting={submitMutation.isPending} />}
        </div>

        {/* STICKY ACTIONS (now uses permissions) */}
        <AdmissionActions 
          profile={profile}
          isSaving={updateMutation.isPending}
          isSubmitting={submitMutation.isPending}
          isEnrolling={enrollMutation.isPending}
          onSave={handleSave}
          onSubmit={handleSubmit}
          onEnroll={handleEnroll}
          onCheckCondition={handleCheckCondition}
        />
      </AdmissionLayout>
    </FormProvider>
  )
}
