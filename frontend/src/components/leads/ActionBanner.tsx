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
import { format } from "date-fns";
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

  // Guard: if date is in the future (stale cache), show as "vừa xong"
  if (diffMs < 0) return "vừa xong";

  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffMinutes = Math.floor(diffMs / (1000 * 60));

  if (diffDays > 0) {
    return `${diffDays} ngày trước`;
  }
  if (diffHours > 0) {
    return `${diffHours} giờ trước`;
  }
  if (diffMinutes > 0) {
    return `${diffMinutes} phút trước`;
  }
  return "vừa xong";
}

function formatScheduledTime(date: Date): string {
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  const time = format(date, "HH:mm");

  if (isToday) {
    return `${time} hôm nay`;
  }

  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) {
    return `${time} ngày mai`;
  }

  return format(date, "dd/MM HH:mm");
}

function getActionBannerConfig(lead: Lead): BannerConfig | null {
  const now = new Date();

  // Hard-terminal leads (enrolled + final) should never show action banners
  // Soft-terminal leads (final but not enrolled) can still receive consultations
  const isHardTerminal = lead.consultation_status?.is_final && lead.consultation_status?.phase === "enrolled";
  if (isHardTerminal) return null;

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
      gradient: "from-error-50 to-rose-50",
      iconBg: "bg-error-100",
      iconColor: "text-error-600",
      textColor: "text-error-800",
      badgeColor: "bg-error-200 text-error-800",
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
        gradient: "from-warning-50 to-orange-50",
        iconBg: "bg-warning-100",
        iconColor: "text-warning-600",
        textColor: "text-warning-800",
        badgeColor: "bg-warning-200 text-warning-800",
        icon: Bell,
      };
    }
  }

  // Priority 3: Hot lead needing contact
  // is_hot_lead = lead_score >= 70 (set by LeadCacheService)
  // Show banner if lead is hot AND no recent contact (within 24h)
  const hasRecentContact = lead.consultation_count > 0 && lead.last_consultation_at &&
    (now.getTime() - new Date(lead.last_consultation_at).getTime()) < 24 * 60 * 60 * 1000;

  if (lead.is_hot_lead && !hasRecentContact) {
    return {
      type: "hot_lead",
      priority: "high",
      title: "LEAD TIỀM NĂNG CAO",
      message: `Điểm: ${lead.lead_score} — Cần liên hệ sớm để không bỏ lỡ cơ hội`,
      actionPrimary: "Gọi ngay",
      actionSecondary: null,
      gradient: "from-orange-50 to-amber-50 dark:from-orange-950/30 dark:to-amber-950/30",
      iconBg: "bg-orange-100 dark:bg-orange-900/50",
      iconColor: "text-orange-600 dark:text-orange-400",
      textColor: "text-orange-800 dark:text-orange-200",
      badgeColor: "bg-orange-200 text-orange-800 dark:bg-orange-900/50 dark:text-orange-200",
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
        "flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-2xl border",
        `bg-gradient-to-r ${config.gradient}`,
        config.type === "overdue" ? "border-error-200" : "border-warning-200",
        className
      )}
    >
      {/* Left: Icon + Message */}
      <div className="flex items-center gap-3 min-w-0">
        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shrink-0", config.iconBg)}>
          <Icon className={cn("w-5 h-5", config.iconColor)} />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("text-sm font-bold", config.textColor)}>{config.title}</span>
            <Badge className={cn("text-xs font-medium shrink-0", config.badgeColor)}>
              {config.priority === "critical" ? "Khẩn cấp" : "Ưu tiên"}
            </Badge>
          </div>
          <p className={cn("text-sm mt-0.5 truncate", config.textColor)} suppressHydrationWarning>
            <Clock className="w-3.5 h-3.5 inline mr-1" />
            {config.message}
          </p>
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2 shrink-0">
        {config.actionSecondary && (
          <Button
            variant="ghost"
            size="sm"
            className={cn("text-sm font-medium", config.textColor, "hover:bg-background/50")}
            onClick={onMarkComplete}
          >
            <CheckCircle className="w-4 h-4 mr-1" />
            <span className="hidden sm:inline">{config.actionSecondary}</span>
            <span className="sm:hidden">Hoàn thành</span>
          </Button>
        )}
        {config.actionPrimary && (
          <Button
            size="sm"
            className={cn(
              "text-sm font-medium text-white",
              config.type === "overdue"
                ? "bg-error-500 hover:bg-error-600"
                : "bg-warning-500 hover:bg-warning-600"
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
