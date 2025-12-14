// src/components/officer/dashboard/PriorityActionsPanel.tsx
/**
 * Priority Actions Panel
 * Displays AI-powered action suggestions sorted by priority
 */

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Target, Zap } from "lucide-react";
import { PriorityActionCard, type PriorityAction } from "./PriorityActionCard";

interface PriorityActionsPanelProps {
  actions: PriorityAction[];
  onCall?: (leadId: number) => void;
  onSchedule?: (leadId: number) => void;
}

export function PriorityActionsPanel({
  actions,
  onCall,
  onSchedule,
}: PriorityActionsPanelProps) {
  const urgentCount = actions.filter((a) => a.priority === "urgent").length;

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-orange-500" />
            <span>Ưu tiên hàng đầu</span>
          </div>
          <div className="flex items-center gap-2">
            {urgentCount > 0 && (
              <Badge variant="destructive" className="flex items-center gap-1">
                <Zap className="h-3 w-3" />
                {urgentCount} gấp
              </Badge>
            )}
            <Badge variant="secondary">{actions.length}</Badge>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {actions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Target className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm text-muted-foreground">
              Không có hành động ưu tiên
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Tất cả leads đang được xử lý tốt!
            </p>
          </div>
        ) : (
          <ScrollArea className="h-[400px] pr-4">
            <div className="space-y-3">
              {actions.map((action) => (
                <PriorityActionCard
                  key={action.id}
                  action={action}
                  onCall={onCall}
                  onSchedule={onSchedule}
                />
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
