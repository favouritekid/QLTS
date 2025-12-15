// src/components/officer/dashboard/PriorityActionsPanel.tsx
/**
 * Priority Actions Panel - Clean shadcn style
 * Displays priority action stream with quick action buttons
 */

"use client";

import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Target, Zap } from "lucide-react";
import { PriorityActionCard, type PriorityAction } from "./PriorityActionCard";
import { toast } from "sonner";

interface PriorityActionsPanelProps {
  actions: PriorityAction[];
}

export function PriorityActionsPanel({ actions }: PriorityActionsPanelProps) {
  const router = useRouter();
  const urgentCount = actions.filter((a) => a.priority === "urgent").length;

  const handleCall = (leadId: number) => {
    toast.info("Tính năng gọi điện đang phát triển");
  };

  const handleEmail = (leadId: number) => {
    toast.info("Tính năng email đang phát triển");
  };

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
              {actions.length}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {actions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-3">
              <Target className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm text-muted-foreground">
              Không có hành động ưu tiên
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Làm việc tốt lắm! 🎉
            </p>
          </div>
        ) : (
          <ScrollArea className="h-[350px]">
            <div className="space-y-2 pr-3">
              {actions.map((action) => (
                <PriorityActionCard
                  key={action.id}
                  action={action}
                  onCall={handleCall}
                  onEmail={handleEmail}
                />
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
