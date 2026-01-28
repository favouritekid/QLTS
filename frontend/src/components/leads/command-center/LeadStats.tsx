// src/components/leads/command-center/LeadStats.tsx
"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, UserPlus, Flame, TrendingUp } from "lucide-react";
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
      title: "Tổng số Lead",
      value: totalCount,
      icon: Users,
      color: "text-info-600",
      bgColor: "bg-info-50",
    },
    {
      title: "Lead mới",
      value: newLeadsCount,
      icon: UserPlus,
      color: "text-success-600",
      bgColor: "bg-success-50",
    },
    {
      title: "Điểm cao",
      value: highScoreCount,
      icon: Flame,
      color: "text-orange-600",
      bgColor: "bg-orange-50",
    },
    {
      title: "Tỉ lệ chuyển đổi",
      value: `${conversionRate}%`,
      icon: TrendingUp,
      color: "text-purple-600",
      bgColor: "bg-purple-50",
    },
  ];

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <div className="h-4 w-20 bg-muted rounded" />
            </CardHeader>
            <CardContent>
              <div className="h-8 w-16 bg-muted rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-4">
      {stats.map((stat) => (
        <Card key={stat.title} className="hover:shadow-md transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {stat.title}
            </CardTitle>
            <div className={`p-2 rounded-lg ${stat.bgColor}`}>
              <stat.icon className={`h-4 w-4 ${stat.color}`} />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stat.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
});
