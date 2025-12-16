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
}

interface FunnelChartProps {
  funnel: FunnelStage[];
  /** Comparison data from previous period */
  previousPeriodConversion?: number;
}

// Industrial color palette - muted, professional
const FUNNEL_COLORS = {
  primary: "hsl(221 83% 53%)",      // Primary blue
  primaryMuted: "hsl(221 70% 60%)", // Lighter blue
  success: "hsl(142 71% 45%)",      // Green
  warning: "hsl(38 92% 50%)",       // Amber
  danger: "hsl(0 84% 60%)",         // Red  
  neutral: "hsl(215 16% 47%)",      // Gray
};

// Get stage background color (subtle gradient based on position)
const getStageColor = (index: number, total: number, isFinal: boolean) => {
  if (isFinal) return "hsl(215 20% 65%)"; // Muted gray for final stages
  const lightness = 50 + (index / Math.max(total - 1, 1)) * 15;
  return `hsl(221 75% ${lightness}%)`;
};

// Get conversion rate status and color
const getConversionStatus = (rate: number): { 
  color: string; 
  textColor: string;
  borderColor: string;
  status: "good" | "warning" | "critical";
  label: string;
} => {
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
  
  // Calculate overall conversion (to positive outcomes like enrolled)
  const enrolledStage = outcomeStages.find(s => 
    s.stage_id === "stg06" || s.stage_id === "enrolled"
  );
  const enrolledCount = enrolledStage?.lead_count || 0;
  const overallConversion = totalLeads > 0 ? (enrolledCount / totalLeads) * 100 : 0;

  // Calculate metrics for each stage
  const stageMetrics = coreStages.map((stage, index) => {
    const percentFromTotal = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
    
    if (index === 0) {
      return { 
        conversion: 100, 
        dropOff: 0, 
        dropOffPercent: 0,
        percentFromTotal,
        prevCount: stage.lead_count
      };
    }
    
    const prevCount = coreStages[index - 1].lead_count;
    const conversion = prevCount > 0 ? (stage.lead_count / prevCount) * 100 : 0;
    const dropOff = Math.max(0, prevCount - stage.lead_count);
    const dropOffPercent = prevCount > 0 ? (dropOff / prevCount) * 100 : 0;
    
    return { conversion, dropOff, dropOffPercent, percentFromTotal, prevCount };
  });

  // Find bottleneck (lowest conversion excluding first stage)
  const bottleneckIndex = stageMetrics.reduce((minIdx, metric, idx) => {
    if (idx === 0) return minIdx;
    if (minIdx === -1) return idx;
    return metric.conversion < stageMetrics[minIdx].conversion ? idx : minIdx;
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
          <div className="space-y-0">
            {coreStages.map((stage, index) => {
              const metrics = stageMetrics[index];
              const isBottleneck = index === bottleneckIndex && metrics.conversion < 50;
              const conversionStatus = getConversionStatus(metrics.conversion);
              const stageColor = getStageColor(index, coreStages.length, false);
              
              // Width based on percentage (min 30%, max 100%)
              const widthPercent = Math.max(30, Math.min(100, metrics.percentFromTotal + 10));

              return (
                <div key={stage.stage_id} className="flex flex-col items-center">
                  {/* Conversion Indicator (between stages) */}
                  {index > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div 
                          className={cn(
                            "flex items-center gap-2 py-1.5 px-3 my-1 rounded border cursor-help transition-colors",
                            conversionStatus.color,
                            conversionStatus.borderColor,
                            isBottleneck && "ring-1 ring-red-400"
                          )}
                        >
                          <ArrowDown className={cn("h-3 w-3", conversionStatus.textColor)} />
                          <span className={cn("text-xs font-semibold tabular-nums", conversionStatus.textColor)}>
                            {metrics.prevCount > 0 ? `${metrics.conversion.toFixed(0)}%` : "N/A"}
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

                  {/* Stage Bar */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        className={cn(
                          "relative group transition-all duration-150 hover:scale-[1.01]",
                          isBottleneck && "ring-2 ring-red-400/50 ring-offset-1 rounded"
                        )}
                        style={{ width: `${widthPercent}%` }}
                        onClick={() => handleStageClick(stage.stage_id)}
                      >
                        <div 
                          className={cn(
                            "relative h-12 overflow-hidden transition-all",
                            "hover:brightness-105"
                          )}
                          style={{
                            backgroundColor: stageColor,
                            clipPath: index < coreStages.length - 1 
                              ? 'polygon(2% 0%, 98% 0%, 100% 100%, 0% 100%)'
                              : 'polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)',
                          }}
                        >
                          <div className="absolute inset-0 flex items-center justify-between px-4">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-white truncate">
                                {stage.stage_name}
                              </span>
                              <ChevronRight className="h-4 w-4 text-white/60 opacity-0 group-hover:opacity-100 transition-opacity" />
                            </div>
                            <div className="flex items-baseline gap-2 text-white">
                              <span className="text-lg font-bold tabular-nums">{stage.lead_count}</span>
                              <span className="text-xs opacity-70">({metrics.percentFromTotal.toFixed(0)}%)</span>
                            </div>
                          </div>
                        </div>
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="right">
                      <p className="text-xs">
                        Click để xem {stage.lead_count} leads ở giai đoạn này
                      </p>
                    </TooltipContent>
                  </Tooltip>
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
