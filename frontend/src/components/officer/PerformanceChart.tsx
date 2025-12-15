// src/components/officer/PerformanceChart.tsx
"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { cn } from "@/lib/utils";
import type { DateRange } from "react-day-picker";
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
  teamAverage?: number; // Optional team average for comparison
}

type TimeRange = "7D" | "30D" | "90D" | "custom";

export function PerformanceChart({ trends, dailyGoal = 5, teamAverage }: PerformanceChartProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("7D");
  const [customDateRange, setCustomDateRange] = useState<DateRange | undefined>(undefined);

  // Filter data based on time range
  const getDaysForRange = (range: TimeRange): number => {
    switch (range) {
      case "7D": return 7;
      case "30D": return 30;
      case "90D": return 90;
      default: return 7;
    }
  };

  // Filter trends by custom date range or preset
  const filteredTrends = useMemo(() => {
    if (timeRange === "custom" && customDateRange?.from && customDateRange?.to) {
      const fromDate = new Date(customDateRange.from);
      const toDate = new Date(customDateRange.to);
      fromDate.setHours(0, 0, 0, 0);
      toDate.setHours(23, 59, 59, 999);
      
      return trends.filter((t) => {
        const date = new Date(t.date);
        return date >= fromDate && date <= toDate;
      });
    }
    return trends.slice(-getDaysForRange(timeRange));
  }, [trends, timeRange, customDateRange]);

  // Format data for Recharts
  const chartData = filteredTrends.map((trend) => ({
    date: new Date(trend.date).toLocaleDateString("vi-VN", {
      month: "short",
      day: "numeric",
    }),
    "Leads Assigned": trend.leads_assigned,
    "Consultations": trend.consultations,
    "Converted": trend.converted,
    ...(teamAverage !== undefined && { "Team Average": teamAverage }),
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

  // Handle preset button click
  const handlePresetClick = (range: TimeRange) => {
    setTimeRange(range);
    if (range !== "custom") {
      setCustomDateRange(undefined);
    }
  };

  // Handle custom date range change
  const handleCustomDateChange = (range: DateRange | undefined) => {
    setCustomDateRange(range);
    if (range?.from && range?.to) {
      setTimeRange("custom");
    }
  };

  // Get description text
  const getDescription = () => {
    if (timeRange === "custom" && customDateRange?.from && customDateRange?.to) {
      const days = Math.ceil((customDateRange.to.getTime() - customDateRange.from.getTime()) / (1000 * 60 * 60 * 24)) + 1;
      return `${days} ngày: ${totals.leads} leads • ${totals.consultations} tư vấn • ${totals.converted} chuyển đổi`;
    }
    return `${getDaysForRange(timeRange)} ngày: ${totals.leads} leads • ${totals.consultations} tư vấn • ${totals.converted} chuyển đổi`;
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle className="text-base font-medium">
              Xu hướng hiệu suất
            </CardTitle>
            <CardDescription className="text-xs mt-1">
              {getDescription()}
            </CardDescription>
          </div>
          {/* Time Range Selector */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
              {(["7D", "30D", "90D"] as TimeRange[]).map((range) => (
                <Button
                  key={range}
                  variant="ghost"
                  size="sm"
                  onClick={() => handlePresetClick(range)}
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
            {/* Custom Date Range Picker */}
            <DateRangePicker
              dateRange={customDateRange}
              onDateRangeChange={handleCustomDateChange}
              placeholder="Tùy chỉnh"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
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
              stroke="#f59e0b" 
              strokeDasharray="5 5"
              label={{ 
                value: `Mục tiêu: ${dailyGoal}`, 
                fill: "#f59e0b",
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

            {/* Team Average Line (if provided) */}
            {teamAverage !== undefined && (
              <ReferenceLine 
                y={teamAverage} 
                stroke="#8b5cf6" 
                strokeDasharray="8 4"
                label={{ 
                  value: `TB team: ${teamAverage}`, 
                  fill: "#8b5cf6",
                  fontSize: 10,
                  position: "insideBottomRight"
                }}
              />
            )}

            <Line
              type="monotone"
              dataKey="Consultations"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={{ r: 4, fill: "#3b82f6" }}
              activeDot={{ r: 6 }}
            />
            <Line
              type="monotone"
              dataKey="Converted"
              stroke="#10b981"
              strokeWidth={2}
              dot={{ r: 4, fill: "#10b981" }}
              activeDot={{ r: 6 }}
            />
            <Line
              type="monotone"
              dataKey="Leads Assigned"
              stroke="#6366f1"
              strokeWidth={2}
              dot={{ r: 4, fill: "#6366f1" }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
        
        {/* Summary Stats */}
        <div className="flex items-center justify-center gap-6 mt-4 pt-4 border-t text-xs text-muted-foreground flex-wrap">
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ background: "#6366f1" }} />
            <span>TB leads/ngày: {filteredTrends.length > 0 ? Math.round(totals.leads / filteredTrends.length) : 0}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ background: "#3b82f6" }} />
            <span>TB tư vấn/ngày: {avgConsultations}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ background: "#10b981" }} />
            <span>Tỉ lệ: {totals.consultations > 0 ? Math.round((totals.converted / totals.consultations) * 100) : 0}%</span>
          </div>
          {teamAverage !== undefined && (
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full" style={{ background: "#8b5cf6" }} />
              <span>TB team: {teamAverage}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
