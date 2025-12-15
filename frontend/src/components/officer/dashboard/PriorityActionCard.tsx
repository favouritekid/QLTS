// src/components/officer/dashboard/PriorityActionCard.tsx
/**
 * Priority Action Card - Clean shadcn styling
 * Compact action item with inline quick action buttons
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
  Mail,
  ChevronRight,
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
  onEmail?: (leadId: number) => void;
}

const typeConfig = {
  hot_lead: {
    icon: Flame,
    color: "text-red-500",
    label: "Hot",
  },
  overdue: {
    icon: AlertTriangle,
    color: "text-amber-500",
    label: "Quá hạn",
  },
  scheduled: {
    icon: Calendar,
    color: "text-blue-500",
    label: "Đã hẹn",
  },
  follow_up: {
    icon: MessageSquare,
    color: "text-purple-500",
    label: "Follow up",
  },
  new_lead: {
    icon: Sparkles,
    color: "text-green-500",
    label: "Mới",
  },
};

export function PriorityActionCard({
  action,
  onCall,
  onEmail,
}: PriorityActionCardProps) {
  const config = typeConfig[action.type];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "group p-3 rounded-lg border bg-card transition-all duration-200",
        "hover:border-primary/30 hover:bg-muted/50"
      )}
    >
      <div className="flex items-center gap-3">
        {/* Type Icon */}
        <div className={cn("flex-shrink-0", config.color)}>
          <Icon className="h-4 w-4" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Link
              href={`/leads/${action.lead_id}`}
              className="font-medium text-sm hover:text-primary truncate"
            >
              {action.lead_name}
            </Link>
            {action.lead_score >= 70 && (
              <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                {action.lead_score}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate mt-0.5">
            {action.reason}
          </p>
        </div>

        {/* Days indicator */}
        {action.days_since_contact !== undefined && action.days_since_contact > 0 && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground flex-shrink-0">
            <Clock className="h-3 w-3" />
            <span>{action.days_since_contact}d</span>
          </div>
        )}

        {/* Quick Actions - Icon buttons */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={(e) => {
              e.preventDefault();
              onCall?.(action.lead_id);
            }}
          >
            <Phone className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={(e) => {
              e.preventDefault();
              onEmail?.(action.lead_id);
            }}
          >
            <Mail className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            asChild
          >
            <Link href={`/leads/${action.lead_id}`}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
