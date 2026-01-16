"use client"

import { useState, useEffect, useMemo } from "react"
import { useForm, FormProvider } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

// Phase 7: Reusable status banners
import { StatusBanner, AdmissionPendingBanner } from "@/components/ui/StatusBanner"

// T3.3 Fix: Use ViewModel hook instead of separate hooks
import {
  useAdmissionViewModel,
  useUpdateAdmission,
  useSubmitAdmission,
  useEnrollStudent,
  useDeleteAdmission,
} from "@/hooks/admissions"
import {
  admissionProfileUpdateSchema,
  type AdmissionProfileResponse,
  type AdmissionProfileUpdate,
} from "@/lib/zod/admissions"

// Architecture Standards (Phase 7)
import { usePermissions } from "@/hooks/usePermissions"

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
  // 1. Data Fetching via ViewModel (T3.3 - Architecture Compliant)
  // =========================================================================
  const { data: vm, isLoading } = useAdmissionViewModel(profileId, {
    initialData,
    staleTime: 15000, // 15 seconds - auto-refresh when stale
  })

  // Mutations
  const updateMutation = useUpdateAdmission(profileId)
  const submitMutation = useSubmitAdmission(profileId)
  const enrollMutation = useEnrollStudent(profileId)
  const deleteMutation = useDeleteAdmission(profileId)

  // =========================================================================
  // 2. Permission-Based Rendering (from ViewModel)
  // =========================================================================
  // Get raw profile for usePermissions (needs full profile object)
  const { can } = usePermissions(vm as unknown as AdmissionProfileResponse)
  
  // =========================================================================
  // 3. Backend-Computed State (from ViewModel - NO local calculation)
  // @see FRONTEND_ARCHITECTURE_V3.md Section 2.6
  // =========================================================================
  const isEligible = vm?.isEligible ?? false
  const validationErrors = vm?.validationErrors ?? []
  const stepsStatusRecord = vm?.stepsStatus ?? {}
  
  // Convert validation errors to missingItems format for AdmissionLayout
  const missingItems = useMemo(() => 
    validationErrors.map(err => ({
      code: err,
      label: err,
      status: "error" as const
    }))
  , [validationErrors])

  // =========================================================================
  // 4. Derived Profile (for component compatibility)
  // Components like AdmissionLayout, Tabs need full profile object
  // =========================================================================
  const profile = vm as unknown as AdmissionProfileResponse | null

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
      citizen_id: vm?.citizen_id || "",
      full_name: vm?.full_name || "",
      phone: vm?.phone || "",
      email: vm?.email || "",
      dob: vm?.dob || undefined,
      gender: vm?.gender || "",
      social_insurance_number: (profile as AdmissionProfileResponse)?.social_insurance_number || "",
      nationality: (profile as AdmissionProfileResponse)?.nationality || "",
      ethnicity: (profile as AdmissionProfileResponse)?.ethnicity || "",
      religion: (profile as AdmissionProfileResponse)?.religion || "",
      disability_type: (profile as AdmissionProfileResponse)?.disability_type || "",
      permanent_province: (profile as AdmissionProfileResponse)?.permanent_province || "",
      permanent_district: (profile as AdmissionProfileResponse)?.permanent_district || "",
      permanent_ward: (profile as AdmissionProfileResponse)?.permanent_ward || "",
      place_of_birth: (profile as AdmissionProfileResponse)?.place_of_birth || "",
      native_place: (profile as AdmissionProfileResponse)?.native_place || "",
      union_entry_date: (profile as AdmissionProfileResponse)?.union_entry_date || undefined,
      party_entry_date: (profile as AdmissionProfileResponse)?.party_entry_date || undefined,
      party_official_entry_date: (profile as AdmissionProfileResponse)?.party_official_entry_date || undefined,
      family_info: vm?.family_info || [],
      academic_history: vm?.academic_history || [],
      admission_scores: vm?.admission_scores || {},
      documents_checklist: vm?.documents_checklist || [],
      version: vm?.version ?? 1,
    },
  })

  // Form Reset on Data Update
  useEffect(() => {
    if (vm) {
      const p = vm as unknown as AdmissionProfileResponse
      form.reset({
        citizen_id: vm.citizen_id || "",
        full_name: vm.full_name || "",
        phone: vm.phone || "",
        email: vm.email || "",
        dob: vm.dob || undefined,
        gender: vm.gender || "",
        social_insurance_number: p.social_insurance_number || "",
        nationality: p.nationality || "",
        ethnicity: p.ethnicity || "",
        religion: p.religion || "",
        disability_type: p.disability_type || "",
        permanent_province: p.permanent_province || "",
        permanent_district: p.permanent_district || "",
        permanent_ward: p.permanent_ward || "",
        place_of_birth: p.place_of_birth || "",
        native_place: p.native_place || "",
        union_entry_date: p.union_entry_date || undefined,
        party_entry_date: p.party_entry_date || undefined,
        party_official_entry_date: p.party_official_entry_date || undefined,
        family_info: vm.family_info || [],
        academic_history: vm.academic_history || [],
        admission_scores: vm.admission_scores || {},
        documents_checklist: vm.documents_checklist || [],
        version: vm.version ?? 1,
      })
    }
  }, [vm, form])

  // =========================================================================
  // 7. Handlers
  // =========================================================================
  const handleSave = () => {
    const data = form.getValues()
    const payload = {
      ...data,
      citizen_id: data.citizen_id === "" ? null : data.citizen_id,
      // Fix: Allow sending admission_scores if either gpa OR subject_scores exist
      admission_scores: (data.admission_scores?.gpa || Object.keys(data.admission_scores?.subject_scores || {}).length > 0) 
        ? data.admission_scores 
        : null
    }
    updateMutation.mutate(payload)
  }

  const handleSubmit = async () => {
    await submitMutation.mutateAsync()
  }

  const handleEnroll = () => {
    enrollMutation.mutate()
  }

  // Phase 7: Delete Handler
  const handleDelete = () => {
    deleteMutation.mutate()
  }

  const handleCheckCondition = () => {
    // Navigate to first error step using backend-computed status
    if (stepsStatusRecord[1] === "error") setCurrentStep(1)
    else if (stepsStatusRecord[4] === "error") setCurrentStep(4)
    else if (stepsStatusRecord[5] === "error") setCurrentStep(5)
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
        stepsStatus={stepsStatusRecord}
        validation={{ isEligible, missingItems }}
      >
        {/* Phase 7: Status-Driven Banners */}
        <StatusBanner status={profile.status} />
        <AdmissionPendingBanner status={profile.status} />
        {/* Phase 0.9: ValidationErrorsBanner removed - validation shown in Header + Sidebar */}

        {/* TAB CONTENT */}
        <div className="bg-white rounded-lg shadow-sm min-h-[500px] p-1">
          {currentStep === 1 && <PersonalInfoTab profile={profile} form={form} isEditable={can('edit')} />}
          {currentStep === 2 && <FamilyTab form={form} isEditable={can('edit')} />}
          {currentStep === 3 && <AcademicHistoryTab form={form} isEditable={can('edit')} />}
          {currentStep === 4 && <ScoresTab form={form} isEditable={can('edit')} appliedRules={profile.applied_rules} profile={profile} />}
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
          onDelete={handleDelete}
          isDeleting={deleteMutation.isPending}
          onCheckCondition={handleCheckCondition}
        />
      </AdmissionLayout>
    </FormProvider>
  )
}
