"use client"

import { useMemo, useEffect } from "react"
import { UseFormReturn, FieldValues } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Calculator, CheckCircle2, XCircle, AlertCircle, BookOpen } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"

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
}

// Map subject group code to display name (Vietnamese)
const SUBJECT_MAP: Record<string, string> = {
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

// Parse subjects from tổ hợp môn name (e.g., "Toán, Vật lí, Hóa học" -> ["math", "physics", "chemistry"])
function parseSubjectsFromName(name: string): string[] {
  const subjectKeys: string[] = []
  const parts = name.split(",").map(s => s.trim())
  
  for (const part of parts) {
    const entry = Object.entries(SUBJECT_MAP).find(([_, vn]) => vn === part)
    if (entry) {
      subjectKeys.push(entry[0])
    }
  }
  
  return subjectKeys
}

export function ScoresTab({ form, isEditable, minGpa, appliedRules }: ScoresTabProps) {
  // Get admission criteria from applied_rules
  const criteria = appliedRules?.criteria || []
  
  // Watch current selections
  const selectedCriterionId = form.watch("admission_scores.selected_criterion_id") || ""
  const selectedGroup = form.watch("admission_scores.selected_group") || ""
  const gpa = form.watch("admission_scores.gpa") || 0
  
  // Find selected criterion
  const selectedCriterion = useMemo(() => {
    return criteria.find(c => c.id === selectedCriterionId)
  }, [criteria, selectedCriterionId])
  
  // Get available subject groups for selected criterion
  const availableGroups = selectedCriterion?.subject_groups || []
  
  // Get subjects for selected group (from name for now, until we fetch from API)
  // TODO: Fetch from /config/subject-groups/{code} API for accurate subjects
  const subjects = useMemo(() => {
    if (!selectedGroup) return []
    // For now, return common subject combinations based on group code prefix
    // This should be fetched from API in production
    const commonGroups: Record<string, string[]> = {
      "A00": ["math", "physics", "chemistry"],
      "A01": ["math", "physics", "english"],
      "B00": ["math", "chemistry", "biology"],
      "C00": ["literature", "history", "geography"],
      "D01": ["literature", "math", "english"],
      "D07": ["math", "chemistry", "english"],
    }
    return commonGroups[selectedGroup] || ["math", "physics", "chemistry"]
  }, [selectedGroup])
  
  // Calculate total score from subject scores
  const subjectScores = subjects.map(subject => {
    const score = form.watch(`admission_scores.subject_scores.${subject}`)
    return score ? parseFloat(score) : 0
  })
  const totalScore = subjectScores.reduce((sum, s) => sum + s, 0)
  const averageScore = subjects.length > 0 ? totalScore / subjects.length : 0
  
  // Auto-update calculated values
  useEffect(() => {
    if (subjects.length > 0 && totalScore > 0) {
      form.setValue("admission_scores.total_score", totalScore)
      form.setValue("admission_scores.average_score", averageScore)
    }
  }, [totalScore, averageScore, subjects.length, form])
  
  // Validation
  const currentGpa = gpa ? parseFloat(gpa) : 0
  const minScore = selectedCriterion?.min_score || 0
  const isGpaMethod = selectedCriterion?.method_name?.toLowerCase().includes("học bạ") || 
                      selectedCriterion?.method_name?.toLowerCase().includes("gpa")
  
  const isQualified = isGpaMethod 
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
                      disabled={!isEditable}
                      value={field.value || ""}
                      onValueChange={field.onChange}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn tổ hợp môn" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {availableGroups.map((group) => (
                          <SelectItem key={group} value={group}>
                            {group}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Step 3A: GPA Input (for học bạ method) */}
            {selectedCriterion && isGpaMethod && (
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

            {/* Step 3B: Subject Score Inputs (for exam-based methods) */}
            {selectedCriterion && !isGpaMethod && selectedGroup && subjects.length > 0 && (
              <div className="space-y-4">
                <p className="text-sm font-medium text-muted-foreground">
                  Nhập điểm các môn trong tổ hợp {selectedGroup}:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {subjects.map((subject) => (
                    <FormField
                      key={subject}
                      control={form.control}
                      name={`admission_scores.subject_scores.${subject}`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>{SUBJECT_MAP[subject] || subject}</FormLabel>
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
                  ))}
                </div>

                {/* Auto-calculated Total */}
                <div className="pt-4 border-t">
                  <div className="flex justify-between items-center text-sm">
                    <span className="font-medium">Tổng điểm:</span>
                    <span className="text-lg font-bold text-primary">
                      {totalScore.toFixed(1)} / 30
                    </span>
                  </div>
                </div>
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
                      {isGpaMethod ? `GPA ≥ ${minGpa}` : `≥ ${minScore} điểm`}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Điểm đạt được:</span>
                    <span className="font-medium">
                      {isGpaMethod ? currentGpa.toFixed(1) : totalScore.toFixed(1)}
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
                      {isGpaMethod
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
