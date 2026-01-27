// src/components/leads/ActionBanner.tsx
/**
 * ActionBanner - Shows priority action for a lead (wireframe design)
 *
 * Priority order:
 * 1. Overdue (is_overdue from backend) - Critical red alert
 * 2. Scheduled appointment (from consultations) - Amber/Blue info
 * 3. Hot lead needing contact - Orange alert
 */
"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  Bell,
  Flame,
  Phone,
  Clock,
  CheckCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";

interface ActionBannerProps {
  lead: Lead;
  onCall?: () => void;
  onMarkComplete?: () => void;
  className?: string;
}

type BannerConfig = {
  type: "overdue" | "scheduled" | "hot_lead";
  priority: "critical" | "high" | "medium";
  title: string;
  message: string;
  actionPrimary: string | null;
  actionSecondary: string | null;
  gradient: string;
  iconBg: string;
  iconColor: string;
  textColor: string;
  badgeColor: string;
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

function formatScheduledTime(date: Date): string {
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  const time = date.toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (isToday) {
    return `${time} hôm nay`;
  }

  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) {
    return `${time} ngày mai`;
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
  // is_overdue = next_activity_at has passed
  if (lead.is_overdue && lead.next_activity_at) {
    const overdueDate = new Date(lead.next_activity_at);
    return {
      type: "overdue",
      priority: "critical",
      title: "QUÁ HẠN LIÊN HỆ",
      message: `Hẹn gọi lại ${formatTimeAgo(overdueDate)} — Cần liên hệ ngay`,
      actionPrimary: "Gọi ngay",
      actionSecondary: "Đánh dấu hoàn thành",
      gradient: "from-red-50 to-rose-50",
      iconBg: "bg-red-100",
      iconColor: "text-red-600",
      textColor: "text-red-800",
      badgeColor: "bg-red-200 text-red-800",
      icon: AlertTriangle,
    };
  }

  // Priority 2: Scheduled appointment (next_activity_at is in the future)
  // NOTE: We use next_activity_at instead of scanning consultations array
  // because Lead API response doesn't include consultations by default
  if (lead.next_activity_at && !lead.is_overdue) {
    const scheduledDate = new Date(lead.next_activity_at);
    // Only show if the scheduled date is in the future
    if (scheduledDate > now) {
      const diffHours = (scheduledDate.getTime() - now.getTime()) / (1000 * 60 * 60);
      const isSoon = diffHours <= 2 && diffHours > 0;

      return {
        type: "scheduled",
        priority: isSoon ? "high" : "medium",
        title: "LỊCH HẸN SẮP TỚI",
        message: `Có lịch hẹn lúc ${formatScheduledTime(scheduledDate)}`,
        actionPrimary: isSoon ? "Gọi ngay" : null,
        actionSecondary: "Đánh dấu hoàn thành",
        gradient: "from-amber-50 to-orange-50",
        iconBg: "bg-amber-100",
        iconColor: "text-amber-600",
        textColor: "text-amber-800",
        badgeColor: "bg-amber-200 text-amber-800",
        icon: Bell,
      };
    }
  }

  // Priority 3: Hot lead needing contact
  // is_hot_lead = lead_score >= 70 (set by LeadCacheService)
  // Show banner if:
  // - Lead is hot (score >= 70) AND
  // - Either no recent contact OR urgency is elevated
  const hasRecentContact = lead.consultation_count > 0 && lead.last_consultation_at &&
    (new Date().getTime() - new Date(lead.last_consultation_at).getTime()) < 24 * 60 * 60 * 1000; // Within 24h

  if (lead.is_hot_lead && !hasRecentContact) {
    return {
      type: "hot_lead",
      priority: "high",
      title: "LEAD TIỀM NĂNG CAO",
      message: `Điểm: ${lead.lead_score} — Cần liên hệ sớm để không bỏ lỡ cơ hội`,
      actionPrimary: "Gọi ngay",
      actionSecondary: null,
      gradient: "from-orange-50 to-amber-50",
      iconBg: "bg-orange-100",
      iconColor: "text-orange-600",
      textColor: "text-orange-800",
      badgeColor: "bg-orange-200 text-orange-800",
      icon: Flame,
    };
  }

  return null; // No banner needed
}

export function ActionBanner({ lead, onCall, onMarkComplete, className }: ActionBannerProps) {
  const config = useMemo(() => getActionBannerConfig(lead), [lead]);

  if (!config) {
    return null;
  }

  const Icon = config.icon;

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
        "flex items-center justify-between p-4 rounded-2xl border",
        `bg-gradient-to-r ${config.gradient}`,
        config.type === "overdue" ? "border-red-200" : "border-amber-200",
        className
      )}
    >
      {/* Left: Icon + Message */}
      <div className="flex items-center gap-3">
        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", config.iconBg)}>
          <Icon className={cn("w-5 h-5", config.iconColor)} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className={cn("text-sm font-bold", config.textColor)}>{config.title}</span>
            <Badge className={cn("text-xs font-medium", config.badgeColor)}>
              {config.priority === "critical" ? "Khẩn cấp" : "Ưu tiên"}
            </Badge>
          </div>
          <p className={cn("text-sm mt-0.5", config.textColor)}>
            <Clock className="w-3.5 h-3.5 inline mr-1" />
            {config.message}
          </p>
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        {config.actionSecondary && (
          <Button
            variant="ghost"
            size="sm"
            className={cn("text-sm font-medium", config.textColor, "hover:bg-white/50")}
            onClick={onMarkComplete}
          >
            <CheckCircle className="w-4 h-4 mr-1" />
            {config.actionSecondary}
          </Button>
        )}
        {config.actionPrimary && (
          <Button
            size="sm"
            className={cn(
              "text-sm font-medium text-white",
              config.type === "overdue"
                ? "bg-red-500 hover:bg-red-600"
                : "bg-amber-500 hover:bg-amber-600"
            )}
            onClick={handleCall}
          >
            <Phone className="w-4 h-4 mr-1" />
            {config.actionPrimary}
          </Button>
        )}
      </div>
    </div>
  );
}

export default ActionBanner;
