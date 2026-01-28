// src/components/officer/dashboard/RecommendationsPanel.tsx
/**
 * Phase 7: Auto Recommendations Panel
 * Displays AI-powered actionable recommendations based on KPI performance.
 */

"use client";

import { useOfficerRecommendations, type Recommendation } from "@/hooks/officer/useOfficerRecommendations";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  Lightbulb,
  TrendingUp,
  Clock,
  Flame,
  Trash2,
  PartyPopper,
  Sparkles,
  AlertTriangle,
  ExternalLink,
} from "lucide-react";

// =============================================================================
// TYPES
// =============================================================================

// Types are now imported from officer.ts

// =============================================================================
// PRIORITY CONFIG
// =============================================================================

const priorityConfig: Record<
  Recommendation["priority"],
  { color: string; bgColor: string; label: string }
> = {
  critical: {
    color: "text-error-600 dark:text-error-400",
    bgColor: "bg-error-50 dark:bg-error-950/30 border-error-200 dark:border-error-900",
    label: "Khẩn cấp",
  },
  high: {
    color: "text-warning-600 dark:text-warning-400",
    bgColor: "bg-warning-50 dark:bg-warning-950/30 border-warning-200 dark:border-warning-900",
    label: "Cao",
  },
  medium: {
    color: "text-info-600 dark:text-info-400",
    bgColor: "bg-info-50 dark:bg-info-950/30 border-info-200 dark:border-info-900",
    label: "Trung bình",
  },
  low: {
    color: "text-success-600 dark:text-success-400",
    bgColor: "bg-success-50 dark:bg-success-950/30 border-success-200 dark:border-success-900",
    label: "Thấp",
  },
};

const typeIconMap: Record<string, typeof Lightbulb> = {
  increase_activity: TrendingUp,
  improve_conversion: TrendingUp,
  reduce_response_time: Clock,
  focus_hot_leads: Flame,
  clear_stale_leads: Trash2,
  balance_workload: TrendingUp,
  celebrate_success: PartyPopper,
  maintain_momentum: Sparkles,
};

// =============================================================================
// API
// =============================================================================

// fetchRecommendations removed as it is now a hook

// =============================================================================
// COMPONENT
// =============================================================================

interface RecommendationsPanelProps {
  /** Maximum recommendations to show */
  limit?: number;
  /** Optional class name */
  className?: string;
}

export function RecommendationsPanel({ limit = 5, className }: RecommendationsPanelProps) {
  const { data, isLoading, error } = useOfficerRecommendations(limit);

  const recommendations = data?.recommendations ?? [];

  // Count by priority
  const criticalCount = recommendations.filter((r) => r.priority === "critical").length;
  const highCount = recommendations.filter((r) => r.priority === "high").length;

  return (
    <Card className={cn("border bg-card", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-amber-500" />
            Khuyến nghị hôm nay
          </CardTitle>
          <div className="flex items-center gap-1.5">
            {criticalCount > 0 && (
              <Badge variant="destructive" className="text-xs h-5 px-1.5">
                <AlertTriangle className="h-3 w-3 mr-0.5" />
                {criticalCount}
              </Badge>
            )}
            {highCount > 0 && (
              <Badge variant="secondary" className="text-xs h-5 px-1.5 bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300">
                {highCount}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <AlertTriangle className="h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">Không thể tải khuyến nghị</p>
          </div>
        ) : recommendations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="h-12 w-12 rounded-full bg-success-100 dark:bg-success-900/30 flex items-center justify-center mb-3">
              <PartyPopper className="h-6 w-6 text-success-600 dark:text-success-400" />
            </div>
            <p className="text-sm font-medium">Tuyệt vời!</p>
            <p className="text-xs text-muted-foreground mt-1">
              Không có khuyến nghị nào. Bạn đang làm rất tốt! 🎉
            </p>
          </div>
        ) : (
          <ScrollArea className="h-[300px]">
            <div className="space-y-2.5 pr-3">
              {recommendations.map((rec, index) => (
                <RecommendationCard key={`${rec.type}-${index}`} recommendation={rec} />
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

// =============================================================================
// RECOMMENDATION CARD
// =============================================================================

function RecommendationCard({ recommendation }: { recommendation: Recommendation }) {
  const config = priorityConfig[recommendation.priority];
  const Icon = typeIconMap[recommendation.type] || Lightbulb;

  return (
    <div
      className={cn(
        "rounded-lg border p-3 transition-all hover:shadow-sm",
        config.bgColor
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "h-8 w-8 rounded-full flex items-center justify-center flex-shrink-0",
            recommendation.priority === "critical" && "bg-error-100 dark:bg-error-900/50",
            recommendation.priority === "high" && "bg-warning-100 dark:bg-warning-900/50",
            recommendation.priority === "medium" && "bg-info-100 dark:bg-info-900/50",
            recommendation.priority === "low" && "bg-success-100 dark:bg-success-900/50"
          )}
        >
          <Icon className={cn("h-4 w-4", config.color)} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium truncate">{recommendation.title}</span>
            {recommendation.priority === "critical" && (
              <Badge variant="destructive" className="text-[10px] h-4 px-1">
                {config.label}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {recommendation.message}
          </p>
          {recommendation.expected_impact && (
            <p className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />
              {recommendation.expected_impact}
            </p>
          )}
          {recommendation.action && recommendation.action_link && (
            <Button
              asChild
              variant="link"
              size="sm"
              className={cn("h-auto p-0 mt-2 text-xs", config.color)}
            >
              <Link href={recommendation.action_link}>
                {recommendation.action}
                <ExternalLink className="h-3 w-3 ml-1" />
              </Link>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
