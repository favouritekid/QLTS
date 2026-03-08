// src/components/officer/FunnelChart.tsx
/**
 * Pipeline Funnel Chart - Industrial Standard
 * Designed for management decision-making
 *
 * SPEC 2026-02-04: Funnel Calculation Logic
 * - Filter: counts_for_funnel = TRUE (excludes activity logs)
 * - Filter: stage_id IS NOT NULL (excludes universal statuses)
 * - Early Exit: FINAL leads (negative) displayed at each non-final stage
 * - Net Conversion Rate: Enrolled / (Enrolled + Lost) - strategic KPI
 *
 * Key Metrics:
 * - Won: stage = stg06 (positive outcome)
 * - Lost: outcome = negative AND counts_for_funnel = TRUE
 * - In-Progress: is_final = FALSE AND stage IN stg01–stg05
 *
 * Features:
 * - Clean, professional design (minimal colors, no excessive animations)
 * - Separate "Core Flow" stages from "Outcome" stages
 * - Early Exit badges at each stage (FINAL leads lost before reaching outcome)
 * - Net Conversion Rate as primary metric (ignores in-progress leads)
 * - Color-coded conversion indicators
 * - Actionable insights through tooltips
 * - Configurable stage IDs via props
 * - Seamless funnel geometry (each stage's bottom matches next stage's top)
 * - Improved bottleneck detection (impact = dropOff × severity)
 */
"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useDashboardDate } from "@/contexts/DashboardDateContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  Users,
  ArrowDown,
  Target,
  CheckCircle2,
  XCircle,
  PauseCircle,
  TrendingUp,
  TrendingDown,
  Clock,
  DollarSign,
  Lightbulb,
  ExternalLink
} from "lucide-react";
import type { TrendInfo } from "@/hooks/useDashboardStats";

// ============================================================================
// INTERFACES
// ============================================================================

interface OutcomeBreakdown {
  positive: number;
  negative: number;
  neutral: number;
}

/** Phase 2: Loss reason breakdown for funnel analytics */
interface LossBreakdownItem {
  reason_code: string;    // e.g., "PRICE_HIGH", "NO_CONTACT"
  count: number;          // Number of leads lost with this reason
  percentage: number;     // Percentage of total losses at this stage
}

/** Phase 2: Stage velocity statistics - time spent in each stage */
interface VelocityStats {
  avg_days: number;     // Average days spent in stage
  min_days: number;     // Minimum days
  max_days: number;     // Maximum days
  sample_size: number;  // Number of transitions measured
}

/** Phase 2: Estimated lost revenue for funnel analytics */
interface EstimatedLostRevenue {
  lost_leads_count: number;     // Number of leads lost at this stage
  avg_tuition: number;          // Average tuition fee (VND)
  total_lost_revenue: number;   // Total lost revenue = lost_leads × avg_tuition
  leads_with_tuition: number;   // Leads that have offering with tuition data
}

/** Format VND currency (compact format for display) */
const formatVND = (amount: number): string => {
  if (amount >= 1_000_000_000) {
    return `${(amount / 1_000_000_000).toFixed(1)}B`;
  }
  if (amount >= 1_000_000) {
    return `${(amount / 1_000_000).toFixed(0)}M`;
  }
  if (amount >= 1_000) {
    return `${(amount / 1_000).toFixed(0)}K`;
  }
  return amount.toFixed(0);
};

/** Format VND currency (full format with thousands separators) */
const formatVNDFull = (amount: number): string => {
  return new Intl.NumberFormat('vi-VN').format(amount) + ' ₫';
};

/** Map loss reason codes to human-readable labels (Vietnamese) */
const LOSS_REASON_LABELS: Record<string, { label: string; icon: string }> = {
  PRICE_HIGH: { label: "Học phí", icon: "💰" },
  LOCATION_FAR: { label: "Xa nhà", icon: "📍" },
  CHOSE_COMPETITOR: { label: "Trường khác", icon: "🎓" },
  NO_CONTACT: { label: "K.liên lạc", icon: "📞" },
  TIMING_BAD: { label: "Chưa sẵn sàng", icon: "⏰" },
  OTHER: { label: "Khác", icon: "❓" },
};

interface FunnelStage {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  lead_count: number;
  is_final_stage?: boolean;
  conversion_rate?: number | null;  // Historical conversion % (30 days)
  outcome_breakdown?: OutcomeBreakdown;  // positive/negative/neutral counts
  // SPEC 2026-02-04: Early Exit metrics
  early_exit_count?: number;  // FINAL leads (negative) at this stage
  move_forward?: number;      // lead_count - early_exit_count
  // Phase 2: Loss reason breakdown
  loss_breakdown?: LossBreakdownItem[] | null;  // Loss reasons for this stage
  // Phase 2: Velocity - time spent in stage
  velocity?: VelocityStats | null;
  // Phase 2: Estimated lost revenue
  estimated_lost_revenue?: EstimatedLostRevenue | null;
}

/** Phase 2: AI-powered suggestion for funnel optimization */
interface FunnelSuggestion {
  id: string;                          // Unique suggestion ID
  type: "bottleneck" | "slow_stage" | "high_loss" | "loss_reason";
  priority: "critical" | "high" | "medium" | "low";
  stage_id?: string | null;            // Related stage (if applicable)
  stage_name?: string | null;          // Stage name for display
  title: string;                       // Short title
  description: string;                 // Detailed description
  metric_value?: number | null;        // The metric that triggered this suggestion
  metric_label?: string | null;        // Label for the metric
  action_label?: string | null;        // Suggested action button label
  action_url?: string | null;          // URL for the action
}

/** Map suggestion type to icon and color */
const SUGGESTION_STYLES: Record<FunnelSuggestion["type"], { icon: string; color: string; bgColor: string }> = {
  bottleneck: { icon: "🚧", color: "text-error-600", bgColor: "bg-error-50 dark:bg-error-950/30" },
  slow_stage: { icon: "🐢", color: "text-amber-600", bgColor: "bg-amber-50 dark:bg-amber-950/30" },
  high_loss: { icon: "💸", color: "text-rose-600", bgColor: "bg-rose-50 dark:bg-rose-950/30" },
  loss_reason: { icon: "📊", color: "text-blue-600", bgColor: "bg-blue-50 dark:bg-blue-950/30" },
};

/** Map priority to badge variant */
const PRIORITY_STYLES: Record<FunnelSuggestion["priority"], { label: string; color: string }> = {
  critical: { label: "Cấp bách", color: "bg-error-500 text-white" },
  high: { label: "Cao", color: "bg-warning-500 text-white" },
  medium: { label: "TB", color: "bg-blue-500 text-white" },
  low: { label: "Thấp", color: "bg-muted text-muted-foreground" },
};

// Funnel configuration interface - allows customization via props
interface FunnelConfig {
  positiveStageIds: string[];  // Stage IDs considered as positive outcome
  negativeStageIds: string[];  // Stage IDs considered as negative outcome
  bottleneckThreshold: number; // Conversion rate below this triggers bottleneck warning
}

// Default configuration - uses actual stage IDs from database seed
// See: Backend_FastAPI/csv_data/pipeline_stage.csv
const DEFAULT_CONFIG: FunnelConfig = {
  positiveStageIds: ["stg06"],  // "Đã nhập học" - enrolled successfully
  negativeStageIds: ["stg07"],  // "Không đi học" - did not enroll
  bottleneckThreshold: 50,
};

/**
 * Auto-detect if a final stage is positive or negative based on:
 * 1. Configured stage IDs
 * 2. Stage name heuristics (Vietnamese keywords)
 * 3. Outcome breakdown statistics
 */
const isPositiveOutcome = (stage: FunnelStage, config: FunnelConfig): boolean => {
  // 1. Check configured IDs first
  if (config.positiveStageIds.includes(stage.stage_id)) return true;
  if (config.negativeStageIds.includes(stage.stage_id)) return false;

  // 2. Heuristics based on Vietnamese stage names
  const nameLower = stage.stage_name.toLowerCase();
  if (nameLower.includes("nhập học") || nameLower.includes("hoàn thành") || nameLower.includes("thành công")) {
    return true;
  }
  if (nameLower.includes("không") || nameLower.includes("từ chối") || nameLower.includes("hủy")) {
    return false;
  }

  // 3. Fallback: Check outcome breakdown if available
  if (stage.outcome_breakdown) {
    const { positive, negative } = stage.outcome_breakdown;
    if (positive > negative) return true;
    if (negative > positive) return false;
  }

  // Default: Unknown final stage treated as neutral (neither positive nor negative)
  return false;
};

const isNegativeOutcome = (stage: FunnelStage, config: FunnelConfig): boolean => {
  // 1. Check configured IDs first
  if (config.negativeStageIds.includes(stage.stage_id)) return true;
  if (config.positiveStageIds.includes(stage.stage_id)) return false;

  // 2. Heuristics based on Vietnamese stage names
  const nameLower = stage.stage_name.toLowerCase();
  if (nameLower.includes("không") || nameLower.includes("từ chối") || nameLower.includes("hủy") || nameLower.includes("thất bại")) {
    return true;
  }
  if (nameLower.includes("nhập học") || nameLower.includes("hoàn thành") || nameLower.includes("thành công")) {
    return false;
  }

  // 3. Fallback: Check outcome breakdown if available
  if (stage.outcome_breakdown) {
    const { positive, negative } = stage.outcome_breakdown;
    if (negative > positive) return true;
  }

  return false;
};

interface FunnelChartProps {
  funnel: FunnelStage[];
  /** Net Conversion Rate trend vs previous period */
  netConversionTrend?: TrendInfo | null;
  /** Optional configuration to override defaults */
  config?: Partial<FunnelConfig>;
  /** Scope filter for navigation context */
  scope?: "personal" | "team" | "organization";
  /** Selected unit ID (for organization scope) */
  unitId?: number | null;
  /** Selected officer ID (for drill-down) */
  officerId?: number | null;
  /** Phase 2: AI-powered funnel suggestions */
  suggestions?: FunnelSuggestion[];
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

// Gradient palette - smooth transition from purple to cyan
const FUNNEL_GRADIENT = {
  startHue: 260,   // Purple
  endHue: 200,     // Cyan/Blue
  saturation: 70,
  lightness: 55,
};

// Get stage background color (smooth gradient based on position)
const getStageColor = (index: number, total: number, isFinal: boolean) => {
  if (isFinal) return "hsl(220 15% 50%)"; // Muted gray for final stages
  
  // Interpolate hue from purple to cyan
  const { startHue, endHue, saturation, lightness } = FUNNEL_GRADIENT;
  const progress = total > 1 ? index / (total - 1) : 0;
  const hue = startHue + (endHue - startHue) * progress;
  
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
};

// Determine text color based on background lightness for contrast
const getContrastTextColor = (stageColor: string): string => {
  // Parse HSL and check lightness
  const match = stageColor.match(/hsl\((\d+)\s+(\d+)%\s+(\d+)%\)/);
  if (match) {
    const lightness = parseInt(match[3]);
    return lightness > 60 ? 'text-foreground' : 'text-white';
  }
  return 'text-white'; // Default fallback
};

// Helper to calculate seamless funnel clip-path
// Makes each stage's bottom match the next stage's top
const getFunnelShape = (index: number, totalStages: number) => {
  const MAX_WIDTH = 100; // Starting width (100%)
  const MIN_WIDTH = 40;  // Final bottom width (40%)
  
  // Calculate step reduction to distribute evenly from 100% to 40%
  const stepReduction = (MAX_WIDTH - MIN_WIDTH) / totalStages;

  // Calculate top and bottom width for current stage
  const topWidth = MAX_WIDTH - (index * stepReduction);
  const bottomWidth = MAX_WIDTH - ((index + 1) * stepReduction);

  // Calculate inset from both sides
  const insetTop = (100 - topWidth) / 2;
  const insetBottom = (100 - bottomWidth) / 2;

  return {
    clipPath: `polygon(${insetTop}% 0%, ${100 - insetTop}% 0%, ${100 - insetBottom}% 100%, ${insetBottom}% 100%)`,
  };
};

// Get conversion rate status and color
const getConversionStatus = (rate: number | null): { 
  color: string; 
  textColor: string;
  borderColor: string;
  status: "good" | "warning" | "critical" | "neutral";
  label: string;
} => {
  if (rate === null) return {
    color: "bg-muted/30",
    textColor: "text-muted-foreground",
    borderColor: "border-muted",
    status: "neutral",
    label: "Chưa có dữ liệu"
  };
  if (rate >= 70) return {
    color: "bg-success-50 dark:bg-success-950/20",
    textColor: "text-success-700 dark:text-success-400",
    borderColor: "border-success-200 dark:border-success-800",
    status: "good",
    label: "Tốt"
  };
  if (rate >= 50) return {
    color: "bg-warning-50 dark:bg-warning-950/20",
    textColor: "text-warning-700 dark:text-warning-400",
    borderColor: "border-warning-200 dark:border-warning-800",
    status: "warning",
    label: "Theo dõi"
  };
  return {
    color: "bg-error-50 dark:bg-error-950/20",
    textColor: "text-error-700 dark:text-error-400",
    borderColor: "border-error-200 dark:border-error-800",
    status: "critical",
    label: "Cần hành động"
  };
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function FunnelChart({
  funnel,
  netConversionTrend,
  config,
  scope,
  unitId,
  officerId,
  suggestions = [],
}: FunnelChartProps) {
  const router = useRouter();
  const { startDate, endDate } = useDashboardDate();

  // Merge user config with defaults — memoize to stabilize references
  const mergedConfig: FunnelConfig = useMemo(() => ({
    ...DEFAULT_CONFIG,
    ...config,
  }), [config]);

  // Get all outcome stage IDs — memoize to prevent useMemo invalidation downstream
  const outcomeStageIds = useMemo(
    () => [...mergedConfig.positiveStageIds, ...mergedConfig.negativeStageIds],
    [mergedConfig]
  );

  // =========== EMPTY STATE HANDLING ===========
  if (!funnel || funnel.length === 0) {
    return (
      <Card className="border bg-card min-h-[300px] flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <Target className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Chưa có dữ liệu Pipeline</p>
        </div>
      </Card>
    );
  }

  // =========== MEMOIZED COMPUTATIONS ===========
  // All heavy data transformations memoized with `funnel` dependency

  // Sort by stage order
  const sortedFunnel = useMemo(
    () => [...funnel].sort((a, b) => a.stage_order - b.stage_order),
    [funnel]
  );

  // Separate core flow stages from outcome stages (using configurable IDs)
  const { coreStages, outcomeStages } = useMemo(() => ({
    coreStages: sortedFunnel.filter(s =>
      !s.is_final_stage && !outcomeStageIds.includes(s.stage_id)
    ),
    outcomeStages: sortedFunnel.filter(s =>
      s.is_final_stage || outcomeStageIds.includes(s.stage_id)
    ),
  }), [sortedFunnel, outcomeStageIds]);

  // Calculate total leads by summing all stages (core + outcome)
  // This is correct for ACTUAL count approach (not cumulative)
  const totalLeads = useMemo(
    () => sortedFunnel.reduce((sum, s) => sum + s.lead_count, 0),
    [sortedFunnel]
  );

  // Memoize all derived metrics together to avoid redundant computation
  const {
    totalEarlyExit, enrolledCount, failedCount, totalLost,
    netConversionRate, overallConversion, stageMetrics, bottleneckIndex,
    aggregatedLossBreakdown, totalLostRevenue
  } = useMemo(() => {
    // SPEC 2026-02-04: Calculate Early Exit total (FINAL leads at non-final stages)
    const _totalEarlyExit = coreStages.reduce((sum, s) =>
      sum + (s.early_exit_count || 0), 0
    );

    // SPEC 2026-02-04: Calculate Lost total (early exits + negative outcomes at final stages)
    const positiveStages = outcomeStages.filter(s => isPositiveOutcome(s, mergedConfig));
    const negativeStages = outcomeStages.filter(s => isNegativeOutcome(s, mergedConfig));
    const _enrolledCount = positiveStages.reduce((sum, s) => sum + s.lead_count, 0);
    const _failedCount = negativeStages.reduce((sum, s) => sum + s.lead_count, 0);

    // Total Lost = Early Exits + Failed at final stage
    const _totalLost = _totalEarlyExit + _failedCount;

    // SPEC 2026-02-04: Net Conversion Rate = Enrolled / (Enrolled + Lost)
    const _netConversionRate = (_enrolledCount + _totalLost) > 0
      ? (_enrolledCount / (_enrolledCount + _totalLost)) * 100
      : 0;

    // Gross conversion (for display/comparison)
    const completedCount = _enrolledCount + _failedCount;
    const _overallConversion = totalLeads > 0 ? (completedCount / totalLeads) * 100 : 0;

    // Calculate metrics for each stage
    const _stageMetrics = coreStages.map((stage, index) => {
      const percentFromTotal = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
      const historicalConversion = stage.conversion_rate;
      const hasHistoricalData = historicalConversion !== null && historicalConversion !== undefined;

      if (index === 0) {
        return {
          conversion: hasHistoricalData ? historicalConversion : null,
          countDiff: 0,
          countDiffPercent: 0,
          percentFromTotal,
          prevCount: stage.lead_count,
          hasHistoricalData
        };
      }

      const prevCount = coreStages[index - 1].lead_count;
      const conversion = hasHistoricalData ? historicalConversion : null;
      const countDiff = Math.max(0, prevCount - stage.lead_count);
      const countDiffPercent = prevCount > 0 ? (countDiff / prevCount) * 100 : 0;

      return { conversion, countDiff, countDiffPercent, percentFromTotal, prevCount, hasHistoricalData };
    });

    // Bottleneck detection
    let maxImpact = -1;
    let _bottleneckIndex = -1;
    _stageMetrics.forEach((metric, idx) => {
      if (idx === 0 || metric.conversion === null) return;
      if (metric.conversion >= mergedConfig.bottleneckThreshold) return;
      const severity = (100 - metric.conversion) / 100;
      const impact = metric.countDiff * severity;
      if (impact > maxImpact) {
        maxImpact = impact;
        _bottleneckIndex = idx;
      }
    });

    // Phase 2: Aggregate loss breakdown across all stages
    const breakdown: Record<string, number> = {};
    let totalLossReasons = 0;
    sortedFunnel.forEach(stage => {
      if (stage.loss_breakdown) {
        stage.loss_breakdown.forEach(item => {
          breakdown[item.reason_code] = (breakdown[item.reason_code] || 0) + item.count;
          totalLossReasons += item.count;
        });
      }
    });
    const _aggregatedLossBreakdown = Object.entries(breakdown)
      .map(([reason_code, count]) => ({
        reason_code,
        count,
        percentage: totalLossReasons > 0 ? Math.round((count / totalLossReasons) * 100 * 10) / 10 : 0,
      }))
      .sort((a, b) => b.count - a.count);

    // Phase 2: Calculate total lost revenue across all stages
    const _totalLostRevenue = sortedFunnel.reduce((sum, stage) => {
      return sum + (stage.estimated_lost_revenue?.total_lost_revenue || 0);
    }, 0);

    return {
      totalEarlyExit: _totalEarlyExit,
      enrolledCount: _enrolledCount,
      failedCount: _failedCount,
      totalLost: _totalLost,
      netConversionRate: _netConversionRate,
      overallConversion: _overallConversion,
      stageMetrics: _stageMetrics,
      bottleneckIndex: _bottleneckIndex,
      aggregatedLossBreakdown: _aggregatedLossBreakdown,
      totalLostRevenue: _totalLostRevenue,
    };
  }, [coreStages, outcomeStages, sortedFunnel, totalLeads, mergedConfig]);

  // Navigate to leads filtered by stage, preserving date and scope context
  const handleStageClick = (stageId: string) => {
    const params = new URLSearchParams();
    params.set("stage", stageId);

    // Include date range from global filter
    if (startDate) params.set("from", startDate);
    if (endDate) params.set("to", endDate);

    // Include scope filters for drill-down context
    if (officerId) {
      params.set("officer", officerId.toString());
    } else if (scope === "team" && unitId) {
      params.set("unit_id", unitId.toString());
    } else if (scope === "organization" && unitId) {
      params.set("unit_id", unitId.toString());
    }

    router.push(`/leads?${params.toString()}`);
  };

  return (
    <TooltipProvider delayDuration={150}>
      <Card className="border bg-card">
        {/* Header */}
        <CardHeader className="pb-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-semibold">
              Phễu Pipeline
            </CardTitle>

            {/* SPEC 2026-02-04: Net Conversion as primary metric */}
            <div className="flex items-center gap-3">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2 cursor-help">
                    <span className="text-sm text-muted-foreground">Chuyển đổi ròng:</span>
                    <span className={cn(
                      "text-lg font-bold",
                      netConversionRate >= 50 ? "text-success-600" :
                      netConversionRate >= 30 ? "text-warning-600" : "text-error-600"
                    )}>
                      {netConversionRate.toFixed(1)}%
                    </span>
                    {netConversionTrend && netConversionTrend.direction !== "neutral" && (
                      <div className={cn(
                        "flex items-center gap-0.5 text-xs",
                        netConversionTrend.direction === "up" ? "text-success-600" : "text-error-600"
                      )}>
                        {netConversionTrend.direction === "up"
                          ? <TrendingUp className="h-3 w-3" />
                          : <TrendingDown className="h-3 w-3" />}
                        <span>
                          {netConversionTrend.direction === "up" ? "+" : "-"}
                          {netConversionTrend.value.toFixed(1)}%
                        </span>
                      </div>
                    )}
                  </div>
                </TooltipTrigger>
                <TooltipContent className="max-w-[280px]">
                  <div className="text-xs space-y-1.5">
                    <p className="font-medium border-b border-white/20 pb-1">
                      Tỷ lệ chuyển đổi ròng (KPI chiến lược)
                    </p>
                    <p className="text-white/90">
                      <span className="font-semibold text-success-300">{enrolledCount}</span> enrolled /
                      (<span className="text-success-300">{enrolledCount}</span> + <span className="text-error-300">{totalLost}</span>) =
                      <span className="font-bold ml-1">{netConversionRate.toFixed(1)}%</span>
                    </p>
                    <p className="text-white/60 text-[10px]">
                      • Won (Enrolled): {enrolledCount}
                      <br />• Lost (Early Exit + Failed): {totalLost}
                      {totalEarlyExit > 0 && (
                        <span className="block pl-2">└ Early Exit: {totalEarlyExit}</span>
                      )}
                      {failedCount > 0 && (
                        <span className="block pl-2">└ Failed: {failedCount}</span>
                      )}
                    </p>
                    {netConversionTrend && (
                      <p className="text-white/70 pt-1 border-t border-white/20">
                        So với kỳ trước: {netConversionTrend.direction === "up" ? "+" : netConversionTrend.direction === "down" ? "-" : ""}
                        {netConversionTrend.value.toFixed(1)}%
                        <span className="text-white/50 ml-1">({netConversionTrend.comparison})</span>
                      </p>
                    )}
                    <p className="text-white/40 text-[9px] italic border-t border-white/20 pt-1">
                      * Không tính leads đang xử lý, phản ánh chất lượng đầu vào + quy trình
                    </p>
                  </div>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* === CORE FUNNEL FLOW === */}
          <div className="space-y-1.5">
            {coreStages.map((stage, index) => {
              const metrics = stageMetrics[index];
              const isBottleneck = index === bottleneckIndex && metrics.conversion !== null && metrics.conversion < mergedConfig.bottleneckThreshold;
              const conversionStatus = getConversionStatus(metrics.conversion);
              const stageColor = getStageColor(index, coreStages.length, false);
              const textColorClass = getContrastTextColor(stageColor);
              
              // Get seamless funnel shape
              const shapeStyle = getFunnelShape(index, coreStages.length);

              return (
                <div key={stage.stage_id} className="flex flex-col items-center">
                  {/* Conversion Indicator (between stages) */}
                  {index > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div 
                          className={cn(
                            "flex items-center gap-2 py-1 px-2 my-0.5 cursor-help transition-colors",
                            isBottleneck && "ring-1 ring-error-400 rounded"
                          )}
                        >
                          <ArrowDown className={cn("h-3 w-3", conversionStatus.textColor)} />
                          <span className={cn("text-xs font-semibold tabular-nums", conversionStatus.textColor)}>
                            {metrics.conversion !== null ? `${metrics.conversion.toFixed(0)}%` : "N/A"}
                          </span>
                          {metrics.countDiff > 0 && (
                            <span className="text-xs text-muted-foreground tabular-nums">
                              Δ{metrics.countDiff}
                            </span>
                          )}
                          {isBottleneck && (
                            <AlertTriangle className="h-3 w-3 text-error-500" />
                          )}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="right" className="max-w-[280px]">
                        <div className="text-xs space-y-1.5">
                          <p className="font-medium border-b border-white/20 pb-1">
                            {coreStages[index - 1].stage_name} → {stage.stage_name}
                          </p>
                          
                          {/* Historical Conversion Rate */}
                          <div className="space-y-0.5">
                            <p className="text-white/90">
                              <span className="font-medium text-white">Tỷ lệ chuyển đổi (30 ngày gần nhất):</span>
                              {" "}
                              {metrics.conversion !== null
                                ? <span className={cn("font-bold",
                                    metrics.conversion >= 70 ? "text-success-300" :
                                    metrics.conversion >= 50 ? "text-warning-300" : "text-error-300"
                                  )}>{metrics.conversion.toFixed(0)}%</span>
                                : <span className="text-white/50">Chưa có dữ liệu</span>
                              }
                            </p>
                            <p className="text-white/50 text-[10px] italic">
                              {`% leads đã tiến lên stage tiếp theo trong 30 ngày gần nhất (cố định, không theo bộ lọc ngày)`}
                            </p>
                          </div>
                          
                          {/* Current Distribution */}
                          <div className="space-y-0.5 pt-1 border-t border-white/20">
                            <p className="text-white/90">
                              <span className="font-medium text-white">Phân bố hiện tại:</span>
                            </p>
                            <p className="text-white/70 pl-2">
                              {`• "${coreStages[index - 1].stage_name}": ${metrics.prevCount} leads`}
                            </p>
                            <p className="text-white/70 pl-2">
                              {`• "${stage.stage_name}": ${stage.lead_count} leads`}
                            </p>
                            {metrics.countDiff > 0 && (
                              <p className="text-white/50 pl-2 text-[10px]">
                                • Chênh lệch số lượng: Δ{metrics.countDiff} ({metrics.countDiffPercent.toFixed(0)}%)
                              </p>
                            )}
                            <p className="text-white/40 text-[9px] italic mt-1">
                              * Chênh lệch ≠ drop-off thực tế (chỉ là hiệu số lượng hiện tại)
                            </p>
                          </div>
                          
                          {/* Status */}
                          <p className={cn("font-medium pt-1 border-t border-white/20",
                            metrics.conversion !== null && metrics.conversion >= 70 ? "text-success-300" :
                            metrics.conversion !== null && metrics.conversion >= 50 ? "text-warning-300" : "text-error-300"
                          )}>
                            Đánh giá: {conversionStatus.label}
                          </p>
                          
                          {isBottleneck && (
                            <p className="text-error-300 font-medium bg-error-500/30 p-1.5 rounded">
                              ⚠️ Điểm nghẽn chính - cần review quy trình
                            </p>
                          )}
                        </div>
                      </TooltipContent>
                    </Tooltip>
                  )}

                  {/* Stage Row: Label | Bar | Count */}
                  <div className="flex items-center w-full gap-3">
                    {/* Left: Stage name */}
                    <div className="w-28 shrink-0 text-right">
                      <span className="text-sm font-medium text-foreground truncate">
                        {stage.stage_name}
                      </span>
                    </div>

                    {/* Center: Seamless Funnel Bar */}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          className={cn(
                            "relative group transition-colors duration-200 hover:brightness-110 h-14 w-full flex-1",
                            isBottleneck && "ring-2 ring-error-400/50 ring-offset-1"
                          )}
                          onClick={() => handleStageClick(stage.stage_id)}
                        >
                          {/* Background layer with clip-path */}
                          <div 
                            className="absolute inset-0 shadow-sm transition-colors hover:shadow-lg"
                            style={{
                              backgroundColor: stageColor,
                              clipPath: shapeStyle.clipPath,
                            }}
                          />
                          
                          {/* Content layer */}
                          <div className="relative z-10 flex items-center justify-center h-full">
                            <span className={cn(
                              "text-lg font-bold tabular-nums drop-shadow-md",
                              textColorClass
                            )}>
                              {metrics.percentFromTotal.toFixed(1)}%
                            </span>
                          </div>
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-[200px]">
                        <div className="text-xs space-y-1">
                          <p className="font-medium">{stage.stage_name}: {stage.lead_count} leads</p>
                          {stage.outcome_breakdown && (
                            <div className="flex gap-3 text-muted-foreground">
                              <span className="text-success-600">+{stage.outcome_breakdown.positive}</span>
                              <span className="text-error-500">−{stage.outcome_breakdown.negative}</span>
                              <span>○{stage.outcome_breakdown.neutral}</span>
                            </div>
                          )}
                          <p className="text-muted-foreground pt-1 border-t">Click để xem danh sách</p>
                        </div>
                      </TooltipContent>
                    </Tooltip>

                    {/* Right: Detailed metrics breakdown */}
                    <div className="w-40 shrink-0">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex flex-col items-end cursor-help text-xs">
                            {/* Entered (total at stage) */}
                            <div className="flex items-center gap-1">
                              <span className="text-muted-foreground">Đầu vào:</span>
                              <span className="font-bold tabular-nums text-foreground">
                                {stage.lead_count}
                              </span>
                            </div>
                            {/* Move Forward (continues to next stage) */}
                            {(stage.move_forward !== undefined || stage.early_exit_count !== undefined) && (
                              <div className="flex items-center gap-1 text-success-600">
                                <ArrowDown className="h-3 w-3" />
                                <span className="tabular-nums font-medium">
                                  {stage.move_forward ?? (stage.lead_count - (stage.early_exit_count || 0))}
                                </span>
                              </div>
                            )}
                            {/* Early Exit */}
                            {stage.early_exit_count !== undefined && stage.early_exit_count > 0 && (
                              <div className="flex items-center gap-1 text-error-500">
                                <XCircle className="h-3 w-3" />
                                <span className="tabular-nums font-medium">
                                  {stage.early_exit_count}
                                </span>
                              </div>
                            )}
                            {/* Phase 2: Velocity - Time in Stage */}
                            {stage.velocity && stage.velocity.sample_size > 0 && (
                              <div className="flex items-center gap-1 text-cyan-600 dark:text-cyan-400">
                                <Clock className="h-3 w-3" />
                                <span className="tabular-nums font-medium">
                                  {stage.velocity.avg_days.toFixed(1)}d
                                </span>
                              </div>
                            )}
                            {/* Phase 2: Estimated Lost Revenue */}
                            {stage.estimated_lost_revenue && stage.estimated_lost_revenue.total_lost_revenue > 0 && (
                              <div className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                                <DollarSign className="h-3 w-3" />
                                <span className="tabular-nums font-medium">
                                  {formatVND(stage.estimated_lost_revenue.total_lost_revenue)}
                                </span>
                              </div>
                            )}
                          </div>
                        </TooltipTrigger>
                        <TooltipContent side="left" className="max-w-[240px]">
                          <div className="text-xs space-y-1.5">
                            <p className="font-medium border-b border-white/20 pb-1">
                              {stage.stage_name}
                            </p>
                            <div className="space-y-1">
                              <p className="text-white/90">
                                <span className="text-white/60">Đầu vào:</span>{" "}
                                <span className="font-semibold">{stage.lead_count}</span> leads
                              </p>
                              {(stage.move_forward !== undefined || stage.early_exit_count !== undefined) && (
                                <p className="text-success-300">
                                  <span className="text-white/60">→ Tiến lên:</span>{" "}
                                  <span className="font-semibold">
                                    {stage.move_forward ?? (stage.lead_count - (stage.early_exit_count || 0))}
                                  </span>
                                </p>
                              )}
                              {/* Phase 2: Velocity - Time in Stage */}
                              {stage.velocity && stage.velocity.sample_size > 0 && (
                                <div className="text-cyan-300 pt-1 border-t border-white/10">
                                  <p className="flex items-center gap-1">
                                    <Clock className="h-3 w-3" />
                                    <span className="text-white/60">Thời gian TB:</span>{" "}
                                    <span className="font-semibold">
                                      {stage.velocity.avg_days.toFixed(1)} ngày
                                    </span>
                                  </p>
                                  <p className="text-white/50 text-[10px] pl-4">
                                    Min: {stage.velocity.min_days.toFixed(1)}d | Max: {stage.velocity.max_days.toFixed(1)}d
                                    <br />
                                    (n={stage.velocity.sample_size} transitions)
                                  </p>
                                </div>
                              )}
                              {/* Phase 2: Estimated Lost Revenue */}
                              {stage.estimated_lost_revenue && stage.estimated_lost_revenue.total_lost_revenue > 0 && (
                                <div className="text-amber-300 pt-1 border-t border-white/10">
                                  <p className="flex items-center gap-1">
                                    <DollarSign className="h-3 w-3" />
                                    <span className="text-white/60">Doanh thu mất:</span>{" "}
                                    <span className="font-semibold">
                                      {formatVNDFull(stage.estimated_lost_revenue.total_lost_revenue)}
                                    </span>
                                  </p>
                                  <p className="text-white/50 text-[10px] pl-4">
                                    {stage.estimated_lost_revenue.lost_leads_count} leads ×{" "}
                                    {formatVND(stage.estimated_lost_revenue.avg_tuition)} TB
                                    {stage.estimated_lost_revenue.leads_with_tuition < stage.estimated_lost_revenue.lost_leads_count && (
                                      <>
                                        <br />
                                        ({stage.estimated_lost_revenue.leads_with_tuition}/{stage.estimated_lost_revenue.lost_leads_count} có dữ liệu học phí)
                                      </>
                                    )}
                                  </p>
                                </div>
                              )}
                              {stage.early_exit_count !== undefined && stage.early_exit_count > 0 && (
                                <div className="text-error-300">
                                  <p>
                                    <span className="text-white/60">✖ Rời bỏ:</span>{" "}
                                    <span className="font-semibold">{stage.early_exit_count}</span>
                                    <span className="text-white/50 text-[10px] ml-1">
                                      (leads kết thúc tại đây)
                                    </span>
                                  </p>
                                  {/* Phase 2: Loss Breakdown */}
                                  {stage.loss_breakdown && stage.loss_breakdown.length > 0 && (
                                    <div className="mt-1.5 pt-1.5 border-t border-white/10 space-y-0.5">
                                      <p className="text-white/60 text-[10px]">Lý do:</p>
                                      {stage.loss_breakdown.slice(0, 4).map((item) => {
                                        const reasonInfo = LOSS_REASON_LABELS[item.reason_code] || {
                                          label: item.reason_code,
                                          icon: "•"
                                        };
                                        return (
                                          <p key={item.reason_code} className="text-white/80 text-[10px] pl-2">
                                            {reasonInfo.icon} {reasonInfo.label}: {item.count} ({item.percentage}%)
                                          </p>
                                        );
                                      })}
                                      {stage.loss_breakdown.length > 4 && (
                                        <p className="text-white/50 text-[10px] pl-2">
                                          +{stage.loss_breakdown.length - 4} lý do khác
                                        </p>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                            <p className="text-white/50 pt-1 border-t border-white/20 text-[10px]">
                              Click để xem danh sách chi tiết
                            </p>
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* === OUTCOME SECTION === */}
          {outcomeStages.length > 0 && (
            <div className="pt-4 border-t">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">
                Kết quả
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {outcomeStages.map(stage => {
                  const isPositive = isPositiveOutcome(stage, mergedConfig);
                  const isNegative = isNegativeOutcome(stage, mergedConfig);
                  const percent = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
                  
                  return (
                    <Tooltip key={stage.stage_id}>
                      <TooltipTrigger asChild>
                        <button
                          onClick={() => handleStageClick(stage.stage_id)}
                          className={cn(
                            "flex items-center gap-2 p-3 rounded-lg border transition-colors text-left",
                            "hover:bg-accent/50",
                            isPositive && "border-success-200 bg-success-50/50 dark:border-success-800 dark:bg-success-950/20",
                            isNegative && "border-error-200 bg-error-50/50 dark:border-error-800 dark:bg-error-950/20",
                            !isPositive && !isNegative && "border-border bg-muted/50 dark:border-border dark:bg-muted/20"
                          )}
                        >
                          {isPositive ? (
                            <CheckCircle2 className="h-4 w-4 text-success-600 shrink-0" />
                          ) : isNegative ? (
                            <XCircle className="h-4 w-4 text-error-500 shrink-0" />
                          ) : (
                            <PauseCircle className="h-4 w-4 text-muted-foreground shrink-0" />
                          )}
                          <div className="flex-1 min-w-0">
                            <p className="text-xs text-muted-foreground truncate">
                              {stage.stage_name}
                            </p>
                            <p className={cn(
                              "text-sm font-semibold tabular-nums",
                              isPositive && "text-success-700 dark:text-success-400",
                              isNegative && "text-error-600 dark:text-error-400"
                            )}>
                              {stage.lead_count} <span className="font-normal text-xs">({percent.toFixed(1)}%)</span>
                            </p>
                          </div>
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="text-xs">Click để xem danh sách {stage.lead_count} leads</p>
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            </div>
          )}

          {/* === SUMMARY === */}
          <div className="pt-3 border-t space-y-2">
            {/* Row 1: Total Leads & Net Conversion */}
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5" />
                <span>Tổng đầu vào: <strong className="text-foreground">{totalLeads}</strong></span>
              </div>
              {/* SPEC 2026-02-04: Net Conversion Rate for strategic reporting */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-1.5 cursor-help">
                    <Target className="h-3.5 w-3.5" />
                    <span>Chuyển đổi ròng: </span>
                    <strong className={cn(
                      netConversionRate >= 50 ? "text-success-600" :
                      netConversionRate >= 30 ? "text-warning-600" : "text-error-600"
                    )}>
                      {netConversionRate.toFixed(1)}%
                    </strong>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[240px]">
                  <div className="text-xs space-y-1">
                    <p className="font-medium">Tỷ lệ chuyển đổi ròng</p>
                    <p className="text-white/80">
                      {enrolledCount} / ({enrolledCount} + {totalLost}) = {netConversionRate.toFixed(1)}%
                    </p>
                    <p className="text-white/60 text-[10px]">
                      Công thức: Enrolled / (Enrolled + Lost)
                      <br />• Enrolled: {enrolledCount} leads
                      <br />• Lost (Early Exit + Failed): {totalLost} leads
                    </p>
                    <p className="text-white/50 text-[10px] italic border-t border-white/20 pt-1 mt-1">
                      * Không tính leads đang xử lý (In-Progress)
                    </p>
                  </div>
                </TooltipContent>
              </Tooltip>
            </div>
            {/* Row 2: Early Exit & Lost breakdown */}
            {totalLost > 0 && (
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-3">
                  {totalEarlyExit > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-1 text-error-500 cursor-help">
                          <XCircle className="h-3 w-3" />
                          <span>Early Exit: {totalEarlyExit}</span>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="text-xs">
                          {totalEarlyExit} leads đã kết thúc (FINAL) trước khi đến stage cuối cùng
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  )}
                  {failedCount > 0 && (
                    <div className="flex items-center gap-1 text-error-600">
                      <AlertTriangle className="h-3 w-3" />
                      <span>Failed: {failedCount}</span>
                    </div>
                  )}
                </div>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="text-error-600 font-medium cursor-help">
                      Tổng Lost: {totalLost} ({(totalLost / Math.max(totalLeads, 1) * 100).toFixed(0)}%)
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-[280px]">
                    <div className="text-xs space-y-1.5">
                      <p className="font-medium border-b border-white/20 pb-1">
                        Phân tích lý do mất leads
                      </p>
                      {aggregatedLossBreakdown.length > 0 ? (
                        <div className="space-y-1">
                          {aggregatedLossBreakdown.slice(0, 5).map((item) => {
                            const reasonInfo = LOSS_REASON_LABELS[item.reason_code] || {
                              label: item.reason_code,
                              icon: "•"
                            };
                            return (
                              <div key={item.reason_code} className="flex items-center justify-between">
                                <span className="text-white/80">
                                  {reasonInfo.icon} {reasonInfo.label}
                                </span>
                                <span className="text-white/60 tabular-nums">
                                  {item.count} ({item.percentage}%)
                                </span>
                              </div>
                            );
                          })}
                          {aggregatedLossBreakdown.length > 5 && (
                            <p className="text-white/50 text-[10px] pt-1 border-t border-white/10">
                              +{aggregatedLossBreakdown.length - 5} lý do khác...
                            </p>
                          )}
                        </div>
                      ) : (
                        <p className="text-white/60 italic">
                          Chưa có dữ liệu lý do. Hãy chọn lý do khi đánh dấu lead là Lost.
                        </p>
                      )}
                      <p className="text-white/40 text-[10px] italic border-t border-white/20 pt-1 mt-1">
                        * Dựa trên dữ liệu Loss Reason được ghi nhận
                      </p>
                    </div>
                  </TooltipContent>
                </Tooltip>
              </div>
            )}
            {/* Row 3: Estimated Lost Revenue (Phase 2) */}
            {totalLostRevenue > 0 && (
              <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-dashed">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-1.5 cursor-help">
                      <DollarSign className="h-3.5 w-3.5 text-amber-600" />
                      <span>Doanh thu mất ước tính:</span>
                      <strong className="text-amber-600 dark:text-amber-400">
                        {formatVNDFull(totalLostRevenue)}
                      </strong>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-[280px]">
                    <div className="text-xs space-y-1.5">
                      <p className="font-medium border-b border-white/20 pb-1">
                        Doanh thu mất theo giai đoạn
                      </p>
                      <div className="space-y-1">
                        {sortedFunnel
                          .filter(s => s.estimated_lost_revenue?.total_lost_revenue && s.estimated_lost_revenue.total_lost_revenue > 0)
                          .slice(0, 5)
                          .map((stage) => (
                            <div key={stage.stage_id} className="flex items-center justify-between">
                              <span className="text-white/80 truncate max-w-[120px]">
                                {stage.stage_name}
                              </span>
                              <span className="text-amber-300 tabular-nums font-medium">
                                {formatVND(stage.estimated_lost_revenue!.total_lost_revenue)}
                              </span>
                            </div>
                          ))}
                      </div>
                      <p className="text-white/50 text-[10px] italic border-t border-white/20 pt-1 mt-1">
                        * Ước tính dựa trên học phí TB của ngành đăng ký
                      </p>
                    </div>
                  </TooltipContent>
                </Tooltip>
              </div>
            )}
          </div>

          {/* === SUGGESTIONS SECTION (Phase 2) === */}
          {suggestions && suggestions.length > 0 && (
            <div className="pt-4 border-t">
              <div className="flex items-center gap-2 mb-3">
                <Lightbulb className="h-4 w-4 text-amber-500" />
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Gợi ý cải thiện
                </h4>
              </div>
              <div className="space-y-2">
                {suggestions.slice(0, 3).map((suggestion) => {
                  const style = SUGGESTION_STYLES[suggestion.type];
                  const priorityStyle = PRIORITY_STYLES[suggestion.priority];

                  return (
                    <div
                      key={suggestion.id}
                      className={cn(
                        "p-3 rounded-lg border transition-colors",
                        style.bgColor,
                        "hover:shadow-sm"
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <span className="text-lg shrink-0">{style.icon}</span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <p className={cn("text-sm font-medium", style.color)}>
                              {suggestion.title}
                            </p>
                            <span className={cn(
                              "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                              priorityStyle.color
                            )}>
                              {priorityStyle.label}
                            </span>
                          </div>
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {suggestion.description}
                          </p>
                          {suggestion.metric_label && (
                            <p className="text-xs text-muted-foreground mt-1 font-medium">
                              {suggestion.metric_label}
                            </p>
                          )}
                          {suggestion.action_url && (
                            <button
                              onClick={() => router.push(suggestion.action_url!)}
                              className={cn(
                                "mt-2 text-xs font-medium flex items-center gap-1",
                                "hover:underline",
                                style.color
                              )}
                            >
                              {suggestion.action_label || "Xem chi tiết"}
                              <ExternalLink className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
                {suggestions.length > 3 && (
                  <p className="text-xs text-muted-foreground text-center pt-1">
                    +{suggestions.length - 3} gợi ý khác
                  </p>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
