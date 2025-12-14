// src/components/leads/LeadInsightsCard.tsx
/**
 * ✅ Combined Lead Insights + Action Suggestions Card
 * 
 * Modern visualization with:
 * - Score indicators with progress rings/bars
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
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
      if (value >= 40) return "bg-amber-500";
      return "bg-green-500";
    }
    if (percentage >= 70) return "bg-emerald-500";
    if (percentage >= 40) return "bg-blue-500";
    return "bg-slate-400";
  };
  
  const getTextColor = () => {
    if (variant === "hot" && value >= 50) return "text-orange-600 dark:text-orange-400";
    if (variant === "urgent" && value >= 70) return "text-red-600 dark:text-red-400";
    if (variant === "urgent" && value >= 40) return "text-amber-600 dark:text-amber-400";
    return "text-foreground";
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-foreground flex items-center gap-1.5">
          {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
          {label}
        </span>
        <span className={cn("text-base font-bold tabular-nums", getTextColor())}>
          {value}
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div 
          className={cn("h-full rounded-full transition-all duration-500", getColor())}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

// =============================================================================
// STAT BOX COMPONENT
// =============================================================================

function StatBox({ 
  label, 
  value, 
  icon: Icon,
  highlight = false,
}: { 
  label: string;
  value: string | number;
  icon?: React.ComponentType<{ className?: string }>;
  highlight?: boolean;
}) {
  return (
    <div className={cn(
      "rounded-lg p-3 text-center border",
      highlight ? "bg-primary/5 border-primary/20" : "bg-muted/30 border-transparent"
    )}>
      <div className="flex items-center justify-center gap-1.5 mb-1">
        {Icon && <Icon className={cn("h-4 w-4", highlight ? "text-primary" : "text-muted-foreground")} />}
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      </div>
      <p className={cn(
        "text-xl font-bold text-foreground",
        highlight && "text-primary"
      )}>{value}</p>
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

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-2">
          <StatBox 
            label="Số lần tư vấn" 
            value={lead.consultation_count}
            icon={MessageSquare}
            highlight={lead.consultation_count > 0}
          />
          <StatBox 
            label="Tư vấn cuối" 
            value={lastConsultation}
            icon={Clock}
          />
        </div>

        {/* Action Suggestions */}
        {suggestions.length > 0 && (
          <div className="space-y-2 pt-2 border-t">
            {suggestions.map((suggestion, index) => (
              <div
                key={index}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm",
                  suggestion.priority === "urgent" && "bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300",
                  suggestion.priority === "high" && "bg-orange-50 dark:bg-orange-950/30 text-orange-700 dark:text-orange-300",
                  suggestion.priority === "medium" && "bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300",
                )}
              >
                <div className="flex items-center gap-2">
                  {suggestion.priority === "urgent" && <Phone className="h-4 w-4" />}
                  {suggestion.priority === "high" && <AlertTriangle className="h-4 w-4" />}
                  {suggestion.priority === "medium" && <CheckCircle className="h-4 w-4" />}
                  <span>{suggestion.message}</span>
                </div>
                {suggestion.actionLabel && suggestion.onAction && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className={cn(
                      "h-7 px-2 text-xs font-medium",
                      suggestion.priority === "urgent" && "text-red-700 hover:bg-red-100 dark:hover:bg-red-900",
                      suggestion.priority === "high" && "text-orange-700 hover:bg-orange-100 dark:hover:bg-orange-900",
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
        <div className="pt-2 border-t">
          <div className="flex items-center gap-2 mb-2">
            <Star className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Đánh giá của bạn</span>
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
