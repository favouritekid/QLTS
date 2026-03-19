"use client";

import { Target, TrendingUp, Users } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { CoverageReport } from "@/types/kpi-setup.types";

interface Props {
  report: CoverageReport;
}

export function HubSummaryCards({ report }: Props) {
  const { summary } = report;

  const atRiskCount = report.units.reduce(
    (sum, u) =>
      sum +
      u.officers.filter(
        (o) => o.status === "at_risk" || o.status === "overdue",
      ).length,
    0,
  );

  const cards = [
    {
      title: "Tổng chỉ tiêu",
      value: summary.total_annual_target,
      icon: Target,
    },
    {
      title: "Đã đạt YTD",
      value: summary.total_achieved_ytd,
      icon: TrendingUp,
    },
    {
      title: "Tiến độ",
      value: `${summary.progress_pct}%`,
      icon: TrendingUp,
    },
    {
      title: "Cán bộ có nguy cơ",
      value: atRiskCount,
      icon: Users,
      highlight: atRiskCount > 0,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <Card key={card.title}>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <card.icon
                aria-hidden="true"
                className={`h-5 w-5 ${card.highlight ? "text-destructive" : "text-muted-foreground"}`}
              />
              <div>
                <p className="text-sm text-muted-foreground">{card.title}</p>
                <p
                  className={`text-2xl font-semibold tabular-nums ${card.highlight ? "text-destructive" : ""}`}
                >
                  {card.value}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
