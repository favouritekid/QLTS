// src/components/officer/PerformanceChart.tsx
"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

interface PerformanceTrend {
  date: string;
  leads_assigned: number;
  consultations: number;
  converted: number;
}

interface PerformanceChartProps {
  trends: PerformanceTrend[];
  dailyGoal?: number; // Optional daily consultations goal
}

type TimeRange = "7D" | "30D" | "90D";

export function PerformanceChart({ trends, dailyGoal = 5 }: PerformanceChartProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("7D");

  // Filter data based on time range
  const getDaysForRange = (range: TimeRange): number => {
    switch (range) {
      case "7D": return 7;
      case "30D": return 30;
      case "90D": return 90;
      default: return 7;
    }
  };

  const filteredTrends = trends.slice(-getDaysForRange(timeRange));

  // Format data for Recharts
  const chartData = filteredTrends.map((trend) => ({
    date: new Date(trend.date).toLocaleDateString("vi-VN", {
      month: "short",
      day: "numeric",
    }),
    "Leads Assigned": trend.leads_assigned,
    "Consultations": trend.consultations,
    "Converted": trend.converted,
  }));

  // Calculate totals
  const totals = filteredTrends.reduce(
    (acc, curr) => ({
      leads: acc.leads + curr.leads_assigned,
      consultations: acc.consultations + curr.consultations,
      converted: acc.converted + curr.converted,
    }),
    { leads: 0, consultations: 0, converted: 0 }
  );

  // Calculate averages
  const avgConsultations = filteredTrends.length > 0 
    ? Math.round(totals.consultations / filteredTrends.length) 
    : 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base font-medium">
              Xu hướng hiệu suất
            </CardTitle>
            <CardDescription className="text-xs mt-1">
              {getDaysForRange(timeRange)} ngày: {totals.leads} leads • {totals.consultations} tư vấn • {totals.converted} chuyển đổi
            </CardDescription>
          </div>
          {/* Time Range Selector */}
          <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
            {(["7D", "30D", "90D"] as TimeRange[]).map((range) => (
              <Button
                key={range}
                variant="ghost"
                size="sm"
                onClick={() => setTimeRange(range)}
                className={cn(
                  "h-7 px-2.5 text-xs font-medium",
                  timeRange === range 
                    ? "bg-background shadow-sm" 
                    : "hover:bg-background/50"
                )}
              >
                {range}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="date"
              className="text-xs"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              className="text-xs"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={30}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--background))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "var(--radius)",
                fontSize: "12px",
              }}
            />
            <Legend 
              wrapperStyle={{ fontSize: "11px" }}
              iconSize={10}
            />
            
            {/* Goal Line */}
            <ReferenceLine 
              y={dailyGoal} 
              stroke="hsl(var(--chart-4))" 
              strokeDasharray="5 5"
              label={{ 
                value: `Mục tiêu: ${dailyGoal}`, 
                fill: "hsl(var(--chart-4))",
                fontSize: 10,
                position: "insideTopRight"
              }}
            />
            
            {/* Average Line */}
            <ReferenceLine 
              y={avgConsultations} 
              stroke="hsl(var(--muted-foreground))" 
              strokeDasharray="3 3"
              strokeOpacity={0.5}
            />

            <Line
              type="monotone"
              dataKey="Leads Assigned"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="Consultations"
              stroke="hsl(var(--chart-2))"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="Converted"
              stroke="hsl(var(--chart-3))"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
        
        {/* Summary Stats */}
        <div className="flex items-center justify-center gap-6 mt-4 pt-4 border-t text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-primary" />
            <span>TB leads/ngày: {filteredTrends.length > 0 ? Math.round(totals.leads / filteredTrends.length) : 0}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ background: "hsl(var(--chart-2))" }} />
            <span>TB tư vấn/ngày: {avgConsultations}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ background: "hsl(var(--chart-3))" }} />
            <span>Tỉ lệ: {totals.consultations > 0 ? Math.round((totals.converted / totals.consultations) * 100) : 0}%</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
