"use client"

import { useMemo, useEffect } from "react"
import { UseFormReturn, FieldValues, useWatch } from "react-hook-form"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Calculator, CheckCircle2, XCircle, AlertCircle, BookOpen } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { configApi, type SubjectGroup } from "@/lib/api/config"

// Types for admission criteria (from applied_rules snapshot)
interface AdmissionCriterion {
  id: string
  method_name: string
  subject_groups?: string[]
  min_score?: number
  conditions?: string
}

interface ScoresTabProps {
  form: UseFormReturn<FieldValues>
  isEditable: boolean
  minGpa: number
  appliedRules?: {
    criteria?: AdmissionCriterion[]
  } | null
  // Phase 7: Backend-computed scores (source of truth)
  profile?: {
    total_score?: number | null
    average_score?: number | null
  }
}

// Vietnamese labels for subject codes
const SUBJECT_LABELS: Record<string, string> = {
  math: "Toán",
  physics: "Vật lí",
  chemistry: "Hóa học",
  biology: "Sinh học",
  literature: "Ngữ văn",
  history: "Lịch sử",
  geography: "Địa lí",
  english: "Tiếng Anh",
  french: "Tiếng Pháp",
  german: "Tiếng Đức",
  russian: "Tiếng Nga",
  japanese: "Tiếng Nhật",
  chinese: "Tiếng Trung",
  korean: "Tiếng Hàn",
  civic_education: "Giáo dục công dân",
  informatics: "Tin học",
  natural_science: "Khoa học tự nhiên",
  social_science: "Khoa học xã hội",
  economic_law: "Giáo dục Kinh tế và pháp luật",
  industrial_tech: "Công nghệ công nghiệp",
  agricultural_tech: "Công nghệ nông nghiệp",
}


export function ScoresTab({ form, isEditable, minGpa, appliedRules, profile }: ScoresTabProps) {
  // Get admission criteria from applied_rules
  const criteria = appliedRules?.criteria || []
  
  // Use useWatch for better reactivity
  const selectedCriterionId = useWatch({
    control: form.control,
    name: "admission_scores.selected_criterion_id",
  })
  
  const selectedGroup = useWatch({
    control: form.control,
    name: "admission_scores.selected_group",
  })
  
  const gpa = useWatch({
    control: form.control,
    name: "admission_scores.gpa",
  })
  
  const subjectScoresData = useWatch({
    control: form.control,
    name: "admission_scores.subject_scores",
  })
  
  // Find selected criterion
  const selectedCriterion = useMemo(() => {
    return criteria.find(c => c.id === selectedCriterionId)
  }, [criteria, selectedCriterionId])
  
  // Get available subject groups for selected criterion
  const availableGroups = selectedCriterion?.subject_groups || []
  
  // Fetch all subject groups from API
  const { data: allSubjectGroups, isLoading: isLoadingGroups } = useQuery({
    queryKey: ["subject-groups"],
    queryFn: () => configApi.getSubjectGroups(),
    staleTime: 1000 * 60 * 10, // Cache 10 mins
  })
  
  // Get selected subject group details from API
  const selectedGroupDetails = useMemo(() => {
    if (!selectedGroup || !allSubjectGroups) return null
    return allSubjectGroups.find(g => g.code === selectedGroup) || null
  }, [selectedGroup, allSubjectGroups])
  
  // Get subjects from API data
  const subjects = useMemo(() => {
    return selectedGroupDetails?.subjects || []
  }, [selectedGroupDetails])
  
  // =========================================================================
  // Calculate scores for real-time preview (UX only - backend is source of truth)
  // =========================================================================
  const localTotalScore = useMemo(() => {
    if (!subjectScoresData || typeof subjectScoresData !== 'object') return 0
    return Object.values(subjectScoresData as Record<string, number>).reduce(
      (sum, score) => sum + (typeof score === 'number' ? score : 0),
      0
    )
  }, [subjectScoresData])
  
  // Phase 7: Prefer backend-computed scores (source of truth) with local fallback for preview
  const totalScore = profile?.total_score ?? localTotalScore
  const averageScore = profile?.average_score ?? (subjects.length > 0 ? localTotalScore / subjects.length : 0)
  
  // Show preview indicator if we're showing local calculation
  const isPreview = !profile?.total_score && localTotalScore > 0
  
  // Initialize subject_scores when group changes
  useEffect(() => {
    if (selectedGroupDetails?.subjects && isEditable && selectedGroup) {
      const currentScores = form.getValues("admission_scores.subject_scores") || {}
      const newScores: Record<string, number | null> = {}
      
      selectedGroupDetails.subjects.forEach((subject) => {
        // Preserve existing score if available
        newScores[subject] = currentScores[subject] ?? null
      })
      
      form.setValue("admission_scores.subject_scores", newScores, { 
        shouldDirty: true,
        shouldValidate: false 
      })
    }
  }, [selectedGroupDetails, selectedGroup, form, isEditable])
  
  // Reset selected_group when criterion changes and group is no longer valid
  useEffect(() => {
    if (isEditable && selectedCriterionId) {
      const currentGroup = form.getValues("admission_scores.selected_group")
      if (currentGroup && !availableGroups.includes(currentGroup)) {
        form.setValue("admission_scores.selected_group", null, { shouldDirty: true })
        form.setValue("admission_scores.subject_scores", {}, { shouldDirty: true })
      }
    }
  }, [selectedCriterionId, availableGroups, form, isEditable])
  
  // Validation
  const currentGpa = gpa ? parseFloat(gpa) : 0
  const minScore = selectedCriterion?.min_score || 0
  
  // Check if this is ONLY a GPA method (no subject groups) or also supports subject-based scoring
  const isGpaOnlyMethod = (
    (selectedCriterion?.method_name?.toLowerCase().includes("học bạ") || 
     selectedCriterion?.method_name?.toLowerCase().includes("gpa")) &&
    (!selectedCriterion?.subject_groups || selectedCriterion.subject_groups.length === 0)
  )
  
  // Method supports subject-based scoring if it has subject_groups
  const supportsSubjectScoring = availableGroups.length > 0
  
  const isQualified = isGpaOnlyMethod 
    ? currentGpa >= minGpa && currentGpa > 0
    : totalScore >= minScore && totalScore > 0
  
  // No criteria available
  if (criteria.length === 0) {
    return (
      <Alert variant="default">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          Chưa có thông tin phương thức xét tuyển. Hãy liên hệ quản trị viên để cập nhật.
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* LEFT: INPUTS */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Calculator className="w-5 h-5" />
              Nhập điểm xét tuyển
            </CardTitle>
            <CardDescription>
              Chọn phương thức và nhập điểm để hệ thống đánh giá
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Step 1: Select Admission Method */}
            <FormField
              control={form.control}
              name="admission_scores.selected_criterion_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-2">
                    <BookOpen className="w-4 h-4" />
                    Phương thức xét tuyển *
                  </FormLabel>
                  <Select
                    disabled={!isEditable}
                    value={field.value || ""}
                    onValueChange={field.onChange}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn phương thức xét tuyển" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {criteria.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.method_name}
                          {c.min_score && ` (≥ ${c.min_score} điểm)`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Step 2: Select Subject Group (if applicable) */}
            {selectedCriterion && availableGroups.length > 0 && (
              <FormField
                control={form.control}
                name="admission_scores.selected_group"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Tổ hợp môn xét tuyển *</FormLabel>
                    <Select
                      disabled={!isEditable || isLoadingGroups}
                      value={field.value || ""}
                      onValueChange={field.onChange}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder={isLoadingGroups ? "Đang tải..." : "Chọn tổ hợp môn"} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {isLoadingGroups ? (
                          <div className="p-2">
                            <Skeleton className="h-6 w-full" />
                          </div>
                        ) : (
                          availableGroups.map((group) => {
                            const groupInfo = allSubjectGroups?.find(g => g.code === group)
                            return (
                              <SelectItem key={group} value={group}>
                                <span className="font-medium">{group}</span>
                                {groupInfo && (
                                  <span className="ml-2 text-muted-foreground">({groupInfo.name})</span>
                                )}
                              </SelectItem>
                            )
                          })
                        )}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Step 3A: GPA Input (for GPA-only methods) */}
            {selectedCriterion && isGpaOnlyMethod && (
              <FormField
                control={form.control}
                name="admission_scores.gpa"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Điểm trung bình (GPA) *</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        step="0.1"
                        min={0}
                        max={10}
                        disabled={!isEditable}
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) =>
                          field.onChange(
                            e.target.value ? parseFloat(e.target.value) : undefined
                          )
                        }
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Step 3B: Subject Score Inputs (for methods with subject_groups) */}
            {selectedCriterion && supportsSubjectScoring && selectedGroup && (
              <div className="space-y-4">
                <p className="text-sm font-medium text-muted-foreground">
                  Nhập điểm các môn trong tổ hợp {selectedGroup}:
                </p>
                
                {/* Loading state */}
                {isLoadingGroups && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                  </div>
                )}
                
                {/* No subjects found */}
                {!isLoadingGroups && subjects.length === 0 && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>
                      Không tìm thấy thông tin môn học cho tổ hợp {selectedGroup}. 
                      Vui lòng liên hệ quản trị viên để cấu hình.
                    </AlertDescription>
                  </Alert>
                )}
                
                {/* Subject inputs */}
                {!isLoadingGroups && subjects.length > 0 && (
                  <>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      {subjects.map((subject) => (
                        <FormField
                          key={subject}
                          control={form.control}
                          name={`admission_scores.subject_scores.${subject}`}
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>{SUBJECT_LABELS[subject] || subject}</FormLabel>
                              <FormControl>
                                <Input
                                  type="number"
                                  step="0.1"
                                  min={0}
                                  max={10}
                                  disabled={!isEditable}
                                  {...field}
                                  value={field.value ?? ""}
                                  onChange={(e) =>
                                    field.onChange(
                                      e.target.value ? parseFloat(e.target.value) : null
                                    )
                                  }
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      ))}
                    </div>

                    {/* Auto-calculated Total */}
                    <div className="pt-4 border-t">
                      <div className="flex justify-between items-center text-sm">
                        <span className="font-medium">
                          Tổng điểm:
                          {isPreview && (
                            <span className="text-xs text-muted-foreground ml-1">(preview)</span>
                          )}
                        </span>
                        <span className="text-lg font-bold text-primary">
                          {totalScore.toFixed(1)} / 30
                        </span>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* RIGHT: RESULT PANEL */}
        <Card
          className={
            !selectedCriterion
              ? "bg-muted/50"
              : isQualified
              ? "bg-green-50 border-green-200"
              : "bg-red-50 border-red-200"
          }
        >
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              {!selectedCriterion ? (
                <AlertCircle className="text-muted-foreground" />
              ) : isQualified ? (
                <CheckCircle2 className="text-green-600" />
              ) : (
                <XCircle className="text-red-600" />
              )}
              KẾT QUẢ XÉT TUYỂN
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selectedCriterion ? (
              <p className="text-sm text-muted-foreground">
                Vui lòng chọn phương thức xét tuyển để xem kết quả.
              </p>
            ) : (
              <>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span>Phương thức:</span>
                    <span className="font-medium">{selectedCriterion.method_name}</span>
                  </div>
                  {selectedGroup && (
                    <div className="flex justify-between">
                      <span>Tổ hợp môn:</span>
                      <span className="font-medium">{selectedGroup}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span>Điểm chuẩn:</span>
                    <span className="font-medium">
                      {isGpaOnlyMethod ? `GPA ≥ ${minGpa}` : `≥ ${minScore} điểm`}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Điểm đạt được:</span>
                    <span className="font-medium">
                      {isGpaOnlyMethod
                    ? currentGpa.toFixed(1)
                    : totalScore.toFixed(1)}
                    </span>
                  </div>
                </div>

                <div className="pt-4 border-t border-dashed">
                  <div className="flex justify-between items-center font-semibold">
                    <span>Kết quả:</span>
                    <span className={isQualified ? "text-green-700" : "text-red-700"}>
                      {isQualified ? "ĐẠT" : "CHƯA ĐẠT"}
                    </span>
                  </div>
                  {!isQualified && (
                    <p className="text-xs text-red-600 mt-2">
                      → Thiếu:{" "}
                      {isGpaOnlyMethod
                        ? "GPA thấp hơn điểm chuẩn"
                        : "Tổng điểm thấp hơn điểm chuẩn"}
                    </p>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
