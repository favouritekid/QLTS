// src/components/officer/FunnelChart.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { TrendingDown, ArrowRight } from "lucide-react";

interface FunnelStage {
  stage_name: string;
  stage_order: number;
  lead_count: number;
}

interface FunnelChartProps {
  funnel: FunnelStage[];
}

// Color palette for funnel stages - gradient from cool to warm
const STAGE_COLORS = [
  { bg: "bg-blue-500", text: "text-blue-500" },
  { bg: "bg-cyan-500", text: "text-cyan-500" },
  { bg: "bg-teal-500", text: "text-teal-500" },
  { bg: "bg-green-500", text: "text-green-500" },
  { bg: "bg-amber-500", text: "text-amber-500" },
  { bg: "bg-orange-500", text: "text-orange-500" },
  { bg: "bg-red-500", text: "text-red-500" },
];

export function FunnelChart({ funnel }: FunnelChartProps) {
  // Sort by stage order
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);

  // Calculate totals and rates
  const totalLeads = sortedFunnel[0]?.lead_count || 0;
  const convertedLeads = sortedFunnel[sortedFunnel.length - 1]?.lead_count || 0;
  const overallConversion = totalLeads > 0 ? (convertedLeads / totalLeads) * 100 : 0;

  // Calculate step conversion rates
  const stageConversions = sortedFunnel.map((stage, index) => {
    if (index === 0) return 100;
    const prevCount = sortedFunnel[index - 1].lead_count;
    return prevCount > 0 ? (stage.lead_count / prevCount) * 100 : 0;
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base font-medium">
              Pipeline Funnel
            </CardTitle>
            <CardDescription className="text-xs">
              Phân bố leads theo giai đoạn
            </CardDescription>
          </div>
          <div className="flex items-center gap-1.5 text-sm">
            <TrendingDown className="h-4 w-4 text-muted-foreground" />
            <span className="font-semibold">{overallConversion.toFixed(1)}%</span>
            <span className="text-muted-foreground text-xs">tổng</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {sortedFunnel.map((stage, index) => {
          const percentage = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
          const color = STAGE_COLORS[index % STAGE_COLORS.length];
          const stepConversion = stageConversions[index];
          const showConversion = index > 0 && sortedFunnel[index - 1].lead_count > 0;
          
          return (
            <div key={stage.stage_name}>
              {/* Step Conversion Arrow (between stages) */}
              {showConversion && (
                <div className="flex items-center justify-center my-1.5 text-xs text-muted-foreground">
                  <ArrowRight className="h-3 w-3 mr-1" />
                  <span>{stepConversion.toFixed(0)}% chuyển đổi</span>
                </div>
              )}
              
              {/* Stage Bar */}
              <div className="group relative">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <div className={cn("h-2.5 w-2.5 rounded-sm", color.bg)} />
                    <span className="text-sm font-medium">{stage.stage_name}</span>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="font-semibold">{stage.lead_count}</span>
                    <span className="text-muted-foreground w-12 text-right">
                      {percentage.toFixed(0)}%
                    </span>
                  </div>
                </div>
                
                {/* Funnel-style Progress Bar */}
                <div className="relative h-8 bg-muted/50 rounded-lg overflow-hidden">
                  <div 
                    className={cn(
                      "absolute left-0 top-0 h-full rounded-lg transition-all duration-500",
                      color.bg,
                      "opacity-80"
                    )}
                    style={{ 
                      width: `${percentage}%`,
                      minWidth: stage.lead_count > 0 ? "2%" : "0%"
                    }}
                  />
                  {/* Center content in bar */}
                  {stage.lead_count > 0 && percentage > 15 && (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-xs font-medium text-white drop-shadow-sm">
                        {stage.lead_count} leads
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        
        {/* Summary Footer */}
        <div className="pt-3 mt-3 border-t flex items-center justify-between text-xs text-muted-foreground">
          <span>Tổng: {totalLeads} leads</span>
          <span>
            Chuyển đổi: {convertedLeads} ({overallConversion.toFixed(1)}%)
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
