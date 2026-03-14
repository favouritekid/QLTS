// src/components/officer/dashboard/KpiSummaryBanner.tsx
/**
 * Actionable KPI summary — shows 2-4 lines near top of officer dashboard.
 * Derived purely from existing data (no new API calls).
 * Rules:
 * - Only shows items that are notable (don't repeat what cards already show)
 * - Non-comparable metrics never mention targets
 * - Tone: good / attention / neutral — never alarmist
 * - Items with matching leads filter are clickable deep-links
 */

"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, AlertTriangle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDashboardDate, formatDateForAPI } from "@/contexts/DashboardDateContext";
import { useKpiCatalog } from "@/lib/hooks/use-kpi-catalog";
import type { KPIStats, AnnualProgressInfo } from "@/hooks/useDashboardStats";
import type { OfficerKpiPlanResponse } from "@/lib/api/officer";

// =============================================================================
// TYPES
// =============================================================================

type SummaryTone = "good" | "attention" | "neutral";

interface SummaryItem {
  tone: SummaryTone;
  text: string;
  href?: string;
}

interface KpiSummaryBannerProps {
  kpis: KPIStats;
  annualProgress?: AnnualProgressInfo | null;
  plan?: OfficerKpiPlanResponse | null;
}

// =============================================================================
// STYLE MAPS
// =============================================================================

const TONE_ICON = {
  good: CheckCircle2,
  attention: AlertTriangle,
  neutral: Info,
} as const;

const TONE_COLOR = {
  good: "text-success-600 dark:text-success-500",
  attention: "text-warning-600 dark:text-warning-500",
  neutral: "text-muted-foreground",
} as const;

// =============================================================================
// COMPONENT
// =============================================================================

export function KpiSummaryBanner({ kpis, annualProgress, plan }: KpiSummaryBannerProps) {
  const router = useRouter();
  const { dateRange, startDate, endDate } = useDashboardDate();
  const { canShowTarget } = useKpiCatalog();

  /** Build /leads URL with dashboard date range + extra params */
  const leadsUrl = (extra: Record<string, string> = {}) => {
    const params: Record<string, string> = {};
    if (startDate) params.from = startDate;
    if (endDate) params.to = endDate;
    Object.assign(params, extra);
    const qs = new URLSearchParams(params).toString();
    return qs ? `/leads?${qs}` : "/leads";
  };

  const items = useMemo(() => {
    const attention: SummaryItem[] = [];
    const good: SummaryItem[] = [];
    const currentMonth = new Date().getMonth() + 1;

    // Detect if today falls within the selected date range
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayInRange =
      dateRange?.from && dateRange?.to &&
      today >= new Date(new Date(dateRange.from).setHours(0, 0, 0, 0)) &&
      today <= new Date(new Date(dateRange.to).setHours(23, 59, 59, 999));

    const todayStr = formatDateForAPI(today);

    // Month start/end for enrollment deep-links
    const monthStart = `${today.getFullYear()}-${String(currentMonth).padStart(2, "0")}-01`;
    const lastDay = new Date(today.getFullYear(), currentMonth, 0).getDate();
    const monthEnd = `${today.getFullYear()}-${String(currentMonth).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;

    // 1. Annual enrollment progress — only notable statuses
    if (annualProgress) {
      const { status, achieved_ytd, annual_target, remaining } = annualProgress;
      const enrollHref = leadsUrl({ status: "converted" });
      if (status === "completed") {
        good.push({ tone: "good", text: `Nhập học năm: hoàn thành (${achieved_ytd}/${annual_target})`, href: enrollHref });
      } else if (status === "at_risk") {
        attention.push({ tone: "attention", text: `Nhập học năm: ${achieved_ytd}/${annual_target} — cần tăng tốc (còn ${remaining})`, href: enrollHref });
      } else if (status === "overdue") {
        attention.push({ tone: "attention", text: `Nhập học năm: chưa đạt, còn thiếu ${remaining}`, href: enrollHref });
      }
    }

    // 2. Current month enrollment (from plan)
    if (plan) {
      const monthData = plan.months.find((m) => m.month === currentMonth);
      if (monthData && monthData.enrollment_actual != null) {
        const met = monthData.enrollment_actual >= monthData.enrollment_target;
        const monthHref = leadsUrl({ status: "converted", from: monthStart, to: monthEnd });
        if (met) {
          good.push({
            tone: "good",
            text: `Nhập học T${currentMonth}: ${monthData.enrollment_actual}/${monthData.enrollment_target} — đạt`,
            href: monthHref,
          });
        } else {
          attention.push({
            tone: "attention",
            text: `Nhập học T${currentMonth}: ${monthData.enrollment_actual}/${monthData.enrollment_target}`,
            href: monthHref,
          });
        }
      }
    }

    // 3. Today's consultations — only when met (notable achievement)
    if (todayInRange && kpis.consultations_target > 0) {
      const met = kpis.consultations_today >= kpis.consultations_target;
      if (met) {
        good.push({
          tone: "good",
          text: `Tư vấn hôm nay: ${kpis.consultations_today}/${kpis.consultations_target} — đạt mục tiêu`,
          href: leadsUrl({ date_field: "last_consultation_at", from: todayStr, to: todayStr }),
        });
      }
    }

    // 4. Comparable KPIs below target
    const dashboardRange = dateRange?.from && dateRange?.to
      ? { start: dateRange.from, end: dateRange.to }
      : undefined;

    if (canShowTarget("win_rate", dashboardRange) && kpis.win_rate_target != null) {
      if (kpis.win_rate < kpis.win_rate_target) {
        attention.push({
          tone: "attention",
          text: `Tỷ lệ chốt đơn ${fmtVal(kpis.win_rate)}% — dưới mục tiêu ${fmtVal(kpis.win_rate_target)}%`,
          href: leadsUrl({ status: "converted,unqualified,rejected" }),
        });
      }
    }

    if (canShowTarget("sla_compliance_rate", dashboardRange) && kpis.sla_compliance_rate_target != null) {
      if (kpis.sla_compliance_rate < kpis.sla_compliance_rate_target) {
        attention.push({
          tone: "attention",
          text: `SLA tuân thủ ${fmtVal(kpis.sla_compliance_rate)}% — dưới mục tiêu ${fmtVal(kpis.sla_compliance_rate_target)}%`,
        });
      }
    }

    // 5. Response time above target (lower is better)
    if (canShowTarget("response_time_hours", dashboardRange) && kpis.avg_response_time_target != null) {
      if (kpis.avg_response_time > kpis.avg_response_time_target) {
        attention.push({
          tone: "attention",
          text: `Thời gian phản hồi ${fmtVal(kpis.avg_response_time)}h — trên mục tiêu ${fmtVal(kpis.avg_response_time_target)}h`,
        });
      }
    }

    // Prioritize attention items, fill remaining slots with good items
    const MAX_ITEMS = 4;
    const result = [...attention];
    const remaining_slots = MAX_ITEMS - result.length;
    if (remaining_slots > 0) {
      result.push(...good.slice(0, remaining_slots));
    }

    return result;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kpis, annualProgress, plan, dateRange, canShowTarget, startDate, endDate]);

  if (items.length === 0) return null;

  return (
    <div
      className="rounded-lg border px-4 py-2.5"
      data-testid="kpi-summary-banner"
    >
      <ul className="space-y-0.5" role="list">
        {items.map((item, idx) => {
          const Icon = TONE_ICON[item.tone];
          const content = (
            <>
              <Icon className={cn("h-3.5 w-3.5 shrink-0", TONE_COLOR[item.tone])} aria-hidden="true" />
              <span className={cn(
                "text-sm",
                item.tone === "attention" ? "text-foreground" : "text-muted-foreground",
              )}>
                {item.text}
              </span>
            </>
          );

          if (item.href) {
            return (
              <li key={idx}>
                <button
                  type="button"
                  onClick={() => router.push(item.href!)}
                  className="flex items-center gap-2 w-full text-left rounded-sm hover:bg-muted/50 transition-colors px-1 -mx-1"
                >
                  {content}
                </button>
              </li>
            );
          }

          return (
            <li key={idx} className="flex items-center gap-2">
              {content}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Format a number with 1 decimal, vi-VN locale */
function fmtVal(n: number): string {
  return n.toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}
