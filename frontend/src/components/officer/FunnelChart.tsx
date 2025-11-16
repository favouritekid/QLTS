// src/components/officer/FunnelChart.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface FunnelStage {
  stage_name: string;
  stage_order: number;
  lead_count: number;
}

interface FunnelChartProps {
  funnel: FunnelStage[];
}

// Color palette for funnel stages
const COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
];

export function FunnelChart({ funnel }: FunnelChartProps) {
  // Sort by stage order and format data
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);

  const chartData = sortedFunnel.map((stage, index) => ({
    name: stage.stage_name,
    count: stage.lead_count,
    color: COLORS[index % COLORS.length],
  }));

  // Calculate conversion rate
  const totalLeads = sortedFunnel[0]?.lead_count || 0;
  const convertedLeads = sortedFunnel[sortedFunnel.length - 1]?.lead_count || 0;
  const conversionRate = totalLeads > 0 ? (convertedLeads / totalLeads) * 100 : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sales Funnel</CardTitle>
        <CardDescription>
          Lead distribution across pipeline stages •{" "}
          <span className="font-medium text-foreground">
            {conversionRate.toFixed(1)}% conversion rate
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={chartData} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              type="number"
              className="text-xs"
              tick={{ fill: "hsl(var(--muted-foreground))" }}
            />
            <YAxis
              type="category"
              dataKey="name"
              className="text-xs"
              tick={{ fill: "hsl(var(--muted-foreground))" }}
              width={120}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--background))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "var(--radius)",
              }}
              formatter={(value: number) => [`${value} leads`, "Count"]}
            />
            <Bar dataKey="count" radius={[0, 8, 8, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        {/* Funnel Breakdown */}
        <div className="mt-4 space-y-2">
          {sortedFunnel.map((stage, index) => {
            const percentage = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
            return (
              <div key={stage.stage_name} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div
                    className="h-3 w-3 rounded-sm"
                    style={{ backgroundColor: COLORS[index % COLORS.length] }}
                  />
                  <span>{stage.stage_name}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="font-medium">{stage.lead_count}</span>
                  <span className="text-muted-foreground w-12 text-right">
                    {percentage.toFixed(0)}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
