// src/components/officer/FunnelChart.tsx
/**
 * Pipeline Funnel Chart - Monochromatic Blue Design
 * Clean, professional visualization following shadcn standards
 */
"use client";

import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TrendingDown, ChevronRight } from "lucide-react";

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
  // HSL: 221 83% X% - varying lightness from 45% to 75%
  const lightness = 45 + (index / Math.max(total - 1, 1)) * 30;
  return `hsl(221 83% ${lightness}%)`;
};

export function FunnelChart({ funnel }: FunnelChartProps) {
  const router = useRouter();

  // Sort by stage order
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);

  // Calculate totals
  const totalLeads = sortedFunnel[0]?.lead_count || 0;
  const convertedLeads = sortedFunnel[sortedFunnel.length - 1]?.lead_count || 0;
  const overallConversion = totalLeads > 0 ? (convertedLeads / totalLeads) * 100 : 0;

  // Calculate step conversion rates  
  const stageConversions = sortedFunnel.map((stage, index) => {
    if (index === 0) return 100;
    const prevCount = sortedFunnel[index - 1].lead_count;
    return prevCount > 0 ? (stage.lead_count / prevCount) * 100 : 0;
  });

  // Navigate to leads filtered by stage
  const handleStageClick = (stageId: string) => {
    router.push(`/leads?stage=${stageId}`);
  };

  return (
    <Card className="border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pipeline Funnel
            </CardTitle>
            <CardDescription className="text-xs mt-0.5">
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
      <CardContent className="space-y-2">
        {sortedFunnel.map((stage, index) => {
          const percentage = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
          const stepConversion = stageConversions[index];
          const showConversion = index > 0 && sortedFunnel[index - 1].lead_count > 0;
          const bgColor = getBlueShade(index, sortedFunnel.length);
          
          return (
            <div key={stage.stage_name}>
              {/* Step Conversion (between stages) */}
              {showConversion && (
                <div className="flex items-center justify-center py-1 text-xs text-muted-foreground">
                  <ChevronRight className="h-3 w-3 rotate-90 mr-1" />
                  <span>{stepConversion.toFixed(0)}%</span>
                </div>
              )}
              
              {/* Stage Bar - Clickable */}
              <div 
                className="group relative cursor-pointer"
                onClick={() => handleStageClick(stage.stage_id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && handleStageClick(stage.stage_id)}
              >
                {/* Bar Container */}
                <div className="relative h-10 bg-muted/40 rounded overflow-hidden hover:bg-muted/60 transition-all hover:ring-2 hover:ring-primary/20">
                  {/* Colored Bar */}
                  <div 
                    className="absolute left-0 top-0 h-full rounded transition-all duration-300 group-hover:brightness-110"
                    style={{ 
                      width: `${Math.max(percentage, 2)}%`,
                      backgroundColor: bgColor,
                    }}
                  />
                  
                  {/* Content Overlay */}
                  <div className="absolute inset-0 flex items-center justify-between px-3">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-sm font-medium z-10",
                        percentage > 40 ? "text-white" : "text-foreground"
                      )}>
                        {stage.stage_name}
                      </span>
                      <ChevronRight className={cn(
                        "h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity",
                        percentage > 40 ? "text-white" : "text-muted-foreground"
                      )} />
                    </div>
                    <div className={cn(
                      "flex items-center gap-2 text-sm z-10",
                      percentage > 60 ? "text-white" : "text-foreground"
                    )}>
                      <span className="font-semibold">{stage.lead_count}</span>
                      <span className="text-xs opacity-70">
                        ({percentage.toFixed(0)}%)
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
        
        {/* Summary Footer */}
        <div className="pt-3 mt-2 border-t flex items-center justify-between text-xs text-muted-foreground">
          <span>Tổng: {totalLeads} leads</span>
          <span>
            Hoàn thành: {convertedLeads} ({overallConversion.toFixed(1)}%)
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
