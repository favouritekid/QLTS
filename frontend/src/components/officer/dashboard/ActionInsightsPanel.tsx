// src/components/officer/dashboard/ActionInsightsPanel.tsx
/**
 * Action Insights Panel - Tabbed wrapper combining Priority Actions + Recommendations
 * Reduces right column component count and groups related "action" panels together.
 */

"use client";

import { useState, useMemo, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Target,
  Zap,
  Flame,
  AlertTriangle,
  Calendar,
  Sparkles,
  MessageSquare,
  Lightbulb,
  TrendingUp,
  Clock,
  Trash2,
  PartyPopper,
  ExternalLink,
} from "lucide-react";
import { PriorityActionCard, type PriorityAction } from "./PriorityActionCard";
import { useOfficerRecommendations, type Recommendation } from "@/hooks/officer/useOfficerRecommendations";
import { useDashboardDate } from "@/contexts/DashboardDateContext";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// =============================================================================
// PRIORITY ACTIONS — Filter config & logic (from PriorityActionsPanel)
// =============================================================================

type FilterType = "all" | "hot_lead" | "overdue" | "scheduled" | "follow_up" | "new_lead";

const filterConfig: Record<FilterType, { label: string; icon?: typeof Flame; color?: string }> = {
  all: { label: "Tất cả" },
  hot_lead: { label: "Hot", icon: Flame, color: "text-error-500" },
  overdue: { label: "Quá hạn", icon: AlertTriangle, color: "text-amber-500" },
  scheduled: { label: "Lịch hẹn", icon: Calendar, color: "text-info-500" },
  follow_up: { label: "Follow up", icon: MessageSquare, color: "text-purple-500" },
  new_lead: { label: "Mới", icon: Sparkles, color: "text-success-500" },
};

// =============================================================================
// RECOMMENDATIONS — Priority & type config (from RecommendationsPanel)
// =============================================================================

const priorityConfigRec: Record<
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
// MAIN COMPONENT
// =============================================================================

interface ActionInsightsPanelProps {
  actions: PriorityAction[];
  scope?: "personal" | "team" | "organization" | null;
  officerId?: number | null;
}

export function ActionInsightsPanel({ actions, scope, officerId }: ActionInsightsPanelProps) {
  // When drilling into a specific officer, treat as personal scope for recommendations
  const isPersonal = (!scope || scope === "personal") || officerId != null;

  // --- Priority Actions state ---
  const [filter, setFilter] = useState<FilterType>("all");

  const urgentCount = actions.filter((a) => a.priority === "urgent").length;

  const filteredActions = useMemo(() => {
    if (filter === "all") return actions;
    return actions.filter((a) => a.type === filter);
  }, [actions, filter]);

  const countByType = useMemo(() => ({
    all: actions.length,
    hot_lead: actions.filter(a => a.type === "hot_lead").length,
    overdue: actions.filter(a => a.type === "overdue").length,
    scheduled: actions.filter(a => a.type === "scheduled").length,
    follow_up: actions.filter(a => a.type === "follow_up").length,
    new_lead: actions.filter(a => a.type === "new_lead").length,
  }), [actions]);

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleCall = useCallback((_leadId: number) => {
    toast.info("Tính năng gọi điện đang phát triển");
  }, []);

  const handleZalo = useCallback((_leadId: number, phone?: string) => {
    if (phone) {
      const cleanPhone = phone.replace(/\D/g, '');
      window.open(`https://zalo.me/${cleanPhone}`, '_blank');
    } else {
      toast.warning("Lead này chưa có số điện thoại");
    }
  }, []);

  // --- Recommendations data (always called — Rules of Hooks) ---
  const { startDate, endDate } = useDashboardDate();
  const { data: recsData, isLoading: recsLoading, error: recsError } = useOfficerRecommendations(5, {
    startDate,
    endDate,
    enabled: isPersonal,
    officerId,
  });
  const recommendations = recsData?.recommendations ?? [];

  return (
    <Card className="border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" aria-hidden="true" />
            Hành động
          </CardTitle>
          {urgentCount > 0 && (
            <Badge variant="destructive" className="text-xs h-5 px-1.5">
              <Zap className="h-3 w-3 mr-0.5" aria-hidden="true" />
              {urgentCount}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="priority">
          <TabsList className="w-full">
            <TabsTrigger value="priority" className="flex-1 gap-1">
              Ưu tiên
              <Badge variant="secondary" className="text-[10px] h-4 px-1 ml-0.5">
                {actions.length}
              </Badge>
            </TabsTrigger>
            {isPersonal && (
              <TabsTrigger value="recommendations" className="flex-1 gap-1">
                Khuyến nghị
                {recommendations.length > 0 && (
                  <Badge variant="secondary" className="text-[10px] h-4 px-1 ml-0.5">
                    {recommendations.length}
                  </Badge>
                )}
              </TabsTrigger>
            )}
          </TabsList>

          {/* Tab: Ưu tiên */}
          <TabsContent value="priority">
            {/* Sub-filter */}
            <div className="flex flex-wrap gap-1 mb-3">
              {(Object.keys(filterConfig) as FilterType[]).map((key) => {
                const config = filterConfig[key];
                const Icon = config.icon;
                const count = countByType[key];

                if (key !== "all" && count === 0) return null;

                return (
                  <Button
                    key={key}
                    variant="ghost"
                    size="sm"
                    onClick={() => setFilter(key)}
                    className={cn(
                      "h-6 px-2 text-xs font-medium gap-1",
                      filter === key
                        ? "bg-muted shadow-sm"
                        : "hover:bg-muted/50"
                    )}
                  >
                    {Icon && <Icon className={cn("h-3 w-3", config.color)} aria-hidden="true" />}
                    {config.label}
                    {key !== "all" && count > 0 && (
                      <span className="text-muted-foreground">({count})</span>
                    )}
                  </Button>
                );
              })}
            </div>

            {/* Priority actions list */}
            {filteredActions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-3">
                  <Target className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground">
                  {filter === "all" ? "Không có hành động ưu tiên" : `Không có mục ${filterConfig[filter].label.toLowerCase()}`}
                </p>
                {filter === "all" && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Làm việc tốt lắm! 🎉
                  </p>
                )}
              </div>
            ) : (
              <ScrollArea className="h-[320px] virtual-list">
                <div className="space-y-2 pr-3">
                  {filteredActions.map((action) => (
                    <PriorityActionCard
                      key={action.id}
                      action={action}
                      onCall={handleCall}
                      onZalo={handleZalo}
                    />
                  ))}
                </div>
              </ScrollArea>
            )}
          </TabsContent>

          {/* Tab: Khuyến nghị (personal scope only) */}
          {isPersonal && (
            <TabsContent value="recommendations">
              {recsLoading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-20 w-full" />
                  ))}
                </div>
              ) : recsError ? (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <AlertTriangle aria-hidden="true" className="h-8 w-8 text-muted-foreground mb-2" />
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
                <ScrollArea className="h-[320px]">
                  <div className="space-y-2.5 pr-3">
                    {recommendations.map((rec, index) => (
                      <RecommendationCard key={`${rec.type}-${index}`} recommendation={rec} />
                    ))}
                  </div>
                </ScrollArea>
              )}
            </TabsContent>
          )}
        </Tabs>
      </CardContent>
    </Card>
  );
}

// =============================================================================
// RECOMMENDATION CARD (inlined from RecommendationsPanel)
// =============================================================================

function RecommendationCard({ recommendation }: { recommendation: Recommendation }) {
  const config = priorityConfigRec[recommendation.priority];
  const Icon = typeIconMap[recommendation.type] || Lightbulb;

  return (
    <div
      className={cn(
        "rounded-lg border p-3 transition-colors hover:shadow-sm",
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
          <Icon className={cn("h-4 w-4", config.color)} aria-hidden="true" />
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
              <TrendingUp aria-hidden="true" className="h-3 w-3" />
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
