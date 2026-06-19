// src/components/leads/LeadActionSuggestions.tsx
/**
 * ✅ Phase 3: AI-Powered Action Suggestions
 * 
 * Shows smart action suggestions based on lead insights and status.
 * Styled to match LeadDetailPanel's Card-based design.
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
  Lightbulb,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { isLeadOverdue } from "@/lib/leads/overdue";
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
// PRIORITY STYLES - Matching existing theme
// =============================================================================

const PRIORITY_STYLES: Record<Suggestion["priority"], {
  bg: string;
  border: string;
  icon: string;
  text: string;
}> = {
  urgent: {
    bg: "bg-error-50 dark:bg-error-950/30",
    border: "border-l-error-500",
    icon: "text-error-500",
    text: "text-error-700 dark:text-error-300",
  },
  high: { 
    bg: "bg-orange-50 dark:bg-orange-950/30", 
    border: "border-l-orange-500",
    icon: "text-orange-500",
    text: "text-orange-700 dark:text-orange-300",
  },
  medium: {
    bg: "bg-warning-50 dark:bg-warning-950/30",
    border: "border-l-warning-500",
    icon: "text-warning-500",
    text: "text-warning-700 dark:text-warning-300",
  },
  low: {
    bg: "bg-muted dark:bg-muted/50",
    border: "border-l-muted-foreground",
    icon: "text-muted-foreground",
    text: "text-muted-foreground dark:text-muted-foreground",
  },
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
    
    // Pure calculation: compute days since last contact inside useMemo
    // Using a local function to keep the impure Date call contained
    const getDaysSinceLastContact = (): number | null => {
      if (!lead.last_consultation_at) return null;
      const lastContactTime = new Date(lead.last_consultation_at).getTime();
      const currentTime = new Date().getTime();
      return Math.floor((currentTime - lastContactTime) / (1000 * 60 * 60 * 24));
    };
    
    const daysSinceLastContact = getDaysSinceLastContact();
    
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
    if (isLeadOverdue(lead)) {
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

  // Don't render if no suggestions
  if (suggestions.length === 0) {
    return null;
  }

  return (
    <Card className={className}>
      <CardHeader className="px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Lightbulb aria-hidden="true" className="h-4 w-4 text-amber-500" />
          Gợi ý hành động
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pt-0 pb-4 space-y-2">
        {suggestions.slice(0, 3).map((suggestion, index) => {
          const Icon = suggestion.icon;
          const styles = PRIORITY_STYLES[suggestion.priority];
          
          return (
            <div
              key={index}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 border-l-3",
                styles.bg,
                styles.border,
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", styles.icon)} />
              <span className={cn("flex-1 text-sm", styles.text)}>
                {suggestion.message}
              </span>
              {suggestion.actionLabel && suggestion.onAction && (
                <Button
                  size="sm"
                  variant="ghost"
                  className={cn(
                    "shrink-0 h-7 px-2 text-xs font-medium",
                    suggestion.priority === "urgent" && "text-error-600 hover:text-error-700 hover:bg-error-100",
                    suggestion.priority === "high" && "text-orange-600 hover:text-orange-700 hover:bg-orange-100",
                    suggestion.priority === "medium" && "text-warning-600 hover:text-warning-700 hover:bg-warning-100",
                    suggestion.priority === "low" && "text-muted-foreground hover:text-foreground hover:bg-muted",
                  )}
                  onClick={suggestion.onAction}
                >
                  {suggestion.actionLabel}
                </Button>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

export default LeadActionSuggestions;
