"use client"

import { cn } from "@/lib/utils"
import { User, Users, GraduationCap, Award, Calculator, FileText, Wallet, CheckSquare } from "lucide-react"
import { Progress } from "@/components/ui/progress"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useMemo } from "react"
import { IssueSummary } from "./IssueSummary"
import { derivePriorityIssues } from "./priorityIssues"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface PipelineSidebarProps {
  profile: AdmissionProfileResponse | null
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
  /**
   * Phase E.4 (PR-1) — prop kept for backward-compat với AdmissionLayout
   * callsite. Phase E.3 "Duyệt UT" Step 8 ĐÃ gộp vào Step 4 (Priority
   * workbench) per Phase E.4 wireframe — flag không còn ảnh hưởng UI ở đây.
   */
  canVerifyPriorityObject?: boolean
}

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
  profile,
  currentStep,
  onStepChange,
  stepsStatus,
  validationErrors = [],
  validationSummary,
  groupedValidationErrors,
  completionPercent,
  canVerifyPriorityObject: _canVerifyPriorityObject = false, // eslint-disable-line @typescript-eslint/no-unused-vars -- legacy prop kept for backward-compat; Phase E.3 logic gộp vào Step 4
}: PipelineSidebarProps) {
  const visibleSteps = STEPS

  const completedSteps = Object.values(stepsStatus).filter(status => status === "success").length

  const focusedSteps = useMemo(() => [
    currentStep - 1,
    currentStep,
    currentStep + 1
  ], [currentStep])

  // BE-driven step error counts. Step 4 (Priority) chỉ flag khi BE thật
  // sự báo unresolved (`requires_manual_override`) hoặc thiếu evidence UT —
  // KHÔNG đếm `kv_resolved === null` vì hồ sơ chưa preview cũng null.
  const stepErrorCount = useMemo(() => {
    const counts: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0 }

    if (validationSummary) {
      if (validationSummary.personal?.has_error) counts[1] = validationSummary.personal.count
      if (validationSummary.gpa?.has_error) counts[5] = validationSummary.gpa.count
      if (validationSummary.documents?.has_error) counts[6] = validationSummary.documents.count
    }

    counts[4] = derivePriorityIssues(profile).length

    return counts
  }, [validationSummary, profile])

  return (
    <div className="space-y-4">
      <div className="px-1">
        <div className="flex justify-between text-xs text-muted-foreground mb-2">
          <span className="font-medium">Tiến độ</span>
          <span>{completedSteps}/{visibleSteps.length} ({completionPercent}%)</span>
        </div>
        <Progress value={completionPercent} className="h-2" />
      </div>

      {/* Commit 2 fix-up + Commit 7 follow-up — Step 8 lock override cho
          mọi user có quyền decision (FinalizeTab Step 8 = Decision Hub).
          Sau Commit 7 thêm submit/request_revision/publish_result/enroll
          vào decision panel. Nếu BE lock Step 8 do validation fail nhưng
          user có quyền quyết định (vd bypass_warning, officer rejected
          state, manager review claimed, admin published) thì UI cần cho
          phép navigate đến Step 8 để reach decision surface.

          UI vs BE gate semantics: override CHỈ là UI navigation gate cho
          tiện. BE mutation API (approve/reject/submit/enroll/...) vẫn
          validate state machine + IDOR scope độc lập. Override không
          bypass authorization — nếu BE thu hồi quyền runtime, action
          API call sẽ fail-closed với 403/409. */}
      <nav className="space-y-3">
      <TooltipProvider>
        {visibleSteps.map((step) => {
          const status = stepsStatus[step.id] || "locked"
          const isActive = currentStep === step.id
          const isFocused = focusedSteps.includes(step.id)
          // Code review 2026-05-22 — ưu tiên BE-aggregated `has_decision`
          // flag (admission_service._compute_frontend_fields ~line 1617).
          // Fallback OR-7-flags cho backward-compat với deploy chưa ship
          // BE change. Khi flag stable → có thể clean fallback (memory:
          // FE-BE additive forward-compat).
          const perms = profile?.permissions
          const canDecide = Boolean(
            perms?.has_decision ??
            (perms?.approve ||
              perms?.reject ||
              perms?.resubmit ||
              perms?.submit ||
              perms?.request_revision ||
              perms?.publish_result ||
              perms?.enroll)
          )
          const isStep8Override = step.id === 8 && canDecide
          const isLocked = !isStep8Override && status === "locked"

          const stepButton = (
            <button
                key={step.id}
                onClick={() => !isLocked && onStepChange(step.id)}
                disabled={isLocked}
                className={cn(
                    "relative w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-colors duration-200",
                    isActive
                        ? "bg-primary/10 text-primary hover:bg-primary/15 font-semibold"
                        : isFocused
                            ? "text-foreground hover:bg-muted font-medium"
                            : "text-muted-foreground/60 hover:bg-muted/50 font-normal opacity-60",
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

                {stepErrorCount[step.id] > 0 && (
                  <div className="absolute -top-1 -right-1 flex items-center justify-center min-w-[20px] h-5 px-1.5 bg-error-500 text-white text-xs font-semibold rounded-full border-2 border-background">
                    {stepErrorCount[step.id]}
                  </div>
                )}
            </button>
          )

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

      <IssueSummary
        profile={profile}
        validationErrors={validationErrors}
        groupedValidationErrors={groupedValidationErrors}
      />
    </div>
  )
}
