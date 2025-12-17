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
 * - Configurable stage IDs via props
 * - Seamless funnel geometry (each stage's bottom matches next stage's top)
 * - Improved bottleneck detection (impact = dropOff × severity)
 */
"use client";

import { useRouter } from "next/navigation";
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
  Minus
} from "lucide-react";

// ============================================================================
// INTERFACES
// ============================================================================

interface OutcomeBreakdown {
  positive: number;
  negative: number;
  neutral: number;
}

interface FunnelStage {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  lead_count: number;
  is_final_stage?: boolean;
  conversion_rate?: number | null;  // Historical conversion % (30 days)
  outcome_breakdown?: OutcomeBreakdown;  // positive/negative/neutral counts
}

// Funnel configuration interface - allows customization via props
interface FunnelConfig {
  positiveStageIds: string[];  // Stage IDs considered as positive outcome
  negativeStageIds: string[];  // Stage IDs considered as negative outcome
  bottleneckThreshold: number; // Conversion rate below this triggers bottleneck warning  
}

// Default configuration
const DEFAULT_CONFIG: FunnelConfig = {
  positiveStageIds: ["stg06", "enrolled"],
  negativeStageIds: ["stg07", "lost", "not_enrolled"],
  bottleneckThreshold: 50,
};

interface FunnelChartProps {
  funnel: FunnelStage[];
  /** Comparison data from previous period */
  previousPeriodConversion?: number;
  /** Optional configuration to override defaults */
  config?: Partial<FunnelConfig>;
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
    return lightness > 60 ? 'text-gray-800' : 'text-white';
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

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function FunnelChart({ funnel, previousPeriodConversion, config }: FunnelChartProps) {
  const router = useRouter();
  
  // Merge user config with defaults
  const mergedConfig: FunnelConfig = {
    ...DEFAULT_CONFIG,
    ...config,
  };

  // Get all outcome stage IDs (both positive and negative)
  const outcomeStageIds = [
    ...mergedConfig.positiveStageIds,
    ...mergedConfig.negativeStageIds,
  ];

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

  // Sort by stage order
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);

  // Separate core flow stages from outcome stages (using configurable IDs)
  const coreStages = sortedFunnel.filter(s => 
    !s.is_final_stage && !outcomeStageIds.includes(s.stage_id)
  );
  const outcomeStages = sortedFunnel.filter(s => 
    s.is_final_stage || outcomeStageIds.includes(s.stage_id)
  );

  // Calculate total leads by summing all stages (core + outcome)
  // This is correct for ACTUAL count approach (not cumulative)
  const totalLeads = sortedFunnel.reduce((sum, s) => sum + s.lead_count, 0);
  
  // Calculate total drop-off (leads with negative outcome across all stages)
  const totalDropoff = sortedFunnel.reduce((sum, s) => 
    sum + (s.outcome_breakdown?.negative || 0), 0
  );
  
  // Calculate overall conversion (completed outcomes / total leads)
  // Using configurable positive stage IDs
  const enrolledStage = outcomeStages.find(s => 
    mergedConfig.positiveStageIds.includes(s.stage_id)
  );
  const failedStages = outcomeStages.filter(s => 
    mergedConfig.negativeStageIds.includes(s.stage_id)
  );
  const enrolledCount = enrolledStage?.lead_count || 0;
  const failedCount = failedStages.reduce((sum, s) => sum + s.lead_count, 0);
  const completedCount = enrolledCount + failedCount;
  const overallConversion = totalLeads > 0 ? (completedCount / totalLeads) * 100 : 0;

  // Calculate metrics for each stage
  const stageMetrics = coreStages.map((stage, index) => {
    const percentFromTotal = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
    
    // Use historical conversion rate from backend if available
    const historicalConversion = stage.conversion_rate;
    const hasHistoricalData = historicalConversion !== null && historicalConversion !== undefined;
    
    if (index === 0) {
      return { 
        conversion: hasHistoricalData ? historicalConversion : null,
        dropOff: 0, 
        dropOffPercent: 0,
        percentFromTotal,
        prevCount: stage.lead_count,
        hasHistoricalData
      };
    }
    
    const prevCount = coreStages[index - 1].lead_count;
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

  // =========== IMPROVED BOTTLENECK DETECTION ===========
  // Find bottleneck using both conversion rate AND volume impact
  // Priority: Stages where high volume is lost (dropOff * severity)
  const findBottleneck = (metrics: typeof stageMetrics, threshold: number) => {
    let maxImpact = -1;
    let bottleneckIdx = -1;
    
    metrics.forEach((metric, idx) => {
      if (idx === 0 || metric.conversion === null) return;
      if (metric.conversion >= threshold) return; // Skip healthy stages
      
      // Impact = volume lost * severity (inverse of conversion rate)
      const severity = (100 - metric.conversion) / 100;
      const impact = metric.dropOff * severity;
      
      if (impact > maxImpact) {
        maxImpact = impact;
        bottleneckIdx = idx;
      }
    });
    
    return bottleneckIdx;
  };
  const bottleneckIndex = findBottleneck(stageMetrics, mergedConfig.bottleneckThreshold);

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
                      <TooltipContent side="right" className="max-w-[280px]">
                        <div className="text-xs space-y-1.5">
                          <p className="font-medium border-b border-white/20 pb-1">
                            {coreStages[index - 1].stage_name} → {stage.stage_name}
                          </p>
                          
                          {/* Historical Conversion Rate */}
                          <div className="space-y-0.5">
                            <p className="text-white/90">
                              <span className="font-medium text-white">Tỷ lệ chuyển đổi (30 ngày):</span>
                              {" "}
                              {metrics.conversion !== null 
                                ? <span className={cn("font-bold", 
                                    metrics.conversion >= 70 ? "text-emerald-300" :
                                    metrics.conversion >= 50 ? "text-amber-300" : "text-red-300"
                                  )}>{metrics.conversion.toFixed(0)}%</span>
                                : <span className="text-white/50">Chưa có dữ liệu</span>
                              }
                            </p>
                            <p className="text-white/50 text-[10px] italic">
                              % leads đã tiến từ "{coreStages[index - 1].stage_name}" lên stage tiếp theo
                            </p>
                          </div>
                          
                          {/* Current Distribution */}
                          <div className="space-y-0.5 pt-1 border-t border-white/20">
                            <p className="text-white/90">
                              <span className="font-medium text-white">Phân bố hiện tại:</span>
                            </p>
                            <p className="text-white/70 pl-2">
                              • "{coreStages[index - 1].stage_name}": {metrics.prevCount} leads
                            </p>
                            <p className="text-white/70 pl-2">
                              • "{stage.stage_name}": {stage.lead_count} leads
                            </p>
                            {metrics.dropOff > 0 && (
                              <p className="text-amber-300 pl-2">
                                • Chênh lệch: -{metrics.dropOff} leads ({metrics.dropOffPercent.toFixed(0)}%)
                              </p>
                            )}
                          </div>
                          
                          {/* Status */}
                          <p className={cn("font-medium pt-1 border-t border-white/20", 
                            metrics.conversion !== null && metrics.conversion >= 70 ? "text-emerald-300" :
                            metrics.conversion !== null && metrics.conversion >= 50 ? "text-amber-300" : "text-red-300"
                          )}>
                            Đánh giá: {conversionStatus.label}
                          </p>
                          
                          {isBottleneck && (
                            <p className="text-red-300 font-medium bg-red-500/30 p-1.5 rounded">
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
                            "relative group transition-all duration-200 hover:brightness-110 h-14 w-full flex-1",
                            isBottleneck && "ring-2 ring-red-400/50 ring-offset-1"
                          )}
                          onClick={() => handleStageClick(stage.stage_id)}
                        >
                          {/* Background layer with clip-path */}
                          <div 
                            className="absolute inset-0 shadow-sm transition-all hover:shadow-lg"
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
                              <span className="text-emerald-600">+{stage.outcome_breakdown.positive}</span>
                              <span className="text-red-500">−{stage.outcome_breakdown.negative}</span>
                              <span>○{stage.outcome_breakdown.neutral}</span>
                            </div>
                          )}
                          <p className="text-muted-foreground pt-1 border-t">Click để xem danh sách</p>
                        </div>
                      </TooltipContent>
                    </Tooltip>

                    {/* Right: Lead count with outcome breakdown */}
                    <div className="w-24 shrink-0 flex items-center justify-end gap-1.5">
                      <span className="text-sm font-bold tabular-nums text-foreground">
                        {stage.lead_count}
                      </span>
                      {stage.outcome_breakdown && stage.outcome_breakdown.negative > 0 && (
                        <span className="text-xs text-red-500 font-medium">
                          −{stage.outcome_breakdown.negative}
                        </span>
                      )}
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
                  const isPositive = mergedConfig.positiveStageIds.includes(stage.stage_id);
                  const isNegative = mergedConfig.negativeStageIds.includes(stage.stage_id);
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
            {totalDropoff > 0 && (
              <div className="flex items-center gap-1.5 text-red-600">
                <AlertTriangle className="h-3 w-3" />
                <span>
                  Drop-off: {totalDropoff} ({(totalDropoff / Math.max(totalLeads, 1) * 100).toFixed(0)}%)
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
