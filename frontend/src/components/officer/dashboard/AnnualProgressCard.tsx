// src/components/officer/dashboard/AnnualProgressCard.tsx
/**
 * Phase 6: Annual Progress Card
 * Displays rolling target progress with visual progress bar
 */

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { 
  Target, 
  TrendingUp, 
  TrendingDown, 
  AlertTriangle, 
  CheckCircle2,
  Calendar
} from "lucide-react";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface AnnualProgressInfo {
  kpi_code: string;
  fiscal_year: number;
  annual_target: number;
  achieved_ytd: number;
  remaining: number;
  progress_pct: number;
  months_left: number;
  monthly_target: number;
  status: "in_progress" | "completed" | "at_risk" | "overdue";
  on_track: boolean;
  surplus?: number | null;
  last_sync_at?: string | null;
}

// =============================================================================
// STATUS CONFIG
// =============================================================================

const statusConfig = {
  completed: {
    color: "text-success-600 dark:text-success-500",
    bgColor: "bg-success-100 dark:bg-success-500/20",
    progressColor: "bg-success-500",
    icon: CheckCircle2,
    label: "Hoàn thành!",
  },
  in_progress: {
    color: "text-info-600 dark:text-info-500",
    bgColor: "bg-info-100 dark:bg-info-500/20",
    progressColor: "bg-info-500",
    icon: TrendingUp,
    label: "Đang tiến hành",
  },
  at_risk: {
    color: "text-warning-600 dark:text-warning-500",
    bgColor: "bg-warning-100 dark:bg-warning-500/20",
    progressColor: "bg-warning-500",
    icon: AlertTriangle,
    label: "Có nguy cơ",
  },
  overdue: {
    color: "text-error-600 dark:text-error-500",
    bgColor: "bg-error-100 dark:bg-error-500/20",
    progressColor: "bg-error-500",
    icon: TrendingDown,
    label: "Quá hạn",
  },
};

// =============================================================================
// COMPONENT
// =============================================================================

interface AnnualProgressCardProps {
  progress: AnnualProgressInfo | null | undefined;
  className?: string;
}

export function AnnualProgressCard({ progress, className }: AnnualProgressCardProps) {
  const currentYear = new Date().getFullYear();
  
  // Show empty state if no progress data
  if (!progress) {
    return (
      <Card className={cn("border bg-card overflow-hidden", className)}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            Chỉ tiêu năm {currentYear}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center mb-3">
              <Target className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="text-sm text-muted-foreground">
              Chưa có chỉ tiêu năm
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Liên hệ quản lý để thiết lập
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const config = statusConfig[progress.status] || statusConfig.in_progress;
  const StatusIcon = config.icon;

  // Format KPI name for display
  const kpiName = progress.kpi_code === "enrollments" ? "Nhập học" : progress.kpi_code;

  return (
    <Card className={cn("border bg-card overflow-hidden", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            Chỉ tiêu năm {progress.fiscal_year}
          </CardTitle>
          <Badge 
            variant="secondary" 
            className={cn("text-xs gap-1", config.bgColor, config.color)}
          >
            <StatusIcon className="h-3 w-3" />
            {config.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Main stats */}
        <div className="flex items-baseline justify-between">
          <div>
            <span className="text-3xl font-bold">{progress.achieved_ytd}</span>
            <span className="text-lg text-muted-foreground ml-1">/ {progress.annual_target}</span>
          </div>
          <div className={cn("text-2xl font-semibold", config.color)}>
            {progress.progress_pct.toFixed(1)}%
          </div>
        </div>

        {/* Progress bar */}
        <div className="relative">
          <Progress 
            value={Math.min(progress.progress_pct, 100)} 
            className="h-3"
          />
          {/* Expected progress marker */}
          {progress.status !== "completed" && (
            <div 
              className="absolute top-0 h-3 w-0.5 bg-muted-foreground dark:bg-muted-foreground"
              style={{ 
                left: `${Math.min(((12 - progress.months_left) / 12) * 100, 100)}%` 
              }}
              title={`Tiến độ kỳ vọng: ${((12 - progress.months_left) / 12 * 100).toFixed(0)}%`}
            />
          )}
        </div>

        {/* Bottom stats */}
        <div className="grid grid-cols-2 gap-4 pt-2">
          {/* Remaining */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              Còn lại
            </div>
            <div className="font-medium">
              {progress.status === "completed" ? (
                <span className="text-success-600 dark:text-success-500">
                  +{progress.surplus} vượt chỉ tiêu
                </span>
              ) : (
                <span>{progress.remaining} {kpiName.toLowerCase()}</span>
              )}
            </div>
          </div>

          {/* Monthly target */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <Target className="h-3 w-3" />
              Mục tiêu/tháng
            </div>
            <div className="font-medium">
              {progress.status === "completed" ? (
                <span className="text-success-600 dark:text-success-500">—</span>
              ) : (
                <>
                  <span className={cn(!progress.on_track && "text-warning-600 dark:text-warning-500")}>
                    {progress.monthly_target.toFixed(1)}
                  </span>
                  <span className="text-xs text-muted-foreground ml-1">
                    × {progress.months_left} tháng
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Warning message for at_risk status */}
        {progress.status === "at_risk" && (
          <div className="text-xs text-warning-600 dark:text-warning-500 flex items-center gap-1 pt-1">
            <AlertTriangle className="h-3 w-3" />
            Cần tăng tốc để đạt chỉ tiêu năm
          </div>
        )}
      </CardContent>
    </Card>
  );
}
