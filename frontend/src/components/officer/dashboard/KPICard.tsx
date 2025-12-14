// src/components/officer/dashboard/KPICard.tsx
/**
 * KPI Card Component for Officer Dashboard
 * Displays a single KPI metric with trend indicator
 */

"use client";

import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
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
  color?: "blue" | "green" | "orange" | "purple";
  onClick?: () => void;
}

const colorStyles = {
  blue: {
    bg: "bg-blue-50 dark:bg-blue-950/30",
    icon: "text-blue-600 dark:text-blue-400",
    badge: "bg-blue-100 dark:bg-blue-900/50",
  },
  green: {
    bg: "bg-green-50 dark:bg-green-950/30",
    icon: "text-green-600 dark:text-green-400",
    badge: "bg-green-100 dark:bg-green-900/50",
  },
  orange: {
    bg: "bg-orange-50 dark:bg-orange-950/30",
    icon: "text-orange-600 dark:text-orange-400",
    badge: "bg-orange-100 dark:bg-orange-900/50",
  },
  purple: {
    bg: "bg-purple-50 dark:bg-purple-950/30",
    icon: "text-purple-600 dark:text-purple-400",
    badge: "bg-purple-100 dark:bg-purple-900/50",
  },
};

export function KPICard({
  title,
  value,
  subtitle,
  trend,
  icon: Icon,
  color = "blue",
  onClick,
}: KPICardProps) {
  const styles = colorStyles[color];

  const TrendIcon =
    trend?.direction === "up"
      ? TrendingUp
      : trend?.direction === "down"
      ? TrendingDown
      : Minus;

  const trendColor =
    trend?.direction === "up"
      ? "text-green-600"
      : trend?.direction === "down"
      ? "text-red-600"
      : "text-muted-foreground";

  return (
    <Card
      className={cn(
        "transition-all duration-200 hover:shadow-md",
        onClick && "cursor-pointer hover:scale-[1.02]",
        styles.bg
      )}
      onClick={onClick}
    >
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <span className="text-sm font-medium text-muted-foreground">
          {title}
        </span>
        <div className={cn("rounded-full p-2", styles.badge)}>
          <Icon className={cn("h-4 w-4", styles.icon)} />
        </div>
      </CardHeader>
      <CardContent>
        {/* Main Value */}
        <div className="text-3xl font-bold tracking-tight">{value}</div>

        {/* Subtitle */}
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
        )}

        {/* Trend Indicator */}
        {trend && (
          <div className={cn("flex items-center gap-1 mt-2", trendColor)}>
            <TrendIcon className="h-3.5 w-3.5" />
            <span className="text-xs font-medium">
              {trend.direction !== "neutral" && (trend.direction === "up" ? "+" : "-")}
              {trend.value}% {trend.comparison}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
