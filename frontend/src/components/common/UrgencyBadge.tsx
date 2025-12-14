// src/components/common/UrgencyBadge.tsx
/**
 * UrgencyBadge - Visual indicator for lead urgency score
 * 
 * Urgency Levels:
 * - URGENT (75-100): Red - Needs immediate attention
 * - HIGH (50-74): Orange - Should act soon
 * - MEDIUM (30-49): Yellow - Normal priority
 * - NORMAL (10-29): Green - Low priority
 * - DONE (0-9): Gray - Completed/Final stage
 */

"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CircleAlert, AlertCircle, Circle, CircleDot, CircleCheck } from "lucide-react";

// =============================================================================
// TYPES
// =============================================================================

export type UrgencyLevel = "urgent" | "high" | "medium" | "normal" | "done";

interface UrgencyBadgeProps {
  /** Urgency score 0-100 */
  score: number;
  /** Show label alongside badge */
  showLabel?: boolean;
  /** Compact mode (just dot) */
  compact?: boolean;
  /** Additional class names */
  className?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const URGENCY_CONFIG: Record<UrgencyLevel, {
  label: string;
  bgColor: string;
  textColor: string;
  dotColor: string;
  icon: React.ElementType;
  description: string;
}> = {
  urgent: {
    label: "Khẩn cấp",
    bgColor: "bg-red-100 dark:bg-red-900/30",
    textColor: "text-red-700 dark:text-red-400",
    dotColor: "bg-red-500",
    icon: CircleAlert,
    description: "Cần hành động ngay",
  },
  high: {
    label: "Cao",
    bgColor: "bg-orange-100 dark:bg-orange-900/30",
    textColor: "text-orange-700 dark:text-orange-400",
    dotColor: "bg-orange-500",
    icon: AlertCircle,
    description: "Nên xử lý sớm",
  },
  medium: {
    label: "Trung bình",
    bgColor: "bg-yellow-100 dark:bg-yellow-900/30",
    textColor: "text-yellow-700 dark:text-yellow-400",
    dotColor: "bg-yellow-500",
    icon: Circle,
    description: "Ưu tiên bình thường",
  },
  normal: {
    label: "Thấp",
    bgColor: "bg-green-100 dark:bg-green-900/30",
    textColor: "text-green-700 dark:text-green-400",
    dotColor: "bg-green-500",
    icon: CircleDot,
    description: "Không gấp",
  },
  done: {
    label: "Xong",
    bgColor: "bg-gray-100 dark:bg-gray-800",
    textColor: "text-gray-600 dark:text-gray-400",
    dotColor: "bg-gray-400",
    icon: CircleCheck,
    description: "Đã hoàn thành",
  },
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

export function getUrgencyLevel(score: number): UrgencyLevel {
  if (score >= 75) return "urgent";
  if (score >= 50) return "high";
  if (score >= 30) return "medium";
  if (score >= 10) return "normal";
  return "done";
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function UrgencyBadge({
  score,
  showLabel = true,
  compact = false,
  className,
}: UrgencyBadgeProps) {
  const urgencyInfo = useMemo(() => {
    const level = getUrgencyLevel(score);
    const config = URGENCY_CONFIG[level];
    return { level, config };
  }, [score]);

  const { config } = urgencyInfo;
  const Icon = config.icon;

  // Compact mode: just a colored dot
  if (compact) {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className={cn(
                "h-2.5 w-2.5 rounded-full shrink-0",
                config.dotColor,
                className
              )}
            />
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            <div className="font-medium">{config.label}</div>
            <div className="text-muted-foreground">Điểm: {score}</div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // Full badge with optional label
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={cn(
              "inline-flex items-center gap-1 text-xs",
              config.textColor,
              className
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {showLabel && <span>{config.label}</span>}
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs space-y-1">
          <div className="font-medium">{config.label} ({score})</div>
          <div className="text-muted-foreground">{config.description}</div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// =============================================================================
// URGENCY DOT (Ultra-compact)
// =============================================================================

interface UrgencyDotProps {
  score: number;
  className?: string;
}

export function UrgencyDot({ score, className }: UrgencyDotProps) {
  return <UrgencyBadge score={score} compact className={className} />;
}

export default UrgencyBadge;
