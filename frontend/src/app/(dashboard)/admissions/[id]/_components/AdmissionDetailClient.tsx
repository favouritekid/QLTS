"use client"

import { useState, useEffect } from "react"
import { useForm, FormProvider, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Alert, AlertDescription } from "@/components/ui/alert"

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

interface SubmitResult {
  status: "approved" | "rejected" | null
  message?: string | null
  errors?: string[] | null
}

interface AdmissionDetailClientProps {
  profileId: number
  initialData: AdmissionProfileResponse
}

export function AdmissionDetailClient({
  profileId,
  initialData,
}: AdmissionDetailClientProps) {
  // 1. Data Fetching
  const { data: profile } = useGetAdmission(profileId, {
    initialData,
    staleTime: 15000, // 15 seconds - auto-refresh when stale
  })

  const updateMutation = useUpdateAdmission(profileId)
  const submitMutation = useSubmitAdmission(profileId)
  const enrollMutation = useEnrollStudent(profileId)

  const [submitResult, setSubmitResult] = useState<SubmitResult | null>(null)
  
  // 2. Navigation State
  const [currentStep, setCurrentStep] = useState(1)

  const isDraft = profile?.status === "draft" || profile?.status === "rejected"
  const isApproved = profile?.status === "approved"
  const isEditable = isDraft

  // 3. Form Setup
  const form = useForm<AdmissionProfileUpdate>({
    resolver: zodResolver(admissionProfileUpdateSchema),
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
      admission_scores: profile?.admission_scores || {
        gpa: undefined,
        math_score: undefined,
        literature_score: undefined,
        english_score: undefined,
      },
      documents_checklist: profile?.documents_checklist || [],
      version: profile?.version ?? 1,
    },
  })

  // 3.1 Form Reset on Data Update
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
        admission_scores: profile.admission_scores || {
           gpa: undefined,
           math_score: undefined,
           literature_score: undefined,
           english_score: undefined,
        },
        documents_checklist: profile.documents_checklist || [],
        version: profile.version ?? 1,
      })
    }
  }, [profile, form])

  // 4. Real-time Validation Logic (Pipeline Status)
  const [stepsStatus, setStepsStatus] = useState<Record<number, "success" | "warning" | "error" | "locked">>({})
  
  // Optimized watch
  const values = useWatch({ control: form.control })
  const valuesStr = JSON.stringify(values)

  useEffect(() => {
     const w = form.getValues() 
     const status: Record<number, "success" | "warning" | "error" | "locked"> = {}

     // Step 1: Personal Info
     const hasPersonal = !!(w.full_name && w.dob && w.gender && w.citizen_id)
     status[1] = hasPersonal ? "success" : "warning" 
     if (!w.citizen_id) status[1] = "error"

     // Step 2: Family
     const hasPrimaryGuardian = w.family_info?.some((f: any) => f.is_primary_guardian)
     status[2] = hasPrimaryGuardian ? "success" : "error"

     // Step 3: Academic
     const hasAcademic = (w.academic_history?.length || 0) > 0
     status[3] = hasAcademic ? "success" : "warning"

     // Step 4: Scores
     const gpa = w.admission_scores?.gpa || 0
     const isQualified = gpa >= (profile?.applied_rules?.min_gpa ?? 5.0)
     status[4] = isQualified ? "success" : "error"

     // Step 5: Documents - Validate mandatory docs are uploaded
     const mandatoryDocs: string[] = profile?.applied_rules?.mandatory_docs || []
     const uploadedDocCodes = (w.documents_checklist || [])
       .filter((d: any) => d.status === "uploaded" && d.file_path)
       .map((d: any) => d.code)
     const allMandatoryUploaded = mandatoryDocs.every((code: string) => uploadedDocCodes.includes(code))
     status[5] = allMandatoryUploaded ? "success" : (mandatoryDocs.length > 0 ? "error" : "warning")

     // Step 6 & 7
     const isEligible = status[1] !== "error" && status[2] === "success" && status[4] === "success"
     status[6] = isEligible ? "warning" : "locked"
     status[7] = isEligible ? "warning" : "locked"

     setStepsStatus(prev => {
         if (JSON.stringify(prev) === JSON.stringify(status)) return prev
         return status
     })
  }, [valuesStr, form])

  // Determine global eligibility
  const isEligible = stepsStatus[7] !== "locked"

  // 5. Handlers
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
    const result = await submitMutation.mutateAsync()
    setSubmitResult(result)
    // On success, maybe redirect or refresh
  }

  const handleEnroll = () => {
    enrollMutation.mutate()
  }

  const handleCheckCondition = () => {
      // Logic to highlight errors
      // Could scroll to first error step
      if (stepsStatus[1] === "error") setCurrentStep(1)
      else if (stepsStatus[2] === "error") setCurrentStep(2)
      else if (stepsStatus[4] === "error") setCurrentStep(4)
  }

  if (!profile) return null

  return (
    <FormProvider {...form}>
        <AdmissionLayout 
            profile={profile}
            currentStep={currentStep}
            onStepChange={setCurrentStep}
            stepsStatus={stepsStatus}
        >
            {/* ALERT MESSAGES */}
            {submitResult && submitResult.status === "rejected" && (
                <div className="mb-6">
                    <Alert variant="destructive">
                    <AlertDescription>
                        <ul className="list-disc pl-5">
                        {submitResult.errors?.map((err, idx) => (
                            <li key={idx}>{err}</li>
                        ))}
                        </ul>
                    </AlertDescription>
                    </Alert>
                </div>
            )}

            {/* TAB CONTENT */}
            <div className="bg-white rounded-lg shadow-sm min-h-[500px] p-1">
                {currentStep === 1 && <PersonalInfoTab profile={profile} form={form as any} isEditable={isEditable} />}
                {currentStep === 2 && <FamilyTab form={form as any} isEditable={isEditable} />}
                {currentStep === 3 && <AcademicHistoryTab form={form as any} isEditable={isEditable} />}
                {currentStep === 4 && <ScoresTab form={form as any} isEditable={isEditable} />}
                {currentStep === 5 && <DocumentsTab profile={profile} isEditable={isEditable} />}
                {currentStep === 6 && <TuitionTab profile={profile} />}
                {currentStep === 7 && <FinalizeTab isEligible={isEligible} onSubmit={handleSubmit} isSubmitting={submitMutation.isPending} />}
            </div>

            {/* STICKY ACTIONS */}
            <AdmissionActions 
                status={profile.status}
                isDraft={isDraft}
                isApproved={isApproved}
                isSaving={updateMutation.isPending}
                isSubmitting={submitMutation.isPending}
                isEnrolling={enrollMutation.isPending}
                onSave={handleSave}
                onSubmit={handleSubmit}
                onEnroll={handleEnroll}
                onCheckCondition={handleCheckCondition}
                isEligible={isEligible}
            />
        </AdmissionLayout>
    </FormProvider>
  )
}
