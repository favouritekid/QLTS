// src/components/officer/dashboard/PriorityActionCard.tsx
/**
 * Priority Action Card - Enhanced version
 * Compact action item with Zalo, Phone, and navigation buttons
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
  ChevronRight,
  Clock,
  MessageCircle,
} from "lucide-react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { vi } from "date-fns/locale";

export interface PriorityAction {
  id: string;
  type: "hot_lead" | "overdue" | "scheduled" | "follow_up" | "new_lead";
  priority: "urgent" | "high" | "medium";
  lead_id: number;
  lead_name: string;
  lead_score: number;
  reason: string;
  phone?: string;
  days_since_contact?: number;
  last_contact_at?: string;
}

interface PriorityActionCardProps {
  action: PriorityAction;
  onCall?: (leadId: number) => void;
  onZalo?: (leadId: number, phone?: string) => void;
}

const typeConfig = {
  hot_lead: {
    icon: Flame,
    color: "text-error-500",
    label: "Hot",
  },
  overdue: {
    icon: AlertTriangle,
    color: "text-warning-500",
    label: "Quá hạn",
  },
  scheduled: {
    icon: Calendar,
    color: "text-info-500",
    label: "Đã hẹn",
  },
  follow_up: {
    icon: MessageSquare,
    color: "text-purple-500",
    label: "Follow up",
  },
  new_lead: {
    icon: Sparkles,
    color: "text-success-500",
    label: "Mới",
  },
};

// Lead score badge color based on score
const getScoreBadgeClass = (score: number) => {
  if (score >= 80) return "bg-error-100 text-error-700 dark:bg-error-900/30 dark:text-error-400";
  if (score >= 60) return "bg-warning-100 text-warning-700 dark:bg-warning-900/30 dark:text-warning-400";
  return "bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground";
};

export function PriorityActionCard({
  action,
  onCall,
  onZalo,
}: PriorityActionCardProps) {
  const config = typeConfig[action.type];
  const Icon = config.icon;

  // Format last contact time
  const lastContactDisplay = action.last_contact_at && !isNaN(new Date(action.last_contact_at).getTime())
    ? formatDistanceToNow(new Date(action.last_contact_at), { addSuffix: true, locale: vi })
    : action.days_since_contact !== undefined && action.days_since_contact > 0
      ? `${action.days_since_contact} ngày trước`
      : null;

  return (
    <div
      className={cn(
        "group p-3 rounded-lg border bg-card transition-all duration-200",
        "hover:border-primary/30 hover:bg-muted/50",
        action.priority === "urgent" && "border-l-2 border-l-error-500"
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
            {/* Enhanced lead score badge */}
            <Badge 
              variant="secondary" 
              className={cn("text-[10px] h-4 px-1.5 font-mono", getScoreBadgeClass(action.lead_score))}
            >
              {action.lead_score}
            </Badge>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-xs text-muted-foreground truncate flex-1">
              {action.reason}
            </p>
            {/* Last contact time */}
            {lastContactDisplay && (
              <span className="text-[10px] text-muted-foreground flex items-center gap-1 flex-shrink-0">
                <Clock className="h-3 w-3" />
                {lastContactDisplay}
              </span>
            )}
          </div>
        </div>

        {/* Quick Actions - Icon buttons */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {/* Phone button */}
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label="Gọi điện"
            onClick={(e) => {
              e.preventDefault();
              onCall?.(action.lead_id);
            }}
          >
            <Phone className="h-3.5 w-3.5" />
          </Button>
          {/* Zalo button */}
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 text-info-500 hover:text-info-600 hover:bg-info-50"
            aria-label="Chat Zalo"
            onClick={(e) => {
              e.preventDefault();
              onZalo?.(action.lead_id, action.phone);
            }}
          >
            <MessageCircle className="h-3.5 w-3.5" />
          </Button>
          {/* View detail button */}
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label="Xem chi tiết"
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
