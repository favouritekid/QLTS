// src/components/officer/dashboard/CurrentMonthSnapshot.tsx
/**
 * Current Month Snapshot — 4 compact stat cards showing this month's KPI progress.
 * Surfaces data that otherwise requires expanding MonthlyBreakdownCard.
 */

"use client";

import { CalendarDays } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { OfficerKpiPlanResponse } from "@/lib/api/officer";

interface CurrentMonthSnapshotProps {
  plan: OfficerKpiPlanResponse | null | undefined;
  isLoading?: boolean;
  /** Anchor month/year from dashboard date range (defaults to client clock) */
  anchorMonth?: number;
  anchorYear?: number;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("vi-VN", { maximumFractionDigits: 1 });
}

/**
 * Consultation achievement: actual_avg vs target daily.
 * Returns "met" | "near" | "behind" | null (no actual data).
 */
function consultationStatus(
  target: number | null | undefined,
  actualAvg: number | null | undefined,
): "met" | "near" | "behind" | null {
  if (actualAvg == null || target == null || target === 0) return null;
  const ratio = actualAvg / target;
  if (ratio >= 1) return "met";
  if (ratio >= 0.8) return "near";
  return "behind";
}

const STATUS_COLORS = {
  met: "text-success-600 dark:text-success-500",
  near: "text-warning-600 dark:text-warning-500",
  behind: "text-destructive",
} as const;

const PROGRESS_INDICATOR_COLORS = {
  met: "bg-success-500",
  near: "bg-warning-500",
  behind: "bg-destructive",
} as const;

export function CurrentMonthSnapshot({ plan, isLoading, anchorMonth, anchorYear }: CurrentMonthSnapshotProps) {
  if (isLoading || !plan) return null;

  const now = new Date();
  const currentMonth = anchorMonth ?? (now.getMonth() + 1);
  const currentYear = anchorYear ?? now.getFullYear();

  const monthData = plan.months.find((m) => m.month === currentMonth);
  if (!monthData) return null;

  // --- Stat 1: Enrollment ---
  const enrollActual = monthData.enrollment_actual ?? 0;
  const enrollTarget = monthData.enrollment_target;
  const enrollPct = enrollTarget > 0 ? Math.min(100, Math.round((enrollActual / enrollTarget) * 100)) : 0;
  const enrollMet = enrollActual >= enrollTarget;

  // --- Stat 2: Avg consultations/day ---
  const cStatus = consultationStatus(monthData.consultations_daily, monthData.consultations_actual_avg);

  // --- Stat 3: Total consultations this month ---
  // plain number, no target comparison

  // --- Stat 4: Conversion rate ---
  // percentage, no target comparison

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
        <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
        Tháng {currentMonth}/{currentYear} — Tiến độ hiện tại
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* 1. Enrollment this month */}
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs text-muted-foreground mb-1">Nhập học tháng</p>
          <p className={cn("text-lg font-semibold tabular-nums", enrollMet ? "text-success-600 dark:text-success-500" : "text-warning-600 dark:text-warning-500")}>
            {fmtNum(monthData.enrollment_actual)}/{fmtNum(enrollTarget)}
          </p>
          <Progress
            value={enrollPct}
            className="h-1.5 mt-1.5"
            indicatorClassName={enrollMet ? "bg-success-500" : "bg-warning-500"}
          />
          <p className="text-[11px] text-muted-foreground mt-1">
            {enrollPct}% chỉ tiêu
          </p>
        </div>

        {/* 2. Avg consultations/day */}
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs text-muted-foreground mb-1">TV trung bình/ngày</p>
          <p className={cn("text-lg font-semibold tabular-nums", cStatus && STATUS_COLORS[cStatus])}>
            {fmtNum(monthData.consultations_actual_avg)}
          </p>
          {monthData.consultations_daily != null && (
            <>
              {monthData.consultations_actual_avg != null && (
                <Progress
                  value={Math.min(100, Math.round((monthData.consultations_actual_avg / monthData.consultations_daily) * 100))}
                  className="h-1.5 mt-1.5"
                  indicatorClassName={cStatus ? PROGRESS_INDICATOR_COLORS[cStatus] : undefined}
                />
              )}
              <p className="text-[11px] text-muted-foreground mt-1">
                Mục tiêu: {fmtNum(monthData.consultations_daily)}/ngày
              </p>
            </>
          )}
        </div>

        {/* 3. Total consultations this month (plan-derived, not actual) */}
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs text-muted-foreground mb-1">CT TV tháng</p>
          <p className="text-lg font-semibold tabular-nums">
            {fmtNum(monthData.consultations_monthly_total)}
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">Chỉ tiêu</p>
        </div>

        {/* 4. Conversion rate — show actual if available, otherwise plan target */}
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs text-muted-foreground mb-1">
            {monthData.conversion_rate_actual != null ? "Conv% thực tế" : "CT Conv%"}
          </p>
          <p className="text-lg font-semibold tabular-nums">
            {(() => {
              const val = monthData.conversion_rate_actual ?? monthData.conversion_rate;
              return val != null
                ? val.toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%"
                : "—";
            })()}
          </p>
          {monthData.conversion_rate_actual == null && monthData.conversion_rate != null && (
            <p className="text-[10px] text-muted-foreground mt-0.5">Chỉ tiêu</p>
          )}
        </div>
      </div>
    </div>
  );
}
