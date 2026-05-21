"use client"

import { useState, useEffect, useCallback } from "react"
import { useForm, FormProvider } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

import { toast } from "sonner"
import { AlertTriangle } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button, buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"

// T3.3 Fix: Use ViewModel hook instead of separate hooks
import {
  useAdmissionViewModel,
  useUpdateAdmission,
  useSubmitAdmission,
  useResubmitAdmission,
  useApproveAdmission,
  useRejectAdmission,
  useRequestRevisionAdmission,
  usePublishAdmissionResult,
  useEnrollStudent,
  useDeleteAdmission,
  useClaimAdmission,
  useUnclaimAdmission,
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
import { StatusBanner } from "@/components/ui/StatusBanner"

// Tabs
import { PersonalInfoTab } from "./tabs/PersonalInfoTab"
import { FamilyTab } from "./tabs/FamilyTab"
import { AcademicHistoryTab } from "./tabs/AcademicHistoryTab"
import { PriorityTab } from "./tabs/PriorityTab"
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
  const { data: vm } = useAdmissionViewModel(profileId, {
    initialData,
    staleTime: 0, // Phase 4 Fix: Always refetch on invalidate for realtime badge updates
  })

  // Mutations
  const updateMutation = useUpdateAdmission(profileId)
  const submitMutation = useSubmitAdmission(profileId)
  const resubmitMutation = useResubmitAdmission(profileId)
  const approveMutation = useApproveAdmission(profileId)
  const rejectMutation = useRejectAdmission(profileId)
  // Phase 3 multi-NV: 1-click publish (BE auto-transition submitted→reviewing
  // internal nếu cần; bỏ T2 start-review YAGNI 2026-05-15)
  const publishResultMutation = usePublishAdmissionResult(profileId)
  // E2E #10 — request_revision (manager → officer fix flow)
  const requestRevisionMutation = useRequestRevisionAdmission(profileId)
  const enrollMutation = useEnrollStudent(profileId)
  const deleteMutation = useDeleteAdmission(profileId)
  const claimMutation = useClaimAdmission(profileId)
  const unclaimMutation = useUnclaimAdmission(profileId)

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
  const [unsavedDialogOpen, setUnsavedDialogOpen] = useState(false)
  const [pendingStep, setPendingStep] = useState<number | null>(null)
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")

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
      permanent_residential_group: (profile as AdmissionProfileResponse)?.permanent_residential_group || "",
      permanent_street_address: (profile as AdmissionProfileResponse)?.permanent_street_address || "",
      place_of_birth: (profile as AdmissionProfileResponse)?.place_of_birth || "",
      native_place: (profile as AdmissionProfileResponse)?.native_place || "",
      union_entry_date: (profile as AdmissionProfileResponse)?.union_entry_date || undefined,
      party_entry_date: (profile as AdmissionProfileResponse)?.party_entry_date || undefined,
      party_official_entry_date: (profile as AdmissionProfileResponse)?.party_official_entry_date || undefined,
      family_info: vm?.family_info || [],
      academic_history: vm?.academic_history || [],
      admission_scores: vm?.admission_scores || {},
      documents_checklist: vm?.documents_checklist || [],
      // Q9 #07 Phase E.4 PR-3 — Priority workbench form fields (P1 hydrate fix).
      // PriorityTab watches these 5 fields cho live preview + officer edit.
      // KHÔNG hydrate priority_object_evidence — dedicated mutation endpoints
      // (verify/reject/upload/untick) là canonical write path; form save không
      // mutate evidence để tránh race với optimistic lock.
      cultural_education_level: ((profile as AdmissionProfileResponse)?.cultural_education_level || null) as AdmissionProfileUpdateInput["cultural_education_level"],
      vocational_qualification: ((profile as AdmissionProfileResponse)?.vocational_qualification || null) as AdmissionProfileUpdateInput["vocational_qualification"],
      area_resolution_basis: ((profile as AdmissionProfileResponse)?.area_resolution_basis || null) as AdmissionProfileUpdateInput["area_resolution_basis"],
      permanent_commune_code: (profile as AdmissionProfileResponse)?.permanent_commune_code || null,
      priority_object_codes: (profile as AdmissionProfileResponse)?.priority_object_codes || [],
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
        permanent_residential_group: p.permanent_residential_group || "",
        permanent_street_address: p.permanent_street_address || "",
        place_of_birth: p.place_of_birth || "",
        native_place: p.native_place || "",
        union_entry_date: p.union_entry_date || undefined,
        party_entry_date: p.party_entry_date || undefined,
        party_official_entry_date: p.party_official_entry_date || undefined,
        family_info: vm.family_info || [],
        academic_history: vm.academic_history || [],
        admission_scores: vm.admission_scores || {},
        documents_checklist: vm.documents_checklist || [],
        // Q9 #07 Phase E.4 PR-3 — Priority workbench fields (mirror defaultValues).
        cultural_education_level: (p.cultural_education_level || null) as AdmissionProfileUpdateInput["cultural_education_level"],
        vocational_qualification: (p.vocational_qualification || null) as AdmissionProfileUpdateInput["vocational_qualification"],
        area_resolution_basis: (p.area_resolution_basis || null) as AdmissionProfileUpdateInput["area_resolution_basis"],
        permanent_commune_code: p.permanent_commune_code || null,
        priority_object_codes: p.priority_object_codes || [],
        version: vm.version ?? 1,
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally sync on version only, not full vm
  }, [vm?.version, form])

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
      setPendingStep(newStep)
      setUnsavedDialogOpen(true)
      return
    }
    setCurrentStep(newStep)
  }, [isDirty])

  const handleConfirmStepChange = useCallback(() => {
    if (pendingStep !== null) {
      form.reset()  // Revert về last saved backend state (defaultValues)
      setCurrentStep(pendingStep)
      setPendingStep(null)
    }
    setUnsavedDialogOpen(false)
  }, [pendingStep, form])

  const handleSave = () => {
    // Phase 4: Save draft without validation
    // "Lưu thay đổi" should allow incomplete data (draft mode)
    // Use getValues() instead of handleSubmit() to bypass required validation
    const data = form.getValues()

    // Transform empty strings to null manually (since we're not using handleSubmit)
    const transformedData: Record<string, unknown> = { ...data }
    Object.keys(transformedData).forEach(key => {
      if (transformedData[key] === "") {
        transformedData[key] = null
      }
    })

    // Transform nested nullable fields: convert "" → null in array items
    const nullifyEmptyStrings = (arr: Array<Record<string, unknown>>) =>
      arr.map(record => {
        const cleaned = { ...record }
        Object.keys(cleaned).forEach(k => {
          if (cleaned[k] === "") cleaned[k] = null
        })
        return cleaned
      })

    if (Array.isArray(transformedData.academic_history)) {
      transformedData.academic_history = nullifyEmptyStrings(
        transformedData.academic_history as Array<Record<string, unknown>>
      )
    }
    if (Array.isArray(transformedData.family_info)) {
      transformedData.family_info = nullifyEmptyStrings(
        transformedData.family_info as Array<Record<string, unknown>>
      )
    }

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

  const handleResubmit = () => {
    if (!vm?.version) {
      toast.error("Không thể nộp lại: thiếu version")
      return
    }
    resubmitMutation.mutate({ version: vm.version })
  }

  const handleEnroll = () => {
    enrollMutation.mutate()
  }

  /**
   * Approve Handler (Manager/Admin)
   * Thin Client: Only delegates to mutation, NO business logic
   * Version read from ViewModel (backend source of truth)
   */
  const handleApprove = () => {
    if (!vm?.version) {
      toast.error("Không thể phê duyệt: thiếu version")
      return
    }
    
    approveMutation.mutate({
      version: vm.version,
      notes: undefined, // Optional approval notes
    })
  }

  /**
   * Reject Handler (Manager/Admin)
   * Thin Client: Only collects input and delegates to mutation
   * Validation handled by Zod schema in mutation hook
   */
  const handleReject = () => {
    setRejectReason("")
    setRejectDialogOpen(true)
  }

  const handleConfirmReject = () => {
    if (rejectReason.length < 10) {
      toast.error("Lý do từ chối phải có ít nhất 10 ký tự")
      return
    }
    if (!vm?.version) {
      toast.error("Không thể từ chối: thiếu version")
      return
    }
    rejectMutation.mutate({
      reason: rejectReason,
      version: vm.version,
    })
    setRejectDialogOpen(false)
  }

  // Phase 7: Delete Handler
  const handleDelete = () => {
    deleteMutation.mutate()
  }

  // E2E #3 fix 2026-05-15 — useCallback wrap for stable function reference.
  // Prior pattern `() => publishResultMutation.mutate()` re-created per
  // render → Radix AlertDialogAction onClick captured stale ref → click
  // sometimes did not fire mutate. Stable reference via useCallback +
  // defensive preventDefault wrapper in AdmissionActions.tsx ensures mutate
  // fires reliably across browser sessions.
  const handlePublishResult = useCallback(() => {
    publishResultMutation.mutate()
  }, [publishResultMutation])

  // E2E #10 — Request revision handler (manager → officer fix flow).
  // Reason placeholder satisfies BE Pydantic min_length=10. FU PR sẽ
  // thêm textarea input dialog cho manager nhập reason cụ thể.
  const handleRequestRevision = useCallback(() => {
    if (!vm?.version) return
    requestRevisionMutation.mutate({
      reason: "Vui lòng chỉnh sửa hồ sơ theo yêu cầu của Manager",
      version: vm.version,
    })
  }, [requestRevisionMutation, vm?.version])

  // Claim/Unclaim Handlers
  const handleClaim = () => {
    if (!vm?.version) return
    claimMutation.mutate({ version: vm.version })
  }

  const handleUnclaim = () => {
    if (!vm?.version) return
    unclaimMutation.mutate({ version: vm.version })
  }

  const handleCheckCondition = () => {
    // Navigate to first error step using backend-computed status.
    // Phase E.4 (G0) — 8-step: 1=Personal, 2=Family, 3=Academic,
    // 4=Priority, 5=Scores, 6=Documents, 7=Tuition, 8=Finalize.
    for (let step = 1; step <= 8; step++) {
      if (stepsStatusRecord[step] === "error") {
        handleStepChange(step)
        return
      }
    }
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
        validationErrors={validationErrors}
        validationSummary={validationSummary}
        groupedValidationErrors={groupedValidationErrors}
      >
        {/* Status Banner for rejected/resubmitted profiles */}
        <StatusBanner status={profile.status} />

        {/* F7 fix: surface bypass-eligibility hazard. BE flag combines
            applied_rules.allow_unverified_submission + status reviewable +
            eligibility_status=ineligible so FE just renders. Without this,
            reviewer sees neutral "Chờ duyệt" badge and can silently approve
            a hồ sơ với required fields missing → student row tên NULL. */}
        {profile.bypass_warning && (
          <div
            role="alert"
            className="mb-4 rounded-lg border-2 border-warning-300 bg-warning-50 p-4 text-warning-900"
          >
            <p className="font-semibold mb-1">
              ⚠️ Hồ sơ này được nộp trong chế độ bỏ qua xét duyệt sơ bộ
            </p>
            <p className="text-sm">
              Đợt tuyển sinh cho phép nộp hồ sơ chưa đầy đủ
              (<code>allow_unverified_submission=true</code>). Hồ sơ hiện có{" "}
              <strong>{profile.validation_errors?.length ?? 0}</strong> lỗi chưa khắc phục.
              Vui lòng xem danh sách <strong>&ldquo;Vấn đề cần sửa&rdquo;</strong> ở panel bên cạnh (desktop) hoặc nút &ldquo;N vấn đề&rdquo; ở góc phải (mobile) trước khi phê duyệt.
            </p>
          </div>
        )}

        {/* TAB CONTENT */}
        <div className="bg-card rounded-lg shadow-sm min-h-[500px] p-1">
          {currentStep === 1 && <PersonalInfoTab profile={profile} form={form} isEditable={can('edit')} />}
          {currentStep === 2 && <FamilyTab form={form} isEditable={can('edit')} />}
          {currentStep === 3 && <AcademicHistoryTab form={form} isEditable={can('edit')} />}
          {currentStep === 4 && (
            <PriorityTab
              form={form}
              profile={profile}
              isEditable={can('edit')}
              onNavigateToDocuments={() => handleStepChange(6)}
              onNavigateToAcademic={() => handleStepChange(3)}
            />
          )}
          {currentStep === 5 && <ScoresTab form={form} isEditable={can('edit')} appliedRules={profile.applied_rules} profile={profile} />}
          {currentStep === 6 && <DocumentsTab profile={profile} isEditable={can('edit')} />}
          {currentStep === 7 && <TuitionTab profile={profile} />}
          {/* Q9 #07 Phase E.4 workbench — UT verify gộp vào Step 4 PriorityTab. */}
          {currentStep === 8 && (
            <FinalizeTab
              profile={profile}
              isEligible={isEligible}
              onSubmit={handleSubmit}
              isSubmitting={submitMutation.isPending}
              canSubmit={can('submit')}
              onResubmit={handleResubmit}
              isResubmitting={resubmitMutation.isPending}
              canResubmit={can('resubmit')}
              onApprove={handleApprove}
              isApproving={approveMutation.isPending}
              canApprove={can('approve')}
              onReject={handleReject}
              isRejecting={rejectMutation.isPending}
              canReject={can('reject')}
            />
          )}
        </div>

        {/* STICKY ACTIONS (Commit 2 — navigation + non-decision workflow only)
            Approve/Reject/Submit/Resubmit moved to FinalizeTab decision panel
            to enforce a single decision surface and preserve bypass_warning guard. */}
        <AdmissionActions
          profile={profile}
          currentStep={currentStep}
          onStepChange={handleStepChange}
          isSaving={updateMutation.isPending}
          isEnrolling={enrollMutation.isPending}
          onSave={handleSave}
          onEnroll={handleEnroll}
          onPublishResult={handlePublishResult}
          isPublishingResult={publishResultMutation.isPending}
          onRequestRevision={handleRequestRevision}
          isRequestingRevision={requestRevisionMutation.isPending}
          onClaim={handleClaim}
          onUnclaim={handleUnclaim}
          isClaiming={claimMutation.isPending}
          isUnclaiming={unclaimMutation.isPending}
          onDelete={handleDelete}
          isDeleting={deleteMutation.isPending}
          onCheckCondition={handleCheckCondition}
        />
      </AdmissionLayout>

      {/* Unsaved Changes Dialog
        * Safe-default: Cancel ("Ở lại và lưu") is the primary button so
        * that pressing Enter / clicking the default target keeps the
        * user's in-progress work. The destructive branch is styled red
        * + icon and labeled explicitly so it can never be chosen by
        * accident. handleConfirmStepChange logic unchanged — only UI
        * emphasis swapped.
        */}
      <AlertDialog open={unsavedDialogOpen} onOpenChange={setUnsavedDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Thay đổi chưa lưu</AlertDialogTitle>
            <AlertDialogDescription>
              Thay đổi ở bước hiện tại sẽ bị mất nếu bạn bỏ qua. Chọn &quot;Ở lại và lưu&quot; để giữ lại dữ liệu, hoặc bỏ thay đổi để chuyển bước.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction
              onClick={handleConfirmStepChange}
              className={cn(buttonVariants({ variant: "destructive" }))}
            >
              <AlertTriangle className="mr-2 h-4 w-4" />
              Bỏ thay đổi và tiếp tục
            </AlertDialogAction>
            <AlertDialogCancel>Ở lại và lưu</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reject Reason Dialog */}
      <Dialog open={rejectDialogOpen} onOpenChange={setRejectDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Từ chối hồ sơ</DialogTitle>
            <DialogDescription>
              Nhập lý do từ chối (tối thiểu 10 ký tự).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reject-reason">Lý do từ chối</Label>
            <Textarea
              id="reject-reason"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Nhập lý do từ chối…"
              rows={3}
            />
            {rejectReason.length > 0 && rejectReason.length < 10 && (
              <p className="text-sm text-destructive">Tối thiểu 10 ký tự ({rejectReason.length}/10)</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectDialogOpen(false)}>
              Hủy
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmReject}
              disabled={rejectReason.length < 10 || rejectMutation.isPending}
            >
              {rejectMutation.isPending ? "Đang từ chối…" : "Từ chối"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </FormProvider>
  )
}
