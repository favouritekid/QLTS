import { useMemo, useEffect, useRef } from "react"
import { UseFormReturn, useWatch } from "react-hook-form"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Calculator, CheckCircle2, XCircle, AlertCircle, BookOpen } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { configApi } from "@/lib/api/config"
import type { AppliedRules, AdmissionProfileUpdate, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

// Internal interface for UI logic compatibility
interface AdmissionCriterion {
  id: string
  method_name: string
  subject_groups?: string[]
  min_score?: number
  conditions?: string
}

interface ScoresTabProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
  // minGpa removed - now read from appliedRules.min_gpa (Phase 2 Fix)
  // Updated to match the actual AppliedRules type from backend/zod
  appliedRules?: AppliedRules | null
  // Phase 7: Backend-computed scores (source of truth)
  profile?: {
    total_score?: number | null
    average_score?: number | null
    // Phase 2 Fix: Read qualification status from backend
    is_qualified?: boolean | null
    // Original backend scores for preservation when switching groups
    admission_scores?: {
      subject_scores?: Record<string, number | null | undefined> | null
    } | null
    // Snapshot score result containing selected subjects (for Best N highlighting)
    snapshot_score?: {
        selected_subjects?: string[]
    } | null
    // Backend validation errors (actual reasons for not qualifying)
    validation_errors?: string[]
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


export function ScoresTab({ form, isEditable, appliedRules, profile }: ScoresTabProps) {
  // Phase 2 Fix: Read minGpa from appliedRules (no prop, no default)
  // @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #2, #3
  const minGpa = appliedRules?.min_gpa
  // Construct criteria from appliedRules
  // Since AppliedRules now represents a snapshot for a SINGLE path,
  // we map it to a single criterion for the UI to consume.
  const criteria = useMemo<AdmissionCriterion[]>(() => {
    if (!appliedRules) return []
    
    // Map the single applied rule configuration to a criterion
    return [{
      id: appliedRules.admission_method_id?.toString() || "default",
      method_name: appliedRules.admission_method || "Phương thức xét tuyển",
      // Map complex SubjectGroupSnapshot to string[] of codes
      subject_groups: appliedRules.subject_groups?.map(g => g.code) || [],
      min_score: appliedRules.min_score ?? undefined,
    }]
  }, [appliedRules])
  
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
  
  // Auto-select criterion if only one option available (profile is created for a single path)
  useEffect(() => {
    if (!selectedCriterionId && criteria.length === 1) {
      form.setValue("admission_scores.selected_criterion_id", criteria[0].id, {
        shouldDirty: false, // Don't mark as dirty since it's initialization
      })
    }
  }, [selectedCriterionId, criteria, form])
  
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
  
  // Auto-select subject group based on:
  // 1. Only one group available -> auto-select
  // 2. OR saved scores keys match a specific group -> infer and select
  useEffect(() => {
    if (!selectedGroup && selectedCriterion && availableGroups.length > 0 && allSubjectGroups) {
      // Case 1: Only one group available
      if (availableGroups.length === 1) {
        form.setValue("admission_scores.selected_group", availableGroups[0], {
          shouldDirty: false,
        })
        return
      }
      
      // Case 2: Infer from saved scores
      if (subjectScoresData && Object.keys(subjectScoresData as Record<string, unknown>).length > 0) {
        const savedSubjectCodes = Object.keys(subjectScoresData as Record<string, unknown>)
        
        // Find which group contains these subjects
        for (const groupCode of availableGroups) {
          const group = allSubjectGroups.find(g => g.code === groupCode)
          if (group && group.subjects) {
            // Check if all saved subjects belong to this group
            const groupSubjects = new Set(group.subjects)
            const allMatch = savedSubjectCodes.every(code => groupSubjects.has(code))
            if (allMatch) {
              form.setValue("admission_scores.selected_group", groupCode, {
                shouldDirty: false,
              })
              return
            }
          }
        }
      }
    }
  }, [selectedGroup, selectedCriterion, availableGroups, subjectScoresData, allSubjectGroups, form])
  
  // Get selected subject group details from API
  const selectedGroupDetails = useMemo(() => {
    if (!selectedGroup || !allSubjectGroups) return null
    return allSubjectGroups.find(g => g.code === selectedGroup) || null
  }, [selectedGroup, allSubjectGroups])
  
  // CHECK BEST N MODE
  const isBestNMode = appliedRules?.subject_selection_mode === 'best_n' || appliedRules?.subject_selection_mode === 'any_n'
  
  // Aggregate all unique subjects for Best N Mode
  const uniqueSubjects = useMemo(() => {
     if (!isBestNMode || !allSubjectGroups || !availableGroups) return []
     
     const relevantGroups = allSubjectGroups.filter(g => availableGroups.includes(g.code))
     const subjectSet = new Set<string>()
     relevantGroups.forEach(g => g.subjects?.forEach(s => subjectSet.add(s)))
     
     // Optional: sort subjects by standard order (if easy) or just alphabetical/insertion
     // For now, let's trust insertion order or sort alphabetically
     return Array.from(subjectSet)
  }, [isBestNMode, allSubjectGroups, availableGroups])

  // Get subjects from API data OR unique subjects for Best N
  const subjects = useMemo(() => {
    if (isBestNMode) {
        return uniqueSubjects
    }
    return selectedGroupDetails?.subjects || []
  }, [isBestNMode, uniqueSubjects, selectedGroupDetails])
  
  // Determine Highlighted Subjects (from Backend Snapshot)
  const highlightedSubjects = useMemo(() => {
      if (!isBestNMode || !profile?.snapshot_score?.selected_subjects) return new Set<string>()
      return new Set(profile.snapshot_score.selected_subjects)
  }, [isBestNMode, profile])
  
  // =========================================================================
  // Phase 2 Fix: REMOVED local score calculation (Architecture Violation #2)
  // Backend is source of truth for total_score and average_score
  // NO fallback to local calculation - if backend doesn't provide, show "—"
  // @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #2, #6
  // =========================================================================
  const totalScore = profile?.total_score ?? null
  const averageScore = profile?.average_score ?? null
  
  // Preview indicator - shows when data is being input but not yet saved
  // This is a UX hint only, NOT a calculated value
  const hasUnsavedInput = subjectScoresData && Object.values(subjectScoresData as Record<string, number>).some(v => v != null)
  
  // P0: Check if data is complete (UX display only - backend is still source of truth)
  const requiredSubjectCount = appliedRules?.required_subject_count ?? 3
  const filledSubjectCount = subjectScoresData 
    ? Object.values(subjectScoresData as Record<string, number | null>).filter(v => v !== null && v !== undefined).length
    : 0
  const isDataComplete = filledSubjectCount >= requiredSubjectCount
  
  // Track previous group to detect user-initiated changes (vs initial load)
  const prevGroupRef = useRef<string | null | undefined>(undefined)
  
  // Initialize subject_scores when group CHANGES (not on initial load)
  // IMPORTANT: Load existing saved scores if available (allows switching back to a group)
  useEffect(() => {
    if (selectedGroupDetails?.subjects && selectedGroup) {
      // First render: just store the group, don't reset scores
      if (prevGroupRef.current === undefined) {
        prevGroupRef.current = selectedGroup
        return
      }
      
      // If same group, no action needed
      if (prevGroupRef.current === selectedGroup) {
        return
      }
      
      // User explicitly changed group -> prepare scores for new group
      prevGroupRef.current = selectedGroup
      
      // Get ORIGINAL saved scores from BACKEND (profile prop)
      // IMPORTANT: Use profile.admission_scores (not form state) to preserve data across group switches
      const backendScores = profile?.admission_scores?.subject_scores || {}
      const currentFormScores = form.getValues("admission_scores.subject_scores") || {}
      // Merge: prefer current form value if exists, then fallback to backend
      const savedScores = { ...backendScores, ...currentFormScores }
      
      const newScores: Record<string, number | null> = {}
      selectedGroupDetails.subjects.forEach((subject) => {
        // Check if this subject has a saved score
        const existingScore = savedScores[subject]
        if (existingScore !== undefined && existingScore !== null) {
          // Preserve existing saved score
          newScores[subject] = existingScore
        } else {
          // No saved score for this subject -> null (user needs to input)
          newScores[subject] = null
        }
      })
      
      
      // Deep check if newScores is different from current form values to avoid dirtying form unnecessarily
      // This fixes the issue where "Kết quả: Đang chờ lưu..." persists after save because this effect runs and dirties form
      const currentValues = form.getValues("admission_scores.subject_scores") || {}
      
      let hasChange = false
      const newKeys = Object.keys(newScores)
      const currentKeys = Object.keys(currentValues)
      
      if (newKeys.length !== currentKeys.length) {
        hasChange = true
      } else {
        for (const key of newKeys) {
          if (newScores[key] !== currentValues[key]) {
            hasChange = true
            break
          }
        }
      }
      
      if (hasChange) {
        form.setValue("admission_scores.subject_scores", newScores, { 
          shouldDirty: isEditable, // Only dirty if editable
          shouldValidate: false 
        })
      }
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroupDetails, selectedGroup, form]) // Intentionally exclude `profile` - effect only runs on GROUP change

  // Initialize scores for Best N Mode (when mode is detected)
  useEffect(() => {
      if (isBestNMode && uniqueSubjects.length > 0) {
           const backendScores = profile?.admission_scores?.subject_scores || {}
           const currentFormScores = form.getValues("admission_scores.subject_scores") || {}
           const savedScores = { ...backendScores, ...currentFormScores }
           
           const newScores: Record<string, number | null> = {}
           uniqueSubjects.forEach(subject => {
               newScores[subject] = savedScores[subject] ?? null
           })
           
           // Check change to avoid dirty loop
           const currentValues = form.getValues("admission_scores.subject_scores") || {}
           let hasChange = false
           // Simple key check + value check
           for (const key of uniqueSubjects) {
               if (newScores[key] !== currentValues[key]) {
                   hasChange = true; break;
               }
           }
           
           if (hasChange) {
                form.setValue("admission_scores.subject_scores", newScores, { 
                  shouldDirty: isEditable, // Only dirty if editable
                  shouldValidate: false 
                })
           }
      }
  }, [isBestNMode, uniqueSubjects, form, profile])
  
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
  
  // Phase 2 Fix: Use type-safe parsing (Violation #9)
  const currentGpa = typeof gpa === 'number' ? gpa : (gpa ? parseFloat(gpa) : null)
  const minScore = selectedCriterion?.min_score ?? null
  
  // Check if this is ONLY a GPA method (no subject groups)
  // Note: This is a UX derivation (allowed) - determines which UI fields to show
  // It does NOT determine eligibility - that comes from backend
  // Check if this is ONLY a GPA method
  // Ticket #3: Use explicit method_type from applied_rules
  // STRICT IMPLEMENTATION: No fallback
  const isGpaOnlyMethod = appliedRules?.method_type === "gpa_only"
  
  // Method supports subject-based scoring if it has subject_groups
  const supportsSubjectScoring = availableGroups.length > 0
  
  // Phase 2 Fix: Read qualification from backend (Violation #2)
  // Backend provides is_qualified - FE does NOT calculate this
  // If backend doesn't provide, show "pending" state
  const isQualified = profile?.is_qualified ?? null
  
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
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Step 2: Select Subject Group (if applicable) */}
            {/* HIDE Group Selector if Best N Mode */}
            {!isBestNMode && selectedCriterion && availableGroups.length > 0 && (
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

            {/* Show Best N Info Alert */}
            {isBestNMode && (
                <Alert className="mb-4 bg-blue-50 text-blue-800 border-blue-200">
                  <CheckCircle2 className="h-4 w-4" />
                  <AlertDescription>
                    Hệ thống sẽ tự động chọn <strong>{requiredSubjectCount} môn có điểm cao nhất</strong> trong các môn hợp lệ để xét tuyển.
                  </AlertDescription>
                </Alert>
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
            {selectedCriterion && supportsSubjectScoring && (selectedGroup || isBestNMode) && (
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
                    <p className="text-sm font-medium text-muted-foreground pb-2">
                       {isBestNMode ? "Nhập điểm môn học:" : `Nhập điểm các môn trong tổ hợp ${selectedGroup}:`}
                    </p>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      {subjects.map((subject) => {
                         const label = SUBJECT_LABELS[subject] || subject
                         const isHighlighted = highlightedSubjects.has(subject)

                         return (
                        <FormField
                          key={subject}
                          control={form.control}
                          name={`admission_scores.subject_scores.${subject}`}
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel className={isHighlighted ? "text-green-700 font-bold flex items-center gap-1" : ""}>
                                {label}
                                {isHighlighted && <CheckCircle2 className="w-3 h-3 text-green-600" />}
                              </FormLabel>
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
                                  className={isHighlighted ? "border-green-500 bg-green-50 ring-green-500/20" : ""}
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )
                      })}
                    </div>

                    {/* Backend-computed Total (Phase 2 Fix) + P0: Conditional Display */}
                    <div className="pt-4 border-t">
                      <div className="flex justify-between items-center text-sm">
                        <span className="font-medium">
                          Tổng điểm:
                          {hasUnsavedInput && !totalScore && (
                            <span className="text-xs text-amber-600 ml-1">(chưa lưu)</span>
                          )}
                        </span>
                        {isDataComplete ? (
                          <span className="text-lg font-bold text-primary">
                            {totalScore !== null ? `${totalScore.toFixed(1)} / 30` : "—"}
                          </span>
                        ) : (
                          <span className="text-lg font-bold text-amber-600">
                            — / 30
                            <span className="text-xs font-normal ml-1">
                              (chưa đủ {filledSubjectCount}/{requiredSubjectCount} môn)
                            </span>
                          </span>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* RIGHT: RESULT PANEL (Phase 2 Fix: Handle null isQualified) */}
        <Card
          className={
            !selectedCriterion || isQualified === null
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
              ) : isQualified === null ? (
                <AlertCircle className="text-amber-500" />
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
                    <span className="text-muted-foreground">Phương thức:</span>
                    <span className="font-medium text-right">{selectedCriterion.method_name}</span>
                  </div>
                  
                  {!isBestNMode && selectedGroup && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Tổ hợp môn:</span>
                      <span className="font-medium text-right">{selectedGroup}</span>
                    </div>
                  )}

                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Điểm chuẩn:</span>
                    <span className="font-medium text-right">
                      {isGpaOnlyMethod 
                        ? (minGpa ? `GPA ≥ ${minGpa}` : "—") 
                        : (minScore ? `≥ ${minScore} điểm` : "—")}
                    </span>
                  </div>
                  
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Điểm đạt được:</span>
                    <span className="font-bold text-lg text-right">
                      {isGpaOnlyMethod
                        ? (currentGpa !== null ? currentGpa.toFixed(2) : "—")
                        : (totalScore !== null ? totalScore.toFixed(2) : "—")}
                    </span>
                  </div>
                </div>

                {/* Best N Breakdown */}
                {isBestNMode && (
                   <div className="pt-3 border-t">
                      <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase flex justify-between">
                         <span>Chi tiết đánh giá</span>
                         <span>({highlightedSubjects.size}/{requiredSubjectCount} môn)</span>
                      </p>
                      <div className="text-sm space-y-1">
                          {Array.from(highlightedSubjects).map(subjCode => (
                              <div key={subjCode} className="flex justify-between items-center bg-green-50/50 px-2 py-1 rounded border border-green-100">
                                  <span>{SUBJECT_LABELS[subjCode] || subjCode}</span>
                                  <span className="font-bold text-green-700">
                                      {profile?.admission_scores?.subject_scores?.[subjCode] ?? "—"}
                                  </span>
                              </div>
                          ))}
                          
                          {highlightedSubjects.size < requiredSubjectCount && (
                             <div className="text-xs text-amber-600 italic px-2 pt-1">
                                (Chưa đủ {requiredSubjectCount} môn hợp lệ để tính điểm)
                             </div>
                          )}
                      </div>
                   </div>
                )}

                <div className="pt-4 border-t border-dashed">
                  <div className="flex justify-between items-center font-semibold">
                    <span>Kết quả:</span>
                    <span className={
                      isQualified === null 
                        ? "text-amber-600" 
                        : isQualified 
                          ? "text-green-700" 
                          : "text-red-700"
                    }>
                      {isQualified === null 
                        ? "Đang xử lý..." 
                        : isQualified 
                          ? "ĐẠT" 
                          : "CHƯA ĐẠT"}
                    </span>
                  </div>
                  
                  {/* Show actual validation errors from backend when not qualified */}
                  {!isQualified && profile?.validation_errors && profile.validation_errors.length > 0 && (
                    <div className="text-xs text-red-600 mt-2 space-y-1">
                      {profile.validation_errors.map((err, i) => (
                        <p key={i}>→ {err}</p>
                      ))}
                    </div>
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

