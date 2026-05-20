"use client"

import { cn } from "@/lib/utils"
import { AlertCircle, User, Users, GraduationCap, Award, Calculator, FileText, Wallet, CheckSquare, ChevronDown, ChevronUp } from "lucide-react"
import { Progress } from "@/components/ui/progress"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useState, useMemo } from "react"

interface PipelineSidebarProps {
  currentStep: number
  onStepChange: (step: number) => void
  stepsStatus: Record<number, "success" | "warning" | "error" | "locked">
  validationErrors?: string[]
  validationSummary?: {
    personal?: { has_error: boolean; count: number }
    gpa?: { has_error: boolean; count: number }
    documents?: { has_error: boolean; count: number }
  } | null
  groupedValidationErrors?: {
    personal_info?: { category: string; errors: string[]; count: number }
    documents?: { category: string; errors: string[]; count: number }
    scores?: { category: string; errors: string[]; count: number }
  } | null
  completionPercent: number
}

// Q9 #07 Phase E.4 workbench refactor: UT verify gộp vào step 4 (Trình độ &
// Ưu tiên) → bỏ "Duyệt UT" step riêng. Step 8 = Hoàn tất & Nộp (revert).
const STEPS = [
    { id: 1, label: "Thông tin cá nhân", icon: User },
    { id: 2, label: "Gia đình / Giám hộ", icon: Users },
    { id: 3, label: "Học tập", icon: GraduationCap },
    { id: 4, label: "Trình độ & Ưu tiên", icon: Award },
    { id: 5, label: "Điểm & Điều kiện", icon: Calculator },
    { id: 6, label: "Tài liệu pháp lý", icon: FileText },
    { id: 7, label: "Học phí", icon: Wallet },
    { id: 8, label: "Hoàn tất & Nộp", icon: CheckSquare },
]

export function PipelineSidebar({
  currentStep,
  onStepChange,
  stepsStatus,
  validationErrors = [],
  validationSummary,
  groupedValidationErrors,
  completionPercent,
}: PipelineSidebarProps) {
  const [isIssuesOpen, setIsIssuesOpen] = useState(false)

  const visibleSteps = STEPS

  // Phase 4 Fix: Progressive Disclosure - Focus current ±1 steps
  const completedSteps = Object.values(stepsStatus).filter(status => status === "success").length
  // Removed local calculation to sync with Backend weighted score


  // Phase 2: Progressive Disclosure - Focus current ±1 steps
  const focusedSteps = useMemo(() => [
    currentStep - 1,
    currentStep,
    currentStep + 1
  ], [currentStep])

  // Phase 4 Fix: Trust backend validation_summary instead of parsing strings
  // Map backend validation_summary to step numbers
  // Phase E.4 (G0) — 8-step model: Step 4=Priority (new), Step 5=Scores (was 4),
  // Step 6=Documents (was 5). validation_summary keys (personal/gpa/documents)
  // không có "priority" key — Step 4 error count chỉ derive từ step_status
  // (BE not surface count cho priority — defer post-launch nếu cần).
  const stepErrorCount = useMemo(() => {
    const counts: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0 }

    if (validationSummary) {
      // Step 1: Personal Info
      if (validationSummary.personal?.has_error) {
        counts[1] = validationSummary.personal.count
      }

      // Step 5: GPA/Scores (renumbered từ Step 4)
      if (validationSummary.gpa?.has_error) {
        counts[5] = validationSummary.gpa.count
      }

      // Step 6: Documents (renumbered từ Step 5)
      if (validationSummary.documents?.has_error) {
        counts[6] = validationSummary.documents.count
      }
    }

    return counts
  }, [validationSummary])

  return (
    <div className="space-y-4">
      {/* Progress Indicator */}
      <div className="px-1">
        <div className="flex justify-between text-xs text-muted-foreground mb-2">
          <span className="font-medium">Tiến độ</span>
          <span>{completedSteps}/{visibleSteps.length} ({completionPercent}%)</span>
        </div>
        <Progress value={completionPercent} className="h-2" />
      </div>

      {/* Steps Navigation */}
      <nav className="space-y-3">
      <TooltipProvider>
        {visibleSteps.map((step) => {
          const status = stepsStatus[step.id] || "locked"
          const isActive = currentStep === step.id
          const isFocused = focusedSteps.includes(step.id)
          const isLocked = status === "locked"

          const stepButton = (
            <button
                key={step.id}
                onClick={() => !isLocked && onStepChange(step.id)}
                disabled={isLocked}
                className={cn(
                    "relative w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-colors duration-200",
                    // Active step: full highlight
                    isActive
                        ? "bg-primary/10 text-primary hover:bg-primary/15 font-semibold"
                        : isFocused
                            ? "text-foreground hover:bg-muted font-medium" // Focused (±1): visible
                            : "text-muted-foreground/60 hover:bg-muted/50 font-normal opacity-60", // Non-focused: dimmed
                    isLocked && "cursor-not-allowed hover:bg-transparent"
                )}
            >
                <div className="flex items-center gap-3">
                    <div className={cn(
                        "w-8 h-8 rounded-full flex items-center justify-center border",
                        isActive ? "border-primary text-primary" : "border-muted bg-background",
                        status === "success" && !isActive && "bg-success-50 border-success-200 text-success-600",
                        status === "error" && !isActive && "bg-error-50 border-error-200 text-error-600"
                    )}>
                        <span className="text-xs">{step.id}</span>
                    </div>
                    <span>{step.label}</span>
                </div>

                {/* Phase 3: Error Count Badge - Positioned like notification */}
                {stepErrorCount[step.id] > 0 && (
                  <div className="absolute -top-1 -right-1 flex items-center justify-center min-w-[20px] h-5 px-1.5 bg-error-500 text-white text-xs font-semibold rounded-full border-2 border-background">
                    {stepErrorCount[step.id]}
                  </div>
                )}
            </button>
          )

          // Phase 2: Add tooltip for locked steps
          if (isLocked) {
            return (
              <Tooltip key={step.id}>
                <TooltipTrigger asChild>
                  {stepButton}
                </TooltipTrigger>
                <TooltipContent side="right">
                  <p className="text-xs">Hoàn thành các bước trước để mở khóa</p>
                </TooltipContent>
              </Tooltip>
            )
          }

          return stepButton
        })}
      </TooltipProvider>
      </nav>

      {/* Issues Summary (Collapsible) - Grouped by Category */}
      {validationErrors.length > 0 && (
        <Collapsible open={isIssuesOpen} onOpenChange={setIsIssuesOpen} className="px-1">
          <CollapsibleTrigger className="flex items-center justify-between w-full px-3 py-2 rounded-lg bg-error-50 border border-error-200 hover:bg-error-100 transition-colors">
            <div className="flex items-center gap-2 text-sm font-medium text-error-700">
              <AlertCircle className="w-4 h-4" />
              <span>Vấn đề cần sửa ({validationErrors.length})</span>
            </div>
            {isIssuesOpen ? (
              <ChevronUp className="w-4 h-4 text-error-600" />
            ) : (
              <ChevronDown className="w-4 h-4 text-error-600" />
            )}
          </CollapsibleTrigger>

          <CollapsibleContent className="mt-2 px-3 py-2 bg-card border border-error-100 dark:border-error-900 rounded-lg max-h-[300px] overflow-y-auto">
            {/* Grouped Errors Display */}
            {groupedValidationErrors ? (
              <div className="space-y-3">
                {/* Personal Info Section */}
                {groupedValidationErrors.personal_info && groupedValidationErrors.personal_info.count > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-foreground mb-1.5">
                      {groupedValidationErrors.personal_info.category} ({groupedValidationErrors.personal_info.count})
                    </h4>
                    <ul className="text-xs text-muted-foreground space-y-1 ml-2">
                      {groupedValidationErrors.personal_info.errors.map((error, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="text-error-500 mt-0.5">•</span>
                          <span className="leading-relaxed">{error}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Documents Section */}
                {groupedValidationErrors.documents && groupedValidationErrors.documents.count > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-foreground mb-1.5">
                      {groupedValidationErrors.documents.category} ({groupedValidationErrors.documents.count})
                    </h4>
                    <ul className="text-xs text-muted-foreground space-y-1 ml-2">
                      {groupedValidationErrors.documents.errors.map((error, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="text-error-500 mt-0.5">•</span>
                          <span className="leading-relaxed">{error}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Scores Section */}
                {groupedValidationErrors.scores && groupedValidationErrors.scores.count > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-foreground mb-1.5">
                      {groupedValidationErrors.scores.category} ({groupedValidationErrors.scores.count})
                    </h4>
                    <ul className="text-xs text-muted-foreground space-y-1 ml-2">
                      {groupedValidationErrors.scores.errors.map((error, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="text-error-500 mt-0.5">•</span>
                          <span className="leading-relaxed">{error}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              /* Fallback to flat list if grouped data not available */
              <ul className="text-xs text-muted-foreground space-y-1.5">
                {validationErrors.map((error, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="text-error-500 mt-0.5">•</span>
                    <span className="leading-relaxed">{error}</span>
                  </li>
                ))}
              </ul>
            )}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}
