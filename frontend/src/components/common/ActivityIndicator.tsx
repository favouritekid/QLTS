// src/components/common/ActivityIndicator.tsx
/**
 * ActivityIndicator - Visual indicator for lead activity and urgency
 * 
 * Features:
 * - Relative time display ("2 ngày trước" instead of date)
 * - Activity status via colored text (active/warm/cold/frozen)
 * - Small dot indicator
 * - All details in tooltip (clean UI)
 */

"use client";

import React, { useMemo } from "react";
import { differenceInDays, differenceInHours, isPast, isToday, format } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export type ActivityLevel = "hot" | "active" | "warm" | "cold" | "frozen";

interface ActivityIndicatorProps {
  /** Date to calculate activity from (usually created_at or last consultation) */
  date: string | null | undefined;
  /** Optional next activity date (for follow-up reminders) */
  nextActivityAt?: string | null;
  /** Number of days to consider "cold" */
  coldThresholdDays?: number;
  /** Number of days to consider "frozen" */
  frozenThresholdDays?: number;
  /** Additional class names */
  className?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const ACTIVITY_CONFIG: Record<ActivityLevel, { 
  textColor: string; 
  dotColor: string;
  label: string;
}> = {
  hot: {
    textColor: "text-red-600 dark:text-red-400",
    dotColor: "bg-red-500",
    label: "Nóng",
  },
  active: {
    textColor: "text-green-600 dark:text-green-400",
    dotColor: "bg-green-500",
    label: "Hoạt động",
  },
  warm: {
    textColor: "text-blue-600 dark:text-blue-400",
    dotColor: "bg-blue-500",
    label: "Ấm",
  },
  cold: {
    textColor: "text-yellow-600 dark:text-yellow-400",
    dotColor: "bg-yellow-500",
    label: "Lạnh",
  },
  frozen: {
    textColor: "text-muted-foreground",
    dotColor: "bg-gray-400",
    label: "Đóng băng",
  },
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function getActivityLevel(
  daysSinceActivity: number,
  coldThreshold: number = 7,
  frozenThreshold: number = 14
): ActivityLevel {
  if (daysSinceActivity <= 1) return "active";
  if (daysSinceActivity <= 3) return "warm";
  if (daysSinceActivity <= coldThreshold) return "cold";
  if (daysSinceActivity <= frozenThreshold) return "cold";
  return "frozen";
}

function formatRelativeTime(date: Date): string {
  const now = new Date();
  const hoursDiff = differenceInHours(now, date);
  const daysDiff = differenceInDays(now, date);
  
  if (hoursDiff < 1) return "Vừa xong";
  if (hoursDiff < 24) return `${hoursDiff}h trước`;
  if (daysDiff === 1) return "Hôm qua";
  if (daysDiff < 7) return `${daysDiff} ngày`;
  if (daysDiff < 14) return "1 tuần";
  if (daysDiff < 30) return `${Math.floor(daysDiff / 7)} tuần`;
  if (daysDiff < 60) return "1 tháng";
  return `${Math.floor(daysDiff / 30)} tháng`;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function ActivityIndicator({
  date,
  nextActivityAt,
  coldThresholdDays = 7,
  frozenThresholdDays = 14,
  className,
}: ActivityIndicatorProps) {
  const activityInfo = useMemo(() => {
    if (!date) return null;
    
    const dateObj = new Date(date);
    const now = new Date();
    const daysSince = differenceInDays(now, dateObj);
    const level = getActivityLevel(daysSince, coldThresholdDays, frozenThresholdDays);
    const config = ACTIVITY_CONFIG[level];
    const relativeTime = formatRelativeTime(dateObj);
    const exactDate = format(dateObj, "dd/MM/yyyy HH:mm", { locale: vi });
    
    return {
      level,
      config,
      relativeTime,
      daysSince,
      exactDate,
    };
  }, [date, coldThresholdDays, frozenThresholdDays]);

  const followUpInfo = useMemo(() => {
    if (!nextActivityAt) return null;
    
    const nextDate = new Date(nextActivityAt);
    const now = new Date();
    const isPastDue = isPast(nextDate) && !isToday(nextDate);
    const isDueToday = isToday(nextDate);
    const exactDate = format(nextDate, "dd/MM/yyyy HH:mm", { locale: vi });
    
    return {
      isPastDue,
      isDueToday,
      exactDate,
      status: isPastDue ? "Quá hạn" : isDueToday ? "Hôm nay" : "Đã lên lịch",
    };
  }, [nextActivityAt]);

  if (!activityInfo) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }

  const { config, relativeTime, level, exactDate, daysSince } = activityInfo;
  
  // Determine if we should show a pulse animation (for urgent items)
  const showPulse = followUpInfo?.isPastDue || followUpInfo?.isDueToday;

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn(
            "inline-flex items-center gap-1.5 cursor-default",
            className
          )}>
            {/* Single dot - colored based on activity level */}
            <div
              className={cn(
                "h-2 w-2 rounded-full shrink-0",
                config.dotColor,
                showPulse && "animate-pulse"
              )}
            />
            
            {/* Relative time - colored text */}
            <span className={cn(
              "text-xs tabular-nums whitespace-nowrap",
              config.textColor
            )}>
              {relativeTime}
            </span>
          </div>
        </TooltipTrigger>
        
        {/* Tooltip with all details */}
        <TooltipContent side="top" className="text-xs space-y-1 max-w-[200px]">
          <div className="font-medium">{config.label}</div>
          <div className="text-muted-foreground">
            Tạo: {exactDate}
          </div>
          <div className="text-muted-foreground">
            ({daysSince} ngày trước)
          </div>
          
          {/* Follow-up info in tooltip */}
          {followUpInfo && (
            <div className={cn(
              "pt-1 border-t mt-1",
              followUpInfo.isPastDue ? "text-red-500" : 
              followUpInfo.isDueToday ? "text-orange-500" : 
              "text-blue-500"
            )}>
              📅 {followUpInfo.status}: {followUpInfo.exactDate}
            </div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// =============================================================================
// SIMPLE DOT COMPONENT (for ultra-compact display)
// =============================================================================

interface ActivityDotProps {
  date: string | null | undefined;
  coldThresholdDays?: number;
  frozenThresholdDays?: number;
  className?: string;
}

export function ActivityDot({
  date,
  coldThresholdDays = 7,
  frozenThresholdDays = 14,
  className,
}: ActivityDotProps) {
  if (!date) return null;
  
  const dateObj = new Date(date);
  const daysSince = differenceInDays(new Date(), dateObj);
  const level = getActivityLevel(daysSince, coldThresholdDays, frozenThresholdDays);
  const config = ACTIVITY_CONFIG[level];

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn(
            "h-2 w-2 rounded-full shrink-0",
            config.dotColor,
            className
          )} />
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          {config.label} • {daysSince} ngày trước
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default ActivityIndicator;
