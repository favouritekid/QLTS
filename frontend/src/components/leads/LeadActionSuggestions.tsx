// src/components/leads/LeadActionSuggestions.tsx
/**
 * ✅ Phase 3: AI-Powered Action Suggestions
 * 
 * Shows smart action suggestions based on lead insights and status.
 * Helps officers prioritize actions for each lead.
 */

"use client";

import React, { useMemo } from "react";
import { 
  Phone, 
  CheckCircle, 
  Clock, 
  AlertTriangle,
  MessageSquare,
  UserPlus,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Lead, LeadInsights } from "@/types/lead.types";

// =============================================================================
// TYPES
// =============================================================================

interface Suggestion {
  priority: "low" | "medium" | "high" | "urgent";
  action: string;
  message: string;
  icon: LucideIcon;
  actionLabel?: string;
  onAction?: () => void;
}

interface LeadActionSuggestionsProps {
  lead: Lead;
  insights?: LeadInsights | null;
  onContact?: () => void;
  onSchedule?: () => void;
  className?: string;
}

// =============================================================================
// PRIORITY COLORS
// =============================================================================

const PRIORITY_STYLES: Record<Suggestion["priority"], string> = {
  urgent: "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950",
  high: "border-orange-200 bg-orange-50 dark:border-orange-900 dark:bg-orange-950",
  medium: "border-yellow-200 bg-yellow-50 dark:border-yellow-900 dark:bg-yellow-950",
  low: "border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950",
};

const PRIORITY_ICON_STYLES: Record<Suggestion["priority"], string> = {
  urgent: "text-red-600 dark:text-red-400",
  high: "text-orange-600 dark:text-orange-400",
  medium: "text-yellow-600 dark:text-yellow-400",
  low: "text-blue-600 dark:text-blue-400",
};

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function LeadActionSuggestions({ 
  lead, 
  insights,
  onContact,
  onSchedule,
  className,
}: LeadActionSuggestionsProps) {
  
  const suggestions = useMemo(() => {
    const items: Suggestion[] = [];
    
    // Calculate days since last contact
    const daysSinceLastContact = lead.last_consultation_at
      ? Math.floor((Date.now() - new Date(lead.last_consultation_at).getTime()) / (1000 * 60 * 60 * 24))
      : null;
    
    // 1. Urgent: High urgency score + no recent contact
    if (lead.cached_urgency_score >= 70 && !lead.last_consultation_at) {
      items.push({
        priority: "urgent",
        action: "contact",
        message: "Lead cần được liên hệ ngay! Điểm khẩn cấp cao.",
        icon: Phone,
        actionLabel: "Gọi ngay",
        onAction: onContact,
      });
    }

    // 2. High: Overdue follow-up
    if (lead.is_overdue) {
      items.push({
        priority: "high",
        action: "followup",
        message: "Đã quá hạn liên hệ theo lịch hẹn.",
        icon: AlertTriangle,
        actionLabel: "Đặt lịch",
        onAction: onSchedule,
      });
    }

    // 3. High: Hot lead without recent activity
    if (lead.is_hot_lead && daysSinceLastContact && daysSinceLastContact > 3) {
      items.push({
        priority: "high",
        action: "engage",
        message: `Lead nóng chưa liên hệ ${daysSinceLastContact} ngày.`,
        icon: TrendingUp,
        actionLabel: "Liên hệ",
        onAction: onContact,
      });
    }

    // 4. Medium: High fit score, should qualify
    if (insights && insights.fit_score >= 80 && lead.status === "contacted") {
      items.push({
        priority: "medium",
        action: "qualify",
        message: "Điểm phù hợp cao, nên chuyển sang qualified.",
        icon: CheckCircle,
      });
    }

    // 5. Medium: Good engagement but no consultation scheduled
    if (insights && insights.engagement_score >= 60 && !lead.next_activity_at) {
      items.push({
        priority: "medium",
        action: "schedule",
        message: "Tương tác tốt, nên đặt lịch tư vấn tiếp.",
        icon: Clock,
        actionLabel: "Đặt lịch",
        onAction: onSchedule,
      });
    }

    // 6. Low: New lead without assignment
    if (lead.status === "new" && !lead.assigned_officer_id) {
      items.push({
        priority: "low",
        action: "assign",
        message: "Lead mới chưa được phân công.",
        icon: UserPlus,
      });
    }

    // 7. Low: Long time without contact (but not urgent)
    if (daysSinceLastContact && daysSinceLastContact > 7 && lead.cached_urgency_score < 50) {
      items.push({
        priority: "low",
        action: "reconnect",
        message: `Chưa liên hệ ${daysSinceLastContact} ngày.`,
        icon: MessageSquare,
      });
    }

    // Sort by priority
    const priorityOrder = { urgent: 0, high: 1, medium: 2, low: 3 };
    return items.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
  }, [lead, insights, onContact, onSchedule]);

  if (suggestions.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-2", className)}>
      <h4 className="text-sm font-medium text-muted-foreground">Gợi ý hành động</h4>
      <div className="space-y-2">
        {suggestions.slice(0, 3).map((suggestion, index) => {
          const Icon = suggestion.icon;
          return (
            <div
              key={index}
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3",
                PRIORITY_STYLES[suggestion.priority]
              )}
            >
              <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", PRIORITY_ICON_STYLES[suggestion.priority])} />
              <div className="flex-1 min-w-0">
                <p className="text-sm">{suggestion.message}</p>
              </div>
              {suggestion.actionLabel && suggestion.onAction && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="shrink-0 h-7 px-2 text-xs"
                  onClick={suggestion.onAction}
                >
                  {suggestion.actionLabel}
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default LeadActionSuggestions;
