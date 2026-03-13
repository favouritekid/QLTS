// src/components/leads/PipelineColumn.tsx
"use client";

import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LeadKanbanCard } from "./LeadKanbanCard";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { sanitizeColorCode } from "@/lib/utils";
import type { PipelineStageWithStats } from "@/types/pipeline.types";
import type { Lead } from "@/types/lead.types";

interface PipelineColumnProps {
  stage: PipelineStageWithStats;
  leads: Lead[];
}

// Get column background style from hex color
const getColumnStyle = (hexColor: string) => ({
  backgroundColor: `${hexColor}15`, // 8% opacity for light background
  borderColor: `${hexColor}40`, // 25% opacity for border
});

export function PipelineColumn({ stage, leads }: PipelineColumnProps) {
  const { setNodeRef } = useDroppable({
    id: stage.id,
    // ✅ T2 FIX: Attach stage metadata so drop-on-card can resolve correct target stage
    data: { type: "column", stageId: stage.id },
  });

  // Use stage.color_code from database, fallback to centralized STAGE_COLORS
  const stageHexColor = sanitizeColorCode(stage.color_code) || STAGE_COLORS[stage.id] || "#6B7280";
  const columnStyle = getColumnStyle(stageHexColor);
  const leadIds = leads.map((lead) => lead.id);

  // Stage distribution: % of total leads sitting in this stage
  const distributionPct = stage.stage_distribution_pct ?? 0;
  let TrendIcon = Minus;
  let trendColor = "text-muted-foreground";
  if (distributionPct > 40) {
    TrendIcon = TrendingUp;
    trendColor = "text-success-600";
  } else if (distributionPct < 10) {
    TrendIcon = TrendingDown;
    trendColor = "text-muted-foreground";
  }

  return (
    <div
      ref={setNodeRef}
      className="flex-shrink-0 w-[85vw] sm:w-72 lg:w-80 snap-center lg:snap-align-none"
    >
      <Card className="h-full flex flex-col border-2" style={columnStyle}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-base leading-none">
                {stage.name}
              </h3>
              <p className="text-xs text-muted-foreground mt-1 tabular-nums">
                {stage.lead_count} lead
              </p>
            </div>
            <Badge variant="secondary" className="text-xs">
              {stage.order}
            </Badge>
          </div>

          {/* Statistics */}
          <div className="flex items-center gap-2 mt-2 pt-2 border-t">
            <div className="flex items-center gap-1">
              <TrendIcon className={`h-3 w-3 ${trendColor}`} />
              <span className={`text-xs font-medium tabular-nums ${trendColor}`}>
                {distributionPct.toFixed(0)}%
              </span>
            </div>
            {stage.avg_time_in_stage_days && (
              <div className="text-xs text-muted-foreground tabular-nums">
                <span className="font-medium">
                  {Math.round(stage.avg_time_in_stage_days)} ngày
                </span>{" "}
                TB
              </div>
            )}
          </div>
        </CardHeader>

        <CardContent className="flex-1 overflow-y-auto max-h-[600px] space-y-2 px-3 pb-3">
          <SortableContext items={leadIds} strategy={verticalListSortingStrategy}>
            {leads.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-sm text-muted-foreground border-2 border-dashed rounded-lg">
                Chưa có lead trong giai đoạn này
              </div>
            ) : (
              leads.map((lead) => (
                <LeadKanbanCard key={lead.id} lead={lead} />
              ))
            )}
          </SortableContext>
        </CardContent>
      </Card>
    </div>
  );
}
