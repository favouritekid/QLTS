// src/components/officer/PerformanceChart.tsx
/**
 * Performance Trend Chart
 * Shows leads assigned, consultations, and conversions over time.
 * Uses global DashboardDateContext for date filtering (no internal filter).
 */
"use client";

import { useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
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
import { useDashboardDate } from "@/contexts/DashboardDateContext";

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

export function PerformanceChart({ trends, dailyGoal = 5, teamAverage }: PerformanceChartProps) {
  // Use global dashboard date context
  const { dateRange } = useDashboardDate();

  // Filter trends by global date range
  const filteredTrends = useMemo(() => {
    if (!dateRange?.from || !dateRange?.to) return trends;
    
    const fromDate = new Date(dateRange.from);
    const toDate = new Date(dateRange.to);
    fromDate.setHours(0, 0, 0, 0);
    toDate.setHours(23, 59, 59, 999);
    
    return trends.filter((t) => {
      const date = new Date(t.date);
      return date >= fromDate && date <= toDate;
    });
  }, [trends, dateRange]);

  // Format data for Recharts
  const chartData = filteredTrends.map((trend) => ({
    date: new Date(trend.date).toLocaleDateString("vi-VN", {
      month: "short",
      day: "numeric",
    }),
    "Leads được giao": trend.leads_assigned,
    "Lượt tư vấn": trend.consultations,
    "Chuyển đổi": trend.converted,
    ...(teamAverage !== undefined && { "Trung bình team": teamAverage }),
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

  // Calculate max value for Y-axis domain to ensure ReferenceLines are visible
  const maxDataValue = Math.max(
    ...filteredTrends.map(t => Math.max(t.leads_assigned, t.consultations, t.converted)),
    0
  );
  
  const chartMax = Math.max(
    maxDataValue,
    dailyGoal,
    teamAverage || 0
  );
  
  // Add some padding (e.g. 10%) on top
  const yAxisDomain = [0, Math.ceil(chartMax * 1.1)];

  // Get description text based on date range
  const getDescription = () => {
    if (dateRange?.from && dateRange?.to) {
      const fromStr = format(dateRange.from, "dd/MM", { locale: vi });
      const toStr = format(dateRange.to, "dd/MM", { locale: vi });
      return `${fromStr} - ${toStr}: ${totals.leads} leads • ${totals.consultations} tư vấn • ${totals.converted} chuyển đổi`;
    }
    return `${totals.leads} leads • ${totals.consultations} tư vấn • ${totals.converted} chuyển đổi`;
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        {/* ... existing header code ... */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle className="text-base font-medium">
              Xu hướng hiệu suất
            </CardTitle>
            <CardDescription className="text-xs mt-1">
              {getDescription()}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {filteredTrends.length === 0 ? (
          <div className="flex items-center justify-center h-[300px] text-sm text-muted-foreground">
            Không có dữ liệu trong khoảng thời gian được chọn
          </div>
        ) : (
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
              domain={yAxisDomain}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--popover))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "6px",
                fontSize: "12px",
                boxShadow: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
                padding: "8px 12px",
                zIndex: 50,
                color: "hsl(var(--popover-foreground))",
              }}
              wrapperStyle={{ zIndex: 50, pointerEvents: "none" }}
              cursor={{ stroke: "hsl(var(--muted-foreground))", strokeWidth: 1, strokeDasharray: "4 4" }}
            />
            <Legend 
              wrapperStyle={{ fontSize: "11px", paddingTop: "10px" }}
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
              dataKey="Leads được giao"
              stroke="#8b5cf6" // Violet-500
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6, fill: "#8b5cf6", strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="Lượt tư vấn"
              stroke="#f97316" // Orange-500 (High contrast vs Violet/Green)
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6, fill: "#f97316", strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="Chuyển đổi"
              stroke="hsl(var(--success-500))" // success-500
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6, fill: "#10b981", strokeWidth: 0 }}
            />
          </LineChart>
        </ResponsiveContainer>
        )}

        {/* Summary Stats */}
        <div className="flex items-center justify-center gap-6 mt-4 pt-4 border-t text-xs text-muted-foreground flex-wrap">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full ring-2 ring-violet-500/20 bg-violet-500" />
            <span>TB leads/ngày: {filteredTrends.length > 0 ? Math.round(totals.leads / filteredTrends.length) : 0}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full ring-2 ring-orange-500/20 bg-orange-500" />
            <span>TB tư vấn/ngày: {avgConsultations}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full ring-2 ring-success-500/20 bg-success-500" />
            <span>Chuyển đổi/tư vấn: {totals.consultations > 0 ? Math.round((totals.converted / totals.consultations) * 100) : 0}%</span>
          </div>
          {teamAverage !== undefined && (
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full ring-2 ring-purple-500/20 bg-purple-500" />
              <span>TB team: {teamAverage}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
