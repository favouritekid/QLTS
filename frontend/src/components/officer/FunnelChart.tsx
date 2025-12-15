// src/components/officer/FunnelChart.tsx
/**
 * Pipeline Funnel Chart - Enhanced Visual Funnel Shape
 * Displays leads distribution with detailed metrics and explanations
 */
"use client";

import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { TrendingDown, ChevronRight, AlertTriangle, Info, Users, ArrowDownRight, Target, HelpCircle } from "lucide-react";

interface FunnelStage {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  lead_count: number;
}

interface FunnelChartProps {
  funnel: FunnelStage[];
}

// Monochromatic blue gradient - dark to light
const getBlueShade = (index: number, total: number) => {
  const lightness = 45 + (index / Math.max(total - 1, 1)) * 30;
  return `hsl(221 83% ${lightness}%)`;
};

// Get color based on conversion rate
const getConversionColor = (rate: number) => {
  if (rate >= 70) return "text-emerald-600 dark:text-emerald-400";
  if (rate >= 50) return "text-amber-600 dark:text-amber-400";
  return "text-red-500 dark:text-red-400";
};

// Get border color for drop-off indicator (using borders for better readability)
const getDropOffBorderColor = (rate: number) => {
  if (rate >= 70) return "border-emerald-300 dark:border-emerald-700";
  if (rate >= 50) return "border-amber-300 dark:border-amber-600";
  return "border-red-300 dark:border-red-600";
};

// Get text color for conversion rate with better contrast
const getConversionTextColor = (rate: number) => {
  if (rate >= 70) return "text-emerald-700 dark:text-emerald-400";
  if (rate >= 50) return "text-amber-700 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
};

export function FunnelChart({ funnel }: FunnelChartProps) {
  const router = useRouter();

  // Sort by stage order
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);

  // Calculate totals
  const totalLeads = sortedFunnel[0]?.lead_count || 0;
  const convertedLeads = sortedFunnel[sortedFunnel.length - 1]?.lead_count || 0;
  const overallConversion = totalLeads > 0 ? (convertedLeads / totalLeads) * 100 : 0;

  // Calculate step conversion rates and drop-offs
  const stageMetrics = sortedFunnel.map((stage, index) => {
    if (index === 0) {
      return { 
        conversion: 100, 
        dropOff: 0, 
        dropOffPercent: 0,
        percentFromTotal: 100 
      };
    }
    const prevCount = sortedFunnel[index - 1].lead_count;
    const conversion = prevCount > 0 ? (stage.lead_count / prevCount) * 100 : 0;
    const dropOff = prevCount - stage.lead_count;
    const dropOffPercent = prevCount > 0 ? (dropOff / prevCount) * 100 : 0;
    const percentFromTotal = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
    return { conversion, dropOff, dropOffPercent, percentFromTotal };
  });

  // Find the stage with lowest conversion (excluding first stage)
  const lowestConversionIndex = stageMetrics.reduce((minIdx, metric, idx) => {
    if (idx === 0) return minIdx;
    if (minIdx === -1) return idx;
    return metric.conversion < stageMetrics[minIdx].conversion ? idx : minIdx;
  }, -1);

  // Navigate to leads filtered by stage
  const handleStageClick = (stageId: string) => {
    router.push(`/leads?stage=${stageId}`);
  };

  return (
    <TooltipProvider delayDuration={200}>
      <Card className="border bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div>
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Pipeline Funnel
                </CardTitle>
                <CardDescription className="text-xs mt-0.5">
                  Click từng giai đoạn để xem leads
                </CardDescription>
              </div>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button className="text-muted-foreground hover:text-foreground transition-colors">
                    <HelpCircle className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[280px] p-3">
                  <div className="space-y-2 text-xs">
                    <p className="font-medium">Hướng dẫn đọc biểu đồ:</p>
                    <ul className="space-y-1 text-muted-foreground">
                      <li>• <strong>Số leads</strong>: Số lượng khách hàng ở mỗi giai đoạn</li>
                      <li>• <strong>% từ tổng</strong>: Tỷ lệ so với tổng leads ban đầu</li>
                      <li>• <strong>Tỷ lệ chuyển đổi</strong>: % leads chuyển từ giai đoạn trước</li>
                      <li>• <strong>Drop-off</strong>: Số leads bị mất giữa các giai đoạn</li>
                    </ul>
                    <div className="pt-1 border-t space-y-1">
                      <p className="font-medium">Màu sắc tỷ lệ:</p>
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-500" />
                        <span className="text-muted-foreground">Tốt (≥70%)</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-amber-500" />
                        <span className="text-muted-foreground">Trung bình (50-70%)</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-red-500" />
                        <span className="text-muted-foreground">Cần cải thiện (&lt;50%)</span>
                      </div>
                    </div>
                  </div>
                </TooltipContent>
              </Tooltip>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1.5 text-sm cursor-help">
                  <Target className="h-4 w-4 text-muted-foreground" />
                  <span className={cn("font-semibold", getConversionColor(overallConversion))}>
                    {overallConversion.toFixed(1)}%
                  </span>
                  <span className="text-muted-foreground text-xs">tổng chuyển đổi</span>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-xs">
                  Tỷ lệ từ giai đoạn đầu đến giai đoạn cuối: {convertedLeads}/{totalLeads} leads
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        </CardHeader>
        <CardContent>
          {/* Legend */}
          <div className="mb-4 pb-3 border-b flex flex-wrap gap-4 text-[10px] text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Users className="h-3 w-3" />
              <span>Số leads</span>
            </div>
            <div className="flex items-center gap-1.5">
              <ArrowDownRight className="h-3 w-3" />
              <span>Tỷ lệ chuyển đổi</span>
            </div>
            <div className="flex items-center gap-1.5">
              <AlertTriangle className="h-3 w-3 text-amber-500" />
              <span>Drop-off (leads bị mất)</span>
            </div>
          </div>

          {/* Funnel Container */}
          <div className="flex flex-col items-center gap-1">
            {sortedFunnel.map((stage, index) => {
              const percentage = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
              const metrics = stageMetrics[index];
              const bgColor = getBlueShade(index, sortedFunnel.length);
              const isLowestConversion = index === lowestConversionIndex && metrics.conversion < 50;
              
              // Width proportional to actual percentage (min 25%, max 100%)
              const widthPercent = Math.max(25, Math.min(100, percentage + 15));

              return (
                <div key={stage.stage_name} className="w-full flex flex-col items-center">
                  {/* Enhanced Conversion indicator between stages */}
                  {index > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div 
                          className={cn(
                            "flex items-center gap-2 px-3 py-1 rounded-full my-1 cursor-help transition-colors border bg-background/80",
                            getDropOffBorderColor(metrics.conversion)
                          )}
                        >
                          <div className={cn("flex items-center gap-1 text-[11px] font-semibold", getConversionTextColor(metrics.conversion))}>
                            <ArrowDownRight className="h-3 w-3" />
                            <span>
                              {sortedFunnel[index - 1].lead_count > 0 
                                ? `${metrics.conversion.toFixed(0)}%` 
                                : "N/A"}
                            </span>
                          </div>
                          {metrics.dropOff > 0 && (
                            <div className="flex items-center gap-1 text-[10px] text-foreground/70 font-medium">
                              <AlertTriangle className="h-2.5 w-2.5 text-amber-600" />
                              <span>-{metrics.dropOff}</span>
                            </div>
                          )}
                          {isLowestConversion && (
                            <AlertTriangle className="h-3 w-3 text-red-500 animate-pulse" />
                          )}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="left" className="max-w-[220px]">
                        <div className="text-xs space-y-1">
                          <p className="font-medium">
                            {sortedFunnel[index - 1].stage_name} → {stage.stage_name}
                          </p>
                          <p className="text-muted-foreground">
                            Chuyển đổi: {stage.lead_count}/{sortedFunnel[index - 1].lead_count} leads
                            ({metrics.conversion.toFixed(1)}%)
                          </p>
                          {metrics.dropOff > 0 && (
                            <p className="text-amber-600 dark:text-amber-400">
                              Drop-off: {metrics.dropOff} leads ({metrics.dropOffPercent.toFixed(1)}%)
                            </p>
                          )}
                          {isLowestConversion && (
                            <p className="text-red-500 font-medium">
                              ⚠️ Giai đoạn cần cải thiện nhất!
                            </p>
                          )}
                        </div>
                      </TooltipContent>
                    </Tooltip>
                  )}
                  
                  {/* Funnel Stage - Trapezoid shape with tooltip */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div 
                        className={cn(
                          "relative group cursor-pointer transition-all duration-200 hover:scale-[1.02]",
                          isLowestConversion && "ring-2 ring-red-400/50 ring-offset-1 rounded-sm"
                        )}
                        style={{ width: `${widthPercent}%` }}
                        onClick={() => handleStageClick(stage.stage_id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => e.key === "Enter" && handleStageClick(stage.stage_id)}
                      >
                        {/* Trapezoid shape using clip-path */}
                        <div 
                          className="relative h-14 rounded-sm overflow-hidden transition-all hover:ring-2 hover:ring-primary/30"
                          style={{
                            backgroundColor: bgColor,
                            clipPath: index < sortedFunnel.length - 1 
                              ? 'polygon(3% 0%, 97% 0%, 100% 100%, 0% 100%)'
                              : 'polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)',
                          }}
                        >
                          {/* Content */}
                          <div className="absolute inset-0 flex items-center justify-between px-4">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-white truncate max-w-[120px]">
                                {stage.stage_name}
                              </span>
                              <ChevronRight className="h-4 w-4 text-white/70 opacity-0 group-hover:opacity-100 transition-opacity" />
                            </div>
                            <div className="flex flex-col items-end text-white">
                              <div className="flex items-center gap-1.5">
                                <Users className="h-3.5 w-3.5 opacity-70" />
                                <span className="text-lg font-bold">{stage.lead_count}</span>
                              </div>
                              <span className="text-[10px] opacity-70">
                                {percentage.toFixed(0)}% từ tổng
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-[200px]">
                      <div className="text-xs space-y-1">
                        <p className="font-medium">{stage.stage_name}</p>
                        <p className="text-muted-foreground">
                          {stage.lead_count} leads ({percentage.toFixed(1)}% từ tổng)
                        </p>
                        {index > 0 && (
                          <p className={cn(getConversionColor(metrics.conversion))}>
                            Tỷ lệ chuyển đổi: {metrics.conversion.toFixed(1)}%
                          </p>
                        )}
                        <p className="text-primary/80 pt-1 border-t">
                          Click để xem danh sách leads →
                        </p>
                      </div>
                    </TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </div>
          
          {/* Enhanced Summary Footer */}
          <div className="pt-4 mt-4 border-t">
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Users className="h-3.5 w-3.5" />
                <span>Tổng leads đầu vào: <strong className="text-foreground">{totalLeads}</strong></span>
              </div>
              <div className="flex items-center gap-1.5">
                <Target className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">Hoàn thành:</span>
                <span className={cn("font-semibold", getConversionColor(overallConversion))}>
                  {convertedLeads} ({overallConversion.toFixed(1)}%)
                </span>
              </div>
            </div>
            {totalLeads > convertedLeads && (
              <div className="mt-2 flex items-center gap-1.5 text-[10px] text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-3 w-3" />
                <span>
                  Tổng drop-off: {totalLeads - convertedLeads} leads 
                  ({((totalLeads - convertedLeads) / totalLeads * 100).toFixed(1)}%)
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
