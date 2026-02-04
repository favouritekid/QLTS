// src/components/officer/dashboard/KPICard.tsx
/**
 * KPI Card Component for Officer Dashboard
 * Clean, minimalist design following shadcn/ui standards
 *
 * Design: White background, subtle border, large numbers, semantic trend colors
 *
 * ✅ PERFORMANCE: React.memo prevents re-renders when parent updates unrelated state
 */

"use client";

import { memo } from "react";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Minus, type LucideIcon } from "lucide-react";

interface TrendInfo {
  value: number;
  direction: "up" | "down" | "neutral";
  comparison: string;
}

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: TrendInfo;
  icon: LucideIcon;
  onClick?: () => void;
  /** If true, inverts trend colors (down = green, up = red). Useful for metrics like response time where lower is better. */
  inverseTrend?: boolean;
}

export const KPICard = memo(function KPICard({
  title,
  value,
  subtitle,
  trend,
  icon: Icon,
  onClick,
  inverseTrend = false,
}: KPICardProps) {
  const TrendIcon =
    trend?.direction === "up"
      ? TrendingUp
      : trend?.direction === "down"
      ? TrendingDown
      : Minus;

  // For inverseTrend (e.g., response time), down = green (improvement), up = red (worsening)
  const trendColor = inverseTrend
    ? (trend?.direction === "down"
        ? "text-success-600 dark:text-success-500"
        : trend?.direction === "up"
        ? "text-error-600 dark:text-error-500"
        : "text-muted-foreground")
    : (trend?.direction === "up"
        ? "text-success-600 dark:text-success-500"
        : trend?.direction === "down"
        ? "text-error-600 dark:text-error-500"
        : "text-muted-foreground");

  return (
    <Card
      className={cn(
        "relative overflow-hidden transition-all duration-200",
        "bg-card border hover:border-primary/20",
        onClick && "cursor-pointer hover:shadow-sm"
      )}
      onClick={onClick}
    >
      <CardContent className="p-6">
        {/* Background Icon (subtle) */}
        <div className="absolute -right-4 -top-4 opacity-[0.04]">
          <Icon className="h-24 w-24" />
        </div>

        {/* Title */}
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium text-muted-foreground">
            {title}
          </span>
          <div className="rounded-lg bg-muted p-2">
            <Icon className="h-4 w-4 text-muted-foreground" />
          </div>
        </div>

        {/* Main Value - Large & Bold */}
        <div className="text-3xl font-bold tracking-tight text-foreground">
          {value}
        </div>

        {/* Subtitle */}
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
        )}

        {/* Trend Indicator */}
        {trend && (
          <div className={cn("flex items-center gap-1.5 mt-3", trendColor)}>
            <TrendIcon className="h-4 w-4" />
            <span className="text-sm font-medium">
              {/* Fix: Use absolute value and only show sign based on direction */}
              {trend.direction === "up" ? "+" : trend.direction === "down" ? "-" : ""}
              {Math.abs(trend.value)}%
            </span>
            <span className="text-xs text-muted-foreground">
              {trend.comparison}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

// ✅ Display name for React DevTools debugging
KPICard.displayName = "KPICard";
