"use client"

/**
 * Admission Scores Tab Component - Phase 6: Dynamic Admission Scoring
 * 
 * Features:
 * 1. Select admission method from applied_rules.criteria
 * 2. Select subject group from method's subject_groups
 * 3. Dynamic score inputs based on selected subject group
 */

import { useMemo, useEffect, useState } from "react"
import { UseFormReturn, FieldValues, useWatch } from "react-hook-form"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { FormField, FormItem, FormLabel, FormControl, FormMessage, FormDescription } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Calculator, BookOpen, Award, AlertCircle } from "lucide-react"
import { configApi, type SubjectGroup } from "@/lib/api/config"

interface AdmissionCriterion {
  id: string
  method_name: string
  program_type?: string
  subject_groups?: string[]
  min_score?: number
  required_documents?: { code: string; label: string }[]
}

interface AppliedRules {
  criteria?: AdmissionCriterion[]
  min_gpa?: number
  mandatory_docs?: string[]
}

interface AdmissionScoresTabProps {
  form: UseFormReturn<FieldValues>
  isEditable: boolean
  appliedRules?: AppliedRules
}

export function AdmissionScoresTab({ form, isEditable, appliedRules }: AdmissionScoresTabProps) {
  // Watch form values for reactivity
  const selectedCriterionId = useWatch({
    control: form.control,
    name: "admission_scores.selected_criterion_id",
  })
  
  const selectedGroup = useWatch({
    control: form.control,
    name: "admission_scores.selected_group",
  })
  
  const subjectScores = useWatch({
    control: form.control,
    name: "admission_scores.subject_scores",
  })

  // Get criteria from applied_rules
  const criteria = useMemo(() => {
    return appliedRules?.criteria || []
  }, [appliedRules])

  // Get selected criterion object
  const selectedCriterion = useMemo(() => {
    if (!selectedCriterionId || !criteria.length) return null
    return criteria.find((c) => c.id === selectedCriterionId) || null
  }, [selectedCriterionId, criteria])

  // Check if selected method is GPA-based
  const isGpaMethod = useMemo(() => {
    if (!selectedCriterion) return false
    const methodName = selectedCriterion.method_name.toLowerCase()
    return methodName.includes("học bạ") || 
           methodName.includes("gpa") || 
           methodName.includes("điểm trung bình")
  }, [selectedCriterion])

  // Get available subject groups for selected method
  const availableGroups = useMemo(() => {
    return selectedCriterion?.subject_groups || []
  }, [selectedCriterion])

  // Fetch all subject groups for lookup
  const { data: allSubjectGroups, isLoading: isLoadingGroups } = useQuery({
    queryKey: ["subject-groups"],
    queryFn: () => configApi.getSubjectGroups(),
    staleTime: 1000 * 60 * 10,
  })

  // Get selected subject group details
  const selectedGroupDetails = useMemo(() => {
    if (!selectedGroup || !allSubjectGroups) return null
    return allSubjectGroups.find((g) => g.code === selectedGroup) || null
  }, [selectedGroup, allSubjectGroups])

  // Calculate total score
  const totalScore = useMemo(() => {
    if (!subjectScores || typeof subjectScores !== 'object') return 0
    return Object.values(subjectScores as Record<string, number>).reduce(
      (sum, score) => sum + (typeof score === 'number' ? score : 0),
      0
    )
  }, [subjectScores])

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

  // Reset selected_group when criterion changes
  useEffect(() => {
    if (isEditable && selectedCriterionId) {
      const currentGroup = form.getValues("admission_scores.selected_group")
      // Check if current group is valid for new criterion
      if (currentGroup && !availableGroups.includes(currentGroup)) {
        form.setValue("admission_scores.selected_group", null, { shouldDirty: true })
        form.setValue("admission_scores.subject_scores", {}, { shouldDirty: true })
      }
    }
  }, [selectedCriterionId, availableGroups, form, isEditable])

  // No criteria defined - show legacy GPA-only
  if (!criteria.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Calculator className="h-5 w-5" />
            Điểm tuyển sinh
          </CardTitle>
          <CardDescription>
            Chương trình này chưa có phương thức xét tuyển được cấu hình
          </CardDescription>
        </CardHeader>
        <CardContent>
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
                    step="0.1"
                    min={0}
                    max={10}
                    placeholder="0.0 - 10.0"
                    disabled={!isEditable}
                    value={field.value ?? ""}
                    onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : null)}
                  />
                </FormControl>
                {appliedRules?.min_gpa && (
                  <FormDescription>
                    Điểm sàn: {appliedRules.min_gpa}
                  </FormDescription>
                )}
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
          Chọn phương thức xét tuyển và nhập điểm theo yêu cầu
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
                <Award className="h-4 w-4" />
                Phương thức xét tuyển <span className="text-red-500">*</span>
              </FormLabel>
              <Select
                value={field.value || ""}
                onValueChange={(value) => {
                  field.onChange(value)
                }}
                disabled={!isEditable}
              >
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder="Chọn phương thức xét tuyển..." />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {criteria.map((criterion) => (
                    <SelectItem key={criterion.id} value={criterion.id}>
                      <div className="flex items-center gap-2">
                        <span>{criterion.method_name}</span>
                        {criterion.min_score && (
                          <Badge variant="outline" className="text-xs">
                            Điểm sàn: {criterion.min_score}
                          </Badge>
                        )}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />

        {/* Show GPA input if GPA-based method */}
        {selectedCriterion && isGpaMethod && (
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
                {selectedCriterion.min_score && (
                  <FormDescription>
                    Điểm sàn của phương thức này: <strong>{selectedCriterion.min_score}</strong>
                  </FormDescription>
                )}
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        {/* Step 2: Select Subject Group (for exam-based methods) */}
        {selectedCriterion && !isGpaMethod && availableGroups.length > 0 && (
          <FormField
            control={form.control}
            name="admission_scores.selected_group"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  Tổ hợp môn xét tuyển <span className="text-red-500">*</span>
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
                    {isLoadingGroups ? (
                      <div className="p-2">
                        <Skeleton className="h-6 w-full" />
                      </div>
                    ) : (
                      availableGroups.map((groupCode) => {
                        const groupInfo = allSubjectGroups?.find((g) => g.code === groupCode)
                        return (
                          <SelectItem key={groupCode} value={groupCode}>
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{groupCode}</span>
                              {groupInfo && (
                                <span className="text-muted-foreground text-sm">
                                  ({groupInfo.name})
                                </span>
                              )}
                            </div>
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

        {/* Step 3: Subject Score Inputs */}
        {selectedCriterion && !isGpaMethod && selectedGroupDetails && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Label className="text-base font-medium">Điểm từng môn</Label>
              <Badge variant={totalScore >= (selectedCriterion.min_score || 0) ? "default" : "destructive"}>
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

            {selectedCriterion.min_score && (
              <div className={`p-3 rounded-lg flex items-start gap-2 ${
                totalScore >= selectedCriterion.min_score 
                  ? 'bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-200' 
                  : 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200'
              }`}>
                <AlertCircle className="h-5 w-5 mt-0.5 shrink-0" />
                <div className="text-sm">
                  <strong>Điểm sàn:</strong> {selectedCriterion.min_score}
                  {totalScore >= selectedCriterion.min_score 
                    ? ` — Tổng điểm (${totalScore.toFixed(2)}) đạt yêu cầu!`
                    : ` — Còn thiếu ${(selectedCriterion.min_score - totalScore).toFixed(2)} điểm`
                  }
                </div>
              </div>
            )}
          </div>
        )}

        {/* No subject groups for exam-based method */}
        {selectedCriterion && !isGpaMethod && availableGroups.length === 0 && (
          <div className="p-4 bg-yellow-50 dark:bg-yellow-950 rounded-lg text-yellow-800 dark:text-yellow-200 text-sm">
            <AlertCircle className="h-4 w-4 inline-block mr-2" />
            Phương thức này chưa có tổ hợp môn xét tuyển. Vui lòng liên hệ quản trị viên.
          </div>
        )}
      </CardContent>
    </Card>
  )
}
