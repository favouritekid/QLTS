// src/components/officer/dashboard/PriorityActionCard.tsx
/**
 * Single Priority Action Card
 * Displays an AI-recommended action with quick action buttons
 */

"use client";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Flame,
  AlertTriangle,
  Calendar,
  MessageSquare,
  Sparkles,
  Phone,
  ExternalLink,
  Clock,
} from "lucide-react";
import Link from "next/link";

export interface PriorityAction {
  id: string;
  type: "hot_lead" | "overdue" | "scheduled" | "follow_up" | "new_lead";
  priority: "urgent" | "high" | "medium";
  lead_id: number;
  lead_name: string;
  lead_score: number;
  reason: string;
  days_since_contact?: number;
}

interface PriorityActionCardProps {
  action: PriorityAction;
  onCall?: (leadId: number) => void;
  onSchedule?: (leadId: number) => void;
}

const typeConfig = {
  hot_lead: {
    icon: Flame,
    color: "text-red-500",
    bg: "bg-red-50 dark:bg-red-950/30",
    border: "border-red-200 dark:border-red-800",
  },
  overdue: {
    icon: AlertTriangle,
    color: "text-amber-500",
    bg: "bg-amber-50 dark:bg-amber-950/30",
    border: "border-amber-200 dark:border-amber-800",
  },
  scheduled: {
    icon: Calendar,
    color: "text-blue-500",
    bg: "bg-blue-50 dark:bg-blue-950/30",
    border: "border-blue-200 dark:border-blue-800",
  },
  follow_up: {
    icon: MessageSquare,
    color: "text-purple-500",
    bg: "bg-purple-50 dark:bg-purple-950/30",
    border: "border-purple-200 dark:border-purple-800",
  },
  new_lead: {
    icon: Sparkles,
    color: "text-green-500",
    bg: "bg-green-50 dark:bg-green-950/30",
    border: "border-green-200 dark:border-green-800",
  },
};

const priorityConfig = {
  urgent: {
    badge: "destructive" as const,
    label: "Gấp",
  },
  high: {
    badge: "default" as const,
    label: "Cao",
  },
  medium: {
    badge: "secondary" as const,
    label: "TB",
  },
};

export function PriorityActionCard({
  action,
  onCall,
  onSchedule,
}: PriorityActionCardProps) {
  const config = typeConfig[action.type];
  const priorityBadge = priorityConfig[action.priority];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "p-3 rounded-lg border transition-all duration-200",
        "hover:shadow-md hover:scale-[1.01]",
        config.bg,
        config.border
      )}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className={cn("mt-0.5 flex-shrink-0", config.color)}>
          <Icon className="h-5 w-5" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Header: Name + Priority */}
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              href={`/leads/${action.lead_id}`}
              className="font-medium text-sm hover:underline truncate"
            >
              {action.lead_name}
            </Link>
            {action.priority === "urgent" && (
              <Badge variant={priorityBadge.badge} className="text-xs h-5">
                {priorityBadge.label}
              </Badge>
            )}
            {action.lead_score >= 70 && (
              <Badge variant="outline" className="text-xs h-5">
                {action.lead_score} điểm
              </Badge>
            )}
          </div>

          {/* Reason */}
          <p className="text-xs text-muted-foreground mt-1 line-clamp-1">
            {action.reason}
          </p>

          {/* Days since contact */}
          {action.days_since_contact !== undefined && action.days_since_contact > 0 && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
              <Clock className="h-3 w-3" />
              <span>{action.days_since_contact} ngày trước</span>
            </div>
          )}

          {/* Quick Actions */}
          <div className="flex gap-2 mt-2">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => onCall?.(action.lead_id)}
            >
              <Phone className="h-3 w-3 mr-1" />
              Gọi
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => onSchedule?.(action.lead_id)}
            >
              <Calendar className="h-3 w-3 mr-1" />
              Hẹn
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              asChild
            >
              <Link href={`/leads/${action.lead_id}`}>
                <ExternalLink className="h-3 w-3 mr-1" />
                Xem
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
