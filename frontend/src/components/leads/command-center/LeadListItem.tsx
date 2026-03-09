// src/components/leads/command-center/LeadListItem.tsx
"use client";

import React from "react";
import { Phone, Mail, UserPlus, Flame, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { format, isToday, isPast, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import type { Lead, LeadStatus } from "@/types/lead.types";
import { getLeadStatusLabel } from "@/constants";

// Activity status helpers
type ActivityStatus = "overdue" | "today" | "future" | "none";

const getActivityStatus = (nextActivityAt: string | null | undefined): ActivityStatus => {
  if (!nextActivityAt) return "none";

  const date = parseISO(nextActivityAt);
  if (isPast(date) && !isToday(date)) return "overdue";
  if (isToday(date)) return "today";
  return "future";
};

const getActivityBadgeStyle = (status: ActivityStatus): string => {
  switch (status) {
    case "overdue":
      return "bg-error-100 text-error-700 border-error-300";
    case "today":
      return "bg-warning-100 text-warning-700 border-warning-300";
    case "future":
      return "bg-info-50 text-info-600 border-info-200";
    default:
      return "";
  }
};

const getActivityLabel = (status: ActivityStatus): string => {
  switch (status) {
    case "overdue":
      return "Quá hạn";
    case "today":
      return "Hôm nay";
    case "future":
      return "Sắp tới";
    default:
      return "";
  }
};

interface LeadListItemProps {
  lead: Lead;
  isSelected: boolean;
  onSelect: (lead: Lead) => void;
  onQuickAssign?: (lead: Lead) => void;
}

const getStatusBadgeVariant = (status: LeadStatus) => {
  switch (status) {
    case "new":
      return "default";
    case "assigned":
      return "secondary";
    case "contacted":
      return "outline";
    case "qualified":
      return "default";
    case "unqualified":
      return "destructive";
    case "converted":
      return "default";
    case "rejected":
      return "destructive";
    default:
      return "secondary";
  }
};

const getStatusColor = (status: LeadStatus) => {
  switch (status) {
    case "new":
      return "bg-info-500";
    case "assigned":
      return "bg-purple-500";
    case "contacted":
      return "bg-cyan-500";
    case "qualified":
      return "bg-success-500";
    case "unqualified":
      return "bg-muted-foreground";
    case "converted":
      return "bg-success-500";
    case "rejected":
      return "bg-error-500";
    default:
      return "bg-muted-foreground";
  }
};

const getScoreColor = (score: number) => {
  if (score >= 80) return "bg-error-100 text-error-700 border-error-200";
  if (score >= 50) return "bg-warning-100 text-warning-700 border-warning-200";
  return "bg-muted text-muted-foreground border-border";
};

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

export const LeadListItem = React.memo(function LeadListItem({
  lead,
  isSelected,
  onSelect,
  onQuickAssign,
}: LeadListItemProps) {
  const isHighScore = lead.lead_score >= 80;
  const activityStatus = getActivityStatus(lead.next_activity_at);

  return (
    <div
      onClick={() => onSelect(lead)}
      className={cn(
        "group relative p-3 border-b cursor-pointer transition-colors",
        "hover:bg-accent/50",
        isSelected && "bg-accent border-l-2 border-l-primary",
        // Activity urgency indicators
        !isSelected && activityStatus === "overdue" && "border-l-2 border-l-error-500 bg-error-50/30",
        !isSelected && activityStatus === "today" && "border-l-2 border-l-warning-500 bg-warning-50/30"
      )}
    >
      <div className="flex items-start gap-3">
        {/* Avatar */}
        <Avatar className="h-10 w-10 shrink-0">
          <AvatarFallback className="text-xs font-medium bg-primary/10 text-primary">
            {getInitials(lead.full_name)}
          </AvatarFallback>
        </Avatar>

        {/* Main Content */}
        <div className="flex-1 min-w-0 space-y-1">
          {/* Name & Score Row */}
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm truncate">{lead.full_name}</span>
            {isHighScore && (
              <Flame className="h-3.5 w-3.5 text-orange-500 shrink-0" />
            )}
          </div>

          {/* Contact Info */}
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="truncate">{lead.phone}</span>
            <span className="truncate hidden sm:inline">{lead.email}</span>
          </div>

          {/* Badges Row */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Score Badge */}
            <Badge
              variant="outline"
              className={cn("text-[10px] px-1.5 py-0", getScoreColor(lead.lead_score))}
            >
              {lead.lead_score}
            </Badge>

            {/* Status Badge */}
            <Badge
              variant={getStatusBadgeVariant(lead.status as LeadStatus)}
              className="text-[10px] px-1.5 py-0"
            >
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full mr-1",
                  getStatusColor(lead.status as LeadStatus)
                )}
              />
              {getLeadStatusLabel(lead.status as LeadStatus)}
            </Badge>

            {/* Offering Badge */}
            {lead.offering && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                {lead.offering.program?.name || lead.offering.offering_type}
              </Badge>
            )}

            {/* Activity Status Badge */}
            {activityStatus !== "none" && lead.next_activity_at && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] px-1.5 py-0",
                      getActivityBadgeStyle(activityStatus)
                    )}
                  >
                    <Clock className={cn(
                      "h-2.5 w-2.5 mr-1",
                      activityStatus === "overdue" && "animate-pulse"
                    )} />
                    {getActivityLabel(activityStatus)}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  <p>
                    {format(parseISO(lead.next_activity_at), "dd/MM/yyyy HH:mm", { locale: vi })}
                  </p>
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Quick Actions (Visible on Hover) */}
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={(e) => {
              e.stopPropagation();
              window.location.href = `tel:${lead.phone}`;
            }}
            aria-label="Gọi điện"
          >
            <Phone className="h-3.5 w-3.5" />
          </Button>
          {lead.email && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation();
                window.location.href = `mailto:${lead.email}`;
              }}
              aria-label="Gửi email"
            >
              <Mail className="h-3.5 w-3.5" />
            </Button>
          )}
          {!lead.assigned_officer && onQuickAssign && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation();
                onQuickAssign(lead);
              }}
              aria-label="Phân công"
            >
              <UserPlus className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Assigned Officer */}
      {lead.assigned_officer && (
        <div className="mt-2 pt-2 border-t border-dashed">
          <span className="text-[10px] text-muted-foreground">
            Phân công: <span className="font-medium">{lead.assigned_officer.full_name}</span>
          </span>
        </div>
      )}
    </div>
  );
});
