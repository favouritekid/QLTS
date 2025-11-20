// src/components/leads/LeadCard.tsx
"use client";

import React from "react";
import { Clock, Phone } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { format, isToday, isPast, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import type { Lead, LeadStatus } from "@/types/lead.types";

// Activity status helpers
type ActivityStatus = "overdue" | "today" | "future" | "none";

const getActivityStatus = (nextActivityAt: string | null | undefined): ActivityStatus => {
  if (!nextActivityAt) return "none";

  const date = parseISO(nextActivityAt);
  if (isPast(date) && !isToday(date)) return "overdue";
  if (isToday(date)) return "today";
  return "future";
};

const getActivityIconColor = (status: ActivityStatus): string => {
  switch (status) {
    case "overdue":
      return "text-red-500";
    case "today":
      return "text-amber-500";
    case "future":
      return "text-blue-500";
    default:
      return "";
  }
};

interface LeadCardProps {
  lead: Lead;
  isSelected: boolean;
  onSelect: (lead: Lead) => void;
}

const getStatusColor = (status: LeadStatus) => {
  switch (status) {
    case "new":
      return "bg-blue-500";
    case "assigned":
      return "bg-purple-500";
    case "contacted":
      return "bg-cyan-500";
    case "qualified":
      return "bg-emerald-500";
    case "unqualified":
      return "bg-gray-500";
    case "converted":
      return "bg-green-500";
    case "rejected":
      return "bg-red-500";
    default:
      return "bg-gray-500";
  }
};

const getScoreColor = (score: number) => {
  if (score >= 80) return "bg-red-100 text-red-700 border-red-200";
  if (score >= 50) return "bg-yellow-100 text-yellow-700 border-yellow-200";
  return "bg-gray-100 text-gray-700 border-gray-200";
};

export const LeadCard = React.memo(function LeadCard({
  lead,
  isSelected,
  onSelect,
}: LeadCardProps) {
  const activityStatus = getActivityStatus(lead.next_activity_at);

  return (
    <Card
      onClick={() => onSelect(lead)}
      className={cn(
        "p-3 cursor-pointer transition-all hover:shadow-md",
        "border-l-4",
        isSelected
          ? "border-l-primary bg-primary/5 ring-1 ring-primary/20"
          : activityStatus === "overdue"
            ? "border-l-red-500 bg-red-50/50 hover:bg-red-50"
            : activityStatus === "today"
              ? "border-l-amber-500 bg-amber-50/50 hover:bg-amber-50"
              : "border-l-transparent hover:bg-accent/50"
      )}
    >
      <div className="space-y-2">
        {/* Name & Phone Row */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-sm truncate">{lead.full_name}</p>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Phone className="h-3 w-3" />
              <span className="truncate">{lead.phone}</span>
            </div>
          </div>

          {/* Activity Indicator */}
          {activityStatus !== "none" && lead.next_activity_at && (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1 shrink-0">
                  <Clock
                    className={cn(
                      "h-4 w-4",
                      getActivityIconColor(activityStatus),
                      activityStatus === "overdue" && "animate-pulse"
                    )}
                  />
                  <span className={cn(
                    "text-xs font-medium",
                    getActivityIconColor(activityStatus)
                  )}>
                    {format(parseISO(lead.next_activity_at), "HH:mm")}
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="left">
                <p className="font-medium">
                  {activityStatus === "overdue" && "Quá hạn"}
                  {activityStatus === "today" && "Hôm nay"}
                  {activityStatus === "future" && "Sắp tới"}
                </p>
                <p className="text-xs">
                  {format(parseISO(lead.next_activity_at), "dd/MM/yyyy HH:mm", { locale: vi })}
                </p>
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        {/* Badges Row */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* Score Badge */}
          <Badge
            variant="outline"
            className={cn("text-[10px] px-1.5 py-0 font-bold", getScoreColor(lead.lead_score))}
          >
            {lead.lead_score}
          </Badge>

          {/* Status Badge */}
          <Badge
            variant="secondary"
            className="text-[10px] px-1.5 py-0"
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full mr-1",
                getStatusColor(lead.status as LeadStatus)
              )}
            />
            {lead.status}
          </Badge>

          {/* Consultation Status Badge */}
          {lead.consultation_status && (
            <Badge
              variant="outline"
              className="text-[10px] px-1.5 py-0"
              style={{
                borderColor: lead.consultation_status.color_code,
                color: lead.consultation_status.color_code
              }}
            >
              {lead.consultation_status.name}
            </Badge>
          )}
        </div>
      </div>
    </Card>
  );
});

export default LeadCard;
