"use client"

import { useState, useEffect, useCallback } from "react"
import { useForm, FormProvider } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { useRouter } from "next/navigation"

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
  type AdmissionProfileUpdateInput,
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
    staleTime: 0, // Phase 4 Fix: Always refetch on invalidate for realtime badge updates
  })

  // Mutations
  const updateMutation = useUpdateAdmission(profileId)
  const submitMutation = useSubmitAdmission(profileId)
  const enrollMutation = useEnrollStudent(profileId)
  const deleteMutation = useDeleteAdmission(profileId)

  // =========================================================================
  // 2. Permission-Based Rendering (from ViewModel)
  // =========================================================================
  // ViewModel includes permissions field via ...rest spread (useAdmissionViewModel.ts:209)
  // Safe to pass directly to usePermissions
  const { can } = usePermissions(vm)

  // =========================================================================
  // 3. Backend-Computed State (from ViewModel - NO local calculation)
  // @see FRONTEND_ARCHITECTURE_V3.md Section 2.6
  // =========================================================================
  const isEligible = vm?.isEligible ?? false
  const validationErrors = vm?.validationErrors ?? []
  const validationSummary = vm?.validationSummary
  const groupedValidationErrors = vm?.groupedValidationErrors
  const stepsStatusRecord = vm?.stepsStatus ?? {}

  // =========================================================================
  // 4. Derived Profile (for component compatibility)
  // ViewModel spreads all AdmissionProfileResponse fields via ...rest
  // Type assertion is safe but needed for TypeScript compatibility
  // =========================================================================
  const profile = vm as AdmissionProfileResponse | null

  // =========================================================================
  // 5. Navigation State
  // =========================================================================
  const [currentStep, setCurrentStep] = useState(1)

  // =========================================================================
  // 6. Form Setup
  // =========================================================================
  const form = useForm<AdmissionProfileUpdateInput>({
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
      religion: (profile as AdmissionProfileResponse)?.religion || "NONE",
      disability_type: (profile as AdmissionProfileResponse)?.disability_type || "NONE",
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
  // CRITICAL: Use vm.version as dependency to detect server-side changes
  // vm.version is incremented by backend on each successful update
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
        religion: p.religion || "NONE",
        disability_type: p.disability_type || "NONE",
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
  }, [vm?.version, form]) // Use version as stable change indicator

  // Phase 3: Sync backend validation_errors to RHF field errors
  // Trigger on vm.version change (stable indicator of backend updates)
  useEffect(() => {
    const errors = vm?.validationErrors ?? []

    // Clear all previous errors first
    form.clearErrors()

    if (errors.length > 0) {
      errors.forEach(error => {
        const lower = error.toLowerCase()

        // Skip document-related errors (they don't map to fields)
        if (lower.includes("tài liệu") || lower.includes("minh chứng") || lower.includes("document")) {
          return
        }

        // Map FIELD errors only (not documents)
        if (lower.includes("chưa nhập cccd") || lower.includes("citizen_id")) {
          form.setError("citizen_id", { type: "backend", message: error })
        } else if (lower.includes("chưa nhập họ tên") || lower.includes("full_name")) {
          form.setError("full_name", { type: "backend", message: error })
        } else if (lower.includes("chưa nhập email") || lower.includes("email không hợp lệ")) {
          form.setError("email", { type: "backend", message: error })
        } else if (lower.includes("chưa nhập số điện thoại") || lower.includes("phone")) {
          form.setError("phone", { type: "backend", message: error })
        } else if (lower.includes("chưa nhập ngày sinh") || lower.includes("dob")) {
          form.setError("dob", { type: "backend", message: error })
        } else if (lower.includes("chưa chọn giới tính")) {
          form.setError("gender", { type: "backend", message: error })
        } else if (lower.includes("gpa") && !lower.includes("tài liệu")) {
          form.setError("admission_scores", { type: "backend", message: error })
        }
        // Add more field-specific mappings as needed
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vm?.version])

  // =========================================================================
  // Phase 4: Unsaved Changes Warning
  // =========================================================================
  const isDirty = form.formState.isDirty

  // Warn on browser navigation (back/close/refresh)
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = "" // Chrome requires returnValue to be set
      }
    }

    window.addEventListener("beforeunload", handleBeforeUnload)
    return () => window.removeEventListener("beforeunload", handleBeforeUnload)
  }, [isDirty])

  // =========================================================================
  // 7. Handlers
  // =========================================================================
  const handleStepChange = useCallback((newStep: number) => {
    if (isDirty) {
      const confirmed = window.confirm(
        "Bạn có thay đổi chưa lưu. Bạn có chắc muốn chuyển sang bước khác?\n\nNhấn OK để tiếp tục (thay đổi sẽ bị mất)\nNhấn Cancel để ở lại và lưu"
      )
      if (!confirmed) return
    }

    // Reset dirty state when changing steps (since we're losing changes)
    form.reset(form.getValues(), { keepValues: true })
    setCurrentStep(newStep)
  }, [isDirty, form])

  const handleSave = () => {
    // Phase 4: Save draft without validation
    // "Lưu thay đổi" should allow incomplete data (draft mode)
    // Use getValues() instead of handleSubmit() to bypass required validation
    const data = form.getValues()

    // Transform empty strings to null manually (since we're not using handleSubmit)
    const transformedData: any = { ...data }
    Object.keys(transformedData).forEach(key => {
      if (transformedData[key] === "") {
        transformedData[key] = null
      }
    })

    updateMutation.mutate(transformedData as AdmissionProfileUpdate, {
      onSuccess: () => {
        // Reset dirty state after successful save
        form.reset(form.getValues(), { keepValues: true })
      }
    })
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
    if (stepsStatusRecord[1] === "error") handleStepChange(1)
    else if (stepsStatusRecord[4] === "error") handleStepChange(4)
    else if (stepsStatusRecord[5] === "error") handleStepChange(5)
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
        onStepChange={handleStepChange}
        stepsStatus={stepsStatusRecord}
        validation={{ isEligible, missingItems: [] }}
        validationErrors={validationErrors}
        validationSummary={validationSummary}
        groupedValidationErrors={groupedValidationErrors}
      >
        {/* TAB CONTENT */}
        <div className="bg-white rounded-lg shadow-sm min-h-[500px] p-1">
          {currentStep === 1 && <PersonalInfoTab profile={profile} form={form} isEditable={can('edit')} />}
          {currentStep === 2 && <FamilyTab form={form} isEditable={can('edit')} />}
          {currentStep === 3 && <AcademicHistoryTab form={form} isEditable={can('edit')} />}
          {currentStep === 4 && <ScoresTab form={form} isEditable={can('edit')} appliedRules={profile.applied_rules} profile={profile} />}
          {currentStep === 5 && <DocumentsTab profile={profile} isEditable={can('edit')} />}
          {currentStep === 6 && <TuitionTab profile={profile} />}
          {currentStep === 7 && <FinalizeTab profile={profile} isEligible={isEligible} onSubmit={handleSubmit} isSubmitting={submitMutation.isPending} canApprove={can('approve')} />}
        </div>

        {/* STICKY ACTIONS (Phase 2: Context-based buttons) */}
        <AdmissionActions
          profile={profile}
          currentStep={currentStep}
          onStepChange={handleStepChange}
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
