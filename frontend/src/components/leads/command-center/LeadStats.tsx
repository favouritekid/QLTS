// src/components/leads/command-center/LeadStats.tsx
"use client";

import React from "react";
import { Users, UserPlus, Flame, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";

interface LeadStatsProps {
  leads: Lead[];
  totalCount: number;
  isLoading?: boolean;
}

export const LeadStats = React.memo(function LeadStats({
  leads,
  totalCount,
  isLoading,
}: LeadStatsProps) {
  // Calculate stats from leads data
  const newLeadsCount = leads.filter((l) => l.status === "new").length;
  const highScoreCount = leads.filter((l) => l.lead_score > 80).length;
  const convertedCount = leads.filter((l) => l.status === "converted").length;
  const conversionRate = totalCount > 0
    ? Math.round((convertedCount / totalCount) * 100)
    : 0;

  const stats = [
    {
      title: "Tổng số",
      value: totalCount,
      icon: Users,
      color: "text-blue-600 dark:text-blue-400",
      bgColor: "bg-blue-100 dark:bg-blue-900/40",
    },
    {
      title: "Mới",
      value: newLeadsCount,
      icon: UserPlus,
      color: "text-emerald-600 dark:text-emerald-400",
      bgColor: "bg-emerald-100 dark:bg-emerald-900/40",
    },
    {
      title: "Điểm cao",
      value: highScoreCount,
      icon: Flame,
      color: "text-orange-600 dark:text-orange-400",
      bgColor: "bg-orange-100 dark:bg-orange-900/40",
    },
    {
      title: "Chuyển đổi",
      value: `${conversionRate}%`,
      icon: TrendingUp,
      color: "text-purple-600 dark:text-purple-400",
      bgColor: "bg-purple-100 dark:bg-purple-900/40",
    },
  ];

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-2 rounded-lg border bg-card p-2.5 sm:p-3 animate-pulse"
          >
            <div className="h-8 w-8 rounded-lg bg-muted" />
            <div className="flex-1 space-y-1">
              <div className="h-3 w-12 rounded bg-muted" />
              <div className="h-5 w-8 rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
      {stats.map((stat) => (
        <div
          key={stat.title}
          className={cn(
            "flex items-center gap-2.5 rounded-lg border bg-card p-2.5 sm:p-3",
            "hover:shadow-sm transition-shadow"
          )}
        >
          {/* Icon - Always visible with strong colors */}
          <div className={cn("flex-shrink-0 rounded-lg p-2", stat.bgColor)}>
            <stat.icon className={cn("h-4 w-4 sm:h-5 sm:w-5", stat.color)} />
          </div>
          {/* Text */}
          <div className="min-w-0 flex-1">
            <p className="text-[10px] sm:text-xs font-medium text-muted-foreground truncate">
              {stat.title}
            </p>
            <p className="text-base sm:text-lg font-bold leading-tight">
              {stat.value}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
});
