// src/components/officer/FunnelChart.tsx
/**
 * Pipeline Funnel Chart - Industrial Standard
 * Designed for management decision-making
 * 
 * Features:
 * - Clean, professional design (minimal colors, no excessive animations)
 * - Separate "Core Flow" stages from "Outcome" stages
 * - Color-coded conversion indicators
 * - Actionable insights through tooltips
 */
"use client";

import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { 
  ChevronRight, 
  AlertTriangle, 
  Users, 
  ArrowDown, 
  Target, 
  CheckCircle2,
  XCircle,
  PauseCircle,
  TrendingUp,
  TrendingDown,
  Minus
} from "lucide-react";

interface FunnelStage {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  lead_count: number;
  is_final_stage?: boolean;
  conversion_rate?: number | null;  // Historical conversion % (30 days)
}

interface FunnelChartProps {
  funnel: FunnelStage[];
  /** Comparison data from previous period */
  previousPeriodConversion?: number;
}

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
    color: "bg-emerald-50 dark:bg-emerald-950/20",
    textColor: "text-emerald-700 dark:text-emerald-400",
    borderColor: "border-emerald-200 dark:border-emerald-800",
    status: "good",
    label: "Tốt"
  };
  if (rate >= 50) return { 
    color: "bg-amber-50 dark:bg-amber-950/20",
    textColor: "text-amber-700 dark:text-amber-400", 
    borderColor: "border-amber-200 dark:border-amber-800",
    status: "warning",
    label: "Theo dõi"
  };
  return { 
    color: "bg-red-50 dark:bg-red-950/20",
    textColor: "text-red-700 dark:text-red-400",
    borderColor: "border-red-200 dark:border-red-800",
    status: "critical",
    label: "Cần hành động"
  };
};

// Outcome stage IDs (final stages)
const OUTCOME_STAGE_IDS = ["stg06", "stg07", "enrolled", "lost", "not_enrolled"];

export function FunnelChart({ funnel, previousPeriodConversion }: FunnelChartProps) {
  const router = useRouter();

  // Sort by stage order
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);

  // Separate core flow stages from outcome stages
  const coreStages = sortedFunnel.filter(s => 
    !s.is_final_stage && !OUTCOME_STAGE_IDS.includes(s.stage_id)
  );
  const outcomeStages = sortedFunnel.filter(s => 
    s.is_final_stage || OUTCOME_STAGE_IDS.includes(s.stage_id)
  );

  // Calculate total leads by summing all stages (core + outcome)
  // This is correct for ACTUAL count approach (not cumulative)
  const totalLeads = sortedFunnel.reduce((sum, s) => sum + s.lead_count, 0);
  
  // Calculate overall conversion (completed outcomes / total leads)
  // This shows what percentage of leads have completed the funnel
  const enrolledStage = outcomeStages.find(s => 
    s.stage_id === "stg06" || s.stage_id === "enrolled"
  );
  const failedStages = outcomeStages.filter(s => 
    s.stage_id === "stg07" || s.stage_id === "lost" || s.stage_id === "not_enrolled"
  );
  const enrolledCount = enrolledStage?.lead_count || 0;
  const failedCount = failedStages.reduce((sum, s) => sum + s.lead_count, 0);
  const completedCount = enrolledCount + failedCount;
  const overallConversion = totalLeads > 0 ? (completedCount / totalLeads) * 100 : 0;

  // Calculate metrics for each stage
  // Use backend-calculated conversion_rate (from lead_status_history) when available
  const stageMetrics = coreStages.map((stage, index) => {
    const percentFromTotal = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
    
    // Use historical conversion rate from backend if available
    // If no historical data, conversion is null (display as N/A)
    const historicalConversion = stage.conversion_rate;
    const hasHistoricalData = historicalConversion !== null && historicalConversion !== undefined;
    
    if (index === 0) {
      return { 
        conversion: hasHistoricalData ? historicalConversion : null,  // First stage
        dropOff: 0, 
        dropOffPercent: 0,
        percentFromTotal,
        prevCount: stage.lead_count,
        hasHistoricalData
      };
    }
    
    const prevCount = coreStages[index - 1].lead_count;
    // Only use historical conversion - don't fallback to count-based (meaningless with actual counts)
    const conversion = hasHistoricalData ? historicalConversion : null;
    const dropOff = Math.max(0, prevCount - stage.lead_count);
    const dropOffPercent = prevCount > 0 ? (dropOff / prevCount) * 100 : 0;
    
    return { 
      conversion, 
      dropOff, 
      dropOffPercent, 
      percentFromTotal, 
      prevCount,
      hasHistoricalData
    };
  });

  // Find bottleneck (lowest conversion excluding first stage, only for stages with data)
  const bottleneckIndex = stageMetrics.reduce((minIdx, metric, idx) => {
    if (idx === 0 || metric.conversion === null) return minIdx;
    if (minIdx === -1) return idx;
    const minConversion = stageMetrics[minIdx].conversion;
    if (minConversion === null) return idx;
    return metric.conversion < minConversion ? idx : minIdx;
  }, -1);

  // Comparison with previous period
  const conversionTrend = previousPeriodConversion !== undefined
    ? overallConversion - previousPeriodConversion
    : null;

  // Navigate to leads filtered by stage
  const handleStageClick = (stageId: string) => {
    router.push(`/leads?stage=${stageId}`);
  };

  return (
    <TooltipProvider delayDuration={150}>
      <Card className="border bg-card">
        {/* Header */}
        <CardHeader className="pb-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-semibold">
              Pipeline Funnel
            </CardTitle>
            
            {/* Overall Conversion with Trend */}
            <div className="flex items-center gap-3">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2 cursor-help">
                    <span className="text-sm text-muted-foreground">Tổng chuyển đổi:</span>
                    <span className={cn(
                      "text-lg font-bold",
                      overallConversion >= 10 ? "text-emerald-600" : 
                      overallConversion >= 5 ? "text-amber-600" : "text-red-600"
                    )}>
                      {overallConversion.toFixed(1)}%
                    </span>
                    {conversionTrend !== null && (
                      <div className={cn(
                        "flex items-center gap-0.5 text-xs",
                        conversionTrend > 0 ? "text-emerald-600" : 
                        conversionTrend < 0 ? "text-red-600" : "text-muted-foreground"
                      )}>
                        {conversionTrend > 0 ? <TrendingUp className="h-3 w-3" /> :
                         conversionTrend < 0 ? <TrendingDown className="h-3 w-3" /> :
                         <Minus className="h-3 w-3" />}
                        <span>{conversionTrend > 0 ? "+" : ""}{conversionTrend.toFixed(1)}%</span>
                      </div>
                    )}
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">
                    {enrolledCount} / {totalLeads} leads hoàn thành nhập học
                    {conversionTrend !== null && (
                      <span className="block mt-1">
                        So với kỳ trước: {conversionTrend > 0 ? "+" : ""}{conversionTrend.toFixed(1)}%
                      </span>
                    )}
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* === CORE FUNNEL FLOW === */}
          <div className="space-y-1">
            {coreStages.map((stage, index) => {
              const metrics = stageMetrics[index];
              const isBottleneck = index === bottleneckIndex && metrics.conversion !== null && metrics.conversion < 50;
              const conversionStatus = getConversionStatus(metrics.conversion);
              const stageColor = getStageColor(index, coreStages.length, false);
              
              // Width based on cumulative conversion (first stage = 100%, then proportionally smaller)
              // This creates the classic funnel trapezoid shape
              const cumulativePercent = index === 0 
                ? 100 
                : Math.max(35, 100 - (index * 12)); // Each stage ~12% narrower
              const widthPercent = cumulativePercent;

              return (
                <div key={stage.stage_id} className="flex flex-col items-center">
                  {/* Conversion Indicator (between stages) */}
                  {index > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div 
                          className={cn(
                            "flex items-center gap-2 py-1 px-2 my-0.5 cursor-help transition-colors",
                            isBottleneck && "ring-1 ring-red-400 rounded"
                          )}
                        >
                          <ArrowDown className={cn("h-3 w-3", conversionStatus.textColor)} />
                          <span className={cn("text-xs font-semibold tabular-nums", conversionStatus.textColor)}>
                            {metrics.conversion !== null ? `${metrics.conversion.toFixed(0)}%` : "N/A"}
                          </span>
                          {metrics.dropOff > 0 && (
                            <span className="text-xs text-muted-foreground tabular-nums">
                              -{metrics.dropOff}
                            </span>
                          )}
                          {isBottleneck && (
                            <AlertTriangle className="h-3 w-3 text-red-500" />
                          )}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="right" className="max-w-[240px]">
                        <div className="text-xs space-y-1.5">
                          <p className="font-medium">
                            {coreStages[index - 1].stage_name} → {stage.stage_name}
                          </p>
                          <div className="text-muted-foreground space-y-0.5">
                            <p>Chuyển đổi: {stage.lead_count}/{metrics.prevCount} leads</p>
                            {metrics.dropOff > 0 && (
                              <p className="text-amber-600">Drop-off: {metrics.dropOff} leads ({metrics.dropOffPercent.toFixed(0)}%)</p>
                            )}
                          </div>
                          <p className={cn("font-medium pt-1 border-t", conversionStatus.textColor)}>
                            Trạng thái: {conversionStatus.label}
                          </p>
                          {isBottleneck && (
                            <p className="text-red-600 font-medium">
                              ⚠️ Điểm nghẽn chính - cần review quy trình
                            </p>
                          )}
                        </div>
                      </TooltipContent>
                    </Tooltip>
                  )}

                  {/* Stage Row: Label | Bar | Conversion */}
                  <div className="flex items-center w-full gap-3">
                    {/* Left: Stage name (outside bar) */}
                    <div className="w-28 shrink-0 text-right">
                      <span className="text-sm font-medium text-foreground truncate">
                        {stage.stage_name}
                      </span>
                    </div>

                    {/* Center: Bar */}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          className={cn(
                            "relative group transition-all duration-200 hover:scale-[1.01] flex-1",
                            isBottleneck && "ring-2 ring-red-400/50 ring-offset-1 rounded"
                          )}
                          style={{ maxWidth: `${widthPercent}%` }}
                          onClick={() => handleStageClick(stage.stage_id)}
                        >
                          <div 
                            className={cn(
                              "relative h-12 overflow-hidden transition-all",
                              "hover:brightness-110 hover:shadow-lg"
                            )}
                            style={{
                              backgroundColor: stageColor,
                              clipPath: 'polygon(0% 0%, 100% 0%, 98% 100%, 2% 100%)',
                              borderRadius: '2px',
                            }}
                          >
                            {/* Content inside bar */}
                            <div className="absolute inset-0 flex items-center justify-center px-4">
                              {/* Center: Percentage */}
                              <span className="text-lg font-bold text-white tabular-nums drop-shadow-sm">
                                {metrics.percentFromTotal.toFixed(1)}%
                              </span>
                            </div>
                          </div>
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        <p className="text-xs">
                          Click để xem {stage.lead_count} leads ở giai đoạn này
                        </p>
                      </TooltipContent>
                    </Tooltip>

                    {/* Right: Lead count + Conversion */}
                    <div className="w-20 shrink-0 text-right">
                      <span className={cn(
                        "text-sm font-bold tabular-nums",
                        conversionStatus.textColor
                      )}>
                        {stage.lead_count}
                      </span>
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
                  const isPositive = stage.stage_id === "stg06" || stage.stage_id === "enrolled";
                  const isNegative = stage.stage_id === "stg07" || stage.stage_id === "lost" || stage.stage_id === "not_enrolled";
                  const percent = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
                  
                  return (
                    <Tooltip key={stage.stage_id}>
                      <TooltipTrigger asChild>
                        <button
                          onClick={() => handleStageClick(stage.stage_id)}
                          className={cn(
                            "flex items-center gap-2 p-3 rounded-lg border transition-colors text-left",
                            "hover:bg-accent/50",
                            isPositive && "border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20",
                            isNegative && "border-red-200 bg-red-50/50 dark:border-red-800 dark:bg-red-950/20",
                            !isPositive && !isNegative && "border-gray-200 bg-gray-50/50 dark:border-gray-700 dark:bg-gray-900/20"
                          )}
                        >
                          {isPositive ? (
                            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                          ) : isNegative ? (
                            <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                          ) : (
                            <PauseCircle className="h-4 w-4 text-gray-500 shrink-0" />
                          )}
                          <div className="flex-1 min-w-0">
                            <p className="text-xs text-muted-foreground truncate">
                              {stage.stage_name}
                            </p>
                            <p className={cn(
                              "text-sm font-semibold tabular-nums",
                              isPositive && "text-emerald-700 dark:text-emerald-400",
                              isNegative && "text-red-600 dark:text-red-400"
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
          <div className="pt-3 border-t flex items-center justify-between text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5" />
              <span>Tổng đầu vào: <strong className="text-foreground">{totalLeads}</strong></span>
            </div>
            {totalLeads > enrolledCount && (
              <div className="flex items-center gap-1.5 text-amber-600">
                <AlertTriangle className="h-3 w-3" />
                <span>
                  Drop-off tổng: {totalLeads - enrolledCount} ({((totalLeads - enrolledCount) / Math.max(totalLeads, 1) * 100).toFixed(0)}%)
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
