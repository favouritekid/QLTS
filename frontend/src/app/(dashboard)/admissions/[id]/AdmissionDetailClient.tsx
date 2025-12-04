"use client"

/**
 * Admission Detail Client Component
 *
 * Main client-side component for admission profile detail page.
 * Hydrates with server-fetched initial data, then uses TanStack Query for updates.
 */

import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Loader2 } from "lucide-react"

import {
  useGetAdmission,
  useUpdateAdmission,
  useSubmitAdmission,
  useEnrollStudent,
} from "@/hooks/admissions"
import {
  admissionProfileUpdateSchema,
  getStatusColor,
  getStatusLabel,
  type AdmissionProfileResponse,
  type AdmissionProfileUpdate,
} from "@/lib/zod/admissions"

interface SubmitResult {
  status: "approved" | "rejected";
  message?: string;
  errors?: string[];
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

  const isDraft = profile?.status === "draft"
  const isApproved = profile?.status === "approved"

  // React Hook Form
  const form = useForm<AdmissionProfileUpdate>({
    resolver: zodResolver(admissionProfileUpdateSchema),
    defaultValues: {
      citizen_id: profile?.citizen_id || "",
      family_info: profile?.family_info || [],
      academic_history: profile?.academic_history || [],
      admission_scores: profile?.admission_scores || null,
      documents_checklist: profile?.documents_checklist || [],
    },
  })

  const onSubmitForm = (data: AdmissionProfileUpdate) => {
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
      {/* Header Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Hồ sơ tuyển sinh #{profile.id}</CardTitle>
              <CardDescription>
                Lead ID: {profile.lead_id} • Tạo:{" "}
                {new Date(profile.created_at).toLocaleDateString("vi-VN")}
              </CardDescription>
            </div>
            <Badge className={getStatusColor(profile.status)}>
              {getStatusLabel(profile.status)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">CCCD/CMND</p>
              <p className="font-medium">{profile.citizen_id || "Chưa nhập"}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">GPA</p>
              <p className="font-medium">
                {profile.admission_scores?.gpa?.toFixed(2) || "Chưa nhập"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Submit Result */}
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

      {/* Simplified Form (placeholder) */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin hồ sơ</CardTitle>
          <CardDescription>
            {isDraft
              ? "Điền đầy đủ thông tin và nộp hồ sơ"
              : "Chế độ xem (không thể chỉnh sửa)"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm font-medium">CCCD/CMND</p>
            <p className="text-muted-foreground">
              {profile.citizen_id || "Chưa nhập"}
            </p>
          </div>

          <div>
            <p className="text-sm font-medium">Điểm GPA</p>
            <p className="text-muted-foreground">
              {profile.admission_scores?.gpa?.toFixed(2) || "Chưa nhập"}
            </p>
          </div>

          <div>
            <p className="text-sm font-medium">Tài liệu</p>
            <p className="text-muted-foreground">
              {profile.documents_checklist?.filter((d) => d.status === "uploaded").length || 0} /{" "}
              {profile.documents_checklist?.length || 0} đã tải lên
            </p>
          </div>

          <div className="text-xs text-muted-foreground mt-4 p-3 bg-muted rounded">
            <p className="font-semibold mb-1">Ghi chú triển khai:</p>
            <p>
              - Form components đầy đủ (FamilyInfoForm, AcademicHistoryForm, etc.) được tạo trong các file riêng biệt
            </p>
            <p>
              - Component này là placeholder để demo workflow
            </p>
            <p>
              - Tích hợp các form components vào đây để có UI đầy đủ
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Footer Actions */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex gap-4 justify-end">
            {isDraft && (
              <>
                <Button
                  onClick={form.handleSubmit(onSubmitForm)}
                  disabled={updateMutation.isPending}
                  variant="outline"
                >
                  {updateMutation.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  Lưu nháp
                </Button>
                <Button
                  onClick={handleSubmit}
                  disabled={submitMutation.isPending}
                >
                  {submitMutation.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  Nộp hồ sơ
                </Button>
              </>
            )}

            {isApproved && (
              <Button
                onClick={handleEnroll}
                disabled={enrollMutation.isPending}
              >
                {enrollMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Nhập học
              </Button>
            )}

            {!isDraft && !isApproved && (
              <Button disabled variant="secondary">
                Không có hành động
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Applied Rules (for debugging) */}
      <Card>
        <CardHeader>
          <CardTitle>Quy tắc xét tuyển (snapshot)</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-xs bg-muted p-3 rounded overflow-auto">
            {JSON.stringify(profile.applied_rules, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}
