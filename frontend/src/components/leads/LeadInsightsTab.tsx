// src/components/leads/LeadInsightsTab.tsx
/**
 * LeadInsightsTab - Enhanced AI insights bar with visual gauges and helper tooltips
 */
"use client";

import { HelpCircle, Users, Target, Clock, Star, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { InsightsHelperDrawer } from "@/components/leads/InsightsHelperDrawer";
import type { LeadInsights, Lead } from "@/types/lead.types";

interface LeadInsightsTabProps {
  leadId: number;
  insights?: LeadInsights;
  /** Optional Lead object to use cached_urgency_score */
  lead?: Lead;
}

// Helper tooltips - ngắn gọn để xem nhanh
const INSIGHT_HELPERS = {
  overall: {
    label: "Điểm tổng hợp",
    icon: Sparkles,
    tooltip: "Điểm cao = lead tiềm năng, ưu tiên chăm sóc",
    color: "text-violet-600",
    bgColor: "bg-violet-100",
    borderColor: "border-violet-200",
  },
  engagement: {
    label: "Mức độ tương tác",
    icon: Users,
    tooltip: "Điểm cao = lead đã được tư vấn nhiều, phản hồi tốt",
    color: "text-blue-600",
    bgColor: "bg-blue-100",
    borderColor: "border-blue-200",
  },
  fit: {
    label: "Phù hợp",
    icon: Target,
    tooltip: "Điểm cao = phù hợp với chương trình",
    color: "text-green-600",
    bgColor: "bg-green-100",
    borderColor: "border-green-200",
  },
  urgency: {
    label: "Khẩn cấp",
    icon: Clock,
    tooltip: "Điểm cao = cần liên hệ ngay!",
    color: "text-orange-600",
    bgColor: "bg-orange-100",
    borderColor: "border-orange-200",
  },
};

const getScoreStatus = (score: number) => {
  if (score >= 70) return { label: "Xuất sắc", color: "text-green-600", bg: "bg-green-500" };
  if (score >= 50) return { label: "Tốt", color: "text-blue-600", bg: "bg-blue-500" };
  if (score >= 30) return { label: "Trung bình", color: "text-yellow-600", bg: "bg-yellow-500" };
  return { label: "Thấp", color: "text-gray-500", bg: "bg-gray-400" };
};

// Urgency có logic màu ngược lại: cao = cảnh báo đỏ, thấp = an toàn xanh
const getUrgencyStatus = (score: number) => {
  if (score >= 70) return { label: "Rất gấp!", color: "text-red-600", bg: "bg-red-500" };
  if (score >= 50) return { label: "Cần sớm", color: "text-orange-600", bg: "bg-orange-500" };
  if (score >= 30) return { label: "Bình thường", color: "text-yellow-600", bg: "bg-yellow-500" };
  return { label: "Không gấp", color: "text-green-600", bg: "bg-green-500" };
};

interface MetricCardProps {
  metricKey: keyof typeof INSIGHT_HELPERS;
  value: number;
  isMain?: boolean;
}

function MetricCard({ metricKey, value, isMain }: MetricCardProps) {
  const config = INSIGHT_HELPERS[metricKey];
  // Urgency dùng logic màu ngược (cao = đỏ cảnh báo)
  const status = metricKey === "urgency" ? getUrgencyStatus(value) : getScoreStatus(value);
  const Icon = config.icon;

  return (
    <div className={cn(
      "rounded-lg border p-3 transition-all",
      isMain 
        ? "bg-gradient-to-br from-violet-50 to-purple-50 border-violet-200 shadow-sm" 
        : "bg-white/50 hover:bg-white hover:shadow-sm",
      config.borderColor
    )}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={cn("p-1.5 rounded-md", config.bgColor)}>
            <Icon className={cn("h-4 w-4", config.color)} />
          </div>
          <span className={cn(
            "font-medium",
            isMain ? "text-base" : "text-sm"
          )}>
            {config.label}
          </span>
        </div>
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle className="h-4 w-4 text-muted-foreground/50 cursor-help hover:text-muted-foreground transition-colors" />
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-[200px] text-xs">
              <p>{config.tooltip}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      <div className="space-y-2">
        <div className="flex items-baseline gap-2">
          <span className={cn(
            "font-bold tabular-nums",
            isMain ? "text-3xl" : "text-2xl",
            status.color
          )}>
            {value}
          </span>
          <span className="text-muted-foreground text-sm">/100</span>
          {isMain && (
            <Badge variant="secondary" className={cn("ml-auto text-xs", status.color)}>
              {status.label}
            </Badge>
          )}
        </div>
        <Progress 
          value={value} 
          className={cn("h-2", isMain ? "h-2.5" : "h-1.5")}
        />
      </div>
    </div>
  );
}

export function LeadInsightsTab({ insights, lead }: LeadInsightsTabProps) {
  if (!insights) {
    return (
      <div className="grid grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-lg border p-3">
            <Skeleton className="h-4 w-20 mb-3" />
            <Skeleton className="h-8 w-16 mb-2" />
            <Skeleton className="h-2 w-full" />
          </div>
        ))}
      </div>
    );
  }

  // Use cached_urgency_score from Lead if available, otherwise fall back to API
  const urgencyScore = lead?.cached_urgency_score ?? insights.urgency_score;

  return (
    <div className="space-y-3">
      {/* Main metric + secondary metrics grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard 
          metricKey="overall" 
          value={insights.overall_score} 
          isMain 
        />
        <MetricCard 
          metricKey="engagement" 
          value={insights.engagement_score} 
        />
        <MetricCard 
          metricKey="fit" 
          value={insights.fit_score} 
        />
        <MetricCard 
          metricKey="urgency" 
          value={urgencyScore} 
        />
      </div>

      {/* Helper drawer trigger */}
      <div className="flex justify-end">
        <InsightsHelperDrawer />
      </div>

      {/* Officer feedback if available */}
      {(insights.officer_rating || insights.officer_summary) && (
        <div className="flex items-center gap-4 p-2 bg-amber-50/50 rounded-lg border border-amber-200/50 text-sm">
          <div className="flex items-center gap-1.5">
            <Star className="h-4 w-4 text-amber-500" />
            <span className="text-muted-foreground">Đánh giá TV:</span>
            {insights.officer_rating && (
              <div className="flex items-center gap-0.5">
                {[...Array(5)].map((_, i) => (
                  <span 
                    key={i}
                    className={cn(
                      "text-sm",
                      i < insights.officer_rating! ? "text-amber-400" : "text-gray-300"
                    )}
                  >
                    ★
                  </span>
                ))}
              </div>
            )}
          </div>
          {insights.officer_summary && (
            <p className="text-muted-foreground truncate flex-1" title={insights.officer_summary}>
              &ldquo;{insights.officer_summary}&rdquo;
            </p>
          )}
        </div>
      )}
    </div>
  );
}
