"use client"

/**
 * Admission Scores Tab Component - Phase 8: Updated for New Applied Rules Schema
 *
 * ✅ UPDATED: Works with flat applied_rules structure (18 fields)
 * - No more nested criteria array
 * - Direct access to subject_groups, allowed_subject_codes, scoring_method, etc.
 * - Fully typed with new AppliedRules schema
 *
 * Features:
 * 1. Display admission method from applied_rules
 * 2. Select subject group from applied_rules.subject_groups
 * 3. Dynamic score inputs based on selected subject group
 * 4. Show scoring configuration (method, selection mode, min subject score)
 */

import { useMemo, useEffect } from "react"
import { UseFormReturn, FieldValues, useWatch } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { FormField, FormItem, FormLabel, FormControl, FormMessage, FormDescription } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Calculator, BookOpen, AlertCircle, Info } from "lucide-react"
import type { AppliedRules } from "@/lib/zod/admissions"

interface AdmissionScoresTabProps {
  form: UseFormReturn<FieldValues>
  isEditable: boolean
  appliedRules?: AppliedRules
}

export function AdmissionScoresTab({ form, isEditable, appliedRules }: AdmissionScoresTabProps) {
  // Watch form values for reactivity
  const selectedGroup = useWatch({
    control: form.control,
    name: "admission_scores.selected_group",
  })

  const subjectScores = useWatch({
    control: form.control,
    name: "admission_scores.subject_scores",
  })

  // ✅ NEW: Extract data from flat applied_rules structure
  const admissionMethod = appliedRules?.admission_method || "Chưa xác định"
  const minScore = appliedRules?.min_score
  const minGpa = appliedRules?.min_gpa
  const minSubjectScore = appliedRules?.min_subject_score
  const scoringMethod = appliedRules?.scoring_method || "sum"
  const subjectSelectionMode = appliedRules?.subject_selection_mode || "fixed"
  const requiredSubjectCount = appliedRules?.required_subject_count
  const maxPossibleScore = appliedRules?.max_possible_score

  // ✅ NEW: Get subject groups directly from applied_rules (not from API)
  const availableSubjectGroups = useMemo(() => {
    return appliedRules?.subject_groups || []
  }, [appliedRules])

  // Check if method is GPA-based
  const isGpaMethod = useMemo(() => {
    const method = admissionMethod.toLowerCase()
    return method.includes("học bạ") ||
           method.includes("gpa") ||
           method.includes("điểm trung bình")
  }, [admissionMethod])

  // Get selected subject group details from snapshot
  const selectedGroupDetails = useMemo(() => {
    if (!selectedGroup || !availableSubjectGroups.length) return null
    return availableSubjectGroups.find((g) => g.code === selectedGroup) || null
  }, [selectedGroup, availableSubjectGroups])

  // Calculate total score based on scoring method
  const totalScore = useMemo(() => {
    if (!subjectScores || typeof subjectScores !== 'object') return 0

    const scores = Object.values(subjectScores as Record<string, number>).filter(
      (score) => typeof score === 'number' && !isNaN(score)
    )

    if (scores.length === 0) return 0

    // Apply scoring method from snapshot
    if (scoringMethod === 'average') {
      return scores.reduce((sum, score) => sum + score, 0) / scores.length
    } else if (scoringMethod === 'weighted') {
      // TODO: Implement weighted scoring with weights from snapshot
      return scores.reduce((sum, score) => sum + score, 0)
    } else {
      // Default: sum
      return scores.reduce((sum, score) => sum + score, 0)
    }
  }, [subjectScores, scoringMethod])

  // Initialize subject_scores when group changes
  useEffect(() => {
    if (selectedGroupDetails?.subjects && isEditable) {
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
  }, [selectedGroupDetails, form, isEditable])

  // ✅ NEW: Show admission method info and scoring config
  
  // Case 1: No rules applied at all
  if (!appliedRules) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2 text-error-600">
            <AlertCircle className="h-5 w-5" />
            Lỗi cấu hình
          </CardTitle>
          <CardDescription className="text-error-700">
            Hồ sơ này chưa có thông tin cấu hình xét tuyển (Applied Rules is null). 
            Vui lòng kiểm tra lại cấu hình đợt tuyển sinh.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  // Case 2: Method requires subjects but none are configured
  if (!isGpaMethod && !availableSubjectGroups.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2 text-warning-600">
            <AlertCircle className="h-5 w-5" />
            Thiếu cấu hình tổ hợp môn
          </CardTitle>
          <CardDescription className="text-warning-700">
            Phương thức <strong>{admissionMethod}</strong> chưa được cấu hình tổ hợp môn xét tuyển.
            Vui lòng liên hệ quản trị viên để cập nhật.
          </CardDescription>
        </CardHeader>
        <CardContent>
           {/* Fallback GPA Input just in case */}
           <FormField
            control={form.control}
            name="admission_scores.gpa"
            render={({ field }) => (
              <FormItem className="max-w-xs">
                <FormLabel>GPA tổng (Fallback)</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    type="number"
                    step="0.1"
                    min={0}
                    max={10}
                    disabled={!isEditable}
                    value={field.value ?? ""}
                    onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : null)}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Calculator className="h-5 w-5" />
          Điểm xét tuyển
        </CardTitle>
        <CardDescription>
          Phương thức: <strong>{admissionMethod}</strong>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* ✅ NEW: Display Scoring Configuration */}
        <div className="bg-info-50 border border-info-200 rounded-lg p-4 space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-info-900">
            <Info className="h-4 w-4" />
            Thông tin cấu hình
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            {minGpa && (
              <div>
                <span className="text-muted-foreground">Điểm GPA tối thiểu:</span>{" "}
                <strong className="text-foreground">{minGpa}</strong>
              </div>
            )}
            {minScore && (
              <div>
                <span className="text-muted-foreground">Điểm sàn:</span>{" "}
                <strong className="text-foreground">{minScore}</strong>
              </div>
            )}
            {minSubjectScore && (
              <div>
                <span className="text-muted-foreground">Điểm liệt (tối thiểu/môn):</span>{" "}
                <strong className="text-error-600">{minSubjectScore}</strong>
              </div>
            )}
            <div>
              <span className="text-muted-foreground">Phương pháp tính điểm:</span>{" "}
              <strong className="text-foreground">
                {scoringMethod === 'sum' && 'Tổng điểm'}
                {scoringMethod === 'average' && 'Trung bình'}
                {scoringMethod === 'weighted' && 'Trọng số'}
              </strong>
            </div>
            <div>
              <span className="text-muted-foreground">Chế độ chọn môn:</span>{" "}
              <strong className="text-foreground">
                {subjectSelectionMode === 'fixed' && 'Cố định'}
                {subjectSelectionMode === 'best_n' && `${requiredSubjectCount} môn cao nhất`}
                {subjectSelectionMode === 'any_n' && `Bất kỳ ${requiredSubjectCount} môn`}
              </strong>
            </div>
            {maxPossibleScore && (
              <div>
                <span className="text-muted-foreground">Điểm tối đa:</span>{" "}
                <strong className="text-foreground">{maxPossibleScore}</strong>
              </div>
            )}
          </div>
        </div>

        {/* Show GPA input if GPA-based method */}
        {isGpaMethod && (
          <FormField
            control={form.control}
            name="admission_scores.gpa"
            render={({ field }) => (
              <FormItem className="max-w-xs">
                <FormLabel>GPA tổng</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    type="number"
                    step="0.01"
                    min={0}
                    max={10}
                    placeholder="0.0 - 10.0"
                    disabled={!isEditable}
                    value={field.value ?? ""}
                    onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : null)}
                  />
                </FormControl>
                {minGpa && (
                  <FormDescription>
                    Điểm GPA tối thiểu: <strong>{minGpa}</strong>
                  </FormDescription>
                )}
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        {/* ✅ NEW: Select Subject Group (for exam-based methods) */}
        {!isGpaMethod && availableSubjectGroups.length > 0 && (
          <FormField
            control={form.control}
            name="admission_scores.selected_group"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  Tổ hợp môn xét tuyển <span className="text-error-500">*</span>
                </FormLabel>
                <Select
                  value={field.value || ""}
                  onValueChange={field.onChange}
                  disabled={!isEditable}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn tổ hợp môn..." />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {availableSubjectGroups.map((group) => (
                      <SelectItem key={group.code} value={group.code}>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{group.code}</span>
                          <span className="text-muted-foreground text-sm">
                            ({group.name})
                          </span>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        {/* ✅ NEW: Subject Score Inputs */}
        {!isGpaMethod && selectedGroupDetails && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Label className="text-base font-medium">Điểm từng môn</Label>
              <Badge variant={totalScore >= (minScore || 0) ? "default" : "destructive"}>
                Tổng điểm: {totalScore.toFixed(2)}
              </Badge>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {selectedGroupDetails.subjects.map((subject) => (
                <FormField
                  key={subject}
                  control={form.control}
                  name={`admission_scores.subject_scores.${subject}`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{subject}</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="number"
                          step="0.1"
                          min={0}
                          max={10}
                          placeholder="0.0 - 10.0"
                          disabled={!isEditable}
                          value={field.value ?? ""}
                          onChange={(e) => {
                            const value = e.target.value ? parseFloat(e.target.value) : null
                            field.onChange(value)
                          }}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))}
            </div>

            {minScore && (
              <div className={`p-3 rounded-lg flex items-start gap-2 ${
                totalScore >= minScore
                  ? 'bg-success-50 text-success-800 dark:bg-success-950 dark:text-success-200'
                  : 'bg-error-50 text-error-800 dark:bg-error-950 dark:text-error-200'
              }`}>
                <AlertCircle className="h-5 w-5 mt-0.5 shrink-0" />
                <div className="text-sm">
                  <strong>Điểm sàn:</strong> {minScore}
                  {totalScore >= minScore 
                    ? ` — Tổng điểm (${totalScore.toFixed(2)}) đạt yêu cầu!`
                    : ` — Còn thiếu ${(minScore - totalScore).toFixed(2)} điểm`
                  }
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
