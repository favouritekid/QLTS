// src/components/officer/dashboard/KPICardsGrid.tsx
/**
 * KPI Cards Grid for Officer Dashboard
 * Tier 1: 4 compact cards (core metrics) with hover tooltips
 * Tier 2: Inline stats strip (secondary metrics) — responsive 1-col on mobile
 */

"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Phone,
  Users,
  TrendingUp,
  TrendingDown,
  Minus,
  Clock,
  GraduationCap,
  ShieldCheck,
  Target,
  Info,
  type LucideIcon,
} from "lucide-react";
import { KPICard, isTargetMet } from "./KPICard";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useDashboardDate, DATE_PRESET_LABELS } from "@/contexts/DashboardDateContext";
import { useKpiCatalog } from "@/lib/hooks/use-kpi-catalog";
import type { KPIStats, TrendInfo, DashboardScope } from "@/hooks/useDashboardStats";
import { buildDashboardDestination, type DrillDownDescriptor } from "@/lib/dashboard/buildDashboardDestination";

interface KPICardsGridProps {
  kpis: KPIStats;
  isPersonalView?: boolean;
  scope?: DashboardScope;
  officerId?: number | null;
  unitId?: number | null;
  includeDescendants?: boolean;
}

// =============================================================================
// NUMBER FORMATTING (vi-VN locale, 1 decimal)
// =============================================================================

function fmtPct(n: number): string {
  return n.toLocaleString("vi-VN", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

function fmtHours(n: number): string {
  return n.toLocaleString("vi-VN", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

// =============================================================================
// TIER 2: INLINE STAT ITEM (used inside the stats strip)
// =============================================================================

interface StatItemProps {
  icon: LucideIcon;
  label: string;
  value: string;
  tooltip?: string;
  trend?: TrendInfo | null;
  inverseTrend?: boolean;
  onClick?: () => void;
  /** Target value for comparison. Null = don't show. */
  target?: number | null;
  /** Raw numeric actual for target comparison. */
  actualValue?: number;
  /** Unit suffix for target display (default: "%") */
  targetUnit?: string;
  /** If true, actual >= target is good. Default: true */
  higherIsBetter?: boolean;
  /** If true, this metric is non-comparable (trend-only, no meaningful target). */
  trendOnly?: boolean;
}

function StatItem({ icon: Icon, label, value, tooltip, trend, inverseTrend = false, onClick, target, actualValue, targetUnit = "%", higherIsBetter = true, trendOnly = false }: StatItemProps) {
  const TrendIcon =
    trend?.direction === "up"
      ? TrendingUp
      : trend?.direction === "down"
      ? TrendingDown
      : Minus;

  const trendColor = inverseTrend
    ? (trend?.direction === "down"
        ? "text-success-600 dark:text-success-500"
        : trend?.direction === "up"
        ? "text-error-600 dark:text-error-500"
        : "text-muted-foreground")
    : (trend?.direction === "up"
        ? "text-success-600 dark:text-success-500"
        : trend?.direction === "down"
        ? "text-error-600 dark:text-error-500"
        : "text-muted-foreground");

  const inner = (
    <div className="flex items-center gap-3 py-2.5 px-3 min-w-0">
      <div className="rounded-md bg-muted p-1.5 shrink-0">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground truncate">{label}</p>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{value}</span>
          {trend && (
            <span className={cn("inline-flex items-center gap-0.5 text-xs", trendColor)}>
              <TrendIcon className="h-3 w-3" aria-hidden="true" />
              {trend.direction === "up" ? "+" : trend.direction === "down" ? "-" : ""}
              {fmtPct(Math.abs(trend.value))}%
            </span>
          )}
        </div>
        {target != null && (
          <p className={cn(
            "text-[11px] mt-0.5",
            isTargetMet(actualValue ?? Number(value.replace(/[^0-9.,-]/g, '').replace(',', '.')), target, higherIsBetter)
              ? "text-success-600 dark:text-success-500"
              : "text-warning-600 dark:text-warning-500",
          )}>
            Mục tiêu: {fmtPct(target)}{targetUnit}
          </p>
        )}
        {trendOnly && target == null && (
          <p className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-0.5">
            <Info className="h-2.5 w-2.5" />
            Xu hướng
          </p>
        )}
      </div>
    </div>
  );

  const content = onClick ? (
    <button
      type="button"
      onClick={onClick}
      className="text-left w-full rounded-md transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      aria-label={`${label}: ${value}`}
    >
      {inner}
    </button>
  ) : (
    inner
  );

  if (!tooltip) return content;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-64 text-center">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  );
}

// =============================================================================
// TOOLTIP DESCRIPTIONS (Vietnamese)
// =============================================================================

const TOOLTIPS = {
  consultations:
    "Số buổi tư vấn đã thực hiện hôm nay so với mục tiêu hàng ngày được cấu hình bởi quản lý",
  activeLeads:
    "Tổng số lead đang xử lý hiện tại (realtime, không phụ thuộc kỳ). Trend so sánh leads mới trong kỳ này vs kỳ trước",
  winRate:
    "Tỉ lệ chốt đơn thành công: số lead Thắng chia cho tổng lead đã kết thúc (Thắng + Thua) trong kỳ",
  conversion:
    "Tỉ lệ chuyển đổi lead mới: số lead được chuyển đổi thành công chia cho tổng lead mới được tạo trong kỳ",
  sla:
    "Tỉ lệ tuân thủ SLA: phần trăm lead được phản hồi đúng hạn (trong số giờ quy định). Lead chưa liên hệ quá hạn cũng bị tính vi phạm",
  effectiveness:
    "Hiệu quả tư vấn: phần trăm lead đã được tư vấn ít nhất 1 lần và kết thúc Thắng, trên tổng lead đã tư vấn và kết thúc. Chỉ tính lead đã đóng",
  responseTime:
    "Thời gian phản hồi trung bình: từ lúc lead được giao đến lần tư vấn đầu tiên. Càng thấp càng tốt",
} as const;

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function KPICardsGrid({
  kpis,
  isPersonalView = true,
  scope,
  officerId,
  unitId,
  includeDescendants = false,
}: KPICardsGridProps) {
  const router = useRouter();
  const { preset, dateRange, startDate, endDate } = useDashboardDate();
  const { canShowTarget } = useKpiCatalog();

  const periodLabel = DATE_PRESET_LABELS[preset] || preset;

  const filteredNavContext = useMemo(() => ({
    scope,
    officerId,
    unitId,
    includeDescendants,
    startDate,
    endDate,
    dateField: "created_at",
  }), [scope, officerId, unitId, includeDescendants, startDate, endDate]);

  const snapshotNavContext = useMemo(() => ({
    scope,
    officerId,
    unitId,
    includeDescendants,
  }), [scope, officerId, unitId, includeDescendants]);

  const navigateToDescriptor = (descriptor: DrillDownDescriptor | null, useFilteredContext: boolean = true) => {
    const destination = buildDashboardDestination(
      useFilteredContext ? filteredNavContext : snapshotNavContext,
      descriptor,
    );
    if (destination) {
      router.push(destination);
    }
  };

  const goActiveLeads = () => navigateToDescriptor(
    {
      target: "leads_snapshot",
      exactness: "exact",
      metric_key: "active_leads",
      filters: { status: "new,assigned,contacted,qualified" },
    },
    false,
  );

  // Detect if today falls within the selected date range
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayInRange =
    dateRange?.from && dateRange?.to &&
    today >= new Date(new Date(dateRange.from).setHours(0, 0, 0, 0)) &&
    today <= new Date(new Date(dateRange.to).setHours(23, 59, 59, 999));

  // Consultations card: show today's count or period average depending on range
  const consultationsTitle = todayInRange ? "Tư vấn hôm nay" : "TB tư vấn/ngày";
  const consultationsValue = todayInRange
    ? `${kpis.consultations_today}/${kpis.consultations_target}`
    : fmtPct(kpis.consultations_avg_per_day ?? 0);
  const consultationsSubtitle = todayInRange ? "Mục tiêu hàng ngày" : periodLabel;

  // Gap 1: Build dashboard range for catalog canShowTarget() comparison policy
  const dashboardRange = dateRange?.from && dateRange?.to
    ? { start: dateRange.from, end: dateRange.to }
    : undefined;

  // Gap 1: Use catalog comparison policy to gate target display
  const winRateTarget = canShowTarget("win_rate", dashboardRange) ? kpis.win_rate_target : null;
  const slaTarget = canShowTarget("sla_compliance_rate", dashboardRange) ? kpis.sla_compliance_rate_target : null;
  const responseTimeTarget = canShowTarget("response_time_hours", dashboardRange) ? kpis.avg_response_time_target : null;
  const enrollmentsMonthlyTarget = canShowTarget("enrollments_monthly", dashboardRange) ? kpis.enrollments_monthly_target : null;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="space-y-3">
        {/* Tier 1: Primary KPI Cards (compact) */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="relative">
            <KPICard
              title={consultationsTitle}
              value={consultationsValue}
              subtitle={consultationsSubtitle}
              tooltip={TOOLTIPS.consultations}
              trend={kpis.consultations_trend}
              icon={Phone}
            />
            {kpis.is_unit_target && todayInRange && (
              <span className="absolute bottom-1.5 left-3 text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                Chỉ tiêu tập thể phòng
              </span>
            )}
          </div>

          <KPICard
            title="Leads đang xử lý"
            value={kpis.active_leads}
            subtitle="Hiện tại"
            tooltip={TOOLTIPS.activeLeads}
            trend={kpis.active_leads_trend}
            icon={Users}
            onClick={goActiveLeads}
          />

          <KPICard
            title="Tỉ lệ chốt đơn"
            value={`${fmtPct(kpis.win_rate)}%`}
            subtitle={periodLabel}
            tooltip={TOOLTIPS.winRate}
            trend={kpis.win_rate_trend ?? undefined}
            icon={TrendingUp}
            target={winRateTarget}
            actualValue={kpis.win_rate}
          />

          <KPICard
            title="Chuyển đổi lead mới"
            value={`${fmtPct(kpis.new_lead_conversion_rate)}%`}
            subtitle={periodLabel}
            tooltip={TOOLTIPS.conversion}
            trend={kpis.new_lead_conversion_rate_trend ?? undefined}
            icon={TrendingUp}
            trendOnly={true}
          />
        </div>

        {/* Tier 2: Secondary Stats Strip — single card, responsive grid */}
        <Card className="border bg-card">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-border">
            <StatItem
              icon={ShieldCheck}
              label="Tuân thủ SLA"
              value={`${fmtPct(kpis.sla_compliance_rate)}%`}
              tooltip={TOOLTIPS.sla}
              trend={kpis.sla_compliance_rate_trend}
              target={slaTarget}
              actualValue={kpis.sla_compliance_rate}
            />
            <StatItem
              icon={Target}
              label="Hiệu quả tư vấn"
              value={`${fmtPct(kpis.consultation_effectiveness)}%`}
              tooltip={TOOLTIPS.effectiveness}
              trend={kpis.consultation_effectiveness_trend}
              trendOnly={true}
            />
            <StatItem
              icon={Clock}
              label="Thời gian phản hồi"
              value={`${fmtHours(kpis.avg_response_time)}h`}
              tooltip={TOOLTIPS.responseTime}
              trend={kpis.avg_response_time_trend}
              inverseTrend={true}
              target={responseTimeTarget}
              actualValue={kpis.avg_response_time}
              targetUnit="h"
              higherIsBetter={false}
            />
            <StatItem
              icon={GraduationCap}
              label="Nhập học"
              value={String(kpis.enrollments_monthly ?? 0)}
              tooltip="Số hồ sơ nhập học trong kỳ (final stage + positive outcome)"
              target={enrollmentsMonthlyTarget}
              actualValue={kpis.enrollments_monthly ?? 0}
            />
          </div>
        </Card>

        {/* Tier 3: Daily Quality KPIs (Phase D) — only for personal view */}
        {isPersonalView && <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Card 1: Realtime quality metrics */}
          <Card className="border bg-card">
            <div className="px-4 py-2 border-b">
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Chất lượng hôm nay
              </h4>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-border">
              <StatItem
                icon={Target}
                label="TV hợp lệ"
                value={String(kpis.verified_consultations_daily ?? 0)}
                tooltip="Số lead DISTINCT được tư vấn hợp lệ trong ngày (loại system, có pipeline update)"
              />
              <StatItem
                icon={ShieldCheck}
                label="Tỷ lệ chất lượng"
                value={kpis.quality_rate_daily != null ? `${fmtPct(kpis.quality_rate_daily)}%` : "N/A"}
                tooltip="TV hợp lệ / Tổng TV hôm nay × 100"
              />
              <StatItem
                icon={Phone}
                label="Cam kết follow-up"
                value={kpis.followup_commitment_rate != null ? `${fmtPct(kpis.followup_commitment_rate)}%` : "N/A"}
                tooltip="% tư vấn non-final có hẹn lịch follow-up"
              />
            </div>
          </Card>

          {/* Card 2: Lagged metrics with data dates */}
          <Card className="border bg-card">
            <div className="px-4 py-2 border-b">
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Kết quả trễ / hậu kiểm
              </h4>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-border">
              <div>
                <StatItem
                  icon={TrendingUp}
                  label="Tiến triển D+7"
                  value={kpis.progress_rate_d7 != null ? `${fmtPct(kpis.progress_rate_d7)}%` : "N/A"}
                  tooltip={`Tỷ lệ lead tiến triển trong 7 ngày${kpis.progress_rate_d7_date ? ` (dữ liệu ngày ${kpis.progress_rate_d7_date})` : ""}`}
                />
                {kpis.progress_rate_d7_date && (
                  <p className="text-[10px] text-muted-foreground text-center mt-[-4px] pb-1">
                    DL: {kpis.progress_rate_d7_date.slice(8, 10)}/{kpis.progress_rate_d7_date.slice(5, 7)}
                  </p>
                )}
              </div>
              <div>
                <StatItem
                  icon={TrendingDown}
                  label="Tụt hạng D+3"
                  value={kpis.rollback_rate_d3 != null ? `${fmtPct(kpis.rollback_rate_d3)}%` : "N/A"}
                  tooltip={`Tỷ lệ lead tụt trạng thái trong 3 ngày${kpis.rollback_rate_d3_date ? ` (dữ liệu ngày ${kpis.rollback_rate_d3_date})` : ""}`}
                  inverseTrend={true}
                />
                {kpis.rollback_rate_d3_date && (
                  <p className="text-[10px] text-muted-foreground text-center mt-[-4px] pb-1">
                    DL: {kpis.rollback_rate_d3_date.slice(8, 10)}/{kpis.rollback_rate_d3_date.slice(5, 7)}
                  </p>
                )}
              </div>
            </div>
          </Card>
        </div>}
      </div>
    </TooltipProvider>
  );
}
