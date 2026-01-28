// src/components/common/WorkflowBreadcrumb.tsx
"use client";

/**
 * WORKFLOW BREADCRUMB COMPONENT
 *
 * Visual representation of lead/admission workflow progression.
 * Shows the current phase in the lifecycle: Consultation → Admission → Fee → Enrolled
 *
 * @example
 * // Basic usage with phase
 * <WorkflowBreadcrumb currentPhase="consultation" />
 *
 * // With workflow context
 * <WorkflowBreadcrumb
 *   currentPhase={workflowContext?.current_phase}
 *   hasAdmissionProfile={workflowContext?.has_admission_profile}
 * />
 *
 * // Compact mode for cards
 * <WorkflowBreadcrumb currentPhase="admission" compact />
 *
 * @see UI_RULEBOOK.md
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  ChevronRight,
  Phone,
  FileText,
  CreditCard,
  GraduationCap,
  CheckCircle2,
  type LucideIcon,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { LeadPhase } from "@/types/lead.types";

// =============================================================================
// TYPES
// =============================================================================

interface PhaseConfig {
  id: LeadPhase;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  description: string;
}

export interface WorkflowBreadcrumbProps {
  /** Current workflow phase */
  currentPhase?: LeadPhase | null;
  /** Whether lead has an admission profile (shows progress indicator) */
  hasAdmissionProfile?: boolean;
  /** Compact mode for smaller spaces */
  compact?: boolean;
  /** Additional className */
  className?: string;
  /** Click handler for phases (optional) */
  onPhaseClick?: (phase: LeadPhase) => void;
}

// =============================================================================
// PHASE CONFIGURATION
// =============================================================================

const WORKFLOW_PHASES: PhaseConfig[] = [
  {
    id: "consultation",
    label: "Tư vấn",
    shortLabel: "TV",
    icon: Phone,
    description: "Giai đoạn tư vấn, tiếp cận khách hàng tiềm năng",
  },
  {
    id: "admission",
    label: "Xét tuyển",
    shortLabel: "XT",
    icon: FileText,
    description: "Giai đoạn xét duyệt hồ sơ nhập học",
  },
  {
    id: "fee",
    label: "Học phí",
    shortLabel: "HP",
    icon: CreditCard,
    description: "Giai đoạn thanh toán học phí",
  },
  {
    id: "enrolled",
    label: "Nhập học",
    shortLabel: "NH",
    icon: GraduationCap,
    description: "Đã hoàn tất nhập học",
  },
];

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function getPhaseIndex(phase: LeadPhase | null | undefined): number {
  if (!phase) return 0;
  const index = WORKFLOW_PHASES.findIndex((p) => p.id === phase);
  return index === -1 ? 0 : index;
}

type PhaseState = "completed" | "current" | "pending";

function getPhaseState(
  phaseIndex: number,
  currentIndex: number
): PhaseState {
  if (phaseIndex < currentIndex) return "completed";
  if (phaseIndex === currentIndex) return "current";
  return "pending";
}

// =============================================================================
// PHASE ITEM COMPONENT
// =============================================================================

interface PhaseItemProps {
  config: PhaseConfig;
  state: PhaseState;
  compact?: boolean;
  showConnector?: boolean;
  onClick?: () => void;
}

function PhaseItem({
  config,
  state,
  compact,
  showConnector,
  onClick,
}: PhaseItemProps) {
  const Icon = config.icon;
  const isClickable = onClick !== undefined;

  const content = (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-md transition-all",
        isClickable && "cursor-pointer",
        // State-based styling
        state === "completed" && "bg-success-50 text-success-700",
        state === "current" && "bg-info-100 text-info-800 font-medium ring-1 ring-info-300",
        state === "pending" && "bg-muted/50 text-muted-foreground"
      )}
      onClick={onClick}
    >
      {state === "completed" ? (
        <CheckCircle2 className={cn(compact ? "h-3 w-3" : "h-4 w-4")} />
      ) : (
        <Icon className={cn(compact ? "h-3 w-3" : "h-4 w-4")} />
      )}
      {!compact && (
        <span className="text-sm">{config.label}</span>
      )}
    </div>
  );

  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip delayDuration={300}>
          <TooltipTrigger asChild>
            <div className="flex items-center">
              {content}
              {showConnector && (
                <ChevronRight
                  className={cn(
                    "h-3 w-3 mx-0.5",
                    state === "completed"
                      ? "text-success-400"
                      : "text-muted-foreground/40"
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
    <div className="flex items-center">
      {content}
      {showConnector && (
        <ChevronRight
          className={cn(
            "h-4 w-4 mx-1",
            state === "completed"
              ? "text-success-400"
              : "text-muted-foreground/40"
          )}
        />
      )}
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function WorkflowBreadcrumb({
  currentPhase,
  hasAdmissionProfile,
  compact = false,
  className,
  onPhaseClick,
}: WorkflowBreadcrumbProps) {
  const currentIndex = getPhaseIndex(currentPhase);

  return (
    <div className={cn("flex items-center", className)}>
      {WORKFLOW_PHASES.map((phase, index) => {
        const state = getPhaseState(index, currentIndex);

        return (
          <PhaseItem
            key={phase.id}
            config={phase}
            state={state}
            compact={compact}
            showConnector={index < WORKFLOW_PHASES.length - 1}
            onClick={onPhaseClick ? () => onPhaseClick(phase.id) : undefined}
          />
        );
      })}

      {/* Optional: Show admission profile indicator */}
      {hasAdmissionProfile && currentPhase === "consultation" && (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="ml-2 flex items-center gap-1 text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded">
                <FileText className="h-3 w-3" />
                {!compact && <span>Có hồ sơ</span>}
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>Lead đã có hồ sơ xét tuyển nhưng vẫn đang ở giai đoạn tư vấn</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </div>
  );
}

// =============================================================================
// MINI BREADCRUMB (for cards/lists)
// =============================================================================

export interface MiniBreadcrumbProps {
  currentPhase?: LeadPhase | null;
  className?: string;
}

/**
 * Compact breadcrumb showing only dots
 * @example <MiniBreadcrumb currentPhase="admission" />
 */
export function MiniBreadcrumb({ currentPhase, className }: MiniBreadcrumbProps) {
  const currentIndex = getPhaseIndex(currentPhase);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn("flex items-center gap-1", className)}>
            {WORKFLOW_PHASES.map((phase, index) => {
              const state = getPhaseState(index, currentIndex);

              return (
                <div
                  key={phase.id}
                  className={cn(
                    "h-2 w-2 rounded-full transition-all",
                    state === "completed" && "bg-success-500",
                    state === "current" && "bg-info-500 ring-1 ring-offset-1 ring-info-400",
                    state === "pending" && "bg-muted-foreground/30"
                  )}
                />
              );
            })}
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            Giai đoạn:{" "}
            <span className="font-medium">
              {WORKFLOW_PHASES.find((p) => p.id === currentPhase)?.label ?? "Tư vấn"}
            </span>
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default WorkflowBreadcrumb;
