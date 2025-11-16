// src/components/officer/PerformanceChart.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface PerformanceTrend {
  date: string;
  leads_assigned: number;
  consultations: number;
  converted: number;
}

interface PerformanceChartProps {
  trends: PerformanceTrend[];
}

export function PerformanceChart({ trends }: PerformanceChartProps) {
  // Format data for Recharts
  const chartData = trends.map((trend) => ({
    date: new Date(trend.date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    "Leads Assigned": trend.leads_assigned,
    "Consultations": trend.consultations,
    "Converted": trend.converted,
  }));

  // Calculate totals
  const totals = trends.reduce(
    (acc, curr) => ({
      leads: acc.leads + curr.leads_assigned,
      consultations: acc.consultations + curr.consultations,
      converted: acc.converted + curr.converted,
    }),
    { leads: 0, consultations: 0, converted: 0 }
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Performance Trends</CardTitle>
        <CardDescription>
          Last 7 days: {totals.leads} leads assigned • {totals.consultations} consultations •{" "}
          {totals.converted} converted
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="date"
              className="text-xs"
              tick={{ fill: "hsl(var(--muted-foreground))" }}
            />
            <YAxis
              className="text-xs"
              tick={{ fill: "hsl(var(--muted-foreground))" }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--background))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "var(--radius)",
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="Leads Assigned"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
            />
            <Line
              type="monotone"
              dataKey="Consultations"
              stroke="hsl(var(--chart-2))"
              strokeWidth={2}
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
            />
            <Line
              type="monotone"
              dataKey="Converted"
              stroke="hsl(var(--chart-3))"
              strokeWidth={2}
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
