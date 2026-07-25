"use client";

import * as React from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AdmissionTrend } from "@/lib/zod/reports";

// Funnel-ordered, theme-legible hues (app convention: recharts hardcodes hex).
// neutral (top of funnel) → indigo (progressing) → emerald (goal reached).
const SERIES = [
  { key: "Nộp hồ sơ", field: "submitted_cumulative", color: "#64748b" },
  { key: "Đủ điều kiện", field: "admitted_cumulative", color: "#6366f1" },
  { key: "Nhập học", field: "enrolled_cumulative", color: "#10b981" },
] as const;

const dm = (s: string) => `${s.slice(8, 10)}/${s.slice(5, 7)}`;

export function OverviewTrend({ trend }: { trend: AdmissionTrend }) {
  const data = React.useMemo(
    () =>
      trend.points.map((p) => ({
        label: dm(p.week_start),
        "Nộp hồ sơ": p.submitted_cumulative,
        "Đủ điều kiện": p.admitted_cumulative,
        "Nhập học": p.enrolled_cumulative,
      })),
    [trend],
  );

  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa có dữ liệu theo tuần.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={40}
          allowDecimals={false}
        />
        <Tooltip
          contentStyle={{
            fontSize: 12,
            borderRadius: 8,
            border: "1px solid var(--border)",
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {SERIES.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            stroke={s.color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
