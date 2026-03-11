// src/components/officer/dashboard/KPICardsGrid.tsx
/**
 * KPI Cards Grid for Officer Dashboard
 * Tier 1: 4 compact cards (core metrics) with hover tooltips
 * Tier 2: Inline stats strip (secondary metrics) — responsive 1-col on mobile
 */

"use client";

import { useRouter } from "next/navigation";
import {
  Phone,
  Users,
  TrendingUp,
  TrendingDown,
  Minus,
  Clock,
  ShieldCheck,
  Target,
  type LucideIcon,
} from "lucide-react";
import { KPICard } from "./KPICard";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useDashboardDate, DATE_PRESET_LABELS } from "@/contexts/DashboardDateContext";

interface TrendInfo {
  value: number;
  direction: "up" | "down" | "neutral";
  comparison: string;
}

interface KPIStats {
  consultations_today: number;
  consultations_target: number;
  is_unit_target?: boolean;
  consultations_trend: TrendInfo;
  active_leads: number;
  active_leads_trend: TrendInfo;
  win_rate: number;
  win_rate_trend?: TrendInfo | null;
  new_lead_conversion_rate: number;
  new_lead_conversion_rate_trend?: TrendInfo | null;
  avg_response_time: number;
  avg_response_time_trend: TrendInfo;
  sla_compliance_rate: number;
  sla_compliance_rate_trend?: TrendInfo | null;
  consultation_effectiveness: number;
  consultation_effectiveness_trend?: TrendInfo | null;
  consultations_avg_per_day?: number;
  // Phase D: Daily Quality KPIs
  verified_consultations_daily?: number;
  quality_rate_daily?: number | null;
  followup_commitment_rate?: number | null;
  progress_rate_d7?: number | null;
  progress_rate_d7_date?: string | null;
  rollback_rate_d3?: number | null;
  rollback_rate_d3_date?: string | null;
}

interface KPICardsGridProps {
  kpis: KPIStats;
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
}

function StatItem({ icon: Icon, label, value, tooltip, trend, inverseTrend = false, onClick }: StatItemProps) {
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

export function KPICardsGrid({ kpis }: KPICardsGridProps) {
  const router = useRouter();
  const { preset, dateRange } = useDashboardDate();

  const periodLabel = DATE_PRESET_LABELS[preset] || preset;
  const goToLeads = () => router.push("/leads");

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
              onClick={goToLeads}
            />
            {kpis.is_unit_target && (
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
            onClick={goToLeads}
          />

          <KPICard
            title="Tỉ lệ chốt đơn"
            value={`${fmtPct(kpis.win_rate)}%`}
            subtitle={periodLabel}
            tooltip={TOOLTIPS.winRate}
            trend={kpis.win_rate_trend ?? undefined}
            icon={TrendingUp}
            onClick={goToLeads}
          />

          <KPICard
            title="Chuyển đổi lead mới"
            value={`${fmtPct(kpis.new_lead_conversion_rate)}%`}
            subtitle={periodLabel}
            tooltip={TOOLTIPS.conversion}
            trend={kpis.new_lead_conversion_rate_trend ?? undefined}
            icon={TrendingUp}
            onClick={goToLeads}
          />
        </div>

        {/* Tier 2: Secondary Stats Strip — single card, responsive grid */}
        <Card className="border bg-card">
          <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-border">
            <StatItem
              icon={ShieldCheck}
              label="Tuân thủ SLA"
              value={`${fmtPct(kpis.sla_compliance_rate)}%`}
              tooltip={TOOLTIPS.sla}
              trend={kpis.sla_compliance_rate_trend}
              onClick={goToLeads}
            />
            <StatItem
              icon={Target}
              label="Hiệu quả tư vấn"
              value={`${fmtPct(kpis.consultation_effectiveness)}%`}
              tooltip={TOOLTIPS.effectiveness}
              trend={kpis.consultation_effectiveness_trend}
              onClick={goToLeads}
            />
            <StatItem
              icon={Clock}
              label="Thời gian phản hồi"
              value={`${fmtHours(kpis.avg_response_time)}h`}
              tooltip={TOOLTIPS.responseTime}
              trend={kpis.avg_response_time_trend}
              inverseTrend={true}
              onClick={goToLeads}
            />
          </div>
        </Card>

        {/* Tier 3: Daily Quality KPIs (Phase D) */}
        <Card className="border bg-card">
          <div className="px-4 py-2 border-b">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Chất lượng tư vấn hôm nay
            </h4>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 divide-y sm:divide-y-0 sm:divide-x divide-border">
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
            <StatItem
              icon={TrendingUp}
              label="Tiến triển D+7"
              value={kpis.progress_rate_d7 != null ? `${fmtPct(kpis.progress_rate_d7)}%` : "N/A"}
              tooltip={`Tỷ lệ lead tiến triển trong 7 ngày${kpis.progress_rate_d7_date ? ` (dữ liệu ngày ${kpis.progress_rate_d7_date})` : ""}`}
            />
            <StatItem
              icon={TrendingDown}
              label="Tụt hạng D+3"
              value={kpis.rollback_rate_d3 != null ? `${fmtPct(kpis.rollback_rate_d3)}%` : "N/A"}
              tooltip={`Tỷ lệ lead tụt trạng thái trong 3 ngày${kpis.rollback_rate_d3_date ? ` (dữ liệu ngày ${kpis.rollback_rate_d3_date})` : ""}`}
              inverseTrend={true}
            />
          </div>
        </Card>
      </div>
    </TooltipProvider>
  );
}
