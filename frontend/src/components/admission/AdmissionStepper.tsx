"use client";

/**
 * ADMISSION STEPPER COMPONENT
 *
 * Visual representation of admission workflow stages.
 * Uses semantic tokens for consistent theming.
 *
 * @example
 * // Basic usage
 * <AdmissionStepper currentStatus="submitted" />
 *
 * // With click handler
 * <AdmissionStepper
 *   currentStatus="reviewing"
 *   onStepClick={(step) => console.log('Clicked:', step)}
 * />
 *
 * // Compact mode for sidebar
 * <AdmissionStepper currentStatus="approved" compact />
 *
 * @see UI_RULEBOOK.md
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  FileText,
  Send,
  Clock,
  CheckCircle,
  XCircle,
  GraduationCap,
  type LucideIcon,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// =============================================================================
// TYPES
// =============================================================================

export type AdmissionStep =
  | "draft"
  | "submitted"
  | "reviewing"
  | "approved"
  | "rejected"
  | "enrolled";

export type StepState = "completed" | "current" | "pending" | "error";

interface StepConfig {
  id: AdmissionStep;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  description: string;
}

export interface AdmissionStepperProps {
  /** Current admission status */
  currentStatus: AdmissionStep;
  /** Compact mode for sidebar */
  compact?: boolean;
  /** Vertical layout */
  vertical?: boolean;
  /** Click handler for steps */
  onStepClick?: (step: AdmissionStep) => void;
  /** Additional className */
  className?: string;
  /** Show rejected as separate branch */
  showRejectedBranch?: boolean;
}

// =============================================================================
// STEP CONFIGURATION
// =============================================================================

const ADMISSION_STEPS: StepConfig[] = [
  {
    id: "draft",
    label: "Nháp",
    shortLabel: "Nháp",
    icon: FileText,
    description: "Hồ sơ đang được soạn thảo",
  },
  {
    id: "submitted",
    label: "Đã nộp",
    shortLabel: "Nộp",
    icon: Send,
    description: "Hồ sơ đã được nộp, chờ xét duyệt",
  },
  {
    id: "reviewing",
    label: "Đang xét",
    shortLabel: "Xét",
    icon: Clock,
    description: "Hồ sơ đang được xem xét",
  },
  {
    id: "approved",
    label: "Đã duyệt",
    shortLabel: "Duyệt",
    icon: CheckCircle,
    description: "Hồ sơ đã được phê duyệt",
  },
  {
    id: "enrolled",
    label: "Nhập học",
    shortLabel: "NH",
    icon: GraduationCap,
    description: "Đã hoàn tất nhập học",
  },
];

const REJECTED_STEP: StepConfig = {
  id: "rejected",
  label: "Từ chối",
  shortLabel: "TC",
  icon: XCircle,
  description: "Hồ sơ bị từ chối",
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function getStepIndex(status: AdmissionStep): number {
  const index = ADMISSION_STEPS.findIndex((s) => s.id === status);
  return index === -1 ? -1 : index;
}

function getStepState(
  stepIndex: number,
  currentIndex: number,
  currentStatus: AdmissionStep
): StepState {
  if (currentStatus === "rejected") {
    // If rejected, show all steps up to reviewing as completed
    if (stepIndex <= 2) return "completed";
    return "pending";
  }

  if (stepIndex < currentIndex) return "completed";
  if (stepIndex === currentIndex) return "current";
  return "pending";
}

// =============================================================================
// STEP COMPONENT
// =============================================================================

interface StepProps {
  config: StepConfig;
  state: StepState;
  compact?: boolean;
  onClick?: () => void;
  showConnector?: boolean;
  vertical?: boolean;
}

function Step({
  config,
  state,
  compact,
  onClick,
  showConnector,
  vertical,
}: StepProps) {
  const Icon = config.icon;
  const isClickable = onClick !== undefined;

  const stepContent = (
    <div
      className={cn(
        "flex items-center gap-2",
        vertical && "flex-col",
        isClickable && "cursor-pointer"
      )}
      onClick={onClick}
    >
      {/* Icon Circle */}
      <div
        className={cn(
          "flex items-center justify-center rounded-full border-2 transition-colors",
          compact ? "h-8 w-8" : "h-10 w-10",
          // State-based styling using semantic tokens
          state === "completed" &&
            "border-admission-approved-border bg-admission-approved-bg text-admission-approved-fg",
          state === "current" &&
            "border-admission-submitted-border bg-admission-submitted-bg text-admission-submitted-fg ring-2 ring-admission-submitted-border ring-offset-2",
          state === "pending" &&
            "border-admission-draft-border bg-admission-draft-bg text-admission-draft-fg",
          state === "error" &&
            "border-admission-rejected-border bg-admission-rejected-bg text-admission-rejected-fg"
        )}
      >
        <Icon className={cn(compact ? "h-4 w-4" : "h-5 w-5")} />
      </div>

      {/* Label */}
      {!compact && (
        <div className={cn("text-center", vertical && "mt-1")}>
          <p
            className={cn(
              "text-sm font-medium",
              state === "current" && "text-foreground",
              state === "completed" && "text-admission-approved-fg",
              state === "pending" && "text-muted-foreground",
              state === "error" && "text-admission-rejected-fg"
            )}
          >
            {config.label}
          </p>
        </div>
      )}
    </div>
  );

  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center">
              {stepContent}
              {showConnector && (
                <div
                  className={cn(
                    "mx-1 h-0.5 w-4",
                    state === "completed"
                      ? "bg-admission-approved-fg"
                      : "bg-admission-draft-border"
                  )}
                />
              )}
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p className="font-medium">{config.label}</p>
            <p className="text-xs text-muted-foreground">{config.description}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <div className={cn("flex items-center", vertical && "flex-col")}>
      {stepContent}
      {showConnector && !vertical && (
        <div
          className={cn(
            "mx-2 h-0.5 flex-1 min-w-[2rem]",
            state === "completed"
              ? "bg-admission-approved-fg"
              : "bg-admission-draft-border"
          )}
        />
      )}
      {showConnector && vertical && (
        <div
          className={cn(
            "my-2 w-0.5 h-8",
            state === "completed"
              ? "bg-admission-approved-fg"
              : "bg-admission-draft-border"
          )}
        />
      )}
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function AdmissionStepper({
  currentStatus,
  compact = false,
  vertical = false,
  onStepClick,
  className,
  showRejectedBranch = true,
}: AdmissionStepperProps) {
  const currentIndex = getStepIndex(currentStatus);
  const isRejected = currentStatus === "rejected";

  // Filter steps based on rejection status
  const stepsToShow = isRejected && showRejectedBranch
    ? [...ADMISSION_STEPS.slice(0, 3), REJECTED_STEP]
    : ADMISSION_STEPS;

  return (
    <div
      className={cn(
        "flex",
        vertical ? "flex-col" : "flex-row items-center",
        className
      )}
    >
      {stepsToShow.map((step, index) => {
        const state =
          step.id === "rejected"
            ? "error"
            : getStepState(index, currentIndex, currentStatus);

        return (
          <Step
            key={step.id}
            config={step}
            state={state}
            compact={compact}
            vertical={vertical}
            showConnector={index < stepsToShow.length - 1}
            onClick={onStepClick ? () => onStepClick(step.id) : undefined}
          />
        );
      })}
    </div>
  );
}

// =============================================================================
// MINI STEPPER (for cards/lists)
// =============================================================================

export interface MiniStepperProps {
  currentStatus: AdmissionStep;
  className?: string;
}

/**
 * Compact stepper showing only dots
 * @example <MiniStepper currentStatus="submitted" />
 */
export function MiniStepper({ currentStatus, className }: MiniStepperProps) {
  const currentIndex = getStepIndex(currentStatus);
  const isRejected = currentStatus === "rejected";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn("flex items-center gap-1", className)}>
            {ADMISSION_STEPS.slice(0, 5).map((step, index) => {
              const state = isRejected
                ? index <= 2
                  ? "completed"
                  : "pending"
                : getStepState(index, currentIndex, currentStatus);

              return (
                <div
                  key={step.id}
                  className={cn(
                    "h-2 w-2 rounded-full transition-colors",
                    state === "completed" && "bg-admission-approved-fg",
                    state === "current" && "bg-admission-submitted-fg ring-1 ring-offset-1 ring-admission-submitted-fg",
                    state === "pending" && "bg-admission-draft-border",
                    isRejected && index === 3 && "bg-admission-rejected-fg"
                  )}
                />
              );
            })}
            {isRejected && (
              <div className="h-2 w-2 rounded-full bg-admission-rejected-fg" />
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            Trạng thái:{" "}
            <span className="font-medium">
              {ADMISSION_STEPS.find((s) => s.id === currentStatus)?.label ??
                REJECTED_STEP.label}
            </span>
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default AdmissionStepper;
