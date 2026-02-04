// src/components/officer/dashboard/PriorityActionsPanel.tsx
/**
 * Priority Actions Panel - Enhanced version
 * Displays priority action stream with filter tabs and quick action buttons
 */

"use client";

import { useState, useMemo, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Target, Zap, Flame, AlertTriangle, Calendar, Sparkles } from "lucide-react";
import { PriorityActionCard, type PriorityAction } from "./PriorityActionCard";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface PriorityActionsPanelProps {
  actions: PriorityAction[];
}

type FilterType = "all" | "hot_lead" | "overdue" | "scheduled" | "new_lead";

const filterConfig: Record<FilterType, { label: string; icon?: typeof Flame; color?: string }> = {
  all: { label: "Tất cả" },
  hot_lead: { label: "Hot", icon: Flame, color: "text-error-500" },
  overdue: { label: "Quá hạn", icon: AlertTriangle, color: "text-amber-500" },
  scheduled: { label: "Lịch hẹn", icon: Calendar, color: "text-info-500" },
  new_lead: { label: "Mới", icon: Sparkles, color: "text-success-500" },
};

export function PriorityActionsPanel({ actions }: PriorityActionsPanelProps) {
  const [filter, setFilter] = useState<FilterType>("all");
  
  const urgentCount = actions.filter((a) => a.priority === "urgent").length;

  // Filter actions based on selected filter
  const filteredActions = useMemo(() => {
    if (filter === "all") return actions;
    return actions.filter((a) => a.type === filter);
  }, [actions, filter]);

  // Count by type for filter badges
  const countByType = useMemo(() => ({
    all: actions.length,
    hot_lead: actions.filter(a => a.type === "hot_lead").length,
    overdue: actions.filter(a => a.type === "overdue").length,
    scheduled: actions.filter(a => a.type === "scheduled").length,
    new_lead: actions.filter(a => a.type === "new_lead").length,
  }), [actions]);

  // ✅ PERFORMANCE: useCallback prevents PriorityActionCard re-renders
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleCall = useCallback((_leadId: number) => {
    // In real implementation, this would trigger a call modal or redirect
    toast.info("Tính năng gọi điện đang phát triển");
  }, []);

  // ✅ PERFORMANCE: useCallback with stable reference
  const handleZalo = useCallback((_leadId: number, phone?: string) => {
    if (phone) {
      // Clean phone number and open Zalo
      const cleanPhone = phone.replace(/\D/g, '');
      // Zalo deep link format
      window.open(`https://zalo.me/${cleanPhone}`, '_blank');
    } else {
      toast.warning("Lead này chưa có số điện thoại");
    }
  }, []);

  return (
    <Card className="border bg-card h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            Ưu tiên hàng đầu
          </CardTitle>
          <div className="flex items-center gap-2">
            {urgentCount > 0 && (
              <Badge variant="destructive" className="text-xs h-5 px-1.5">
                <Zap className="h-3 w-3 mr-0.5" />
                {urgentCount}
              </Badge>
            )}
            <Badge variant="secondary" className="text-xs h-5">
              {filteredActions.length}
            </Badge>
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="flex flex-wrap gap-1 mt-3">
          {(Object.keys(filterConfig) as FilterType[]).map((key) => {
            const config = filterConfig[key];
            const Icon = config.icon;
            const count = countByType[key];
            
            // Hide filter if no items
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
                {Icon && <Icon className={cn("h-3 w-3", config.color)} />}
                {config.label}
                {key !== "all" && count > 0 && (
                  <span className="text-muted-foreground">({count})</span>
                )}
              </Button>
            );
          })}
        </div>
      </CardHeader>
      <CardContent>
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
          <ScrollArea className="h-[350px]">
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
      </CardContent>
    </Card>
  );
}
