// src/components/officer/FunnelChart.tsx
/**
 * Pipeline Funnel Chart - Visual Funnel Shape
 * Displays leads distribution with actual funnel visualization
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
              Click từng giai đoạn để xem leads
            </CardDescription>
          </div>
          <div className="flex items-center gap-1.5 text-sm">
            <TrendingDown className="h-4 w-4 text-muted-foreground" />
            <span className="font-semibold">{overallConversion.toFixed(1)}%</span>
            <span className="text-muted-foreground text-xs">chuyển đổi</span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {/* Funnel Container */}
        <div className="flex flex-col items-center gap-1">
          {sortedFunnel.map((stage, index) => {
            const percentage = totalLeads > 0 ? (stage.lead_count / totalLeads) * 100 : 0;
            const stepConversion = stageConversions[index];
            const bgColor = getBlueShade(index, sortedFunnel.length);
            
            // Width proportional to actual percentage (min 25%, max 100%)
            const widthPercent = Math.max(25, Math.min(100, percentage + 15));

            return (
              <div key={stage.stage_name} className="w-full flex flex-col items-center">
                {/* Conversion indicator between stages - Fix: Show N/A when previous stage has 0 leads */}
                {index > 0 && (
                  <div className="text-[10px] text-muted-foreground py-0.5">
                    ↓ {sortedFunnel[index - 1].lead_count > 0 ? `${stepConversion.toFixed(0)}%` : "N/A"}
                  </div>
                )}
                
                {/* Funnel Stage - Trapezoid shape */}
                <div 
                  className="relative group cursor-pointer transition-all duration-200 hover:scale-[1.02]"
                  style={{ width: `${widthPercent}%` }}
                  onClick={() => handleStageClick(stage.stage_id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && handleStageClick(stage.stage_id)}
                >
                  {/* Trapezoid shape using clip-path */}
                  <div 
                    className="relative h-12 rounded-sm overflow-hidden transition-all hover:ring-2 hover:ring-primary/30"
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
                      <div className="flex items-center gap-2 text-white">
                        <span className="text-lg font-bold">{stage.lead_count}</span>
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
        </div>
        
        {/* Summary Footer */}
        <div className="pt-4 mt-4 border-t flex items-center justify-between text-xs text-muted-foreground">
          <span>Tổng leads: {totalLeads}</span>
          <span className="font-medium text-foreground">
            Hoàn thành: {convertedLeads} ({overallConversion.toFixed(1)}%)
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
