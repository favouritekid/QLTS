"use client"

import { cn } from "@/lib/utils"
import { canDecide, isStepNavLocked } from "@/lib/utils/admission-permissions"
import { ADMISSION_STEPS } from "@/lib/constants/admission-steps"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface MobileStepStripProps {
  profile: AdmissionProfileResponse | null
  currentStep: number
  onStepChange: (step: number) => void
  stepsStatus: Record<number, "success" | "warning" | "error" | "locked">
}

/**
 * Mobile-only horizontal step navigator (lg:hidden). The desktop PipelineSidebar
 * is `hidden lg:block`, so on mobile the only step navigation was the sequential
 * "Quay lại" / "Tiếp tục" buttons — no overview of the 8 steps and no direct
 * jump. This strip surfaces every step with its status colour and lets the user
 * tap to jump straight to any unlocked step. Rendered inside the sticky header
 * region so it stays reachable while the content scrolls.
 */
export function MobileStepStrip({
  profile,
  currentStep,
  onStepChange,
  stepsStatus,
}: MobileStepStripProps) {
  // Step-8 unlock for decision-capable users, via the shared isStepNavLocked so
  // the strip agrees with PipelineSidebar on which steps are reachable.
  const decide = canDecide(profile?.permissions)

  return (
    <nav
      aria-label="Điều hướng bước hồ sơ"
      className="lg:hidden flex gap-1.5 overflow-x-auto px-4 pb-2 pt-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {ADMISSION_STEPS.map((step) => {
        const status = stepsStatus[step.id] || "locked"
        const isActive = currentStep === step.id
        const isLocked = isStepNavLocked(step.id, status, decide)

        return (
          <button
            key={step.id}
            type="button"
            onClick={() => !isLocked && onStepChange(step.id)}
            disabled={isLocked}
            aria-current={isActive ? "step" : undefined}
            className={cn(
              "flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs transition-colors",
              isActive
                ? "border-primary bg-primary/10 font-semibold text-primary"
                : "border-border bg-background text-muted-foreground",
              !isActive && status === "success" && "border-success-200 text-success-700",
              !isActive && status === "warning" && "border-warning-200 text-warning-700",
              !isActive && status === "error" && "border-error-200 text-error-700",
              isLocked && "cursor-not-allowed opacity-50",
            )}
          >
            <span
              className={cn(
                "flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-semibold",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : status === "success"
                    ? "bg-success-100 text-success-700"
                    : status === "warning"
                      ? "bg-warning-100 text-warning-700"
                      : status === "error"
                        ? "bg-error-100 text-error-700"
                        : "bg-muted",
              )}
            >
              {step.id}
            </span>
            {step.label}
          </button>
        )
      })}
    </nav>
  )
}
