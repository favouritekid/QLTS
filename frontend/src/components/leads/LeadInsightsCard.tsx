// src/components/leads/LeadInsightsCard.tsx
/**
 * ✅ Combined Lead Insights + Action Suggestions Card
 * 
 * Modern visualization with:
 * - Score indicators with progress bars
 * - Action suggestions integrated
 * - Officer rating
 */

"use client";

import React, { useMemo } from "react";
import { 
  Phone, 
  AlertTriangle,
  TrendingUp,
  Clock,
  CheckCircle,
  MessageSquare,
  Flame,
  Activity,
  Star,
  Layers,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { OfficerRatingInput } from "@/components/leads/OfficerRatingInput";
import type { Lead } from "@/types/lead.types";

// =============================================================================
// TYPES
// =============================================================================

interface LeadInsightsCardProps {
  lead: Lead;
  onContact?: () => void;
  className?: string;
}

interface Suggestion {
  priority: "urgent" | "high" | "medium";
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}

// =============================================================================
// SCORE INDICATOR COMPONENT
// =============================================================================

function ScoreIndicator({ 
  label, 
  value, 
  maxValue = 100,
  icon: Icon,
  variant = "default",
}: { 
  label: string;
  value: number;
  maxValue?: number;
  icon?: React.ComponentType<{ className?: string }>;
  variant?: "default" | "hot" | "urgent";
}) {
  const percentage = Math.min((value / maxValue) * 100, 100);
  
  const getColor = () => {
    if (variant === "hot") return "bg-orange-500";
    if (variant === "urgent") {
      if (value >= 70) return "bg-red-500";
      if (value >= 40) return "bg-yellow-500";
      return "bg-green-500";
    }
    if (percentage >= 70) return "bg-emerald-500";
    if (percentage >= 40) return "bg-blue-500";
    return "bg-slate-400";
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground flex items-center gap-2">
          {Icon && <Icon className="h-4 w-4" />}
          {label}
        </span>
        <span className={cn(
          "text-sm font-bold tabular-nums",
          variant === "hot" && value >= 70 && "text-orange-600",
          variant === "urgent" && value >= 70 && "text-red-600",
        )}>
          {value}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div 
          className={cn("h-full rounded-full transition-all duration-500", getColor())}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function LeadInsightsCard({ 
  lead, 
  onContact,
  className,
}: LeadInsightsCardProps) {
  
  // Generate suggestions based on lead data
  const suggestions = useMemo(() => {
    const items: Suggestion[] = [];
    
    const daysSinceLastContact = lead.last_consultation_at
      ? Math.floor((Date.now() - new Date(lead.last_consultation_at).getTime()) / (1000 * 60 * 60 * 24))
      : null;
    
    if (lead.cached_urgency_score >= 70 && !lead.last_consultation_at) {
      items.push({
        priority: "urgent",
        message: "Lead cần được liên hệ ngay!",
        actionLabel: "Gọi ngay",
        onAction: onContact,
      });
    }

    if (lead.is_overdue) {
      items.push({
        priority: "high",
        message: "Đã quá hạn liên hệ theo lịch hẹn",
      });
    }

    if (lead.is_hot_lead && daysSinceLastContact && daysSinceLastContact > 3) {
      items.push({
        priority: "high",
        message: `Lead nóng chưa liên hệ ${daysSinceLastContact} ngày`,
        actionLabel: "Liên hệ",
        onAction: onContact,
      });
    }

    return items.slice(0, 2);
  }, [lead, onContact]);

  const lastConsultation = lead.last_consultation_at
    ? new Date(lead.last_consultation_at).toLocaleDateString("vi-VN")
    : "Chưa có";

  return (
    <Card className={className}>
      <CardHeader className="px-4 py-3 pb-2">
        <CardTitle className="flex items-center justify-between text-sm font-medium">
          <span className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            Lead Insights
          </span>
          {lead.is_hot_lead && (
            <span className="flex items-center gap-1 text-orange-600 text-xs font-medium bg-orange-100 dark:bg-orange-950 px-2 py-0.5 rounded-full">
              <Flame className="h-3 w-3" />
              Hot Lead
            </span>
          )}
        </CardTitle>
      </CardHeader>
      
      <CardContent className="px-4 pt-0 pb-4 space-y-4">
        {/* Score Indicators */}
        <div className="space-y-3">
          <ScoreIndicator 
            label="Điểm Lead" 
            value={lead.lead_score} 
            icon={TrendingUp}
            variant="hot"
          />
          <ScoreIndicator 
            label="Độ khẩn cấp" 
            value={lead.cached_urgency_score} 
            icon={AlertTriangle}
            variant="urgent"
          />
        </div>

        {/* Stats Rows */}
        <div className="space-y-2.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-2">
              <MessageSquare className="h-4 w-4" />
              Số lần tư vấn
            </span>
            <span className="font-medium">{lead.consultation_count}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-2">
              <Layers className="h-4 w-4" />
              Số ngày trong giai đoạn
            </span>
            <span className="font-medium">
              {lead.days_in_stage ?? 0} ngày
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Tư vấn lần cuối
            </span>
            <span className="font-medium">{lastConsultation}</span>
          </div>
        </div>

        {/* Action Suggestions */}
        {suggestions.length > 0 && (
          <div className="space-y-2 pt-3 border-t">
            {suggestions.map((suggestion, index) => (
              <div
                key={index}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-sm border",
                  suggestion.priority === "urgent" && "bg-red-100 border-red-200 text-red-800 dark:bg-red-900/50 dark:border-red-700 dark:text-red-100",
                  suggestion.priority === "high" && "bg-orange-100 border-orange-200 text-orange-800 dark:bg-orange-900/50 dark:border-orange-700 dark:text-orange-100",
                  suggestion.priority === "medium" && "bg-amber-100 border-amber-200 text-amber-800 dark:bg-amber-900/50 dark:border-amber-700 dark:text-amber-100",
                )}
              >
                <div className="flex items-center gap-2">
                  {suggestion.priority === "urgent" && <Phone className="h-4 w-4 shrink-0" />}
                  {suggestion.priority === "high" && <AlertTriangle className="h-4 w-4 shrink-0" />}
                  {suggestion.priority === "medium" && <CheckCircle className="h-4 w-4 shrink-0" />}
                  <span className="font-medium">{suggestion.message}</span>
                </div>
                {suggestion.actionLabel && suggestion.onAction && (
                  <Button
                    size="sm"
                    className={cn(
                      "h-7 px-3 text-xs font-semibold shrink-0",
                      suggestion.priority === "urgent" && "bg-red-600 text-white hover:bg-red-700",
                      suggestion.priority === "high" && "bg-orange-600 text-white hover:bg-orange-700",
                    )}
                    onClick={suggestion.onAction}
                  >
                    {suggestion.actionLabel}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Officer Rating */}
        <div className="pt-3 border-t">
          <div className="flex items-center gap-2 mb-2">
            <Star className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Đánh giá của bạn</span>
          </div>
          <OfficerRatingInput
            key={`rating-${lead.id}`}
            leadId={lead.id}
            currentRating={lead.officer_rating ?? null}
            currentLeadScore={lead.lead_score}
            compact
          />
        </div>
      </CardContent>
    </Card>
  );
}

export default LeadInsightsCard;
