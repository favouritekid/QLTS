// src/components/leads/ActionBanner.tsx
/**
 * ActionBanner - Shows priority action for a lead
 *
 * Priority order:
 * 1. Overdue (is_overdue from backend) - Critical red alert
 * 2. Scheduled appointment (from consultations) - Blue/Amber info
 * 3. Hot lead needing contact - Orange alert
 */
"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  CalendarClock,
  Flame,
  Phone,
  Clock
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";

interface ActionBannerProps {
  lead: Lead;
  onCall?: () => void;
  className?: string;
}

type BannerConfig = {
  type: "overdue" | "scheduled" | "hot_lead";
  priority: "critical" | "high" | "medium";
  message: string;
  action: string | null;
  color: "red" | "amber" | "blue" | "orange";
  icon: React.ElementType;
};

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays > 0) {
    return `${diffDays} ngày trước`;
  }
  if (diffHours > 0) {
    return `${diffHours} giờ trước`;
  }
  return "vừa xong";
}

function formatDateTime(date: Date): string {
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  const time = date.toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (isToday) {
    return `hôm nay lúc ${time}`;
  }

  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) {
    return `ngày mai lúc ${time}`;
  }

  return date.toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getActionBannerConfig(lead: Lead): BannerConfig | null {
  const now = new Date();

  // Priority 1: Overdue check (from cached field)
  if (lead.is_overdue) {
    const overdueDate = lead.next_activity_at ? new Date(lead.next_activity_at) : null;
    return {
      type: "overdue",
      priority: "critical",
      message: overdueDate
        ? `Quá hạn liên hệ ${formatTimeAgo(overdueDate)}`
        : "Quá hạn liên hệ",
      action: "Gọi ngay",
      color: "red",
      icon: AlertTriangle,
    };
  }

  // Priority 2: Scheduled appointment
  const nextConsultation = lead.consultations?.find(
    (c) => c.scheduled_at && new Date(c.scheduled_at) > now
  );
  if (nextConsultation?.scheduled_at) {
    const scheduledDate = new Date(nextConsultation.scheduled_at);
    const diffHours = (scheduledDate.getTime() - now.getTime()) / (1000 * 60 * 60);
    const isSoon = diffHours <= 2 && diffHours > 0;

    return {
      type: "scheduled",
      priority: isSoon ? "high" : "medium",
      message: `Có lịch hẹn ${formatDateTime(scheduledDate)}`,
      action: isSoon ? "Chuẩn bị gọi" : null,
      color: isSoon ? "amber" : "blue",
      icon: isSoon ? Clock : CalendarClock,
    };
  }

  // Priority 3: Hot lead without recent contact
  if (lead.is_hot_lead && lead.cached_urgency_score >= 70) {
    return {
      type: "hot_lead",
      priority: "high",
      message: "Lead tiềm năng cao - Cần liên hệ sớm",
      action: "Gọi ngay",
      color: "orange",
      icon: Flame,
    };
  }

  return null; // No banner needed
}

const colorClasses = {
  red: {
    bg: "bg-red-50 border-red-200",
    text: "text-red-800",
    icon: "text-red-600",
    button: "bg-red-600 hover:bg-red-700 text-white",
  },
  amber: {
    bg: "bg-amber-50 border-amber-200",
    text: "text-amber-800",
    icon: "text-amber-600",
    button: "bg-amber-600 hover:bg-amber-700 text-white",
  },
  blue: {
    bg: "bg-blue-50 border-blue-200",
    text: "text-blue-800",
    icon: "text-blue-600",
    button: "bg-blue-600 hover:bg-blue-700 text-white",
  },
  orange: {
    bg: "bg-orange-50 border-orange-200",
    text: "text-orange-800",
    icon: "text-orange-600",
    button: "bg-orange-600 hover:bg-orange-700 text-white",
  },
};

export function ActionBanner({ lead, onCall, className }: ActionBannerProps) {
  const config = useMemo(() => getActionBannerConfig(lead), [lead]);

  if (!config) {
    return null;
  }

  const Icon = config.icon;
  const colors = colorClasses[config.color];

  const handleCall = () => {
    if (onCall) {
      onCall();
    } else {
      window.open(`tel:${lead.phone}`, "_blank");
    }
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 px-4 py-2.5 rounded-lg border",
        colors.bg,
        className
      )}
    >
      <div className="flex items-center gap-3">
        <Icon className={cn("h-5 w-5 shrink-0", colors.icon)} />
        <span className={cn("text-sm font-medium", colors.text)}>
          {config.message}
        </span>
      </div>

      {config.action && (
        <Button
          size="sm"
          className={cn("shrink-0", colors.button)}
          onClick={handleCall}
        >
          <Phone className="mr-1.5 h-4 w-4" />
          {config.action}
        </Button>
      )}
    </div>
  );
}

export default ActionBanner;
