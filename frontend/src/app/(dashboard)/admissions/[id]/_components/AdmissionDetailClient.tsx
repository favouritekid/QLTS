"use client"

/**
 * Admission Detail Client Component
 * 
 * Main client-side component for admission profile detail page.
 * Hydrates with server-fetched initial data, then uses TanStack Query for updates.
 * 
 * Architecture:
 * - Uses Tabs for organized form sections
 * - Form state managed by react-hook-form
 * - API calls via TanStack Query mutations
 */

import { useState } from "react"
import { useForm, FormProvider } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { User, Users, GraduationCap, Calculator, FileText, CreditCard } from "lucide-react"

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

// Import sub-components
import { AdmissionHeader } from "./AdmissionHeader"
import { AdmissionActions } from "./AdmissionActions"
import { PersonalInfoTab } from "./tabs/PersonalInfoTab"
import { FamilyInfoTab } from "./tabs/FamilyInfoTab"
import { AcademicHistoryTab } from "./tabs/AcademicHistoryTab"
import { AdmissionScoresTab } from "./tabs/AdmissionScoresTab"
import { DocumentsTab } from "./tabs/DocumentsTab"
import { TuitionTab } from "./tabs/TuitionTab"

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
  // TanStack Query with hydration
  const { data: profile } = useGetAdmission(profileId, {
    initialData,
    staleTime: 60000,
  })

  const updateMutation = useUpdateAdmission(profileId)
  const submitMutation = useSubmitAdmission(profileId)
  const enrollMutation = useEnrollStudent(profileId)

  const [submitResult, setSubmitResult] = useState<SubmitResult | null>(null)
  const [activeTab, setActiveTab] = useState("personal")

  const isDraft = profile?.status === "draft" || profile?.status === "rejected"
  const isApproved = profile?.status === "approved"
  const isEditable = isDraft

  // React Hook Form
  const form = useForm<AdmissionProfileUpdate>({
    resolver: zodResolver(admissionProfileUpdateSchema),
    defaultValues: {
      citizen_id: profile?.citizen_id || "",
      family_info: profile?.family_info || [],
      academic_history: profile?.academic_history || [],
      admission_scores: profile?.admission_scores || {
        gpa: undefined,
        math_score: undefined,
        literature_score: undefined,
        english_score: undefined,
      },
      documents_checklist: profile?.documents_checklist || [],
    },
  })

  const handleSave = () => {
    const data = form.getValues()
    updateMutation.mutate(data)
  }

  const handleSubmit = async () => {
    const result = await submitMutation.mutateAsync()
    setSubmitResult(result)
  }

  const handleEnroll = () => {
    enrollMutation.mutate()
  }

  if (!profile) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <AdmissionHeader profile={profile} />

      {/* Submit Result Alerts */}
      {submitResult && submitResult.status === "rejected" && (
        <Alert variant="destructive">
          <AlertDescription>
            <div className="font-semibold mb-2">
              Hồ sơ không đạt yêu cầu ({submitResult.errors?.length || 0} lỗi):
            </div>
            <ul className="list-disc pl-5 space-y-1">
              {submitResult.errors?.map((error: string, idx: number) => (
                <li key={idx}>{error}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {submitResult && submitResult.status === "approved" && (
        <Alert>
          <AlertDescription>
            <div className="font-semibold text-green-600">
              ✓ {submitResult.message}
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* Form with Tabs */}
      <FormProvider {...form}>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="grid w-full grid-cols-3 lg:grid-cols-6">
            <TabsTrigger value="personal" className="gap-1">
              <User className="h-4 w-4 hidden sm:inline" />
              <span>Cá nhân</span>
            </TabsTrigger>
            <TabsTrigger value="family" className="gap-1">
              <Users className="h-4 w-4 hidden sm:inline" />
              <span>Gia đình</span>
            </TabsTrigger>
            <TabsTrigger value="academic" className="gap-1">
              <GraduationCap className="h-4 w-4 hidden sm:inline" />
              <span>Học tập</span>
            </TabsTrigger>
            <TabsTrigger value="scores" className="gap-1">
              <Calculator className="h-4 w-4 hidden sm:inline" />
              <span>Điểm</span>
            </TabsTrigger>
            <TabsTrigger value="documents" className="gap-1">
              <FileText className="h-4 w-4 hidden sm:inline" />
              <span>Tài liệu</span>
            </TabsTrigger>
            <TabsTrigger value="tuition" className="gap-1">
              <CreditCard className="h-4 w-4 hidden sm:inline" />
              <span>Học phí</span>
            </TabsTrigger>
          </TabsList>

          <div className="mt-6">
            <TabsContent value="personal">
              <PersonalInfoTab
                profile={profile}
                form={form}
                isEditable={isEditable}
              />
            </TabsContent>

            <TabsContent value="family">
              <FamilyInfoTab form={form} isEditable={isEditable} />
            </TabsContent>

            <TabsContent value="academic">
              <AcademicHistoryTab form={form} isEditable={isEditable} />
            </TabsContent>

            <TabsContent value="scores">
              <AdmissionScoresTab form={form} isEditable={isEditable} />
            </TabsContent>

            <TabsContent value="documents">
              <DocumentsTab profile={profile} isEditable={isEditable} />
            </TabsContent>

            <TabsContent value="tuition">
              <TuitionTab profile={profile} />
            </TabsContent>
          </div>
        </Tabs>
      </FormProvider>

      {/* Action Buttons */}
      <AdmissionActions
        status={profile?.status || ""}
        isDraft={isDraft}
        isApproved={isApproved}
        isSaving={updateMutation.isPending}
        isSubmitting={submitMutation.isPending}
        isEnrolling={enrollMutation.isPending}
        onSave={handleSave}
        onSubmit={handleSubmit}
        onEnroll={handleEnroll}
      />
    </div>
  )
}
