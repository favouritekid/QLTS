// src/components/officer/dashboard/MonthlyBreakdownCard.tsx
/**
 * Gap 2: Monthly KPI Plan Breakdown Card
 * Collapsed by default, full-width, shows 12-month target vs actual.
 * Returns null when no plan exists (404).
 */

"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, CalendarDays } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { OfficerKpiPlanResponse } from "@/lib/api/officer";

interface MonthlyBreakdownCardProps {
  plan: OfficerKpiPlanResponse | undefined;
  isLoading?: boolean;
}

const MONTH_NAMES = [
  "Tháng 1", "Tháng 2", "Tháng 3", "Tháng 4",
  "Tháng 5", "Tháng 6", "Tháng 7", "Tháng 8",
  "Tháng 9", "Tháng 10", "Tháng 11", "Tháng 12",
];

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("vi-VN", { maximumFractionDigits: 1 });
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
}

export function MonthlyBreakdownCard({ plan, isLoading }: MonthlyBreakdownCardProps) {
  const [expanded, setExpanded] = useState(false);

  // Don't render if no plan or loading
  if (isLoading || !plan) return null;

  const currentMonth = new Date().getMonth() + 1; // 1-based
  const currentYear = new Date().getFullYear();
  const isCurrentYear = plan.fiscal_year === currentYear;

  // Compute totals
  const totalTarget = plan.annual_target;
  const totalActual = plan.achieved_ytd;
  const totalConsultMonthly = plan.months.reduce(
    (sum, m) => sum + (m.consultations_monthly_total ?? 0), 0
  );

  return (
    <Card className="border bg-card">
      <CardHeader className="p-0">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center justify-between w-full px-4 py-3 text-left rounded-t-xl transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          aria-expanded={expanded}
          aria-label="Kế hoạch theo tháng"
        >
          <div className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="text-sm font-semibold">Kế hoạch theo tháng</span>
            <span className="text-xs text-muted-foreground">
              ({plan.fiscal_year} — {plan.source === "officer" ? "Cá nhân" : "Đơn vị"})
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground hidden sm:inline">
              {totalActual}/{totalTarget} ({fmtPct(plan.progress_pct)})
            </span>
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            )}
          </div>
        </button>
      </CardHeader>

      {expanded && (
        <CardContent className="px-0 pb-0 pt-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="monthly-breakdown-table">
              <thead>
                <tr className="border-t border-b bg-muted/30">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Tháng</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">CT Tuyển sinh</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Thực tế</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">TV/ngày</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Tổng TV tháng</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Conv%</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Win%</th>
                </tr>
              </thead>
              <tbody>
                {plan.months.map((m) => {
                  const isCurrent = isCurrentYear && m.month === currentMonth;
                  const isFuture = isCurrentYear && m.month > currentMonth;
                  const isOnTrack = m.enrollment_actual != null && m.enrollment_actual >= m.enrollment_target;
                  const isBehind = m.enrollment_actual != null && m.enrollment_actual < m.enrollment_target;

                  return (
                    <tr
                      key={m.month}
                      className={cn(
                        "border-b transition-colors",
                        isCurrent && "bg-primary/5 font-medium",
                        isFuture && "text-muted-foreground/60",
                        !isCurrent && !isFuture && "hover:bg-muted/20",
                      )}
                    >
                      <td className="px-4 py-2">
                        {MONTH_NAMES[m.month - 1]}
                        {isCurrent && (
                          <span className="ml-1.5 text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                            Hiện tại
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtNum(m.enrollment_target)}</td>
                      <td className={cn(
                        "px-3 py-2 text-right tabular-nums",
                        isOnTrack && "text-success-600 dark:text-success-500",
                        isBehind && "text-warning-600 dark:text-warning-500",
                      )}>
                        {fmtNum(m.enrollment_actual)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtNum(m.consultations_daily)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtNum(m.consultations_monthly_total)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtPct(m.conversion_rate)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtPct(m.win_rate)}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 font-semibold bg-muted/20">
                  <td className="px-4 py-2">Tổng cộng</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmtNum(totalTarget)}</td>
                  <td className={cn(
                    "px-3 py-2 text-right tabular-nums",
                    totalActual >= totalTarget
                      ? "text-success-600 dark:text-success-500"
                      : "text-warning-600 dark:text-warning-500",
                  )}>
                    {fmtNum(totalActual)}
                  </td>
                  <td className="px-3 py-2 text-right text-muted-foreground">—</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmtNum(totalConsultMonthly)}</td>
                  <td className="px-3 py-2 text-right text-muted-foreground">—</td>
                  <td className="px-3 py-2 text-right text-muted-foreground">—</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
