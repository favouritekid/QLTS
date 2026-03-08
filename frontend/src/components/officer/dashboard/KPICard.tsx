// src/components/officer/dashboard/KPICard.tsx
/**
 * KPI Card Component for Officer Dashboard
 * Compact design with keyboard-accessible button semantics + tooltip
 */

"use client";

import { memo } from "react";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
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
  tooltip?: string;
  trend?: TrendInfo;
  icon: LucideIcon;
  onClick?: () => void;
  inverseTrend?: boolean;
}

/** Format number with vi-VN locale, 1 decimal place */
function formatViNumber(n: number): string {
  return n.toLocaleString("vi-VN", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

export const KPICard = memo(function KPICard({
  title,
  value,
  subtitle,
  tooltip,
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

  const cardContent = (
    <CardContent className="p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-muted-foreground">
          {title}
        </span>
        <div className="rounded-lg bg-muted p-1.5">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        </div>
      </div>

      <div className="text-2xl font-bold tracking-tight text-foreground">
        {value}
      </div>

      {subtitle && (
        <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>
      )}

      {trend && (
        <div className={cn("flex items-center gap-1 mt-2", trendColor)}>
          <TrendIcon className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="text-xs font-medium">
            {trend.direction === "up" ? "+" : trend.direction === "down" ? "-" : ""}
            {formatViNumber(Math.abs(trend.value))}%
          </span>
          <span className="text-xs text-muted-foreground">
            {trend.comparison}
          </span>
        </div>
      )}
    </CardContent>
  );

  const card = onClick ? (
    <button
      type="button"
      onClick={onClick}
      className="text-left w-full rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      aria-label={`${title}: ${value}`}
    >
      <Card className="h-full border bg-card transition-shadow duration-200 hover:border-primary/20 hover:shadow-sm">
        {cardContent}
      </Card>
    </button>
  ) : (
    <Card className="border bg-card">
      {cardContent}
    </Card>
  );

  if (!tooltip) return card;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{card}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-64 text-center">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  );
});

KPICard.displayName = "KPICard";
